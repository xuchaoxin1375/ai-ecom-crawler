"""Fetcher and per-domain rate limiter for the runtime prototype."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Self
from urllib.parse import urlparse

from .models import FetchResult

logger = logging.getLogger(__name__)


class UnsupportedAdvanceError(RuntimeError):
    """The selected fetch engine cannot perform a browser-only advance."""


RATE_LIMIT_MIN_RPS = 0.1
RATE_LIMIT_MAX_RPS = 10.0
RATE_LIMIT_MAX_RETRY_AFTER = 300.0
RATE_LIMIT_RECOVERY_SUCCESSES = 20


def retry_after_seconds(headers: Any) -> float | None:
    """Read ``Retry-After`` as seconds or an HTTP date."""
    if not headers:
        return None
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
    except AttributeError:
        return None
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        parsed = parsedate_to_datetime(text)
        if parsed is None:
            return None
        import datetime as _datetime

        now = _datetime.datetime.now(_datetime.UTC)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_datetime.UTC)
        return max(0.0, (parsed - now).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


class DomainLimiter:
    """Serialize and adapt request rates per domain across tasks."""

    def __init__(self, per_domain_rps: float = 1.0) -> None:
        self.default_rps = max(
            RATE_LIMIT_MIN_RPS,
            min(float(per_domain_rps), RATE_LIMIT_MAX_RPS),
        )
        self._lock = threading.Lock()
        self._next_at: dict[str, float] = {}
        self._base_rps: dict[str, float] = {}
        self._current_rps: dict[str, float] = {}
        self._cooldown_until: dict[str, float] = {}
        self._successes: dict[str, int] = {}
        self.waits = 0
        self.rate_limit_events = 0
        self.last_retry_after: float | None = None
        self.last_reduced_rps: float | None = None

    @staticmethod
    def _domain(url: str) -> str:
        return urlparse(url).netloc.lower()

    def configure(self, domain: str, rps: float | None) -> None:
        """Set a site policy rate, or reset the domain to the worker default."""
        key = str(domain or "").strip().lower()
        if not key:
            return
        value = (
            self.default_rps
            if rps is None
            else max(RATE_LIMIT_MIN_RPS, min(float(rps), RATE_LIMIT_MAX_RPS))
        )
        with self._lock:
            self._base_rps[key] = value
            self._current_rps[key] = value
            self._successes[key] = 0

    def _rate(self, domain: str) -> float:
        return self._current_rps.get(domain, self.default_rps)

    def wait(self, url: str) -> None:
        domain = self._domain(url)
        with self._lock:
            now = time.monotonic()
            rate = self._current_rps.get(domain, self.default_rps)
            interval = 1.0 / max(rate, RATE_LIMIT_MIN_RPS)
            wait_until = max(
                self._next_at.get(domain, now),
                now,
                self._cooldown_until.get(domain, 0.0),
            )
            self._next_at[domain] = wait_until + interval
        delay = wait_until - time.monotonic()
        if delay > 0:
            self.waits += 1
            time.sleep(delay)

    def penalize(self, url: str, retry_after: float | None = None) -> None:
        """Slow a domain after 429 and remember Retry-After for the next wait."""
        domain = self._domain(url)
        with self._lock:
            base = self._base_rps.get(domain, self.default_rps)
            current = self._current_rps.get(domain, base)
            reduced = max(RATE_LIMIT_MIN_RPS, min(current, base) / 2)
            self._current_rps[domain] = reduced
            self.last_reduced_rps = reduced
            self._successes[domain] = 0
            self.rate_limit_events += 1
            if retry_after is not None:
                capped = min(
                    max(float(retry_after), 0.0),
                    RATE_LIMIT_MAX_RETRY_AFTER,
                )
                self.last_retry_after = capped
                self._cooldown_until[domain] = max(
                    self._cooldown_until.get(domain, 0.0),
                    time.monotonic() + capped,
                )

    def success(self, url: str) -> None:
        """Gradually restore a reduced domain after a run of successes."""
        domain = self._domain(url)
        with self._lock:
            base = self._base_rps.get(domain, self.default_rps)
            current = self._current_rps.get(domain, base)
            if current >= base:
                return
            count = self._successes.get(domain, 0) + 1
            if count >= RATE_LIMIT_RECOVERY_SUCCESSES:
                self._current_rps[domain] = min(base, current * 1.25)
                count = 0
            self._successes[domain] = count

    def metrics(self) -> dict[str, Any]:
        with self._lock:
            rates = dict(self._current_rps)
        return {
            "rate_limit_events": self.rate_limit_events,
            "last_retry_after": self.last_retry_after,
            "last_reduced_rps": self.last_reduced_rps,
            "current_rps": rates,
            "default_rps": self.default_rps,
        }


class ScraplingFetcher:
    """Thin wrapper around a Scrapling session; returns status instead of raising."""

    def __init__(
        self,
        session: Any,
        *,
        limiter: DomainLimiter | None = None,
        timeout_ms: int = 45000,
        max_attempts: int = 2,
        backoff_ms: int = 1000,
        delay_ms: int = 0,
        session_manager: Any | None = None,
    ) -> None:
        self.session = session
        self.limiter = limiter
        self.timeout = max(timeout_ms, 1) / 1000
        self.max_attempts = max(max_attempts, 1)
        self.backoff = max(backoff_ms, 0) / 1000
        self.delay = max(delay_ms, 0) / 1000
        self.requests = 0
        self.retries = 0
        self.rate_limit_events = 0
        self.last_retry_after: float | None = None
        self._session_manager = session_manager

    def get(self, url: str, *, item_type: str | None = None) -> FetchResult:
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            if self.limiter is not None:
                self.limiter.wait(url)
            if self.delay > 0:
                time.sleep(self.delay)
            self.requests += 1
            if attempt > 1:
                self.retries += 1
            try:
                response = self.session.get(
                    url,
                    timeout=self.timeout,
                    retries=1,
                    follow_redirects=True,
                )
            except Exception as exc:  # noqa: BLE001 - transport / TLS / timeout
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.max_attempts:
                    self._sleep_backoff(attempt)
                    continue
                return FetchResult(status=0, url=url, error=last_error)

            status = int(getattr(response, "status", 0) or 0)
            body = getattr(response, "body", b"") or b""
            if isinstance(body, str):
                body = body.encode("utf-8")
            final_url = str(getattr(response, "url", url))
            headers = getattr(response, "headers", {}) or {}
            content_type = ""
            try:
                content_type = str(
                    headers.get("content-type")
                    or headers.get("Content-Type")
                    or ""
                )
            except AttributeError:
                content_type = ""
            if status == 429:
                retry_after = retry_after_seconds(headers)
                self.rate_limit_events += 1
                if retry_after is not None:
                    self.last_retry_after = retry_after
                if self.limiter is not None:
                    self.limiter.penalize(url, retry_after)
                if attempt < self.max_attempts:
                    if self.limiter is None:
                        wait = min(
                            max(
                                retry_after or 0.0,
                                self.backoff * (2 ** (attempt - 1)),
                            ),
                            30.0,
                        )
                        if wait > 0:
                            time.sleep(wait)
                    elif retry_after is None:
                        self._sleep_backoff(attempt)
                    continue
            elif 500 <= status < 600 and attempt < self.max_attempts:
                self._sleep_backoff(attempt)
                continue
            if self.limiter is not None and 200 <= status < 400:
                self.limiter.success(url)
            return FetchResult(
                status=status,
                url=final_url,
                body=bytes(body),
                meta={"content_type": content_type},
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
            "load_more/infinite_scroll require a browser engine for the listing"
        )

    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "engine": "static",
            "engines_used": ["static"] if self.requests else [],
            "thread_affine": False,
            "browser_launched": False,
            "delay_ms": int(self.delay * 1000),
            "rate_limit_events": self.rate_limit_events,
            "last_retry_after": self.last_retry_after,
        }
        if self.limiter is not None:
            metrics = self.limiter.metrics()
            info["rate_limit_events"] = max(
                self.rate_limit_events,
                int(metrics.get("rate_limit_events") or 0),
            )
            info["last_retry_after"] = (
                self.last_retry_after
                if self.last_retry_after is not None
                else metrics.get("last_retry_after")
            )
            info["current_rps"] = metrics.get("current_rps")
            info["default_rps"] = metrics.get("default_rps")
        return info

    def close(self) -> None:
        if self._session_manager is not None:
            manager = self._session_manager
            self._session_manager = None
            try:
                manager.__exit__(None, None, None)
            except Exception:
                logger.debug("static session close failed", exc_info=True)

    def _sleep_backoff(self, attempt: int) -> None:
        if self.backoff > 0:
            time.sleep(min(self.backoff * (2 ** (attempt - 1)), 5.0))


class HybridFetcher:
    """Route each work item to a lazily built engine.

    ``default_engine`` and ``overrides`` use the same names as the rule
    package: ``static``, ``browser``, ``stealth`` or ``http_json``.
    ``http_json`` is a static HTTP request in this runtime.  Engines are built
    lazily so a rule that never reaches a browser URL does not launch one.
    """

    def __init__(
        self,
        *,
        default_engine: str,
        overrides: dict[str, str],
        builders: dict[str, Callable[[], Any]],
    ) -> None:
        self.default_engine = normalize_engine(default_engine)
        self.overrides = {
            key: normalize_engine(value) for key, value in overrides.items()
        }
        self.builders = builders
        self._fetchers: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._thread_affine = bool(
            {"browser", "stealth"} & {self.default_engine, *self.overrides.values()}
        )

    @property
    def thread_affine(self) -> bool:
        # The runner decides between inline and pooled items before the first
        # fetch.  A hybrid plan that may reach the browser must therefore
        # declare thread affinity up front, not after the browser is built.
        return self._thread_affine

    @property
    def requests(self) -> int:
        return sum(
            int(getattr(fetcher, "requests", 0)) for fetcher in self._fetchers.values()
        )

    @property
    def retries(self) -> int:
        return sum(
            int(getattr(fetcher, "retries", 0)) for fetcher in self._fetchers.values()
        )

    def get(self, url: str, *, item_type: str | None = None) -> FetchResult:
        if urlparse(url).path.rstrip("/") == "/robots.txt" and "static" in self.builders:
            # robots.txt is plain text; do not launch a browser just to probe it.
            return self._fetcher("static").get(url, item_type=item_type)
        engine = self._engine_for(item_type)
        fetcher = self._fetcher(engine)
        return fetcher.get(url, item_type=item_type)

    def get_listing(
        self,
        url: str,
        *,
        advance: dict[str, Any],
        item_selector: str | None = None,
        item_type: str | None = None,
    ) -> FetchResult:
        engine = self._engine_for(item_type)
        fetcher = self._fetcher(engine)
        method = getattr(fetcher, "get_listing", None)
        if not callable(method):
            raise UnsupportedAdvanceError(
                "load_more/infinite_scroll require a browser engine for the listing"
            )
        return method(
            url,
            advance=advance,
            item_selector=item_selector,
            item_type=item_type,
        )

    def describe(self) -> dict[str, Any]:
        descriptions = {
            engine: fetcher.describe()
            for engine, fetcher in self._fetchers.items()
            if hasattr(fetcher, "describe")
        }
        engines_used = sorted(
            {
                engine
                for engine, description in descriptions.items()
                if description.get("engines_used")
            }
        )
        merged: dict[str, Any] = {
            "engine": "hybrid",
            "thread_affine": self.thread_affine,
            "engines_used": engines_used,
            "engines": descriptions,
        }
        browser = descriptions.get("browser") or descriptions.get("stealth")
        if browser:
            for key in (
                "browser_launched",
                "browser_headless",
                "browser_binary",
                "browser_version",
                "browser_pid",
                "browser_profile",
            ):
                if key in browser:
                    merged[key] = browser[key]
        else:
            merged["browser_launched"] = False
        return merged

    def close(self) -> None:
        for engine in reversed(list(self._fetchers)):
            fetcher = self._fetchers.pop(engine)
            try:
                fetcher.close()
            except Exception:
                logger.debug("engine close failed: %s", engine, exc_info=True)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _engine_for(self, item_type: str | None) -> str:
        if item_type and item_type in self.overrides:
            return self.overrides[item_type]
        return self.default_engine

    def _fetcher(self, engine: str) -> Any:
        with self._lock:
            fetcher = self._fetchers.get(engine)
            if fetcher is not None:
                return fetcher
            builder = self.builders.get(engine)
            if builder is None:
                raise RuntimeError(f"no fetcher builder for engine={engine}")
            fetcher = builder()
            self._fetchers[engine] = fetcher
            return fetcher


def normalize_engine(value: str) -> str:
    engine = str(value or "static").strip().lower()
    if engine == "http_json":
        return "static"
    if engine not in {"static", "browser", "stealth"}:
        raise ValueError(f"unsupported fetch engine: {value!r}")
    return engine
