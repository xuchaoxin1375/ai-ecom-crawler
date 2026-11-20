#!/usr/bin/env python3
"""Offline check for the familidoo R04 pilot output."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the 9-column CSV and task-result invariants.")
    parser.add_argument("--dir", default=str(Path(__file__).resolve().parents[1]), help="output directory")
    return parser.parse_args(argv)


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = Path(args.dir).resolve()
    csv_path = out_dir / "valid.csv"
    result_path = out_dir / "task-result.json"
    summary_path = out_dir / "run-summary.json"
    for path in (csv_path, result_path, summary_path):
        if not path.is_file():
            fail(f"missing {path}")
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != CSV_COLUMNS:
            fail(f"CSV columns differ: {reader.fieldnames}")
        rows = list(reader)
    if not rows:
        fail("valid.csv has no rows")
    for index, row in enumerate(rows, start=2):
        name = (row.get("name") or "").strip()
        price = (row.get("price_amount") or "").strip()
        currency = (row.get("price_currency") or "").strip()
        image = (row.get("primary_image_url") or "").strip()
        description = (row.get("description_html") or "").strip()
        source = (row.get("source_url") or "").strip()
        if not name:
            fail(f"row {index}: empty name")
        try:
            amount = float(price)
        except ValueError:
            fail(f"row {index}: price is not numeric: {price!r}")
        if not amount > 0:
            fail(f"row {index}: price must be positive")
        if currency != "EUR":
            fail(f"row {index}: unexpected currency {currency!r}")
        if not image.startswith("https://"):
            fail(f"row {index}: image is not https: {image!r}")
        if not description:
            fail(f"row {index}: empty description")
        if not source.startswith("https://"):
            fail(f"row {index}: source URL is not https: {source!r}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    counts = result.get("counts", {})
    if counts.get("product_candidates") != (
        counts.get("pending_products", 0)
        + counts.get("in_flight_products", 0)
        + counts.get("processed_products", 0)
    ):
        fail("product_candidates invariant failed")
    if counts.get("processed_products") != (
        counts.get("valid_products", 0)
        + counts.get("excluded_products", 0)
        + counts.get("failed_products", 0)
    ):
        fail("processed_products invariant failed")
    if counts.get("valid_products") != len(rows):
        fail("valid_products does not match CSV row count")
    coverage = result.get("coverage", {})
    if coverage.get("covered") != len(rows):
        fail("coverage.covered does not match CSV row count")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("requests", 0) < 2:
        fail("run-summary requests look incomplete")
    print(f"OK: {len(rows)} valid products, {summary.get('requests')} requests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
