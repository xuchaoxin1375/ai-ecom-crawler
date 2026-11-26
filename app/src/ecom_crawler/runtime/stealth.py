"""Challenge-capable browser fetcher built on Scrapling's stealth session.

The regular ``browser`` engine uses Patchright without challenge solving.  This
engine is for sites where a Cloudflare-style challenge blocks that path.  It
reuses one Scrapling ``StealthySession`` and one task-owned profile for the
whole task, so the first solved challenge warms the following requests.

Boundaries:

- No login, paywall, CAPTCHA bypass or credential use is attempted.  Scrapling
  solves the challenge the same way the collection skill does; if the challenge
  remains, the result is marked ``challenge_suspected`` and the runner stops.
- The session is thread-affine, so the runner processes items inline.
- The profile lives under ``<out-root>/<task-id>/stealth-profile`` and is
  registered for normal/takeover cleanup.  A profile left by a killed worker is
  removed by the worker's orphan sweep once it is old enough.
"""

from __future__ import annotations

import logging
import re
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlparse

from .browser import is_challenge_title
from .fetcher import DomainLimiter, UnsupportedAdvanceError
from .models import FetchResult
from .resources import register_path
from .store import TaskStore

DEFAULT_PROFILE_NAME = "stealth-profile"
DEFAULT_TIMEOUT_MS = 240_000
DEFAULT_CHALLENGE_WAIT_MS = 180_000

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StealthConfig:
    headless: bool = True
    real_chrome: bool = False
    executable_path: str | None = None
    extra_flags: tuple[str, ...] = ()
    user_agent: str | None = None
    locale: str | None = None
    timezone: str | None = None
    proxy: str | None = None
    profile_name: str = DEFAULT_PROFILE_NAME
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    challenge_wait_ms: int = DEFAULT_CHALLENGE_WAIT_MS
    wait_until: str = "domcontentloaded"
    wait_selector: str | None = None
    wait_selector_state: str = "attached"
    wait_ms: int = 0
    network_idle: bool = False
    disable_resources: bool = False
    solve_cloudflare: bool = True

    @classmethod
    def from_fetch(cls, fetch: dict[str, Any]) -> Self:
        from .browser import BrowserConfig

        base = BrowserConfig.from_fetch(fetch)
        raw = fetch.get("browser")
        browser = raw if isinstance(raw, dict) else {}
        timeout_ms = max(base.page.timeout_ms, DEFAULT_TIMEOUT_MS)
        challenge_wait_ms = max(
            base.launch.challenge_wait_ms, DEFAULT_CHALLENGE_WAIT_MS
        )
        profile = _optional_string(browser.get("profile_name"))
        profile_name = (
            _safe_profile_name(f"stealth-{profile}")
            if profile
            else DEFAULT_PROFILE_NAME
        )
        return cls(
            headless=base.launch.headless,
            real_chrome=base.launch.real_chrome,
            executable_path=base.launch.executable_path,
            extra_flags=base.launch.extra_flags,
            user_agent=base.launch.user_agent,
            locale=base.launch.locale,
            timezone=base.launch.timezone,
            proxy=base.launch.proxy,
            profile_name=profile_name,
            timeout_ms=timeout_ms,
            challenge_wait_ms=challenge_wait_ms,
            wait_until=base.page.wait_until,
            wait_selector=base.page.wait_selector,
            wait_selector_state=base.page.wait_selector_state,
            wait_ms=base.page.wait_ms,
            network_idle=base.page.network_idle or base.page.wait_until == "networkidle",
            disable_resources=base.page.disable_resources,
        )


