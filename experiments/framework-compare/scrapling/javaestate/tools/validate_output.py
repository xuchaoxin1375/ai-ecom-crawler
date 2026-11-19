"""Validate a produced valid.csv / task-result.json pair against docs/02 and docs/09.

Usage:
  python tools/validate_output.py --csv valid.csv --task-result task-result.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path

EXPECTED_COLUMNS = [
    "name",
    "price_amount",
    "price_currency",
    "primary_image_url",
    "description_html",
    "category",
    "brand",
    "attributes",
    "source_url",
    "description_format",
    "description_status",
    "partial_reason",
    "missing_reasons",
    "market",
    "locale",
    "availability",
    "tax_basis",
    "price_basis",
    "task_id",
    "plan_id",
    "plan_version",
    "extracted_at",
]
STATUSES = {"complete", "partial", "fallback", "not_provided", "failed"}
DANGEROUS = re.compile(r"(?is)<(script|style|iframe|form|button|input|img|a\s)")


def validate(csv_path: Path, result_path: Path) -> list[str]:
    problems: list[str] = []
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != EXPECTED_COLUMNS:
            problems.append(f"CSV columns differ: {reader.fieldnames}")
        rows = list(reader)
    if not rows:
        problems.append("valid.csv has no rows")

    urls: set[str] = set()
    for index, row in enumerate(rows, start=2):
        name = (row.get("name") or "").strip()
        if not name:
            problems.append(f"line {index}: empty name")
        try:
            amount = float(row["price_amount"])
            if not math.isfinite(amount) or amount <= 0:
                problems.append(f"line {index}: non-positive/non-finite price {row['price_amount']!r}")
        except (TypeError, ValueError):
            problems.append(f"line {index}: unparseable price {row['price_amount']!r}")
        if not re.fullmatch(r"[A-Z]{3}", row.get("price_currency") or ""):
            problems.append(f"line {index}: bad currency {row.get('price_currency')!r}")
        if not re.match(r"^https://", row.get("primary_image_url") or ""):
            problems.append(f"line {index}: bad image URL")
        if not re.match(r"^https://javaestate\.com/products/[^/]+$", row.get("source_url") or ""):
            problems.append(f"line {index}: bad source URL")
        if row.get("source_url") in urls:
            problems.append(f"line {index}: duplicate source_url {row.get('source_url')}")
        urls.add(row.get("source_url"))
        if row.get("description_status") not in STATUSES:
            problems.append(f"line {index}: bad description_status")
        if row.get("description_status") == "partial" and not row.get("partial_reason"):
            problems.append(f"line {index}: partial without partial_reason")
        if row.get("description_status") != "partial" and row.get("partial_reason"):
            problems.append(f"line {index}: partial_reason on non-partial row")
        if row.get("description_status") in {"complete", "partial"} and not row.get("description_html"):
            problems.append(f"line {index}: body status without description_html")
        if row.get("description_format") not in {"html", "text", ""}:
            problems.append(f"line {index}: bad description_format")
        try:
            missing = json.loads(row.get("missing_reasons") or "{}")
            if not isinstance(missing, dict):
                problems.append(f"line {index}: missing_reasons is not an object")
        except json.JSONDecodeError:
            problems.append(f"line {index}: missing_reasons is not valid JSON")
        if DANGEROUS.search(row.get("description_html") or ""):
            problems.append(f"line {index}: description contains unsafe tags")
        if row.get("market") != "US" or row.get("locale") != "en-US":
            problems.append(f"line {index}: unexpected market/locale")
        if row.get("tax_basis") not in {"unknown_not_stated", "no_tax_applied", "mixed_taxability"}:
            problems.append(f"line {index}: unexpected tax_basis {row.get('tax_basis')!r}")

    result = json.loads(result_path.read_text(encoding="utf-8"))
    counts = result.get("counts", {})
    invariant_errors = []
    if counts.get("product_candidates") != (
        counts.get("pending_products", 0) + counts.get("in_flight_products", 0) + counts.get("processed_products", 0)
    ):
        invariant_errors.append("product_candidates != pending + in_flight + processed")
    if counts.get("processed_products") != (
        counts.get("valid_products", 0) + counts.get("excluded_products", 0) + counts.get("failed_products", 0)
    ):
        invariant_errors.append("processed != valid + excluded + failed")
    if counts.get("valid_products") != len(rows):
        invariant_errors.append(f"valid_products {counts.get('valid_products')} != CSV rows {len(rows)}")
    if counts.get("partial_description_products", 0) > counts.get("valid_products", 0):
        invariant_errors.append("partial_description_products > valid_products")
    if counts.get("in_flight_products", 0) != 0:
        invariant_errors.append("in_flight_products != 0 at FINISHED")
    problems.extend(invariant_errors)
    if result.get("state") != "FINISHED":
        problems.append(f"state is {result.get('state')}, expected FINISHED")
    if result.get("runtime", {}).get("llm_calls") != 0:
        problems.append("runtime.llm_calls is not 0")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="valid.csv")
    parser.add_argument("--task-result", default="task-result.json")
    args = parser.parse_args()
    problems = validate(Path(args.csv), Path(args.task_result))
    if problems:
        print("FAIL")
        for item in problems:
            print("-", item)
        return 1
    print("OK: 22 columns, prices, currencies, descriptions, CSV/JSON invariants")
    return 0


if __name__ == "__main__":
    sys.exit(main())
