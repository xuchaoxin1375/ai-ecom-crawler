#!/usr/bin/env python
"""Validate the S5 shopthebulkstore 9-column output (offline).

Usage:
  python experiments/d01/shopthebulkstore/tools/validate_output.py --dir experiments/d01/shopthebulkstore
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
]
FORBIDDEN_TAGS = re.compile(r"(?i)<(script|style|iframe|img|form|input|select|textarea|a)\b")
REQUIRED_RESULT_FIELDS = [
    "task_id",
    "plan_id",
    "plan_version",
    "market",
    "locale",
    "state",
    "outcome",
    "stop_reason",
    "counts",
    "coverage",
    "business_acceptance",
    "quality_exceptions",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate shopthebulkstore 9-column output")
    parser.add_argument("--dir", default=".", help="run output directory")
    parser.add_argument("--expected-products", type=int, default=30)
    parser.add_argument("--source-prefix", default="https://shopthebulkstore.com/")
    args = parser.parse_args(argv)
    out = Path(args.dir)
    problems: list[str] = []

    try:
        with (out / "valid.csv").open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != EXPECTED_COLUMNS:
                problems.append(f"CSV columns differ: {reader.fieldnames}")
            rows = list(reader)
    except FileNotFoundError:
        print(f"FAIL: missing {out / 'valid.csv'}", file=sys.stderr)
        return 1

    if len(rows) != args.expected_products:
        problems.append(f"expected {args.expected_products} rows, got {len(rows)}")

    seen: set[str] = set()
    for row in rows:
        amount = row.get("price_amount", "")
        try:
            value = float(amount)
            if not math.isfinite(value) or value <= 0:
                problems.append(f"non-positive price: {amount!r}")
        except ValueError:
            problems.append(f"non-numeric price: {amount!r}")
        if not re.fullmatch(r"[A-Z]{3}", row.get("price_currency", "")):
            problems.append(f"bad currency: {row.get('price_currency')!r}")
        if not row.get("name", "").strip():
            problems.append("empty name")
        if not row.get("primary_image_url", "").startswith("https://"):
            problems.append(f"bad image: {row.get('primary_image_url')!r}")
        url = row.get("source_url", "")
        if not url.startswith(args.source_prefix):
            problems.append(f"bad source_url: {url!r}")
        if url in seen:
            problems.append(f"duplicate source_url: {url}")
        seen.add(url)
        if FORBIDDEN_TAGS.search(row.get("description_html", "")):
            problems.append(f"forbidden tag in description: {url}")

    result_path = out / "task-result.json"
    if not result_path.is_file():
        problems.append("missing task-result.json")
        result = {}
    else:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        for field in REQUIRED_RESULT_FIELDS:
            if field not in result:
                problems.append(f"task-result missing {field}")
        counts = result.get("counts", {})
        checks = [
            counts.get("product_candidates")
            == counts.get("pending_products", 0)
            + counts.get("in_flight_products", 0)
            + counts.get("processed_products", 0),
            counts.get("processed_products")
            == counts.get("valid_products", 0)
            + counts.get("excluded_products", 0)
            + counts.get("failed_products", 0),
            counts.get("valid_products") == len(rows),
            result.get("runtime", {}).get("llm_calls") == 0,
            result.get("runtime", {}).get("browser_launched") is False,
            result.get("coverage", {}).get("covered") == len(rows),
        ]
        if not all(checks):
            problems.append(f"count/runtime invariants failed: {checks} / {counts}")
        if not isinstance(result.get("quality_exceptions"), list):
            problems.append("quality_exceptions is not a list")
        unit_counts = result.get("discovery", {}).get("price_unit_counts") or {}
        if unit_counts.get("per_lb", 0) < 1:
            problems.append(f"expected at least one per_lb product, got {unit_counts}")

    print(json.dumps({"rows": len(rows), "problems": problems}, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
