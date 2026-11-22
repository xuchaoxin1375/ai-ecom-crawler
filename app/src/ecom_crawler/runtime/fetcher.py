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


class DomainLimiter:
    """Serialize requests per domain across tasks in the same worker process."""

    def __init__(self, per_domain_rps: float = 1.0) -> None:
        self.interval = 1.0 / max(float(per_domain_rps), 0.001)
        self._lock = threading.Lock()
        self._next_at: dict[str, float] = {}
        self.waits = 0

    def wait(self, url: str) -> None:
        domain = urlparse(url).netloc.lower()
        with self._lock:
            now = time.monotonic()
            wait_until = max(self._next_at.get(domain, now), now)
            self._next_at[domain] = wait_until + self.interval
        delay = wait_until - time.monotonic()
        if delay > 0:
            self.waits += 1
            time.sleep(delay)


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
        session_manager: Any | None = None,
    ) -> None:
        self.session = session
        self.limiter = limiter
        self.timeout = max(timeout_ms, 1) / 1000
        self.max_attempts = max(max_attempts, 1)
        self.backoff = max(backoff_ms, 0) / 1000
        self.requests = 0
        self.retries = 0
        self._session_manager = session_manager

    def get(self, url: str, *, item_type: str | None = None) -> FetchResult:
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            if self.limiter is not None:
                self.limiter.wait(url)
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
            if (status == 429 or 500 <= status < 600) and attempt < self.max_attempts:
                self._sleep_backoff(attempt)
                continue
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
        return {
            "engine": "static",
            "engines_used": ["static"] if self.requests else [],
            "thread_affine": False,
            "browser_launched": False,
        }

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
    package: ``static``, ``browser`` or ``http_json``.  ``http_json`` is a
    static HTTP request in this runtime.  Engines are built lazily so a rule
    that never reaches a browser URL does not launch one.
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
        self._thread_affine = "browser" in {
            self.default_engine,
            *self.overrides.values(),
        }

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
        browser = descriptions.get("browser")
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
    if engine not in {"static", "browser"}:
        raise ValueError(f"unsupported fetch engine: {value!r}")
    return engine
