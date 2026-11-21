"""Fetcher and per-domain rate limiter for the runtime prototype."""

from __future__ import annotations

import threading
import time
from typing import Any
from urllib.parse import urlparse

from .models import FetchResult


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
    ) -> None:
        self.session = session
        self.limiter = limiter
        self.timeout = max(timeout_ms, 1) / 1000
        self.max_attempts = max(max_attempts, 1)
        self.backoff = max(backoff_ms, 0) / 1000
        self.requests = 0
        self.retries = 0

    def get(self, url: str) -> FetchResult:
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
            if (status == 429 or 500 <= status < 600) and attempt < self.max_attempts:
                self._sleep_backoff(attempt)
                continue
            return FetchResult(status=status, url=final_url, body=bytes(body))
        return FetchResult(status=0, url=url, error=last_error)

    def _sleep_backoff(self, attempt: int) -> None:
        if self.backoff > 0:
            time.sleep(min(self.backoff * (2 ** (attempt - 1)), 5.0))
