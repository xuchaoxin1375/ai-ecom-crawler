"""Validate the exported CSV and task result against the local contracts.

Usage:
  python tools/validate_output.py --valid-csv valid.csv \
      --task-result task-result.json --diagnostics diagnostics/run-001

The check compares the 9-column CSV with the internal rows that produced it,
so a status or reason that only exists in the task report cannot drift away
from the exported business values.  It is a local consistency check; it does
not claim the site was fully audited or that the sitemap is complete.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawlee_skatepro.export import CSV_COLUMNS, DESCRIPTION_STATUSES  # noqa: E402


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--valid-csv", required=True)
    parser.add_argument("--task-result", required=True)
    parser.add_argument("--diagnostics", required=True)
    parser.add_argument("--currency", default="EUR")
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []

    csv_path = Path(args.valid_csv)
    result = json.loads(Path(args.task_result).read_text(encoding="utf-8"))
    diag = Path(args.diagnostics)

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != CSV_COLUMNS:
            errors.append(f"CSV columns differ from docs/02 9 columns: {reader.fieldnames}")
        rows = list(reader)

    counts = result["counts"]
    if len(rows) != counts["valid_products"]:
        errors.append(f"CSV rows {len(rows)} != valid_products {counts['valid_products']}")
    if len(rows) == 0:
        errors.append("No valid rows")

    internal = [
        item["row"]
        for item in read_jsonl(diag / "products.jsonl")
        if item.get("status") == "valid"
    ]
    by_url = {row["source_url"]: row for row in internal}
    if len(internal) != len(rows):
        errors.append(f"internal valid rows {len(internal)} != CSV rows {len(rows)}")

    seen_urls: set[str] = set()
    for index, row in enumerate(rows, start=2):
        try:
            amount = Decimal(row["price_amount"])
        except (InvalidOperation, ValueError):
            errors.append(f"row {index}: invalid price {row['price_amount']!r}")
            continue
        if not amount.is_finite() or amount <= 0:
            errors.append(f"row {index}: non-positive price {amount}")
        if not re.fullmatch(r"[A-Z]{3}", row["price_currency"]):
            errors.append(f"row {index}: invalid currency {row['price_currency']!r}")
        if row["price_currency"] != args.currency:
            errors.append(f"row {index}: currency is not {args.currency}")
        for field in ("primary_image_url", "source_url"):
            parts = urlsplit(row[field])
            if parts.scheme not in ("http", "https") or not parts.hostname:
                errors.append(f"row {index}: invalid {field}")
        if row["source_url"] in seen_urls:
            errors.append(f"row {index}: duplicate source_url {row['source_url']}")
        seen_urls.add(row["source_url"])
        if row["category"] == "!":
            errors.append(f"row {index}: legacy ! category")
        if "\r" in row["description_html"]:
            warnings.append(f"row {index}: description_html contains CR")
        internal_row = by_url.get(row["source_url"])
        if internal_row is None:
            errors.append(f"row {index}: no internal row for {row['source_url']}")
            continue
        for column in CSV_COLUMNS:
            if row[column] != internal_row[column]:
                errors.append(f"row {index}: CSV {column} differs from internal row")
        status = internal_row["description_status"]
        if status not in DESCRIPTION_STATUSES:
            errors.append(f"row {index}: bad description_status {status!r}")
        if status == "complete" and not internal_row["description_html"]:
            errors.append(f"row {index}: complete but empty description")
        if status == "not_provided" and internal_row["description_html"]:
            errors.append(f"row {index}: not_provided but non-empty description")
        if status == "partial" and not internal_row["partial_reason"]:
            errors.append(f"row {index}: partial without partial_reason")
        if status != "partial" and internal_row["partial_reason"]:
            errors.append(f"row {index}: non-partial has partial_reason")

    if counts["processed_products"] != (
        counts["valid_products"] + counts["excluded_products"] + counts["failed_products"]
    ):
        errors.append(f"processed invariant violated: {counts}")
    if counts["product_candidates"] != (
        counts["pending_products"]
        + counts["in_flight_products"]
        + counts["processed_products"]
    ):
        errors.append(f"candidate invariant violated: {counts}")
    if counts["partial_description_products"] > counts["valid_products"]:
        errors.append(f"partial invariant violated: {counts}")
    if counts["in_flight_products"] != 0:
        errors.append(f"in_flight_products must be 0 in a terminal state: {counts}")

    expected_partial = sum(
        1 for row in internal if row["description_status"] == "partial"
    )
    if expected_partial != counts["partial_description_products"]:
        errors.append(
            f"partial_description_products {counts['partial_description_products']} "
            f"!= internal partial rows {expected_partial}"
        )

    exceptions = result.get("quality_exceptions") or []
    expected_exceptions = {
        row["source_url"]
        for row in internal
        if row["description_status"] != "complete" or row.get("missing_reasons")
    }
    listed = {item["source_url"] for item in exceptions}
    if listed != expected_exceptions:
        errors.append(
            "quality_exceptions does not match the rows with a non-complete "
            f"description or a missing reason: missing={sorted(expected_exceptions - listed)} "
            f"extra={sorted(listed - expected_exceptions)}"
        )
    for item in exceptions:
        for key in ("source_url", "description_status", "partial_reason", "missing_reasons"):
            if key not in item:
                errors.append(f"quality_exceptions entry lacks {key}")
        if item.get("description_status") not in DESCRIPTION_STATUSES:
            errors.append(f"quality_exceptions bad status for {item.get('source_url')}")

    for name in ("excluded.jsonl", "failed.jsonl", "pending.jsonl"):
        path = diag / name
        if not path.exists():
            warnings.append(f"{name} missing (expected when the count is zero)")
            continue
        records = read_jsonl(path)
        expected_key = {
            "excluded.jsonl": "excluded_products",
            "failed.jsonl": "failed_products",
            "pending.jsonl": "pending_products",
        }[name]
        if len(records) != counts[expected_key]:
            errors.append(f"{name} has {len(records)} rows, expected {counts[expected_key]}")

    if result["runtime"].get("llm_calls") != 0:
        errors.append("runtime.llm_calls is not 0")

    print(
        f"rows={len(rows)} candidates={counts['product_candidates']} "
        f"valid={counts['valid_products']} excluded={counts['excluded_products']} "
        f"failed={counts['failed_products']} pending={counts['pending_products']} "
        f"partial={counts['partial_description_products']} exceptions={len(exceptions)}"
    )
    print(
        f"outcome={result['outcome']} stop_reason={result['stop_reason']} "
        f"coverage={result['coverage']['status']} plan_version={result['plan_version']}"
    )
    for warning in warnings:
        print(f"WARN {warning}")
    for error in errors:
        print(f"ERROR {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
