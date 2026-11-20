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
    rule_id: str
    rule_version: str
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

    def __post_init__(self) -> None:
        if self.task_type not in TASK_TYPES:
            raise ValueError(f"unsupported task_type: {self.task_type!r}")
        if self.state not in TASK_STATES:
            raise ValueError(f"unsupported task state: {self.state!r}")


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
    parent_url: str | None = None
    discovered_from: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.item_type not in ITEM_TYPES:
            raise ValueError(f"unsupported item_type: {self.item_type!r}")
        if self.state not in ITEM_STATES:
            raise ValueError(f"unsupported item state: {self.state!r}")


@dataclass
class FetchResult:
    status: int
    url: str
    body: bytes = b""
    error: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300
