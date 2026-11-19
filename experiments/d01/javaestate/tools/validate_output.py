"""Validate the D01 javaestate 9-column CSV and task result.

Usage:
  python tools/validate_output.py --dir experiments/d01/javaestate
  python tools/validate_output.py --dir experiments/d01/javaestate --expected-products 30
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path

COLUMNS = [
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
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate D01 javaestate output.")
    parser.add_argument("--dir", default=".", help="directory containing valid.csv and task-result.json")
    parser.add_argument("--expected-products", type=int, default=30, help="expected valid product count")
    args = parser.parse_args()

    root = Path(args.dir)
    csv_path = root / "valid.csv"
    result_path = root / "task-result.json"
    errors: list[str] = []

    if not csv_path.is_file():
        print(f"FAIL: missing {csv_path}", file=sys.stderr)
        return 1
    if not result_path.is_file():
        print(f"FAIL: missing {result_path}", file=sys.stderr)
        return 1

    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != COLUMNS:
            errors.append(f"columns: expected {COLUMNS}, got {reader.fieldnames}")
        rows = list(reader)

    if len(rows) != args.expected_products:
        errors.append(f"rows: expected {args.expected_products}, got {len(rows)}")

    seen_urls: set[str] = set()
    for index, row in enumerate(rows, start=2):
        for column in ("name", "price_amount", "price_currency", "primary_image_url", "description_html", "source_url"):
            if not (row.get(column) or "").strip():
                errors.append(f"row {index}: empty {column}")
        try:
            price = float(row.get("price_amount") or "")
            if not math.isfinite(price) or price <= 0:
                errors.append(f"row {index}: invalid price {row.get('price_amount')!r}")
        except ValueError:
            errors.append(f"row {index}: non-numeric price {row.get('price_amount')!r}")
        currency = (row.get("price_currency") or "").strip()
        if not CURRENCY_RE.match(currency):
            errors.append(f"row {index}: invalid currency {currency!r}")
        url = (row.get("source_url") or "").strip()
        if url in seen_urls:
            errors.append(f"row {index}: duplicate source_url {url}")
        seen_urls.add(url)

    result = json.loads(result_path.read_text(encoding="utf-8"))
    counts = result.get("counts", {})
    if result.get("state") != "FINISHED":
        errors.append(f"state: expected FINISHED, got {result.get('state')}")
    if result.get("outcome") != "PARTIAL":
        errors.append(f"outcome: expected PARTIAL, got {result.get('outcome')}")
    if result.get("stop_reason") != "BUDGET_EXHAUSTED":
        errors.append(f"stop_reason: expected BUDGET_EXHAUSTED, got {result.get('stop_reason')}")
    if counts.get("valid_products") != len(rows):
        errors.append(f"counts.valid_products: {counts.get('valid_products')} != {len(rows)}")
    if counts.get("processed_products") != len(rows) + counts.get("excluded_products", 0) + counts.get("failed_products", 0):
        errors.append("counts: processed != valid + excluded + failed")
    if counts.get("pending_products") != 0 or counts.get("in_flight_products") != 0:
        errors.append("counts: pending or in_flight is not zero")
    if result.get("coverage", {}).get("covered") != len(rows):
        errors.append(f"coverage.covered: {result.get('coverage', {}).get('covered')} != {len(rows)}")
    if result.get("runtime", {}).get("llm_calls") != 0:
        errors.append("runtime.llm_calls: expected 0")
    if result.get("runtime", {}).get("browser_launched") is not False:
        errors.append("runtime.browser_launched: expected false")
    if not isinstance(result.get("quality_exceptions"), list):
        errors.append("quality_exceptions: expected a list")

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(
        f"OK: {len(rows)} rows, {len(COLUMNS)} columns, "
        f"{counts.get('valid_products')} valid, {counts.get('excluded_products')} excluded, "
        f"{counts.get('failed_products')} failed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
