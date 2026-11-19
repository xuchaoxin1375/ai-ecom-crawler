"""CSV, JSON and task-result serialisation for the skatepro.es plan.

The business CSV is the 9-column contract from docs/02.  Quality and trace
fields stay in the internal rows (``diagnostics/<run>/products.jsonl``) and in
the task result's ``quality_exceptions`` array; they are not CSV columns.
"""

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
]

# Fields that must be present for a valid product.  Optional business fields
# may be empty when the source does not provide them, with a reason in
# missing_reasons.  These keys live on the internal row, not in the CSV.
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

DESCRIPTION_STATUSES = {
    "complete",
    "partial",
    "fallback",
    "not_provided",
    "failed",
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


def write_valid_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=CSV_COLUMNS,
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n",
            extrasaction="ignore",
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


def quality_exceptions(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Index valid products whose description or fields are not complete.

    A row is listed when its description is not ``complete`` or when at least
    one field has a recorded missing reason.  Complete rows without any missing
    reason are not repeated here.
    """

    exceptions: list[dict[str, Any]] = []
    for row in rows:
        reasons = row.get("missing_reasons") or {}
        status = row.get("description_status")
        if status == "complete" and not reasons:
            continue
        exceptions.append(
            {
                "source_url": row["source_url"],
                "description_status": status,
                "partial_reason": row.get("partial_reason") or None,
                "missing_reasons": reasons,
            }
        )
    return exceptions


def build_task_result(
    *,
    task_id: str,
    plan_id: str,
    plan_version: str,
    site: str,
    market: str,
    locale: str,
    state: str,
    outcome: str,
    stop_reason: str,
    started_at: str,
    finished_at: str,
    discovered_urls: int,
    pending_navigation_entries: int,
    candidate_count: int,
    processed_count: int,
    valid_count: int,
    excluded_count: int,
    failed_count: int,
    partial_count: int,
    coverage: dict[str, Any],
    runtime: dict[str, Any],
    notes: list[str],
    exceptions: list[dict[str, Any]],
) -> dict[str, Any]:
    pending = max(0, candidate_count - processed_count)
    payload: dict[str, Any] = {
        "task_id": task_id,
        "plan_id": plan_id,
        "plan_version": plan_version,
        "site": site,
        "market": market,
        "locale": locale,
        "state": state,
        "outcome": outcome,
        "stop_reason": stop_reason,
        "started_at": started_at,
        "finished_at": finished_at,
        "counts": {
            "discovered_urls": discovered_urls,
            "pending_navigation_entries": pending_navigation_entries,
            "product_candidates": candidate_count,
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
            "scope": f"First {candidate_count} sampled public product pages.",
        },
        "runtime": runtime,
        "notes": notes,
    }
    if exceptions:
        payload["quality_exceptions"] = exceptions
    return payload
