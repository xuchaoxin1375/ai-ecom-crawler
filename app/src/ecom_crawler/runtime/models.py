"""Serializable task, work item and fetch result models."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

TASK_TYPES = {"discovery", "product"}
TASK_STATES = {
    "DRAFT",
    "QUEUED",
    "RUNNING",
    "PAUSING",
    "PAUSED",
    "CANCELLING",
    "CANCELLED",
    "FINISHED",
}
TERMINAL_TASK_STATES = {"CANCELLED", "FINISHED"}
ITEM_TYPES = {"navigation", "product"}
ITEM_STATES = {"PENDING", "IN_FLIGHT", "DONE", "EXCLUDED", "FAILED"}
FAILURE_CLASSES = {"transient", "permanent", "blocked"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


@dataclass
class Task:
    task_id: str
    plan_id: str
    plan_version: str
    task_type: str
    state: str = "DRAFT"
    outcome: str | None = None
    stop_reason: str | None = None
    input: dict[str, Any] = field(default_factory=dict)
    limits: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    counters: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    finished_at: str | None = None
    site_key: str | None = None
    domain_key: str | None = None
    market: str | None = None
    rule_path: str | None = None
    archived_at: str | None = None
    batch_id: str | None = None
    lease_owner: str | None = None
    lease_token: int = 0
    lease_expires_at: float | None = None
    lease_heartbeat_at: float | None = None

    def __post_init__(self) -> None:
        if self.task_type not in TASK_TYPES:
            raise ValueError(f"unsupported task_type: {self.task_type!r}")
        if self.state not in TASK_STATES:
            raise ValueError(f"unsupported task state: {self.state!r}")


@dataclass(frozen=True)
class Lease:
    """A time-boxed task ownership token used to fence stale writers.

    ``token`` is monotonically increasing per task.  A worker must present the
    same owner and token for every write and renew before ``expires_at``; after
    a takeover both checks fail for the previous holder.
    """

    task_id: str
    owner: str
    token: int
    expires_at: float


@dataclass
class Batch:
    """A user-facing project that groups imported sites.

    ``status`` is deliberately not stored: it is derived from member sites and
    tasks by the service layer.  The batch itself is only an organizing object.
    """

    batch_id: str
    name: str
    country: str | None = None
    market: str | None = None
    language: str | None = None
    category: str | None = None
    note: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    archived_at: str | None = None


BATCH_READINESS = {
    "ready",
    "needs_onboarding",
    "building",
    "invalid",
    "duplicate",
}

BUILD_STATES = {
    "CREATED",
    "RUNNING",
    "PAUSING",
    "PAUSED",
    "CANCELLING",
    "CANCELLED",
    "VALIDATING",
    "FINISHED",
}


@dataclass
class BatchSite:
    batch_id: str
    site_key: str
    domain: str
    input_value: str
    readiness: str
    rule_id: str | None = None
    rule_version: str | None = None
    rule_path: str | None = None
    task_id: str | None = None
    build_id: str | None = None
    proxy: str | None = None
    note: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.readiness not in BATCH_READINESS:
            raise ValueError(f"unsupported batch readiness: {self.readiness!r}")


@dataclass
class BuildRecord:
    """A build-session record linked to one batch site.

    Harness session state still lives in ``BuildService`` while the process is
    running; this ledger row is the durable view used by the API and restart
    reconciliation.  ``VALIDATING`` is host-side rule verification, not an
    OpenCode session state.
    """

    build_id: str
    batch_id: str
    site_key: str
    state: str = "CREATED"
    outcome: str | None = None
    workspace: str | None = None
    session_id: str | None = None
    model: dict[str, Any] | None = None
    proxy: str | None = None
    error: str | None = None
    rule_id: str | None = None
    rule_version: str | None = None
    rule_path: str | None = None
    mode: str = "build"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    finished_at: str | None = None

    def __post_init__(self) -> None:
        if self.state not in BUILD_STATES:
            raise ValueError(f"unsupported build state: {self.state!r}")
        if self.mode not in {"build", "repair"}:
            raise ValueError(f"unsupported build mode: {self.mode!r}")


@dataclass
class WorkItem:
    task_id: str
    item_id: str
    item_type: str
    url: str
    normalized_url: str
    stage: str = "discover"
    state: str = "PENDING"
    attempts: int = 0
    failure_class: str | None = None
    parent_url: str | None = None
    discovered_from: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.item_type not in ITEM_TYPES:
            raise ValueError(f"unsupported item_type: {self.item_type!r}")
        if self.state not in ITEM_STATES:
            raise ValueError(f"unsupported item state: {self.state!r}")
        if self.failure_class is not None and self.failure_class not in FAILURE_CLASSES:
            raise ValueError(f"unsupported failure_class: {self.failure_class!r}")


@dataclass
class FetchResult:
    status: int
    url: str
    body: bytes = b""
    error: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300
