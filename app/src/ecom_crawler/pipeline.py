"""D02 export pipeline: candidates in, 9-column CSV and task result out."""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .model import (
    BUSINESS_ACCEPTANCE_STATUSES,
    COVERAGE_STATUSES,
    CSV_COLUMNS,
    EXCLUDED_REASONS,
    STOP_REASONS,
    TASK_TYPES,
    ContractError,
    ExportResult,
    NormalizedProduct,
    OptionGroup,
    RecordIssue,
)
from .normalize import (
    apply_sales_unit,
    clean_name,
    clean_text,
    csv_safe,
    format_price,
    merge_options,
    normalize_availability,
    normalize_categories,
    normalize_currency,
    normalize_description,
    normalize_image_url,
    normalize_options,
    normalize_source_url,
    normalize_tax_basis,
    parse_price,
    serialize_options,
)


@dataclass(frozen=True)
class ResolvedPrice:
    amount: Decimal
    currency: str
    tax_basis: str
    price_basis: str
    displayed: Decimal | None
    pretax: Decimal | None
    options: tuple[OptionGroup, ...] = ()
    variants: tuple[dict[str, Any], ...] = ()


def load_task(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ContractError(f"missing task file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"task.json is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError("task.json must be a JSON object")
    return payload


def load_candidates(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError as exc:
        raise ContractError(f"missing candidates file: {path}") from exc
    candidates: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContractError(f"candidates.jsonl:{line_number}: {exc}") from exc
        if not isinstance(item, dict):
            raise ContractError(f"candidates.jsonl:{line_number}: expected a JSON object")
        candidates.append(item)
    return candidates


def normalize_task_meta(meta: Mapping[str, Any]) -> dict[str, Any]:
    required = ("task_id", "plan_id", "plan_version", "market", "locale", "stop_reason")
    missing = [field for field in required if not clean_text(meta.get(field))]
    if missing:
        raise ContractError(f"task.json missing required fields: {', '.join(missing)}")

    task_type = clean_text(meta.get("task_type")) or "product"
    if task_type not in TASK_TYPES:
        raise ContractError(f"task_type must be one of {TASK_TYPES}")
    if task_type != "product":
        raise ContractError("D02 export supports task_type=product only")

    state = clean_text(meta.get("state")) or "FINISHED"
    if state not in {"FINISHED", "CANCELLED"}:
        raise ContractError("export requires a terminal state: FINISHED or CANCELLED")

    stop_reason = clean_text(meta.get("stop_reason"))
    if stop_reason not in STOP_REASONS:
        raise ContractError(f"stop_reason must be one of {STOP_REASONS}")
    if state == "CANCELLED" and stop_reason != "USER_CANCELLED":
        raise ContractError("CANCELLED state requires stop_reason=USER_CANCELLED")

    started_at = clean_text(meta.get("started_at"))
    finished_at = clean_text(meta.get("finished_at"))
    if not started_at or not finished_at:
        raise ContractError("task.json requires started_at and finished_at")

    counts_in = meta.get("counts")
    if counts_in is not None and not isinstance(counts_in, Mapping):
        raise ContractError("task.json counts must be an object")
    counts_in = counts_in or {}

    pending_products = _non_negative_int(
        meta.get("pending_products", counts_in.get("pending_products", 0)),
        "pending_products",
    )
    in_flight_products = _non_negative_int(
        meta.get("in_flight_products", counts_in.get("in_flight_products", 0)),
        "in_flight_products",
    )
    if in_flight_products != 0:
        raise ContractError("export cannot run with in_flight_products > 0")

    discovered_raw = meta.get("discovered_urls", counts_in.get("discovered_urls"))
    discovered_urls = (
        None if discovered_raw is None else _non_negative_int(discovered_raw, "discovered_urls")
    )
    pending_navigation_entries = _non_negative_int(
        meta.get(
            "pending_navigation_entries",
            counts_in.get("pending_navigation_entries", 0),
        ),
        "pending_navigation_entries",
    )

    return {
        "task_id": clean_text(meta.get("task_id")),
        "task_type": task_type,
        "plan_id": clean_text(meta.get("plan_id")),
        "plan_version": clean_text(meta.get("plan_version")),
        "market": clean_text(meta.get("market")),
        "locale": clean_text(meta.get("locale")),
        "state": state,
        "stop_reason": stop_reason,
        "stop_detail_code": clean_text(meta.get("stop_detail_code")) or None,
        "stop_evidence": (
            dict(meta["stop_evidence"])
            if isinstance(meta.get("stop_evidence"), Mapping)
            else None
        ),
        "language_check": (
            dict(meta["language_check"])
            if isinstance(meta.get("language_check"), Mapping)
            else None
        ),
        "started_at": started_at,
        "finished_at": finished_at,
        "pending_products": pending_products,
        "in_flight_products": in_flight_products,
        "discovered_urls": discovered_urls,
        "pending_navigation_entries": pending_navigation_entries,
        "coverage": _normalize_coverage(meta.get("coverage")),
        "business_acceptance": _normalize_acceptance(meta.get("business_acceptance")),
        "runtime": _normalize_runtime(meta.get("runtime")),
        "limitations": _normalize_limitations(meta.get("limitations")),
        "synthetic_example": bool(meta.get("synthetic_example", False)),
    }


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ContractError(f"{field} must be a non-negative integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{field} must be a non-negative integer") from exc
    if number < 0:
        raise ContractError(f"{field} must be a non-negative integer")
    return number


def _normalize_coverage(value: Any) -> dict[str, Any]:
    if value is None:
        return {
            "status": "UNKNOWN",
            "denominator_source": None,
            "denominator": None,
            "covered": None,
            "notes": "No reliable site-wide denominator; task-scoped facts only.",
        }
    if not isinstance(value, Mapping):
        raise ContractError("coverage must be an object")
    status = clean_text(value.get("status")).upper() or "UNKNOWN"
    if status not in COVERAGE_STATUSES:
        raise ContractError(f"coverage.status must be one of {COVERAGE_STATUSES}")
    denominator_source = clean_text(value.get("denominator_source")) or None
    denominator = value.get("denominator")
    covered = value.get("covered")
    notes = clean_text(value.get("notes"))
    if status == "UNKNOWN":
        denominator_source = None
        denominator = None
        covered = None
        notes = notes or "No reliable site-wide denominator."
    else:
        if denominator is None:
            raise ContractError("coverage.denominator is required for KNOWN/PARTIAL")
        denominator = _non_negative_int(denominator, "coverage.denominator")
        if covered is not None:
            covered = _non_negative_int(covered, "coverage.covered")
    return {
        "status": status,
        "denominator_source": denominator_source,
        "denominator": denominator,
        "covered": covered,
        "notes": notes,
    }


def _normalize_acceptance(value: Any) -> dict[str, Any]:
    if value is None:
        return {
            "status": "NOT_REVIEWED",
            "accepted_by": None,
            "accepted_at": None,
            "reason": "No business sign-off recorded.",
            "scope": "Task-scoped export.",
        }
    if not isinstance(value, Mapping):
        raise ContractError("business_acceptance must be an object")
    status = clean_text(value.get("status")).upper() or "NOT_REVIEWED"
    if status not in BUSINESS_ACCEPTANCE_STATUSES:
        raise ContractError(
            f"business_acceptance.status must be one of {BUSINESS_ACCEPTANCE_STATUSES}"
        )
    accepted_by = clean_text(value.get("accepted_by")) or None
    accepted_at = clean_text(value.get("accepted_at")) or None
    reason = clean_text(value.get("reason"))
    scope = clean_text(value.get("scope"))
    if status in {"ACCEPTED_BY_USER", "REJECTED_BY_USER"} and (
        not accepted_by or not accepted_at or not reason
    ):
        raise ContractError(
            "accepted/rejected business_acceptance requires accepted_by, accepted_at and reason"
        )
    if not reason:
        reason = "No business sign-off recorded."
    if not scope:
        scope = "Task-scoped export."
    return {
        "status": status,
        "accepted_by": accepted_by,
        "accepted_at": accepted_at,
        "reason": reason,
        "scope": scope,
    }


def _normalize_runtime(value: Any) -> dict[str, Any]:
    if value is None:
        return {"llm_calls": 0, "raw_pages_retained": False}
    if not isinstance(value, Mapping):
        raise ContractError("runtime must be an object")
    llm_calls = _non_negative_int(value.get("llm_calls", 0), "runtime.llm_calls")
    return {
        "llm_calls": llm_calls,
        "raw_pages_retained": bool(value.get("raw_pages_retained", False)),
    }


def _normalize_limitations(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ContractError("limitations must be an array of strings")
    return [text for item in value if (text := clean_text(item))]


def resolve_price(price: Any, *, locale: str) -> ResolvedPrice:
    if price is None:
        raise RecordIssue("MISSING_PRICE")
    if not isinstance(price, Mapping):
        raise RecordIssue("INVALID_PRICE_SHAPE")

    currency = normalize_currency(price.get("currency"))
    variants = price.get("variants")
    candidates = price.get("candidates")
    options: tuple[OptionGroup, ...] = ()
    variant_records: tuple[dict[str, Any], ...] = ()

    if variants:
        if not isinstance(variants, list):
            raise RecordIssue("INVALID_PRICE_VARIANTS")
        amount, chosen, options, variant_records = _choose_variant(variants, locale=locale)
        tax_basis = normalize_tax_basis(chosen.get("tax_basis", price.get("tax_basis")))
    elif candidates:
        if not isinstance(candidates, list):
            raise RecordIssue("INVALID_PRICE_CANDIDATES")
        amount, chosen = _choose_candidate(candidates, locale=locale)
        tax_basis = normalize_tax_basis(chosen.get("tax_basis", price.get("tax_basis")))
    else:
        amount, reason = parse_price(price.get("amount"), locale=locale)
        if reason is not None:
            raise RecordIssue(reason)
        assert amount is not None
        chosen = {}
        tax_basis = normalize_tax_basis(price.get("tax_basis"))

    displayed = _optional_price(chosen.get("displayed", price.get("displayed")), locale)
    pretax = _optional_price(chosen.get("pretax", price.get("pretax")), locale)
    if candidates is not None:
        for item in candidates:
            if not isinstance(item, Mapping):
                continue
            label = clean_text(item.get("label")).lower()
            parsed = _optional_price(item.get("amount"), locale)
            if parsed is None:
                continue
            if label == "displayed":
                displayed = parsed
            elif label == "pretax":
                pretax = parsed

    price_basis = clean_text(price.get("price_basis")) or "LOWEST_PUBLIC_CURRENT"
    return ResolvedPrice(
        amount=amount,
        currency=currency,
        tax_basis=tax_basis,
        price_basis=price_basis,
        displayed=displayed,
        pretax=pretax,
        options=options,
        variants=variant_records,
    )


def _choose_variant(
    variants: list[Any], *, locale: str
) -> tuple[Decimal, Mapping[str, Any], tuple[OptionGroup, ...], tuple[dict[str, Any], ...]]:
    valid: list[tuple[Decimal, Mapping[str, Any]]] = []
    reasons: list[str] = []
    option_groups: list[OptionGroup] = []
    records: list[dict[str, Any]] = []
    for variant in variants:
        if not isinstance(variant, Mapping):
            reasons.append("INVALID_PRICE")
            continue
        amount, reason = parse_price(variant.get("amount"), locale=locale)
        if reason is not None:
            reasons.append(reason)
        else:
            assert amount is not None
            valid.append((amount, variant))
        variant_options = variant.get("options")
        if variant_options is not None:
            option_groups.extend(normalize_options(variant_options))
        options_payload = (
            {str(key): str(value) for key, value in variant_options.items()}
            if isinstance(variant_options, Mapping)
            else {}
        )
        records.append(
            {
                "amount": None if amount is None else float(amount),
                "available": variant.get("available")
                if isinstance(variant.get("available"), bool)
                else None,
                "sku": clean_text(variant.get("sku")) or None,
                "options": options_payload,
                "price_reason": reason,
            }
        )
    if not valid:
        raise RecordIssue(_pick_price_reason(reasons))
    amount, chosen = min(valid, key=lambda pair: pair[0])
    return amount, chosen, merge_options((), option_groups), tuple(records)


def _choose_candidate(
    candidates: list[Any], *, locale: str
) -> tuple[Decimal, Mapping[str, Any]]:
    valid: list[tuple[Decimal, Mapping[str, Any]]] = []
    reasons: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            reasons.append("INVALID_PRICE")
            continue
        amount, reason = parse_price(candidate.get("amount"), locale=locale)
        if reason is not None:
            reasons.append(reason)
        else:
            assert amount is not None
            valid.append((amount, candidate))
    if not valid:
        raise RecordIssue(_pick_price_reason(reasons))
    return min(valid, key=lambda pair: pair[0])


def _pick_price_reason(reasons: Iterable[str]) -> str:
    items = list(reasons)
    if items and all(item == "NON_POSITIVE_PRICE" for item in items):
        return "NON_POSITIVE_PRICE"
    if items and all(item == "MISSING_PRICE" for item in items):
        return "MISSING_PRICE"
    for code in ("AMBIGUOUS_PRICE", "INVALID_PRICE", "NON_POSITIVE_PRICE"):
        if code in items:
            return code
    return items[0] if items else "MISSING_PRICE"


def _optional_price(value: Any, locale: str) -> Decimal | None:
    if value is None or clean_text(value) == "":
        return None
    amount, reason = parse_price(value, locale=locale)
    return None if reason is not None else amount


def _normalize_candidate(
    raw: Mapping[str, Any], *, task_meta: Mapping[str, Any], seen: set[str]
) -> NormalizedProduct:
    source_url = normalize_source_url(raw.get("source_url"))
    if source_url in seen:
        raise RecordIssue("DUPLICATE_SOURCE_URL", source_url)
    seen.add(source_url)

    record_market = clean_text(raw.get("market"))
    if record_market and record_market.casefold() != task_meta["market"].casefold():
        raise RecordIssue("MARKET_MISMATCH", f"{record_market} != {task_meta['market']}")

    resolved = resolve_price(raw.get("price"), locale=task_meta["locale"])

    name = clean_name(raw.get("name"), source_url=source_url)
    if not name:
        raise RecordIssue("MISSING_NAME")

    image = normalize_image_url(raw.get("primary_image_url"), source_url=source_url)
    description = normalize_description(raw)
    if description.status == "FAILED":
        raise RecordIssue("DESCRIPTION_EXTRACTION_FAILED")

    brand = clean_text(raw.get("brand")) or None
    if brand and "brand" in description.missing_reasons:
        raise RecordIssue("MISSING_REASON_CONFLICT", "brand")
    sales_unit = clean_text(raw.get("sales_unit")) or None
    description_html = apply_sales_unit(description.html, sales_unit)

    base_options = normalize_options(raw.get("options"))
    options = merge_options(base_options, resolved.options)
    attributes = serialize_options(options)

    categories = normalize_categories(raw.get("categories"))
    availability, availability_observed = normalize_availability(raw.get("availability"))
    market = record_market or task_meta["market"]
    locale = clean_text(raw.get("locale")) or task_meta["locale"]
    extracted_at = clean_text(raw.get("extracted_at")) or task_meta["finished_at"]

    field_sources_raw = raw.get("field_sources")
    if field_sources_raw is not None and not isinstance(field_sources_raw, Mapping):
        raise RecordIssue("INVALID_FIELD_SOURCES")
    field_sources = (
        {clean_text(key): clean_text(value) for key, value in field_sources_raw.items()}
        if isinstance(field_sources_raw, Mapping)
        else {}
    )

    return NormalizedProduct(
        name=name,
        price_amount=resolved.amount,
        price_currency=resolved.currency,
        primary_image_url=image,
        description_html=description_html,
        description_status=description.status,
        partial_reason=description.partial_reason,
        missing_reasons=dict(description.missing_reasons),
        categories=categories,
        category=categories[0] if categories else "",
        brand=brand,
        options=options,
        attributes=attributes,
        source_url=source_url,
        market=market,
        locale=locale,
        availability=availability,
        availability_observed=availability_observed,
        sales_unit=sales_unit,
        tax_basis=resolved.tax_basis,
        price_basis=resolved.price_basis,
        extracted_at=extracted_at,
        price_displayed=resolved.displayed,
        price_pretax=resolved.pretax,
        relations=description.relations,
        variants=resolved.variants,
        field_sources=dict(field_sources),
    )


def _diagnostic(raw: Mapping[str, Any], issue: RecordIssue) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "source_url": clean_text(raw.get("source_url")) or None,
        "reason": issue.code,
        "detail": issue.detail,
    }
    price = raw.get("price")
    if isinstance(price, Mapping):
        entry["observed_price"] = {
            "amount": price.get("amount"),
            "currency": price.get("currency"),
        }
    if issue.code == "DUPLICATE_SOURCE_URL":
        entry["duplicate_of"] = issue.detail
    return entry


def export_candidates(
    task_meta: Mapping[str, Any], candidates: Iterable[Mapping[str, Any]]
) -> ExportResult:
    meta = normalize_task_meta(task_meta)
    products: list[NormalizedProduct] = []
    excluded: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in candidates:
        if not isinstance(raw, Mapping):
            raise ContractError("candidate must be a JSON object")
        try:
            product = _normalize_candidate(raw, task_meta=meta, seen=seen)
        except RecordIssue as issue:
            entry = _diagnostic(raw, issue)
            if issue.code in EXCLUDED_REASONS:
                excluded.append(entry)
            else:
                failed.append(entry)
        else:
            products.append(product)

    task_result = build_task_result(meta, products, excluded, failed)
    return ExportResult(
        products=tuple(products),
        excluded=tuple(excluded),
        failed=tuple(failed),
        task_result=task_result,
    )


def build_task_result(
    meta: Mapping[str, Any],
    products: list[NormalizedProduct],
    excluded: list[dict[str, Any]],
    failed: list[dict[str, Any]],
) -> dict[str, Any]:
    processed = len(products) + len(excluded) + len(failed)
    product_candidates = processed + int(meta["pending_products"]) + int(
        meta["in_flight_products"]
    )
    discovered_urls = meta["discovered_urls"]
    if discovered_urls is None:
        discovered_urls = product_candidates
    if discovered_urls < product_candidates:
        raise ContractError(
            "discovered_urls cannot be smaller than product_candidates "
            f"({discovered_urls} < {product_candidates})"
        )
    counts = {
        "discovered_urls": discovered_urls,
        "pending_navigation_entries": int(meta["pending_navigation_entries"]),
        "product_candidates": product_candidates,
        "pending_products": int(meta["pending_products"]),
        "in_flight_products": int(meta["in_flight_products"]),
        "processed_products": processed,
        "valid_products": len(products),
        "excluded_products": len(excluded),
        "failed_products": len(failed),
        "partial_description_products": sum(
            1 for product in products if product.description_status == "PARTIAL"
        ),
    }
    outcome = _outcome(meta["state"], meta["stop_reason"], counts)
    exceptions = [
        exception
        for product in products
        if (exception := product.quality_exception()) is not None
    ]
    exceptions.sort(key=lambda item: item["source_url"])

    result: dict[str, Any] = {}
    if meta["synthetic_example"]:
        result["synthetic_example"] = True
    result.update(
        {
            "task_id": meta["task_id"],
            "task_type": meta["task_type"],
            "plan_id": meta["plan_id"],
            "plan_version": meta["plan_version"],
            "market": meta["market"],
            "locale": meta["locale"],
            "state": meta["state"],
            "outcome": outcome,
            "stop_reason": meta["stop_reason"],
            "started_at": meta["started_at"],
            "finished_at": meta["finished_at"],
            "counts": counts,
            "coverage": dict(meta["coverage"]),
            "business_acceptance": dict(meta["business_acceptance"]),
            "quality_exceptions": exceptions,
            "runtime": dict(meta["runtime"]),
        }
    )
    if meta["limitations"]:
        result["limitations"] = list(meta["limitations"])
    for key in ("stop_detail_code", "stop_evidence", "language_check"):
        if meta.get(key) is not None:
            result[key] = meta[key]
    return result


def _outcome(state: str, stop_reason: str, counts: Mapping[str, int]) -> str:
    if state == "CANCELLED":
        return "CANCELLED"
    valid = counts["valid_products"]
    failed = counts["failed_products"]
    pending = counts["pending_products"] + counts["pending_navigation_entries"]
    if valid == 0 and (
        failed > 0
        or stop_reason
        in {"ENVIRONMENT_ERROR", "PLAN_ERROR", "ACCESS_DENIED", "LANGUAGE_MISMATCH"}
    ):
        return "FAILED"
    if pending > 0 or failed > 0:
        return "PARTIAL"
    return "COMPLETED"


def render_products_csv(products: Iterable[NormalizedProduct]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for product in products:
        writer.writerow(
            [
                csv_safe(product.name),
                format_price(product.price_amount),
                csv_safe(product.price_currency),
                csv_safe(product.primary_image_url),
                csv_safe(product.description_html),
                csv_safe(product.category),
                csv_safe(product.brand or ""),
                csv_safe(product.attributes),
                csv_safe(product.source_url),
            ]
        )
    return buffer.getvalue()


def _render_jsonl(records: Iterable[Mapping[str, Any]]) -> str:
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    return "\n".join(lines) + ("\n" if lines else "")


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def export_run(run_dir: Path, out_dir: Path, *, force: bool = False) -> ExportResult:
    run_dir = Path(run_dir)
    out_dir = Path(out_dir)
    if not run_dir.is_dir():
        raise ContractError(f"run directory not found: {run_dir}")
    task = load_task(run_dir / "task.json")
    candidates = load_candidates(run_dir / "candidates.jsonl")
    result = export_candidates(task, candidates)

    targets = [out_dir / "products.csv", out_dir / "task-result.json"]
    if not force:
        existing = [str(path) for path in targets if path.exists()]
        if existing:
            raise ContractError(
                "output already exists; use --force to replace: " + ", ".join(existing)
            )

    products_csv = render_products_csv(result.products)
    task_json = json.dumps(result.task_result, ensure_ascii=False, indent=2) + "\n"
    records = (product.to_record() for product in result.products)
    excluded_jsonl = _render_jsonl(result.excluded)
    failed_jsonl = _render_jsonl(result.failed)

    atomic_write_text(out_dir / "products.csv", products_csv)
    atomic_write_text(out_dir / "task-result.json", task_json)
    atomic_write_text(out_dir / "records.jsonl", _render_jsonl(records))
    atomic_write_text(out_dir / "diagnostics" / "excluded.jsonl", excluded_jsonl)
    atomic_write_text(out_dir / "diagnostics" / "failed.jsonl", failed_jsonl)
    return result
