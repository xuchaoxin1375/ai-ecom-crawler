"""Validation for the D02 task result and exported run directory."""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .model import (
    BUSINESS_ACCEPTANCE_STATUSES,
    COVERAGE_STATUSES,
    CSV_COLUMNS,
    DESCRIPTION_STATUSES,
    OUTCOMES,
    STOP_REASONS,
    TASK_STATES,
    TASK_TYPES,
)

COUNT_KEYS = (
    "discovered_urls",
    "pending_navigation_entries",
    "product_candidates",
    "pending_products",
    "in_flight_products",
    "processed_products",
    "valid_products",
    "excluded_products",
    "failed_products",
    "partial_description_products",
)
REQUIRED_RESULT_FIELDS = (
    "task_id",
    "task_type",
    "plan_id",
    "plan_version",
    "market",
    "locale",
    "state",
    "outcome",
    "stop_reason",
    "started_at",
    "finished_at",
    "counts",
    "coverage",
    "business_acceptance",
    "quality_exceptions",
)
ERROR_STOP_REASONS = {"ENVIRONMENT_ERROR", "PLAN_ERROR", "ACCESS_DENIED"}


def validate_task_result(result: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(result, Mapping):
        return ["task-result must be a JSON object"]

    for field in REQUIRED_RESULT_FIELDS:
        if field not in result:
            errors.append(f"missing required field: {field}")
    if errors:
        return errors

    for field in ("task_id", "plan_id", "plan_version", "market", "locale"):
        if not isinstance(result[field], str) or not result[field].strip():
            errors.append(f"{field} must be a non-empty string")

    if result.get("task_type") not in TASK_TYPES:
        errors.append(f"task_type must be one of {TASK_TYPES}")
    if result.get("state") not in TASK_STATES:
        errors.append(f"state must be one of {TASK_STATES}")
    if result.get("outcome") not in OUTCOMES:
        errors.append(f"outcome must be one of {OUTCOMES}")
    if result.get("stop_reason") not in STOP_REASONS:
        errors.append(f"stop_reason must be one of {STOP_REASONS}")
    for field in ("started_at", "finished_at"):
        if not isinstance(result[field], str) or not result[field].strip():
            errors.append(f"{field} must be a non-empty string")

    counts = result.get("counts")
    if not isinstance(counts, Mapping):
        errors.append("counts must be an object")
        counts = {}
    for key in COUNT_KEYS:
        value = counts.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            errors.append(f"counts.{key} must be a non-negative integer")
    if counts:
        _check_counts(counts, errors)
        if all(
            isinstance(counts.get(key), int) and not isinstance(counts.get(key), bool)
            for key in COUNT_KEYS
        ):
            _check_outcome(result, counts, errors)

    _check_coverage(result.get("coverage"), errors)
    _check_acceptance(result.get("business_acceptance"), errors)
    _check_quality_exceptions(result.get("quality_exceptions"), counts, errors)

    runtime = result.get("runtime")
    if runtime is not None:
        if not isinstance(runtime, Mapping):
            errors.append("runtime must be an object")
        elif (
            isinstance(runtime.get("llm_calls"), bool)
            or not isinstance(runtime.get("llm_calls"), int)
            or runtime.get("llm_calls") < 0
        ):
            errors.append("runtime.llm_calls must be a non-negative integer")

    limitations = result.get("limitations")
    if limitations is not None and not isinstance(limitations, list):
        errors.append("limitations must be an array of strings")
    return errors


def _check_counts(counts: Mapping[str, Any], errors: list[str]) -> None:
    if not all(isinstance(counts.get(key), int) for key in COUNT_KEYS):
        return
    if counts["product_candidates"] != (
        counts["pending_products"]
        + counts["in_flight_products"]
        + counts["processed_products"]
    ):
        errors.append(
            "counts invariant failed: product_candidates != pending + in_flight + processed"
        )
    if counts["processed_products"] != (
        counts["valid_products"] + counts["excluded_products"] + counts["failed_products"]
    ):
        errors.append(
            "counts invariant failed: processed != valid + excluded + failed"
        )
    if counts["partial_description_products"] > counts["valid_products"]:
        errors.append("counts invariant failed: partial_description_products > valid_products")
    if counts["in_flight_products"] != 0:
        errors.append("terminal task result must have in_flight_products = 0")
    if counts["discovered_urls"] < counts["product_candidates"]:
        errors.append("counts invariant failed: discovered_urls < product_candidates")


def _check_outcome(
    result: Mapping[str, Any], counts: Mapping[str, int], errors: list[str]
) -> None:
    state = result.get("state")
    outcome = result.get("outcome")
    stop_reason = result.get("stop_reason")
    if state == "CANCELLED":
        if outcome != "CANCELLED":
            errors.append("CANCELLED state requires outcome=CANCELLED")
        return
    if outcome == "CANCELLED":
        errors.append("outcome=CANCELLED requires state=CANCELLED")
        return
    pending = counts["pending_products"] + counts["pending_navigation_entries"]
    if pending > 0 and outcome == "COMPLETED":
        errors.append("outcome cannot be COMPLETED while pending work remains")
    if counts["failed_products"] > 0 and counts["valid_products"] == 0:
        if outcome != "FAILED":
            errors.append("zero valid products with failures requires outcome=FAILED")
    elif counts["failed_products"] > 0 and outcome == "COMPLETED":
        errors.append("outcome cannot be COMPLETED while products failed")
    if (
        counts["valid_products"] == 0
        and counts["failed_products"] == 0
        and stop_reason in ERROR_STOP_REASONS
        and outcome != "FAILED"
    ):
        errors.append("zero valid products with an error stop_reason requires outcome=FAILED")


def _check_coverage(coverage: Any, errors: list[str]) -> None:
    if not isinstance(coverage, Mapping):
        errors.append("coverage must be an object")
        return
    status = coverage.get("status")
    if status not in COVERAGE_STATUSES:
        errors.append(f"coverage.status must be one of {COVERAGE_STATUSES}")
        return
    for field in ("denominator_source", "denominator", "covered", "notes"):
        if field not in coverage:
            errors.append(f"coverage missing field: {field}")
    if status == "UNKNOWN":
        if coverage.get("denominator") is not None:
            errors.append("UNKNOWN coverage must not carry a denominator")
    else:
        denominator = coverage.get("denominator")
        if isinstance(denominator, bool) or not isinstance(denominator, int) or denominator <= 0:
            errors.append("KNOWN/PARTIAL coverage requires a positive integer denominator")


def _check_acceptance(acceptance: Any, errors: list[str]) -> None:
    if not isinstance(acceptance, Mapping):
        errors.append("business_acceptance must be an object")
        return
    for field in ("status", "accepted_by", "accepted_at", "reason", "scope"):
        if field not in acceptance:
            errors.append(f"business_acceptance missing field: {field}")
    status = acceptance.get("status")
    if status not in BUSINESS_ACCEPTANCE_STATUSES:
        errors.append(
            f"business_acceptance.status must be one of {BUSINESS_ACCEPTANCE_STATUSES}"
        )


def _check_quality_exceptions(
    exceptions: Any, counts: Mapping[str, Any], errors: list[str]
) -> None:
    if not isinstance(exceptions, list):
        errors.append("quality_exceptions must be an array")
        return
    seen: set[str] = set()
    partial = 0
    for index, item in enumerate(exceptions, start=1):
        if not isinstance(item, Mapping):
            errors.append(f"quality_exceptions[{index}] must be an object")
            continue
        for field in ("source_url", "description_status", "partial_reason", "missing_reasons"):
            if field not in item:
                errors.append(f"quality_exceptions[{index}] missing field: {field}")
        url = item.get("source_url")
        if not isinstance(url, str) or not url.strip():
            errors.append(f"quality_exceptions[{index}].source_url must be non-empty")
        elif url in seen:
            errors.append(f"quality_exceptions has duplicate source_url: {url}")
        else:
            seen.add(url)
        status = item.get("description_status")
        if status not in DESCRIPTION_STATUSES:
            errors.append(
                f"quality_exceptions[{index}].description_status must be one of "
                f"{DESCRIPTION_STATUSES}"
            )
        if status == "PARTIAL":
            partial += 1
            if not isinstance(item.get("partial_reason"), str) or not item["partial_reason"].strip():
                errors.append(f"quality_exceptions[{index}] PARTIAL requires partial_reason")
        missing = item.get("missing_reasons")
        if not isinstance(missing, Mapping):
            errors.append(f"quality_exceptions[{index}].missing_reasons must be an object")
    if (
        isinstance(counts.get("partial_description_products"), int)
        and partial != counts["partial_description_products"]
    ):
        errors.append(
            "quality_exceptions PARTIAL count does not match "
            "counts.partial_description_products"
        )


def validate_task_result_file(path: Path) -> list[str]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return [f"task result not found: {path}"]
    except json.JSONDecodeError as exc:
        return [f"task result is not valid JSON: {exc}"]
    return validate_task_result(payload)


def read_products_csv(path: Path, expected_rows: int) -> tuple[list[dict[str, str]], list[str]]:
    errors: list[str] = []
    try:
        with Path(path).open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            header = list(reader.fieldnames or [])
            rows = [dict(row) for row in reader]
    except FileNotFoundError:
        return [], [f"products CSV not found: {path}"]
    if header != list(CSV_COLUMNS):
        errors.append(f"CSV header mismatch: {header}")
    if len(rows) != expected_rows:
        errors.append(f"CSV row count {len(rows)} != counts.valid_products {expected_rows}")
    seen_urls: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if any(value is None for value in row.values()):
            errors.append(f"CSV row {index} has a different number of fields")
            continue
        try:
            amount = Decimal(row.get("price_amount", ""))
        except (InvalidOperation, ValueError):
            errors.append(f"CSV row {index} price_amount is not a number")
        else:
            if not amount.is_finite() or amount <= 0:
                errors.append(f"CSV row {index} price_amount is not a positive number")
        currency = row.get("price_currency", "")
        if not re.fullmatch(r"[A-Z]{3}", currency):
            errors.append(f"CSV row {index} price_currency is invalid")
        source_url = row.get("source_url", "")
        if not source_url.startswith(("http://", "https://")):
            errors.append(f"CSV row {index} source_url is invalid")
        elif source_url in seen_urls:
            errors.append(f"CSV row {index} duplicates source_url: {source_url}")
        else:
            seen_urls.add(source_url)
    return rows, errors


def read_diagnostics(path: Path, expected: int, label: str) -> list[str]:
    errors: list[str] = []
    if not Path(path).exists():
        if expected:
            errors.append(f"missing {label} diagnostics: {path}")
        return errors
    count = 0
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{label} diagnostics line {line_number}: {exc}")
            continue
        if not isinstance(item, Mapping):
            errors.append(f"{label} diagnostics line {line_number}: expected object")
            continue
        if "source_url" not in item or "reason" not in item:
            errors.append(f"{label} diagnostics line {line_number}: source_url/reason required")
        count += 1
    if count != expected:
        errors.append(f"{label} diagnostics count {count} != expected {expected}")
    return errors


def read_records(path: Path, expected: int) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    if not Path(path).exists():
        return [], [f"records file not found: {path}"]
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"records.jsonl line {line_number}: {exc}")
            continue
        if not isinstance(item, Mapping):
            errors.append(f"records.jsonl line {line_number}: expected object")
            continue
        records.append(dict(item))
    if len(records) != expected:
        errors.append(f"records count {len(records)} != counts.valid_products {expected}")
    for index, record in enumerate(records, start=1):
        if not isinstance(record.get("source_url"), str) or not record["source_url"]:
            errors.append(f"records line {index}: source_url is required")
        if record.get("description_status") not in DESCRIPTION_STATUSES:
            errors.append(f"records line {index}: invalid description_status")
        if not isinstance(record.get("missing_reasons"), Mapping):
            errors.append(f"records line {index}: missing_reasons must be an object")
    return records, errors


