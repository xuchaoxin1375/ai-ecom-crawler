"""Host-side rule diff and validation normalisation.

A build Agent may propose a candidate rule, but the change summary and the
validation report are host outputs.  These helpers compare the candidate
payload with its parent and turn the raw bounded-validation result into the
shape described by ``docs/schema/v2-build-change-summary.schema.json`` and
``docs/schema/v2-build-validation.schema.json``.  They never call the network
and never trust an Agent-authored summary.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Bookkeeping keys change on every build and must not count as rule changes.
_METADATA_KEYS = {
    "rule_id",
    "rule_version",
    "status",
    "updated_at",
    "created_at",
    "generated_at",
    "evidence",
}
_MAX_CHANGED_FIELDS = 60
_MAX_CHANGED_SELECTORS = 20
_MAX_DIFF_DEPTH = 4


def canonical_sha256(payload: Any) -> str:
    """Hash a JSON-compatible payload deterministically."""

    text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _walk_changes(
    old: Any,
    new: Any,
    path: str,
    depth: int,
    changed: list[str],
) -> None:
    if old == new:
        return
    if depth > _MAX_DIFF_DEPTH:
        if path:
            changed.append(path)
        return
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted({str(item) for item in old} | {str(item) for item in new}):
            if not path and key in _METADATA_KEYS:
                continue
            child_path = f"{path}.{key}" if path else key
            if key not in old or key not in new:
                changed.append(child_path)
                continue
            _walk_changes(old[key], new[key], child_path, depth + 1, changed)
        return
    if path:
        changed.append(path)


def _collect_selectors(
    node: Any,
    path: str,
    selectors: dict[str, str],
) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else str(key)
            if isinstance(value, str) and "selector" in str(key).lower():
                selectors[child_path] = value
            else:
                _collect_selectors(value, child_path, selectors)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _collect_selectors(item, f"{path}.{index}", selectors)


def _coalesce_paths(paths: list[str]) -> list[str]:
    """Keep extract field paths at the field level for readable summaries."""

    coalesced: set[str] = set()
    for path in paths:
        parts = path.split(".")
        if len(parts) > 3 and parts[0] == "extract" and parts[1] == "fields":
            coalesced.add(".".join(parts[:3]))
        else:
            coalesced.add(path)
    return sorted(coalesced)


def _selector_path(path: str) -> str:
    parts = path.split(".")
    if len(parts) >= 3 and parts[0] == "extract" and parts[1] == "fields":
        return ".".join(parts[:3])
    return path


def changed_selectors(old_payload: Any, new_payload: Any) -> list[str]:
    """Return selector paths whose value or location changed."""

    old_selectors: dict[str, str] = {}
    new_selectors: dict[str, str] = {}
    _collect_selectors(old_payload, "", old_selectors)
    _collect_selectors(new_payload, "", new_selectors)
    changed = {
        _selector_path(path)
        for path in set(old_selectors) | set(new_selectors)
        if old_selectors.get(path) != new_selectors.get(path)
    }
    return sorted(changed)[:_MAX_CHANGED_SELECTORS]


def build_change_summary(
    old_payload: Any,
    new_payload: Any,
    *,
    rule_id: str,
    rule_version: str,
    parent_version: str | None,
) -> dict[str, Any]:
    """Compare a candidate rule with its parent.

    ``parent_version`` is recorded even when the parent file could not be
    read; in that case ``old_payload`` should be ``None`` and the summary says
    explicitly that no field comparison was possible.
    """

    old = old_payload if isinstance(old_payload, dict) else {}
    new = new_payload if isinstance(new_payload, dict) else {}
    changed: list[str] = []
    if parent_version is None:
        notes = "initial build; no parent rule to compare"
    elif not old:
        notes = "parent rule file was not readable; no field comparison"
    else:
        _walk_changes(old, new, "", 0, changed)
        changed = _coalesce_paths(changed)
        if len(changed) > _MAX_CHANGED_FIELDS:
            notes = (
                f"{len(changed)} fields changed; only the first "
                f"{_MAX_CHANGED_FIELDS} are listed"
            )
        elif changed:
            notes = f"{len(changed)} field(s) changed against parent"
        else:
            notes = "no field changes detected against parent"

    selectors = (
        changed_selectors(old, new)
        if parent_version is not None and old
        else []
    )
    return {
        "rule_id": rule_id,
        "rule_version": rule_version,
        "parent_version": parent_version,
        "changed_fields": changed[:_MAX_CHANGED_FIELDS],
        "changed_selectors": selectors,
        "discovery_changed": old.get("discovery") != new.get("discovery"),
        "scope_changed": old.get("scope") != new.get("scope"),
        "market_changed": _nested(old, "site", "market")
        != _nested(new, "site", "market"),
        "currency_changed": _nested(old, "site", "currency")
        != _nested(new, "site", "currency"),
        "notes": notes,
    }


def _nested(payload: Any, *keys: str) -> Any:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def normalize_validation(
    raw: dict[str, Any] | None,
    change_summary: dict[str, Any] | None,
    *,
    status: str = "PASSED",
    error_class: str | None = None,
) -> dict[str, Any]:
    """Return a validation payload that satisfies the v2 schema.

    Raw host counts stay in the payload as additional properties so the UI and
    existing tests can keep reading ``valid_products`` and friends.  Only
    fields actually produced by the host are filled in; no cross-version
    regression is invented when the bounded run did not check one.
    """

    source = raw if isinstance(raw, dict) else {}
    summary = change_summary if isinstance(change_summary, dict) else {}
    audit = source.get("content_audit")
    audit = audit if isinstance(audit, dict) else {}

    issue_checks: list[dict[str, Any]] = []
    for sample in audit.get("samples") or []:
        if not isinstance(sample, dict):
            continue
        url = str(sample.get("source_url") or "").strip()
        if not url:
            continue
        missing = [
            str(block)
            for block in (sample.get("missing_blocks") or [])
            if str(block).strip()
        ]
        issue_checks.append(
            {
                "sample": url,
                "expected": (
                    "description blocks present: " + ", ".join(missing)
                    if missing
                    else "description blocks present"
                ),
                "passed": not missing,
                **(
                    {"detail": "missing: " + ", ".join(missing)}
                    if missing
                    else {}
                ),
            }
        )

    normalized: dict[str, Any] = dict(source)
    normalized.update(
        {
            "status": status,
            "issue_checks": issue_checks,
            "regression": {
                "checked": int(source.get("valid_products") or 0),
                "regressions": [],
            },
            "content_audit": {
                "products_checked": int(audit.get("products_checked") or 0),
                "description_gaps": int(audit.get("description_gaps") or 0),
                **(
                    {"samples": audit.get("samples")}
                    if audit.get("samples")
                    else {}
                ),
            },
            "diff": {
                "changed_fields": list(summary.get("changed_fields") or []),
                "discovery_changed": bool(
                    summary.get("discovery_changed") or False
                ),
            },
            "error_class": error_class,
        }
    )
    normalized.pop("evidence_sha256", None)
    normalized["evidence_sha256"] = canonical_sha256(normalized)
    return normalized
