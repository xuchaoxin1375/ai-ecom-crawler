"""CSV, JSON and task-result serialisation."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any, Iterable

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

# Fields that must be present for a valid product.  Optional fields may be
# empty when the source does not provide them, with a reason in
# missing_reasons.
REQUIRED_ROW_FIELDS = {
    "name",
    "price_amount",
    "price_currency",
    "primary_image_url",
    "source_url",
    "market",
    "locale",
    "description_status",
    "price_basis",
    "task_id",
    "plan_id",
    "plan_version",
    "extracted_at",
}


def csv_safe(value: Any) -> Any:
    """Protect spreadsheet consumers from formula-looking text cells.

    Amounts are written as numbers and never go through this function.
    """

    if not isinstance(value, str):
        return value
    if value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def write_valid_csv(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=CSV_COLUMNS,
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n",
            extrasaction="raise",
        )
        writer.writeheader()
        for row in rows:
            missing = [column for column in CSV_COLUMNS if column not in row]
            if missing:
                raise ValueError(f"Row is missing CSV columns: {missing}")
            output = {column: row[column] for column in CSV_COLUMNS}
            for column, value in output.items():
                if column == "price_amount":
                    continue
                output[column] = csv_safe(value)
            writer.writerow(output)
    os.replace(temp, path)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temp, path)


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_jsonl(path: Path, rows: Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(temp, path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def build_task_result(
    *,
    task_id: str,
    plan_id: str,
    plan_version: str,
    market: str,
    locale: str,
    state: str,
    outcome: str,
    stop_reason: str,
    started_at: str,
    finished_at: str,
    candidates: list[str],
    processed: dict[str, str],
    valid_count: int,
    excluded_count: int,
    failed_count: int,
    partial_count: int,
    coverage: dict[str, Any],
    runtime: dict[str, Any],
    notes: list[str],
) -> dict[str, Any]:
    processed_count = len(processed)
    pending = max(0, len(candidates) - processed_count)
    return {
        "task_id": task_id,
        "plan_id": plan_id,
        "plan_version": plan_version,
        "site": "javaestate.com",
        "market": market,
        "locale": locale,
        "state": state,
        "outcome": outcome,
        "stop_reason": stop_reason,
        "started_at": started_at,
        "finished_at": finished_at,
        "counts": {
            "discovered_urls": len(candidates) + 2,
            "pending_navigation_entries": 0 if candidates else 1,
            "product_candidates": len(candidates),
            "pending_products": pending,
            "in_flight_products": 0,
            "processed_products": processed_count,
            "valid_products": valid_count,
            "excluded_products": excluded_count,
            "failed_products": failed_count,
            "partial_description_products": partial_count,
        },
        "coverage": coverage,
        "business_acceptance": {
            "status": "NOT_REVIEWED",
            "accepted_by": None,
            "accepted_at": None,
            "reason": "Bounded framework-comparison trial; user acceptance pending.",
            "scope": f"First {len(candidates)} selected product pages from the public product sitemap.",
        },
        "runtime": runtime,
        "notes": notes,
    }
