#!/usr/bin/env python
"""Contract checks for a produced run (no network).

Usage:
  python -m uv run --project experiments/framework-compare/scrapling \
    python experiments/framework-compare/scrapling/skatepro/tools/validate_output.py \
    --dir experiments/framework-compare/scrapling/skatepro
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
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate skatepro valid.csv and task-result.json")
    parser.add_argument("--dir", default=".", help="run output directory")
    args = parser.parse_args(argv)
    out = Path(args.dir)
    problems: list[str] = []

    with (out / "valid.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != EXPECTED_COLUMNS:
            problems.append(f"CSV columns differ: {reader.fieldnames}")
        rows = list(reader)

    seen: set[str] = set()
    for row in rows:
        amount = row["price_amount"]
        try:
            value = float(amount)
        except ValueError:
            problems.append(f"non-numeric price: {amount!r}")
            continue
        if not math.isfinite(value) or value <= 0:
            problems.append(f"non-positive price: {amount!r}")
        if not re.fullmatch(r"[A-Z]{3}", row["price_currency"]):
            problems.append(f"bad currency: {row['price_currency']!r}")
        if not row["name"].strip():
            problems.append("empty name")
        if not row["primary_image_url"].startswith("https://"):
            problems.append(f"bad image: {row['primary_image_url']!r}")
        if not row["source_url"].startswith("https://www.skatepro.es/"):
            problems.append(f"bad source_url: {row['source_url']!r}")
        if row["source_url"] in seen:
            problems.append(f"duplicate source_url: {row['source_url']}")
        seen.add(row["source_url"])
        if not row["description_html"].strip():
            problems.append(f"empty description: {row['source_url']}")
        if FORBIDDEN_TAGS.search(row["description_html"]):
            problems.append(f"forbidden tag in description: {row['source_url']}")

    result = json.loads((out / "task-result.json").read_text(encoding="utf-8"))
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
        counts.get("partial_description_products", 0) <= counts.get("valid_products", 0),
    ]
    if not all(checks):
        problems.append(f"count invariants failed: {checks} / {counts}")

    print(json.dumps({"rows": len(rows), "problems": problems}, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