def validate_run(out_dir: Path) -> list[str]:
    out_dir = Path(out_dir)
    errors = validate_task_result_file(out_dir / "task-result.json")
    if errors:
        return errors
    result = json.loads((out_dir / "task-result.json").read_text(encoding="utf-8-sig"))
    counts = result["counts"]
    rows, csv_errors = read_products_csv(out_dir / "products.csv", counts["valid_products"])
    errors.extend(csv_errors)
    errors.extend(
        read_diagnostics(
            out_dir / "diagnostics" / "excluded.jsonl",
            counts["excluded_products"],
            "excluded",
        )
    )
    errors.extend(
        read_diagnostics(
            out_dir / "diagnostics" / "failed.jsonl",
            counts["failed_products"],
            "failed",
        )
    )
    records, record_errors = read_records(out_dir / "records.jsonl", counts["valid_products"])
    errors.extend(record_errors)

    csv_urls = [row.get("source_url", "") for row in rows]
    record_urls = [str(record.get("source_url", "")) for record in records]
    if csv_urls != record_urls:
        errors.append("records.jsonl source_url order does not match products.csv")

    expected_exception_urls = {
        str(record.get("source_url"))
        for record in records
        if record.get("description_status") != "COMPLETE" or record.get("missing_reasons")
    }
    actual_exception_urls = {
        str(item.get("source_url"))
        for item in result.get("quality_exceptions", [])
        if isinstance(item, Mapping)
    }
    if expected_exception_urls != actual_exception_urls:
        errors.append(
            "quality_exceptions do not match non-complete records: "
            f"expected={sorted(expected_exception_urls)}, "
            f"actual={sorted(actual_exception_urls)}"
        )

    urls = set(csv_urls)
    for item in result.get("quality_exceptions", []):
        if isinstance(item, Mapping) and item.get("source_url") not in urls:
            errors.append(
                "quality_exceptions source_url is not in products.csv: "
                f"{item.get('source_url')}"
            )
    return errors
