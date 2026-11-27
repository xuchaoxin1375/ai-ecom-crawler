"""Sanitized build-session traces for review and efficiency analysis.

The raw OpenCode export can contain full page text, file contents, commands and
provider metadata.  This module keeps the useful review surface - phases, tool
names, commands/selectors, truncated outputs, visible assistant messages and
token/cost/timing totals - while dropping private reasoning and secret-like
values.  Raw exports are never written to the repository by default.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any

SECRET_RE = re.compile(
    r"(?i)(authorization|api[_-]?key|access[_-]?token|password|secret|bearer)"
    r"(\s*[:=]\s*|\s+)([^\s\"']+)"
)
BEARER_RE = re.compile(r"(?i)\bbearer\s+[^\s\"']+")
OUTPUT_LIMIT = 2000
MESSAGE_LIMIT = 4000
COMMAND_LIMIT = 2000
REASONING_LIMIT = 4000
REASONING_TOTAL_LIMIT = 20000


def _iso(value: Any) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    return (
        datetime.fromtimestamp(float(value) / 1000, UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _truncate(value: Any, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… truncated ({len(text)} chars total)"


def _redact(text: str) -> str:
    text = BEARER_RE.sub("Bearer ***", text)
    return SECRET_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}***", text)


def _tool_input(input_value: Any) -> Any:
    if not isinstance(input_value, dict):
        return _truncate(_redact(str(input_value)), COMMAND_LIMIT)
    if "command" in input_value:
        return {"command": _truncate(_redact(str(input_value["command"])), COMMAND_LIMIT)}
    if "url" in input_value:
        return {"url": _truncate(_redact(str(input_value["url"])), COMMAND_LIMIT)}
    if "filePath" in input_value or "path" in input_value:
        result: dict[str, Any] = {}
        for key in ("filePath", "path", "offset", "limit", "pattern", "glob"):
            if key in input_value:
                result[key] = _truncate(_redact(str(input_value[key])), COMMAND_LIMIT)
        for key in ("content", "newString", "oldString", "text"):
            if key in input_value:
                result[f"{key}_chars"] = len(str(input_value[key] or ""))
        return result
    result = {}
    for key, value in input_value.items():
        if key in {"content", "newString", "oldString", "text"}:
            result[f"{key}_chars"] = len(str(value or ""))
        else:
            result[key] = _truncate(_redact(str(value)), COMMAND_LIMIT)
    return result


def _looks_like_html(text: str) -> bool:
    head = text[:2000].lower()
    return "<!doctype html" in head or "<html" in head or "<head" in head


def _tool_output(state: dict[str, Any]) -> str:
    content = state.get("content")
    chunks: list[str] = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                chunks.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                chunks.append(item)
    raw = "\n".join(chunks).strip()
    if _looks_like_html(raw):
        return f"[HTML output suppressed: {len(raw)} chars]"
    return _truncate(_redact(raw), OUTPUT_LIMIT)


def summarize_tool_input(value: Any) -> Any:
    """Return a safe, bounded tool-input summary for live timeline events.

    OpenCode streams the tool input as JSON text in ``session.tool.input.ended``;
    completed builds expose the parsed input on the tool part.  Both shapes are
    accepted here so the live timeline can show the same details as the trace.
    """
    if value is None or value == "":
        return None
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in {"{", "["}:
            try:
                value = json.loads(text)
            except (TypeError, ValueError):
                return _truncate(_redact(text), COMMAND_LIMIT)
        else:
            return _truncate(_redact(text), COMMAND_LIMIT)
    return _tool_input(value)


def summarize_tool_output(value: Any) -> str:
    """Return a safe, bounded tool-output summary for live timeline events."""
    if value is None:
        return ""
    if isinstance(value, dict):
        if "content" in value or "output" in value or "result" in value:
            raw = value.get("content", value.get("output", value.get("result")))
        else:
            raw = value
    else:
        raw = value
    if isinstance(raw, list):
        return _tool_output({"content": raw})
    if isinstance(raw, dict):
        return _truncate(_redact(json.dumps(raw, ensure_ascii=False)), OUTPUT_LIMIT)
    text = str(raw or "")
    if _looks_like_html(text):
        return f"[HTML output suppressed: {len(text)} chars]"
    return _truncate(_redact(text), OUTPUT_LIMIT)


def _tool_trace(part: dict[str, Any]) -> dict[str, Any]:
    state = part.get("state") if isinstance(part.get("state"), dict) else {}
    timing = part.get("time") if isinstance(part.get("time"), dict) else {}
    created = timing.get("created")
    completed = timing.get("completed")
    duration_ms = None
    if isinstance(created, (int, float)) and isinstance(completed, (int, float)):
        duration_ms = max(0, int(completed - created))
    metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
    return {
        "name": str(part.get("name") or "unknown"),
        "status": str(state.get("status") or ""),
        "input": _tool_input(state.get("input")),
        "output": _tool_output(state),
        "exit": metadata.get("exit"),
        "truncated": bool(metadata.get("truncated")),
        "created_at": _iso(created),
        "completed_at": _iso(completed),
        "duration_ms": duration_ms,
    }


def _message_trace(message: dict[str, Any]) -> dict[str, Any] | None:
    content = message.get("content")
    if not isinstance(content, list):
        return None
    texts = [
        str(part.get("text") or "")
        for part in content
        if isinstance(part, dict) and part.get("type") == "text"
    ]
    if not texts:
        return None
    return {
        "created_at": _iso((message.get("time") or {}).get("created")),
        "text": _truncate(_redact("\n".join(texts).strip()), MESSAGE_LIMIT),
    }


def build_trace(
    export: dict[str, Any] | None,
    *,
    build_id: str,
    model: dict[str, Any] | None,
    events: list[dict[str, Any]] | None = None,
    validation: dict[str, Any] | None = None,
    repairs: list[dict[str, Any]] | None = None,
    repair_limit: int = 0,
    error: str | None = None,
    capture_reasoning: bool = False,
) -> dict[str, Any]:
    """Convert a raw OpenCode export into a review-safe trace.

    Only ``tool`` and visible ``text`` content is retained by default.
    Reasoning parts are included only with ``capture_reasoning``; they are
    truncated and marked local-review-only.  Tool outputs and messages are
    truncated and secret-like values are redacted.
    """
    export = export or {}
    info = export.get("info") if isinstance(export.get("info"), dict) else {}
    messages = export.get("messages") if isinstance(export.get("messages"), list) else []

    tools: list[dict[str, Any]] = []
    visible: list[dict[str, Any]] = []
    reasoning: list[dict[str, Any]] = []
    reasoning_chars = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("type") == "assistant":
            content = message.get("content")
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    part_type = part.get("type")
                    if part_type == "tool":
                        tools.append(_tool_trace(part))
                    elif part_type == "text":
                        text = str(part.get("text") or "").strip()
                        if text:
                            visible.append(
                                {
                                    "created_at": _iso(
                                        (message.get("time") or {}).get("created")
                                    ),
                                    "text": _truncate(_redact(text), MESSAGE_LIMIT),
                                }
                            )
                    elif part_type == "reasoning" and capture_reasoning:
                        text = str(part.get("text") or "").strip()
                        if not text:
                            continue
                        clipped = _truncate(_redact(text), REASONING_LIMIT)
                        remaining = max(0, REASONING_TOTAL_LIMIT - reasoning_chars)
                        if remaining <= 0:
                            continue
                        clipped = clipped[:remaining]
                        reasoning_chars += len(clipped)
                        reasoning.append(
                            {
                                "created_at": _iso(
                                    (part.get("time") or {}).get("created")
                                ),
                                "text": clipped,
                            }
                        )
            continue
        if message.get("type") == "user":
            item = _message_trace(message)
            if item is not None:
                visible.append({"role": "user", **item})

    by_tool = Counter(tool["name"] for tool in tools)
    failed_tools = sum(1 for tool in tools if tool["status"] not in {"completed", ""})
    phases = [
        {
            "type": str(event.get("type") or ""),
            "phase": str((event.get("data") or {}).get("phase") or ""),
            "created_at": event.get("created_at"),
        }
        for event in (events or [])
        if event.get("type") in {"phase_changed", "finished", "error"}
    ]
    return {
        "build_id": build_id,
        "model": model or info.get("model"),
        "agent_outcome": info.get("outcome"),
        "outcome": "failed" if error else info.get("outcome"),
        "error": error,
        "tokens": info.get("tokens"),
        "cost": info.get("cost"),
        "time": {
            "created_at": _iso((info.get("time") or {}).get("created")),
            "updated_at": _iso((info.get("time") or {}).get("updated")),
            "created_ms": (info.get("time") or {}).get("created"),
            "updated_ms": (info.get("time") or {}).get("updated"),
        },
        "counts": {
            "tools": len(tools),
            "failed_tools": failed_tools,
            "by_tool": dict(sorted(by_tool.items())),
            "messages": len(visible),
            "reasoning_parts": len(reasoning),
            "reasoning_chars": reasoning_chars,
        },
        "phases": phases,
        "tools": tools,
        "messages": visible,
        "reasoning": reasoning,
        "reasoning_retained": bool(reasoning),
        "validation": validation,
        "repairs": repairs or [],
        "repair_limit": int(repair_limit or 0),
        "limitations": [
            (
                "Trace is sanitized and truncated; reasoning is retained only "
                "because capture_reasoning was explicitly enabled."
                if reasoning
                else "Trace is sanitized and truncated; private reasoning is not retained."
            ),
            "Raw OpenCode export, full page HTML and file contents are not stored in this trace.",
        ],
    }


def render_trace_markdown(trace: dict[str, Any]) -> str:
    """Render a compact human-readable review sheet."""
    lines = [
        f"# Build trace: {trace.get('build_id')}",
        "",
        f"- Build outcome: `{trace.get('outcome') or '-'}`",
        f"- Agent outcome: `{trace.get('agent_outcome') or '-'}`",
        f"- Model: `{json.dumps(trace.get('model'), ensure_ascii=False)}`",
        (
            f"- Tools: {trace.get('counts', {}).get('tools', 0)} "
            f"(failed: {trace.get('counts', {}).get('failed_tools', 0)})"
        ),
        f"- Messages: {trace.get('counts', {}).get('messages', 0)}",
    ]
    tokens = trace.get("tokens")
    if tokens:
        lines.append(f"- Tokens: `{json.dumps(tokens, ensure_ascii=False)}`")
    cost = trace.get("cost")
    if cost is not None:
        lines.append(f"- Cost: `{cost}`")
    if trace.get("error"):
        lines.append(f"- Error: `{trace['error']}`")
    lines.extend(["", "## Tools", "", "| Time | Tool | Status | Duration | Input |", "| --- | --- | --- | --- | --- |"])
    for tool in trace.get("tools", []):
        input_value = tool.get("input")
        if isinstance(input_value, dict):
            input_text = json.dumps(input_value, ensure_ascii=False)
        else:
            input_text = str(input_value or "")
        input_text = input_text.replace("|", "\\|").replace("\n", " ")[:240]
        lines.append(
            f"| {tool.get('created_at') or '-'} | {tool.get('name')} | "
            f"{tool.get('status') or '-'} | {tool.get('duration_ms') or '-'} ms | "
            f"`{input_text}` |"
        )
    if trace.get("validation"):
        lines.extend(
            [
                "",
                "## Host validation",
                "",
                "```json",
                json.dumps(trace["validation"], ensure_ascii=False, indent=2),
                "```",
            ]
        )
    if trace.get("repairs"):
        lines.extend(
            [
                "",
                f"## Automatic repair rounds ({trace.get('repair_limit', 0)} allowed)",
                "",
            ]
        )
        for repair in trace["repairs"]:
            status = "resolved" if repair.get("resolved") else "not resolved"
            lines.append(
                f"- Round {repair.get('round')} ({status}, "
                f"{repair.get('started_at') or '-'}): {repair.get('error')}"
            )
    if trace.get("messages"):
        lines.extend(["", "## Visible messages", ""])
        for message in trace["messages"]:
            lines.append(f"- {message.get('created_at') or '-'}: {message.get('text')}")
    if trace.get("reasoning"):
        lines.extend(
            [
                "",
                "## Reasoning (local review only)",
                "",
                (
                    "> Explicitly enabled; truncated. Do not commit if it contains "
                    "private or proprietary content."
                ),
                "",
            ]
        )
        for item in trace["reasoning"]:
            lines.append(f"- {item.get('created_at') or '-'}: {item.get('text')}")
    lines.extend(
        [
            "",
            "> Sanitized trace: raw page HTML and file contents are not retained.",
            "",
        ]
    )
    return "\n".join(lines)
