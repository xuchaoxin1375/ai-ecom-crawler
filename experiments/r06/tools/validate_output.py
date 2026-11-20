#!/usr/bin/env python3
"""Validate an R06 output directory against the local contract subset."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

CSV_COLUMNS = [
    "name",
    "price_amount",
    "price_currency",
    "primary_image_url",
    "description_html",
    "category",
    "brand",
    "attributes",
    "source_url",
]
STOP_REASONS = {
    "NATURAL_END",
    "BUDGET_EXHAUSTED",
    "ACCESS_DENIED",
    "QUALITY_BLOCKED",
    "ENVIRONMENT_ERROR",
    "PLAN_ERROR",
    "USER_CANCELLED",
    "OTHER",
}
OUTCOMES = {"COMPLETED", "PARTIAL", "FAILED", "CANCELLED"}
COVERAGE_STATUSES = {"KNOWN", "PARTIAL", "UNKNOWN"}


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        fail(f"missing {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[list[str]]:
    if not path.is_file():
        fail(f"missing {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def check_url(value: str, field: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        fail(f"{field} is not an absolute http(s) URL: {value!r}")


def validate(directory: Path) -> dict[str, Any]:
    task = load_json(directory / "task-result.json")
    summary = load_json(directory / "run-summary.json")
    rows = read_csv(directory / "valid.csv")
    if not rows:
        fail("valid.csv is empty")
    if rows[0] != CSV_COLUMNS:
        fail(f"valid.csv header mismatch: {rows[0]}")
    data_rows = rows[1:]

    required_task = {
        "task_id",
        "plan_id",
        "plan_version",
        "state",
        "outcome",
        "stop_reason",
        "counts",
        "coverage",
        "business_acceptance",
        "quality_exceptions",
    }
    missing = required_task - set(task)
    if missing:
        fail(f"task-result missing keys: {sorted(missing)}")
    if task["state"] != "FINISHED":
        fail(f"state is {task['state']!r}, expected FINISHED")
    if task["outcome"] not in OUTCOMES:
        fail(f"invalid outcome: {task['outcome']!r}")
    if task["stop_reason"] not in STOP_REASONS:
        fail(f"invalid stop_reason: {task['stop_reason']!r}")

    counts = task["counts"]
    required_counts = {
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
    }
    missing = required_counts - set(counts)
    if missing:
        fail(f"counts missing keys: {sorted(missing)}")
    if counts["product_candidates"] != (
        counts["pending_products"] + counts["in_flight_products"] + counts["processed_products"]
    ):
        fail("product_candidates invariant broken")
    if counts["processed_products"] != (
        counts["valid_products"] + counts["excluded_products"] + counts["failed_products"]
    ):
        fail("processed_products invariant broken")
    if counts["in_flight_products"] != 0:
        fail("in_flight_products must be 0 at FINISHED")
    if counts["partial_description_products"] > counts["valid_products"]:
        fail("partial_description_products exceeds valid_products")
    if counts["valid_products"] != len(data_rows):
        fail(
            f"valid.csv has {len(data_rows)} rows but counts.valid_products="
            f"{counts['valid_products']}"
        )

    coverage = task["coverage"]
    if coverage.get("status") not in COVERAGE_STATUSES:
        fail(f"invalid coverage.status: {coverage.get('status')!r}")
    for key in ("status", "denominator_source", "denominator", "covered", "notes"):
        if key not in coverage:
            fail(f"coverage missing {key}")

    acceptance = task["business_acceptance"]
    for key in ("status", "accepted_by", "accepted_at", "reason", "scope"):
        if key not in acceptance:
            fail(f"business_acceptance missing {key}")

    source_urls: set[str] = set()
    for index, row in enumerate(data_rows, start=2):
        name, price, currency, image, _description, _category, _brand, _attrs, source = row
        if not name.strip():
            fail(f"row {index}: empty name")
        try:
            amount = float(price)
        except ValueError:
            fail(f"row {index}: price is not numeric: {price!r}")
        if amount <= 0:
            fail(f"row {index}: price is not positive")
        if not re.fullmatch(r"[A-Z]{3}", currency):
            fail(f"row {index}: invalid currency {currency!r}")
        check_url(image, f"row {index} primary_image_url")
        check_url(source, f"row {index} source_url")
        if source in source_urls:
            fail(f"row {index}: duplicate source_url {source}")
        source_urls.add(source)

    for exception in task["quality_exceptions"]:
        for key in ("source_url", "description_status", "missing_reasons"):
            if key not in exception:
                fail(f"quality_exception missing {key}: {exception}")
        if exception["source_url"] not in source_urls:
            fail(f"quality_exception source_url not in valid.csv: {exception['source_url']}")

    audit_path = directory / "diagnostics" / summary["label"] / "product-audit.jsonl"
    if not audit_path.is_file():
        fail(f"missing {audit_path}")
    audits = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    valid_audits = sum(1 for audit in audits if audit.get("status") == "valid")
    excluded_audits = sum(1 for audit in audits if audit.get("status") == "excluded")
    failed_audits = sum(1 for audit in audits if audit.get("status") == "failed")
    if (valid_audits, excluded_audits, failed_audits) != (
        counts["valid_products"],
        counts["excluded_products"],
        counts["failed_products"],
    ):
        fail("product-audit counts do not match task-result counts")

    diagnostics = directory / "diagnostics" / summary["label"]
    for name in (
        "events.ndjson",
        "product-audit.jsonl",
        "discovered_urls.txt",
        "robots.txt",
        "excluded_products.csv",
        "failed_products.csv",
    ):
        if not (diagnostics / name).is_file():
            fail(f"missing diagnostics/{summary['label']}/{name}")

    if summary["valid_products"] != counts["valid_products"]:
        fail("run-summary valid_products does not match task-result")
    if summary["failed_products"] != counts["failed_products"]:
        fail("run-summary failed_products does not match task-result")

    return {
        "valid_products": counts["valid_products"],
        "excluded_products": counts["excluded_products"],
        "failed_products": counts["failed_products"],
        "requests": summary["requests"],
        "elapsed_s": summary["elapsed_s"],
        "first_valid_product_s": summary["first_valid_product_s"],
        "outcome": task["outcome"],
        "coverage": coverage["status"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir",
        default="experiments/r06/familidoo",
        help="R06 output directory containing task-result.json and valid.csv",
    )
    args = parser.parse_args(argv)
    result = validate(Path(args.dir))
    first_valid = result["first_valid_product_s"]
    first_valid_text = "None" if first_valid is None else f"{first_valid}s"
    print(
        "OK: "
        f"{result['valid_products']} valid, "
        f"{result['excluded_products']} excluded, "
        f"{result['failed_products']} failed, "
        f"{result['requests']} requests, "
        f"{result['elapsed_s']}s, "
        f"first_valid={first_valid_text}, "
        f"outcome={result['outcome']}, coverage={result['coverage']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
