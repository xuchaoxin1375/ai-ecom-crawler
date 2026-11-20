#!/usr/bin/env python3
"""Compare the A08 homepage, D06 collection page and public JSON paths."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_A08 = REPO_ROOT / "experiments/d03/decohappy/tasks/a08-product-003/products.jsonl"
DEFAULT_COLLECTION = REPO_ROOT / "experiments/d06/decohappy/tasks/d06-collection-001/urls.csv"
DEFAULT_JSON = REPO_ROOT / "experiments/d06/decohappy/public-json-summary.json"


def read_a08(path: Path) -> set[str]:
    return {
        json.loads(line)["source_url"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def read_collection(path: Path) -> set[str]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["url"] for row in csv.DictReader(handle) if row.get("url")}


def read_json(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        f"https://decohappy.com/fr/products/{item['handle']}"
        for item in payload["products"]
        if item.get("handle")
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a08-products", type=Path, default=DEFAULT_A08)
    parser.add_argument("--collection-urls", type=Path, default=DEFAULT_COLLECTION)
    parser.add_argument("--json-summary", type=Path, default=DEFAULT_JSON)
    args = parser.parse_args()

    home = read_a08(args.a08_products)
    collection = read_collection(args.collection_urls)
    public_json = read_json(args.json_summary)
    print(f"homepage A08: {len(home)}")
    print(f"collection page 1: {len(collection)}")
    print(f"public JSON: {len(public_json)}")
    print(f"homepage ∩ collection: {len(home & collection)}")
    print(f"homepage ∩ JSON: {len(home & public_json)}")
    print(f"collection ∩ JSON: {len(collection & public_json)}")
    print(f"all three: {len(home & collection & public_json)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
