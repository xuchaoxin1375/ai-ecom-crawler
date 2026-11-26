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
    rule_sha256: str | None = None
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
    collection_mode: str | None = None
    folder_id: str | None = None


@dataclass
class BatchFolder:
    """A user-created, nestable grouping for batches.

    Folders only change how batches are presented.  They never own tasks,
    results or delivery records, so dissolving a folder must not delete work.
    """

    folder_id: str
    name: str
    parent_id: str | None = None
    sort_order: int = 0
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


BATCH_READINESS = {
    "ready",
    "needs_onboarding",
    "building",
    "invalid",
    "duplicate",
}

BUILD_STATES = {
    "QUEUED",
    "CREATED",
    "RUNNING",
    "PAUSING",
    "PAUSED",
    "CANCELLING",
    "CANCELLED",
    "VALIDATING",
    "FINISHED",
}

FEEDBACK_STATUSES = {
    "OPEN",
    "TRIAGED",
    "REPAIRING",
    "AWAITING_ACTIVATION",
    "AWAITING_RERUN",
    "RERUN_PENDING",
    "RESOLVED",
    "WONTFIX",
}

FEEDBACK_CATEGORIES = {
    "DISCOVERY",
    "IDENTITY",
    "PRICE_CURRENCY_UNIT",
    "DESCRIPTION",
    "BASIC_FIELDS",
    "ACCESS_RUNTIME",
    "BUSINESS_EXPECTATION",
    "OTHER",
}

FEEDBACK_TRIAGE = {"RULE_REPAIR", "RUNTIME", "BUSINESS", "DUPLICATE"}
FEEDBACK_RESOLUTIONS = {"RESOLVED", "WONTFIX", "DUPLICATE"}

RULE_VERSION_STATUSES = {"candidate", "active", "superseded", "rejected", "retired"}
RULE_ACTIONS = {"activate", "rollback"}


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
    delivery_task_id: str | None = None

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
    feedback_id: str | None = None
    request_id: str | None = None
    request: dict[str, Any] = field(default_factory=dict)
    source_rule_version: str | None = None
    source_rule_sha256: str | None = None
    target_rule_version: str | None = None
    target_rule_sha256: str | None = None
    error_class: str | None = None
    change_summary: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    evidence_sha256: str | None = None
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
class QualityFeedback:
    """A user's recorded judgement that a task result is not acceptable."""

    feedback_id: str
    request_id: str
    task_id: str
    category: str
    expectation: str
    status: str = "OPEN"
    batch_id: str | None = None
    site_key: str | None = None
    rule_id: str | None = None
    rule_version: str | None = None
    rule_sha256: str | None = None
    samples: list[str] = field(default_factory=list)
    note: str | None = None
    scope: str = "Task-scoped review."
    triage: str | None = None
    triage_note: str | None = None
    triage_source: str | None = None
    duplicate_of: str | None = None
    repair_build_id: str | None = None
    rerun_task_id: str | None = None
    resolution: str | None = None
    resolution_note: str | None = None
    created_by: str = "local-user"
    resolved_by: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    closed_at: str | None = None
    request_json: str = ""

    def __post_init__(self) -> None:
        if self.status not in FEEDBACK_STATUSES:
            raise ValueError(f"unsupported feedback status: {self.status!r}")
        if self.category not in FEEDBACK_CATEGORIES:
            raise ValueError(f"unsupported feedback category: {self.category!r}")
        if self.triage is not None and self.triage not in FEEDBACK_TRIAGE:
            raise ValueError(f"unsupported feedback triage: {self.triage!r}")
        if self.resolution is not None and self.resolution not in FEEDBACK_RESOLUTIONS:
            raise ValueError(f"unsupported feedback resolution: {self.resolution!r}")


@dataclass
class BuildContinuation:
    """An idempotent user request to continue one finished build session."""

    request_id: str
    build_id: str
    message_sha256: str
    message_chars: int
    state: str = "ACCEPTED"
    error: str | None = None
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.state not in {"ACCEPTED", "FAILED"}:
            raise ValueError(f"unsupported continuation state: {self.state!r}")


@dataclass
class RuleVersion:
    rule_id: str
    rule_version: str
    sha256: str
    path: str
    status: str = "candidate"
    parent_version: str | None = None
    source_build_id: str | None = None
    source_feedback_id: str | None = None
    created_at: str = field(default_factory=utc_now)
    activated_at: str | None = None
    activated_by: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.status not in RULE_VERSION_STATUSES:
            raise ValueError(f"unsupported rule version status: {self.status!r}")


@dataclass
class SiteRule:
    site_key: str
    rule_id: str
    rule_version: str
    sha256: str
    path: str
    updated_at: str = field(default_factory=utc_now)


@dataclass
class RuleActivation:
    activation_id: str
    request_id: str
    site_key: str
    rule_id: str
    action: str
    to_version: str
    to_sha256: str
    from_version: str | None = None
    from_sha256: str | None = None
    reason: str | None = None
    actor: str = "local-user"
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.action not in RULE_ACTIONS:
            raise ValueError(f"unsupported rule action: {self.action!r}")


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