class StealthFetcher:
    """Fetch rendered HTML through a challenge-capable Scrapling session."""

    thread_affine = True

    def __init__(
        self,
        store: TaskStore,
        *,
        task_id: str,
        out_root: str | Path,
        config: StealthConfig | None = None,
        limiter: DomainLimiter | None = None,
        lease_token: int | None = None,
        max_attempts: int = 2,
        backoff_ms: int = 1000,
        session: Any | None = None,
        started: bool = False,
    ) -> None:
        self.store = store
        self.task_id = task_id
        self.out_root = Path(out_root)
        self.config = config or StealthConfig()
        self.limiter = limiter
        self.lease_token = lease_token
        self.max_attempts = max(1, int(max_attempts))
        self.backoff = max(0, int(backoff_ms)) / 1000
        self.requests = 0
        self.retries = 0
        self._session = session
        self._started = started or session is not None
        self._warmed = False
        self._lock = threading.Lock()
        self._profile_dir = self.out_root / task_id / self.config.profile_name
        self._profile_resource = f"stealth-profile:{task_id}"

    def get(self, url: str, *, item_type: str | None = None) -> FetchResult:
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            if self.limiter is not None:
                self.limiter.wait(url)
            try:
                self._ensure_started()
                self.requests += 1
                if attempt > 1:
                    self.retries += 1
                status, final_url, body, headers = self._fetch_once(url)
            except Exception as exc:  # noqa: BLE001 - transport / browser / challenge
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.max_attempts:
                    self._sleep_backoff(attempt)
                    continue
                return FetchResult(status=0, url=url, error=last_error)

            content_type = ""
            try:
                content_type = str(
                    headers.get("content-type")
                    or headers.get("Content-Type")
                    or ""
                )
            except AttributeError:
                content_type = ""
            title = _response_title(body)
            challenge = is_challenge_title(title)
            meta: dict[str, Any] = {
                "content_type": content_type,
                "challenge_suspected": challenge,
            }
            if challenge:
                meta["challenge_title"] = title[:200]
            if (status == 429 or 500 <= status < 600) and attempt < self.max_attempts:
                self._sleep_backoff(attempt)
                continue
            return FetchResult(
                status=status,
                url=final_url,
                body=bytes(body),
                meta=meta,
            )
        return FetchResult(status=0, url=url, error=last_error)

    def get_listing(
        self,
        url: str,
        *,
        advance: dict[str, Any],
        item_selector: str | None = None,
        item_type: str | None = None,
    ) -> FetchResult:
        raise UnsupportedAdvanceError(
            "load_more/infinite_scroll require the browser engine; "
            "the stealth engine does not automate listing actions"
        )

    def describe(self) -> dict[str, Any]:
        return {
            "engine": "stealth",
            "engines_used": ["stealth"] if self.requests else [],
            "thread_affine": True,
            "browser_launched": self._started,
            "browser_headless": self.config.headless,
            "browser_profile": self.config.profile_name,
            "browser_binary": "scrapling-stealth",
        }

    def close(self) -> None:
        with self._lock:
            session, self._session = self._session, None
            if session is not None:
                try:
                    session.close()
                except Exception:
                    logger.debug("stealth session close failed", exc_info=True)
            self._started = False
            if _remove_profile(self._profile_dir):
                try:
                    self.store.remove_resource(
                        self.task_id, self._profile_resource
                    )
                except Exception:
                    logger.debug(
                        "stealth profile resource cleanup failed", exc_info=True
                    )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _fetch_once(self, url: str) -> tuple[int, str, bytes, Any]:
        """Fetch HTML through the page, and documents through the context.

        ``page.goto`` starts a download for ``.xml.gz`` and other attachment
        responses, which fails before the body can be read.  A sitemap child is
        often gzipped XML, so document URLs use the browser context's request
        API after the session has passed a challenge at least once.  The first
        navigation still goes through the page: the context request alone does
        not run the Cloudflare solver.
        """
        document = _is_document_url(url)
        if document and self._warmed:
            result = self._fetch_document(url)
            if not _is_challenge(result[2]):
                return result
            if not url.lower().endswith(".gz"):
                page = self._fetch_page(url)
                if not _is_challenge(page[2]):
                    return page
            return result
        if document and not self._warmed:
            if url.lower().endswith(".xml"):
                result = self._fetch_page(url)
                if result[0] == 200 and not _is_challenge(result[2]):
                    self._warmed = True
                return result
            warm = self._warm_origin(url)
            if _is_challenge(warm[2]):
                return warm
            return self._fetch_document(url)
        result = self._fetch_page(url)
        if result[0] == 200 and not _is_challenge(result[2]):
            self._warmed = True
        return result

    def _fetch_page(self, url: str) -> tuple[int, str, bytes, Any]:
        response = self._session.fetch(url, **self._fetch_options())
        body = getattr(response, "body", b"") or b""
        if isinstance(body, str):
            body = body.encode("utf-8")
        return (
            int(getattr(response, "status", 0) or 0),
            str(getattr(response, "url", url)),
            bytes(body),
            getattr(response, "headers", {}) or {},
        )

    def _fetch_document(self, url: str) -> tuple[int, str, bytes, Any]:
        request = self._context_request()
        if request is None:
            return self._fetch_page(url)
        response = request.get(
            url,
            timeout=self.config.timeout_ms,
            headers={"Accept": "*/*"},
        )
        body = response.body() or b""
        if isinstance(body, str):
            body = body.encode("utf-8")
        return (
            int(getattr(response, "status", 0) or 0),
            str(getattr(response, "url", url)),
            bytes(body),
            getattr(response, "headers", {}) or {},
        )

    def _warm_origin(self, url: str) -> tuple[int, str, bytes, Any]:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}/"
        result = self._fetch_page(origin)
        if result[0] == 200 and not _is_challenge(result[2]):
            self._warmed = True
        return result

    def _context_request(self) -> Any | None:
        context = getattr(self._session, "context", None)
        request = getattr(context, "request", None)
        return request

    def _ensure_started(self) -> None:
        if self._session is not None:
            return
        with self._lock:
            if self._session is not None:
                return
            self._profile_dir.mkdir(parents=True, exist_ok=True)
            register_path(
                self.store,
                self.task_id,
                self._profile_dir,
                resource_id=self._profile_resource,
                lease_token=self.lease_token,
            )
            from scrapling.fetchers import StealthySession

            session = StealthySession(
                headless=self.config.headless,
                real_chrome=self.config.real_chrome,
                executable_path=self.config.executable_path,
                extra_flags=list(self.config.extra_flags),
                useragent=self.config.user_agent,
                locale=self.config.locale,
                timezone_id=self.config.timezone,
                proxy=self.config.proxy,
                user_data_dir=str(self._profile_dir),
                disable_resources=self.config.disable_resources,
                solve_cloudflare=self.config.solve_cloudflare,
                retries=1,
            )
            session.start()
            self._session = session
            self._started = True

    def _fetch_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "timeout": self.config.timeout_ms,
            "network_idle": self.config.network_idle,
            "load_dom": self.config.wait_until in {"load", "networkidle"},
            "solve_cloudflare": self.config.solve_cloudflare,
            "disable_resources": self.config.disable_resources,
        }
        if self.config.wait_selector:
            options["wait_selector"] = self.config.wait_selector
            options["wait_selector_state"] = self.config.wait_selector_state
        if self.config.wait_ms:
            options["wait"] = self.config.wait_ms
        return options

    def _sleep_backoff(self, attempt: int) -> None:
        if self.backoff > 0:
            time.sleep(min(self.backoff * (2 ** (attempt - 1)), 5.0))


def _is_document_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(
        (
            ".xml",
            ".xml.gz",
            ".gz",
            ".json",
            ".ndjson",
            ".txt",
            ".csv",
            ".tsv",
        )
    )


def _is_challenge(body: bytes) -> bool:
    return is_challenge_title(_response_title(body))


def _response_title(body: bytes) -> str:
    match = re.search(rb"<title[^>]*>(.*?)</title>", body, re.DOTALL | re.IGNORECASE)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1).decode("utf-8", errors="replace")).strip()


def _remove_profile(path: Path) -> bool:
    try:
        if not path.exists() and not path.is_symlink():
            return True
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError:
        logger.debug("stealth profile removal failed: %s", path, exc_info=True)
        return False
    return True


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_profile_name(value: str) -> str:
    cleaned = "".join(
        character
        for character in value
        if character.isalnum() or character in {"-", "_", "."}
    ).strip(". ")
    return cleaned or DEFAULT_PROFILE_NAME
