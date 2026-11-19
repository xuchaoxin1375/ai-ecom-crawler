"""Validate the exported CSV and task result against the local contracts.

Usage:
  python tools/validate_output.py --valid-csv valid.csv --task-result task-result.json \
      --diagnostics diagnostics/fix-rerun

This is deliberately a local consistency check; it does not claim the site was
fully audited or that the sitemap denominator is complete.
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

from crawlee_javaestate.export import CSV_COLUMNS


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--valid-csv", required=True)
    parser.add_argument("--task-result", required=True)
    parser.add_argument("--diagnostics", required=True)
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []

    csv_path = Path(args.valid_csv)
    result = json.loads(Path(args.task_result).read_text(encoding="utf-8"))
    diag = Path(args.diagnostics)

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != CSV_COLUMNS:
            errors.append(f"CSV columns differ from docs/02: {reader.fieldnames}")
        rows = list(reader)

    if len(rows) != result["counts"]["valid_products"]:
        errors.append(
            f"CSV rows {len(rows)} != valid_products {result['counts']['valid_products']}"
        )
    if len(rows) == 0:
        errors.append("No valid rows")

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
        if row["price_currency"] != "USD":
            errors.append(f"row {index}: currency is not USD")
        if row["market"] != "US" or row["locale"] != "en-US":
            errors.append(f"row {index}: market/locale mismatch")
        if row["description_status"] not in {
            "complete",
            "partial",
            "fallback",
            "not_provided",
            "failed",
        }:
            errors.append(f"row {index}: bad description_status")
        if row["description_status"] == "complete" and not row["description_html"]:
            errors.append(f"row {index}: complete but empty description")
        if row["description_status"] == "not_provided" and row["description_html"]:
            errors.append(f"row {index}: not_provided but non-empty description")
        if row["description_status"] == "partial" and not row["partial_reason"]:
            errors.append(f"row {index}: partial without partial_reason")
        if row["description_status"] != "partial" and row["partial_reason"]:
            errors.append(f"row {index}: non-partial has partial_reason")
        for field in ("primary_image_url", "source_url"):
            parts = urlsplit(row[field])
            if parts.scheme not in ("http", "https") or not parts.hostname:
                errors.append(f"row {index}: invalid {field}")
        if row["source_url"] in seen_urls:
            errors.append(f"row {index}: duplicate source_url {row['source_url']}")
        seen_urls.add(row["source_url"])
        try:
            reasons = json.loads(row["missing_reasons"])
        except json.JSONDecodeError:
            errors.append(f"row {index}: missing_reasons is not JSON")
            continue
        if not isinstance(reasons, dict):
            errors.append(f"row {index}: missing_reasons is not an object")
        if row["category"] == "!":
            errors.append(f"row {index}: legacy ! category")
        if row["plan_id"] != result["plan_id"]:
            errors.append(f"row {index}: plan_id mismatch")
        if row["plan_version"] != result["plan_version"]:
            errors.append(f"row {index}: plan_version mismatch")
        if row["task_id"] != result["task_id"]:
            errors.append(f"row {index}: task_id mismatch")

    counts = result["counts"]
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

    for name in ("excluded.jsonl", "failed.jsonl", "pending.jsonl"):
        path = diag / name
        if not path.exists():
            warnings.append(f"{name} missing (expected when the count is zero)")
            continue
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        expected_key = {
            "excluded.jsonl": "excluded_products",
            "failed.jsonl": "failed_products",
            "pending.jsonl": "pending_products",
        }[name]
        if len(records) != counts[expected_key]:
            errors.append(f"{name} has {len(records)} rows, expected {counts[expected_key]}")

    print(f"rows={len(rows)} candidates={counts['product_candidates']} "
          f"valid={counts['valid_products']} excluded={counts['excluded_products']} "
          f"failed={counts['failed_products']} pending={counts['pending_products']} "
          f"partial={counts['partial_description_products']}")
    print(f"outcome={result['outcome']} stop_reason={result['stop_reason']} "
          f"coverage={result['coverage']['status']} plan_version={result['plan_version']}")
    for warning in warnings:
        print(f"WARN {warning}")
    for error in errors:
        print(f"ERROR {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
