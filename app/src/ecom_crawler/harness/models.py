"""Serializable build-task and normalized event models."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

BUILD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class BuildTask:
    """Build-side input from ADR 0005.

    Only the fields the adapter needs are interpreted; the rest is preserved
    so the BuildService can add policy without changing the adapter.
    """

    build_id: str
    site: dict[str, Any] = field(default_factory=dict)
    scope: dict[str, Any] = field(default_factory=dict)
    market: str | None = None
    locale: str | None = None
    limits: dict[str, Any] = field(default_factory=dict)
    tools: list[str] = field(default_factory=list)
    model: dict[str, Any] | None = None
    workspace: str | None = None
    output_dir: str | None = None
    data_standard_version: str = "docs/02"
    notes: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not BUILD_ID_RE.fullmatch(self.build_id):
            raise ValueError(
                "build_id must match [A-Za-z0-9][A-Za-z0-9._-]{0,127}"
            )
        if self.model is not None and not {
            "providerID",
            "id",
        } <= set(self.model):
            raise ValueError("model must include providerID and id")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "build_id": self.build_id,
            "site": self.site,
            "scope": self.scope,
            "market": self.market,
            "locale": self.locale,
            "limits": self.limits,
            "tools": self.tools,
            "model": self.model,
            "workspace": self.workspace,
            "output_dir": self.output_dir,
            "data_standard_version": self.data_standard_version,
            "notes": self.notes,
        }
        payload.update(self.extra)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BuildTask:
        known = {
            "build_id",
            "site",
            "scope",
            "market",
            "locale",
            "limits",
            "tools",
            "model",
            "workspace",
            "output_dir",
            "data_standard_version",
            "notes",
        }
        extra = {key: value for key, value in payload.items() if key not in known}
        return cls(
            build_id=str(payload.get("build_id") or ""),
            site=dict(payload.get("site") or {}),
            scope=dict(payload.get("scope") or {}),
            market=payload.get("market"),
            locale=payload.get("locale"),
            limits=dict(payload.get("limits") or {}),
            tools=[str(item) for item in payload.get("tools") or []],
            model=payload.get("model"),
            workspace=payload.get("workspace"),
            output_dir=payload.get("output_dir"),
            data_standard_version=str(
                payload.get("data_standard_version") or "docs/02"
            ),
            notes=payload.get("notes"),
            extra=extra,
        )


@dataclass(frozen=True)
class HarnessEvent:
    """A normalized event safe to write to ``out/session.ndjson``."""

    type: str
    source_type: str
    session_id: str | None
    data: dict[str, Any]
    created_at: str
    raw: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "type": self.type,
            "source_type": self.source_type,
            "session_id": self.session_id,
            "data": self.data,
            "created_at": self.created_at,
        }
        if self.raw is not None:
            payload["raw"] = self.raw
        return payload
