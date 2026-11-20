#!/usr/bin/env python3
"""Validate an R06 runtime demo directory: task ledger, task results and CSVs."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

URL_COLUMNS = ["url", "source", "status", "title"]
PRODUCT_COLUMNS = [
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
OUTCOMES = {"COMPLETED", "PARTIAL", "FAILED", "CANCELLED"}


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def read_csv(path: Path) -> list[list[str]]:
    if not path.is_file():
        fail(f"missing {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def validate(root: Path) -> dict[str, Any]:
    db_path = root / "tasks.db"
    if not db_path.is_file():
        fail(f"missing {db_path}")
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    tasks = connection.execute("SELECT * FROM tasks ORDER BY task_id").fetchall()
    if not tasks:
        fail("task ledger is empty")

    summaries = []
    for task in tasks:
        task_id = task["task_id"]
        task_type = task["task_type"]
        state = task["state"]
        outcome = task["outcome"]
        task_dir = root / "tasks" / task_id
        result_path = task_dir / "task-result.json"
        if not result_path.is_file():
            fail(f"missing {result_path}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("task_type") != task_type:
            fail(f"{task_id}: task_type mismatch")
        if result.get("state") not in {"FINISHED", "CANCELLED"}:
            fail(f"{task_id}: runtime demo task should be terminal")
        if state not in {"FINISHED", "CANCELLED"}:
            fail(f"{task_id}: ledger state {state} is not terminal")
        if outcome not in OUTCOMES:
            fail(f"{task_id}: invalid outcome {outcome!r}")

        counts = result.get("counts", {})
        if task_type == "discovery":
            expected = (
                counts.get("pending_urls", 0)
                + counts.get("valid_urls", 0)
                + counts.get("excluded_urls", 0)
                + counts.get("failed_urls", 0)
            )
            if counts.get("url_candidates") != expected:
                fail(f"{task_id}: url_candidates invariant broken")
        else:
            candidates = (
                counts.get("pending_products", 0)
                + counts.get("in_flight_products", 0)
                + counts.get("processed_products", 0)
            )
            if counts.get("product_candidates") != candidates:
                fail(f"{task_id}: product_candidates invariant broken")
            processed = (
                counts.get("valid_products", 0)
                + counts.get("excluded_products", 0)
                + counts.get("failed_products", 0)
            )
            if counts.get("processed_products") != processed:
                fail(f"{task_id}: processed_products invariant broken")
            if counts.get("partial_description_products", 0) > counts.get(
                "valid_products", 0
            ):
                fail(f"{task_id}: partial_description_products exceeds valid_products")

        urls = read_csv(task_dir / "urls.csv")
        if urls and urls[0] != URL_COLUMNS:
            fail(f"{task_id}: urls.csv header mismatch")
        url_rows = urls[1:] if urls else []
        if len({row[0] for row in url_rows}) != len(url_rows):
            fail(f"{task_id}: duplicate URLs in urls.csv")
        if task_type == "discovery" and counts.get("valid_urls") != len(url_rows):
            fail(f"{task_id}: valid_urls does not match urls.csv")

        products = read_csv(task_dir / "products.csv")
        if products and products[0] != PRODUCT_COLUMNS:
            fail(f"{task_id}: products.csv header mismatch")
        product_rows = products[1:] if products else []
        if task_type == "product" and counts.get("valid_products") != len(product_rows):
            fail(f"{task_id}: valid_products does not match products.csv")

        for name in ("events.ndjson", "items.jsonl"):
            if not (task_dir / name).is_file():
                fail(f"{task_id}: missing {name}")

        summaries.append(
            {
                "task_id": task_id,
                "task_type": task_type,
                "outcome": outcome,
                "urls": len(url_rows),
                "products": len(product_rows),
            }
        )

    connection.close()
    return {"tasks": summaries}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default="experiments/r06/runtime-demo",
        help="runtime demo root containing tasks.db and tasks/",
    )
    args = parser.parse_args(argv)
    result = validate(Path(args.root))
    print("OK: runtime demo")
    for task in result["tasks"]:
        print(
            f"  {task['task_id']}: type={task['task_type']} outcome={task['outcome']} "
            f"urls={task['urls']} products={task['products']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
