"""HTTP access through Scrapling's FetcherSession with explicit pacing and stop rules.

Reused, unchanged in behaviour, from the Scrapling javaestate plan in this
repository (same framework, shared pacing/retry/stop semantics); only the
callers and defaults differ.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable


class StopRun(Exception):
    """Base class for conditions that must stop the whole run."""

    stop_reason = "OTHER"


class BudgetExhausted(StopRun):
    stop_reason = "BUDGET_EXHAUSTED"


class AccessDenied(StopRun):
    stop_reason = "ACCESS_DENIED"


class PlanError(StopRun):
    stop_reason = "PLAN_ERROR"


class EnvironmentError(StopRun):
    stop_reason = "ENVIRONMENT_ERROR"


@dataclass
class FetchOutcome:
    url: str
    status: int | None = None
    response: Any = None
    attempts: int = 0
    error: str | None = None
    error_class: str | None = None
    retry_after: float | None = None
    elapsed_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300 and self.response is not None


def parse_retry_after(headers: Any) -> float | None:
    """Read Retry-After seconds or HTTP-date; values are capped by the caller."""
    value = ""
    try:
        for key in headers:
            if str(key).lower() == "retry-after":
                value = str(headers[key]).strip()
                break
    except Exception:
        return None
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        return max((parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds(), 0.0)
    except (TypeError, ValueError):
        return None


class PacedFetcher:
    """Sequential, delay-respecting wrapper around one Scrapling FetcherSession.

    - the next request starts at least ``delay`` seconds after the previous
      response finished (measured end-to-next-start).
    - every HTTP attempt is counted, including retries.
    - 401/403, a persistent 429 above the Retry-After bound, or an unexpected
      access challenge stops the run (AccessDenied).
    - the wall-clock budget is checked before every attempt.
    """

    def __init__(
        self,
        session: Any,
        *,
        delay: float,
        max_attempts: int,
        timeout: float,
        deadline_monotonic: float,
        max_retry_after: float,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.session = session
        self.delay = max(delay, 1.0)
        self.max_attempts = max_attempts
        self.timeout = timeout
        self.deadline = deadline_monotonic
        self.max_retry_after = max_retry_after
        self.event_sink = event_sink or (lambda _event: None)
        self.requests = 0
        self.retries = 0
        self.last_end: float | None = None
        self.per_purpose: dict[str, int] = {}
        self.per_status: dict[str, int] = {}

    def _event(self, payload: dict[str, Any]) -> None:
        self.event_sink(payload)

    def _check_budget(self) -> None:
        if time.monotonic() >= self.deadline:
            raise BudgetExhausted("wall-clock budget exhausted before request")

    def _pace(self) -> None:
        if self.last_end is not None:
            wait = self.delay - (time.monotonic() - self.last_end)
            if wait > 0:
                time.sleep(wait)

    def get(self, url: str, *, purpose: str) -> FetchOutcome:
        started = time.monotonic()
        attempts = 0
        last_error: str | None = None
        last_class: str | None = None
        last_status: int | None = None
        last_retry_after: float | None = None

        while attempts < self.max_attempts:
            self._check_budget()
            self._pace()
            attempts += 1
            self.requests += 1
            self.per_purpose[purpose] = self.per_purpose.get(purpose, 0) + 1
            if attempts > 1:
                self.retries += 1
            attempt_started = time.monotonic()
            try:
                response = self.session.get(
                    url,
                    timeout=self.timeout,
                    retries=1,  # retries are owned here, not by the transport
                    follow_redirects=True,
                )
            except Exception as exc:  # network / TLS / timeout / transport error
                self.last_end = time.monotonic()
                last_error = f"{type(exc).__name__}: {exc}"
                last_class = "transport_error"
                self.per_status["transport_error"] = self.per_status.get("transport_error", 0) + 1
                self._event(
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "event": "http_attempt",
                        "url": url,
                        "purpose": purpose,
                        "attempt": attempts,
                        "status": None,
                        "error": last_error,
                        "duration_s": round(time.monotonic() - attempt_started, 3),
                    }
                )
                if attempts < self.max_attempts:
                    time.sleep(min(2 ** (attempts - 1), 4))
                    continue
                return FetchOutcome(
                    url=url,
                    status=None,
                    attempts=attempts,
                    error=last_error,
                    error_class=last_class,
                    elapsed_s=time.monotonic() - started,
                )

            self.last_end = time.monotonic()
            status = int(response.status)
            last_status = status
            self.per_status[f"status_{status}"] = self.per_status.get(f"status_{status}", 0) + 1
            retry_after = parse_retry_after(response.headers)
            last_retry_after = retry_after
            self._event(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "event": "http_attempt",
                    "url": url,
                    "purpose": purpose,
                    "attempt": attempts,
                    "status": status,
                    "final_url": getattr(response, "url", url),
                    "bytes": len(getattr(response, "body", b"") or b""),
                    "retry_after": retry_after,
                    "duration_s": round(time.monotonic() - attempt_started, 3),
                }
            )

            if status == 429:
                last_error = f"HTTP 429 (attempt {attempts}/{self.max_attempts})"
                last_class = "http_429"
                if attempts >= self.max_attempts:
                    raise AccessDenied(
                        f"HTTP 429 persisted after {attempts} attempts; Retry-After={retry_after}"
                    )
                wait = retry_after if retry_after is not None else min(2 ** attempts, 8)
                if wait > self.max_retry_after:
                    raise AccessDenied(
                        f"HTTP 429 asks Retry-After={wait:.0f}s, above the {self.max_retry_after:.0f}s bound"
                    )
                time.sleep(wait)
                continue

            if status in (401, 403):
                raise AccessDenied(f"HTTP {status} on {url}")

            if status >= 500:
                last_error = f"HTTP {status}"
                last_class = "http_5xx"
                if attempts < self.max_attempts:
                    time.sleep(min(2 ** (attempts - 1), 4))
                    continue
                return FetchOutcome(
                    url=url,
                    status=status,
                    attempts=attempts,
                    error=last_error,
                    error_class=last_class,
                    retry_after=retry_after,
                    elapsed_s=time.monotonic() - started,
                )

            return FetchOutcome(
                url=url,
                status=status,
                response=response,
                attempts=attempts,
                retry_after=retry_after,
                elapsed_s=time.monotonic() - started,
            )

        return FetchOutcome(
            url=url,
            status=last_status,
            attempts=attempts,
            error=last_error,
            error_class=last_class,
            retry_after=last_retry_after,
            elapsed_s=time.monotonic() - started,
        )
