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
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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


_REGRESSION_FIELDS = [
    "name",
    "price_amount",
    "price_currency",
    "primary_image_url",
    "description_html",
]
_AUTOMATED_FEEDBACK_CATEGORIES = {
    "DESCRIPTION",
    "PRICE_CURRENCY_UNIT",
    "BASIC_FIELDS",
    "DISCOVERY",
    "IDENTITY",
    "ACCESS_RUNTIME",
}


def _url_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parts = urlsplit(text)
    if not parts.scheme or not parts.netloc:
        return text
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/") or "/",
            parts.query,
            "",
        )
    )


def _text_key(value: Any) -> str:
    return " ".join(str(value or "").split())


def _price_key(value: Any) -> Any:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return Decimal(text)
    except InvalidOperation:
        return text


def _description_regressed(before: Any, after: Any) -> bool:
    old = str(before or "").strip()
    new = str(after or "").strip()
    if not old:
        return False
    return not new or len(new) < max(30, int(len(old) * 0.8))


def compare_product_samples(
    old_samples: Any,
    new_samples: Any,
    *,
    source_rule_version: str | None = None,
    source_rule_sha256: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Compare core product fields for the same fixed page set.

    The caller must run both rules over the same URLs.  ``checked`` counts the
    pages present on both sides; pages only seen on one side are reported in
    ``skipped`` instead of being treated as a regression.
    """

    old = [item for item in old_samples or [] if isinstance(item, dict)]
    new = [item for item in new_samples or [] if isinstance(item, dict)]
    old_by_url = {
        _url_key(item.get("source_url")): item
        for item in old
        if _url_key(item.get("source_url"))
    }
    new_by_url = {
        _url_key(item.get("source_url")): item
        for item in new
        if _url_key(item.get("source_url"))
    }
    shared = sorted(set(old_by_url) & set(new_by_url))[: max(1, int(limit))]
    skipped = [
        {"sample": key, "reason": "missing_from_old_rule"}
        for key in sorted(set(new_by_url) - set(old_by_url))[:limit]
    ] + [
        {"sample": key, "reason": "missing_from_new_rule"}
        for key in sorted(set(old_by_url) - set(new_by_url))[:limit]
    ]
    regressions: list[dict[str, Any]] = []
    for key in shared:
        before = old_by_url[key]
        after = new_by_url[key]
        for field in _REGRESSION_FIELDS:
            if field == "name":
                degraded = _text_key(before.get(field)) != _text_key(
                    after.get(field)
                )
            elif field == "price_amount":
                degraded = _price_key(before.get(field)) != _price_key(
                    after.get(field)
                )
            elif field == "price_currency":
                degraded = (
                    str(before.get(field) or "").strip().upper()
                    != str(after.get(field) or "").strip().upper()
                )
            elif field == "primary_image_url":
                degraded = str(before.get(field) or "").strip() != str(
                    after.get(field) or ""
                ).strip()
            else:
                degraded = _description_regressed(
                    before.get(field), after.get(field)
                )
            if not degraded:
                continue
            before_value = before.get(field)
            after_value = after.get(field)
            if field == "description_html":
                before_value = str(before_value or "")[:400]
                after_value = str(after_value or "")[:400]
            regressions.append(
                {
                    "field": field,
                    "sample": key,
                    "before": before_value,
                    "after": after_value,
                }
            )
    executed = bool(shared)
    return {
        "executed": executed,
        "source_rule_version": source_rule_version,
        "source_rule_sha256": source_rule_sha256,
        "checked": len(shared),
        "compared_fields": list(_REGRESSION_FIELDS),
        "regressions": regressions,
        "skipped": skipped,
        **(
            {}
            if executed
            else {
                "reason": (
                    "no product page was extracted by both rules"
                    if old and new
                    else "old or new rule produced no product records"
                )
            }
        ),
    }


def feedback_issue_checks(
    feedback: Any,
    product_samples: Any,
    *,
    rule_currency: str | None = None,
    audit_samples: Any = None,
) -> list[dict[str, Any]]:
    """Turn a feedback record into host-checkable sample assertions.

    Only categories with a deterministic field assertion return checks.  A
    business-expectation or free-form note still needs human review and is not
    disguised as a passed automated check.
    """

    category = str(getattr(feedback, "category", "") or "").upper()
    if category not in _AUTOMATED_FEEDBACK_CATEGORIES:
        return []
    samples = [
        str(sample).strip()
        for sample in (getattr(feedback, "samples", None) or [])
        if str(sample).strip()
    ]
    if not samples:
        return []
    products = {
        _url_key(item.get("source_url")): item
        for item in product_samples or []
        if isinstance(item, dict) and _url_key(item.get("source_url"))
    }
    missing_blocks: dict[str, list[str]] = {}
    for item in audit_samples or []:
        if not isinstance(item, dict):
            continue
        key = _url_key(item.get("source_url"))
        if key:
            missing_blocks[key] = [
                str(block)
                for block in (item.get("missing_blocks") or [])
                if str(block).strip()
            ]
    checks: list[dict[str, Any]] = []
    currency = str(rule_currency or "").strip().upper()
    for sample in samples:
        key = _url_key(sample)
        product = products.get(key)
        if product is None:
            checks.append(
                {
                    "sample": sample,
                    "expected": "问题样本在本次有界验证中可抓取",
                    "passed": False,
                    "detail": "sample was not extracted by the bounded validation run",
                }
            )
            continue
        if category == "DESCRIPTION":
            description = str(product.get("description_html") or "").strip()
            missing = missing_blocks.get(key) or []
            passed = len(description) >= 30 and not missing
            checks.append(
                {
                    "sample": sample,
                    "expected": "描述正文和声明的页面块均出现",
                    "observed": f"description {len(description)} chars",
                    "passed": passed,
                    **(
                        {"detail": "missing blocks: " + ", ".join(missing)}
                        if missing
                        else {}
                    ),
                }
            )
        elif category == "PRICE_CURRENCY_UNIT":
            amount = _price_key(product.get("price_amount"))
            product_currency = str(
                product.get("price_currency") or ""
            ).strip().upper()
            passed = bool(amount) and (
                not currency or product_currency == currency
            )
            checks.append(
                {
                    "sample": sample,
                    "expected": (
                        f"价格为正且币种为 {currency}"
                        if currency
                        else "价格为正且币种明确"
                    ),
                    "observed": f"{product.get('price_amount')} {product_currency}".strip(),
                    "passed": passed,
                }
            )
        elif category == "BASIC_FIELDS":
            name = str(product.get("name") or "").strip()
            image = str(product.get("primary_image_url") or "").strip()
            checks.append(
                {
                    "sample": sample,
                    "expected": "名称和主图均出现",
                    "observed": (
                        f"name={bool(name)} image={bool(image)}"
                    ),
                    "passed": bool(name and image),
                }
            )
        else:
            checks.append(
                {
                    "sample": sample,
                    "expected": "问题样本在本次有界验证中产生有效商品",
                    "passed": True,
                }
            )
    return checks


def normalize_validation(
    raw: dict[str, Any] | None,
    change_summary: dict[str, Any] | None,
    *,
    status: str = "PASSED",
    error_class: str | None = None,
) -> dict[str, Any]:
    """Return a validation payload that satisfies the v2 schema.

    Candidate smoke, issue samples and cross-version regression are separate
    facts.  A repair whose regression did not run is ``INCOMPLETE`` rather than
    ``PASSED``; activation must reject it.  Raw host counts stay in the payload
    as additional properties so the UI and existing tests can keep reading
    ``valid_products`` and friends.
    """

    source = raw if isinstance(raw, dict) else {}
    summary = change_summary if isinstance(change_summary, dict) else {}
    audit = source.get("content_audit")
    audit = audit if isinstance(audit, dict) else {}
    parent_version = summary.get("parent_version")
    smoke_raw = source.get("candidate_smoke")
    smoke_raw = smoke_raw if isinstance(smoke_raw, dict) else {}
    smoke_valid = int(
        smoke_raw.get("valid_products", source.get("valid_products") or 0) or 0
    )
    smoke_failed = int(
        smoke_raw.get("failed_products", source.get("failed_products") or 0) or 0
    )
    smoke_excluded = int(
        smoke_raw.get(
            "excluded_products", source.get("excluded_products") or 0
        )
        or 0
    )
    product_samples = smoke_raw.get("product_samples") or source.get(
        "product_samples"
    )
    candidate_smoke = {
        "executed": bool(
            smoke_raw.get("executed", smoke_valid >= 1)
            if "executed" in smoke_raw
            else smoke_valid >= 1
        ),
        "valid_products": smoke_valid,
        "failed_products": smoke_failed,
        "excluded_products": smoke_excluded,
        "currencies": dict(smoke_raw.get("currencies") or source.get("currencies") or {}),
        "product_samples": [
            item
            for item in (product_samples or [])
            if isinstance(item, dict)
        ][:10],
    }

    issue_checks: list[dict[str, Any]] = []
    seen_checks: set[tuple[str, str]] = set()

    def add_check(item: Any) -> None:
        if not isinstance(item, dict):
            return
        sample = str(item.get("sample") or "").strip()
        expected = str(item.get("expected") or "").strip()
        if not sample or not expected:
            return
        key = (_url_key(sample), expected)
        if key in seen_checks:
            return
        seen_checks.add(key)
        issue_checks.append(
            {
                "sample": sample,
                "expected": expected,
                "passed": bool(item.get("passed")),
                **(
                    {"observed": str(item["observed"])}
                    if item.get("observed") is not None
                    else {}
                ),
                **(
                    {"detail": str(item["detail"])}
                    if item.get("detail")
                    else {}
                ),
            }
        )

    for item in source.get("issue_checks") or []:
        add_check(item)
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
        add_check(
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
    for sample in source.get("feedback_samples") or []:
        url = str(sample or "").strip()
        if not url:
            continue
        if any(
            check["sample"] == url
            or _url_key(check["sample"]) == _url_key(url)
            for check in issue_checks
        ):
            continue
        add_check(
            {
                "sample": url,
                "expected": "问题样本在本次有界验证中可抓取",
                "passed": False,
                "detail": "no host check covered this feedback sample",
            }
        )

    regression_raw = source.get("regression")
    regression_raw = regression_raw if isinstance(regression_raw, dict) else {}
    required = bool(regression_raw.get("required", parent_version is not None))
    regressions = [
        item
        for item in (regression_raw.get("regressions") or [])
        if isinstance(item, dict)
    ]
    regression: dict[str, Any] = {
        "executed": bool(regression_raw.get("executed")) and bool(
            int(regression_raw.get("checked") or 0)
        ),
        "required": required,
        "required_checked": int(regression_raw.get("required_checked") or 0),
        "checked": int(regression_raw.get("checked") or 0),
        "compared_fields": list(
            regression_raw.get("compared_fields") or _REGRESSION_FIELDS
        ),
        "regressions": regressions,
    }
    for key in (
        "source_rule_version",
        "source_rule_sha256",
        "skipped",
        "reason",
    ):
        if regression_raw.get(key) not in (None, "", []):
            regression[key] = regression_raw[key]

    reasons: list[str] = []
    requested = str(source.get("status") or status or "PASSED").upper()
    if requested == "FAILED":
        final_status = "FAILED"
        reasons.append("host validation reported a failure")
    elif error_class:
        final_status = "FAILED"
        reasons.append(f"error_class={error_class}")
    elif not candidate_smoke["executed"] or smoke_valid < 1:
        final_status = "FAILED"
        reasons.append("candidate smoke produced no valid product")
    elif any(not check["passed"] for check in issue_checks):
        final_status = "FAILED"
        reasons.append("at least one issue-sample check failed")
    elif regressions:
        final_status = "FAILED"
        reasons.append("cross-version regression detected")
    elif required and not regression["executed"]:
        final_status = "INCOMPLETE"
        reasons.append("required cross-version regression did not run")
    elif (
        required
        and regression["required_checked"]
        and regression["checked"] < regression["required_checked"]
    ):
        final_status = "INCOMPLETE"
        reasons.append(
            "cross-version regression covered "
            f"{regression['checked']} of {regression['required_checked']} "
            "required pages"
        )
    else:
        final_status = "PASSED"

    normalized: dict[str, Any] = dict(source)
    normalized.update(
        {
            "status": final_status,
            "status_reasons": reasons,
            "candidate_smoke": candidate_smoke,
            "issue_checks": issue_checks,
            "regression": regression,
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
                **(
                    {"market_changed": bool(summary["market_changed"])}
                    if "market_changed" in summary
                    else {}
                ),
                **(
                    {"currency_changed": bool(summary["currency_changed"])}
                    if "currency_changed" in summary
                    else {}
                ),
            },
            "error_class": error_class,
        }
    )
    normalized.pop("evidence_sha256", None)
    normalized["evidence_sha256"] = canonical_sha256(normalized)
    return normalized
