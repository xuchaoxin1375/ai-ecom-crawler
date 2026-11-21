"""Normalize OpenCode events into the stable build-session vocabulary."""

from __future__ import annotations

from typing import Any

from .models import HarnessEvent, utc_now

# OpenCode event names are experimental; keep the mapping in one place so an
# upstream rename fails tests instead of leaking into the build UI.
EVENT_MAP: dict[str, tuple[str, dict[str, Any]]] = {
    "server.connected": ("server_connected", {}),
    "session.created": ("progress", {"phase": "created"}),
    "session.execution.started": ("phase_changed", {"phase": "executing"}),
    "session.execution.succeeded": ("finished", {"outcome": "succeeded"}),
    "session.execution.failed": ("error", {"outcome": "failed"}),
    "session.execution.interrupted": ("finished", {"outcome": "interrupted"}),
    "session.step.started": ("progress", {"phase": "step_started"}),
    "session.step.ended": ("progress", {"phase": "step_ended"}),
    "session.step.failed": ("error", {"phase": "step_failed"}),
    "session.tool.called": ("tool_started", {}),
    "session.tool.success": ("tool_finished", {"status": "success"}),
    "session.tool.failed": ("tool_finished", {"status": "failed"}),
    "permission.asked": ("permission_requested", {}),
    "permission.replied": ("permission_replied", {}),
    "session.text.delta": ("message_delta", {}),
    "session.text.started": ("progress", {"phase": "text_started"}),
    "session.text.ended": ("progress", {"phase": "text_ended"}),
    "session.idle": ("progress", {"phase": "idle"}),
    "session.status": ("progress", {}),
}

REASONING_PREFIX = "session.reasoning."


def _data_of(raw: dict[str, Any]) -> dict[str, Any]:
    data = raw.get("data")
    if isinstance(data, dict):
        return data
    properties = raw.get("properties")
    if isinstance(properties, dict):
        return properties
    return {}


def _session_id(data: dict[str, Any], raw: dict[str, Any]) -> str | None:
    for source in (data, raw):
        value = source.get("sessionID") or source.get("session_id")
        if value:
            return str(value)
    return None


def _tool_name(data: dict[str, Any]) -> str | None:
    native = data.get("native")
    if isinstance(native, dict):
        for key in ("name", "tool", "id"):
            value = native.get(key)
            if value:
                return str(value)
    for key in ("name", "tool", "id"):
        value = data.get(key)
        if value:
            return str(value)
    return None


def _summary(raw_type: str, data: dict[str, Any]) -> dict[str, Any]:
    if raw_type == "server.connected":
        return {}
    if raw_type == "session.tool.called":
        summary: dict[str, Any] = {"tool": _tool_name(data)}
        if "id" in data:
            summary["call_id"] = data["id"]
        return summary
    if raw_type == "session.text.delta":
        delta = str(data.get("delta") or "")
        return {"delta": delta[:2000], "truncated": len(delta) > 2000}
    if raw_type == "permission.asked":
        return {
            key: data[key]
            for key in ("id", "action", "resources", "save", "message")
            if key in data
        }
    if raw_type == "permission.replied":
        return {
            key: data[key]
            for key in ("requestID", "reply")
            if key in data
        }
    if raw_type in {
        "session.execution.succeeded",
        "session.execution.failed",
        "session.execution.interrupted",
    }:
        return {
            key: data[key]
            for key in ("outcome", "error", "message")
            if key in data
        }
    if raw_type == "session.status":
        status = data.get("status")
        return {"status": status} if status is not None else {}
    # Unknown or low-value events: keep a short, explicit summary rather than
    # the entire payload, which can contain prompts, tool output or reasoning.
    return {
        "keys": sorted(str(key) for key in data)[:40],
    }


def normalize_event(raw: dict[str, Any]) -> HarnessEvent:
    """Map one raw OpenCode event to a stable build event.

    Reasoning deltas and other private content are dropped before the event is
    persisted.  Unknown events keep their source type and a key summary.
    """
    raw_type = str(raw.get("type") or raw.get("event") or "unknown")
    data = _data_of(raw)
    session_id = _session_id(data, raw)
    created_at = utc_now()
    if isinstance(raw.get("created"), (int, float)):
        from datetime import UTC, datetime

        created_at = (
            datetime.fromtimestamp(float(raw["created"]) / 1000, UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )

    if raw_type.startswith(REASONING_PREFIX):
        return HarnessEvent(
            type="reasoning_event",
            source_type=raw_type,
            session_id=session_id,
            data={"redacted": True},
            created_at=created_at,
        )

    normalized, extra = EVENT_MAP.get(raw_type, ("other", {}))
    summary = _summary(raw_type, data)
    summary.update(extra)
    return HarnessEvent(
        type=normalized,
        source_type=raw_type,
        session_id=session_id,
        data=summary,
        created_at=created_at,
        raw=None,
    )
