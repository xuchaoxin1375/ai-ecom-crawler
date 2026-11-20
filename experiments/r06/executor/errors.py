"""Exceptions used by the R06 declarative executor."""

from __future__ import annotations


class StopRun(Exception):
    """A condition that stops the whole run and is reported as stop_reason."""

    stop_reason = "OTHER"


class AccessDenied(StopRun):
    stop_reason = "ACCESS_DENIED"


class BudgetExhausted(StopRun):
    stop_reason = "BUDGET_EXHAUSTED"


class PlanError(StopRun):
    stop_reason = "PLAN_ERROR"


class EnvironmentFailure(StopRun):
    stop_reason = "ENVIRONMENT_ERROR"


class HttpStatusError(Exception):
    """A non-2xx response that is handled per product instead of stopping the run."""

    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"HTTP {status} for {url}")
        self.status = status
        self.url = url


class TransportError(Exception):
    """A transport failure after all retry attempts."""
