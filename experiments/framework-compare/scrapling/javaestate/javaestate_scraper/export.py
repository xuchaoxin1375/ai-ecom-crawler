"""CSV and diagnostics writers that follow the 22-column data contract."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .config import CSV_COLUMNS
from .normalize import sanitize_spreadsheet_text

TEXT_COLUMNS = {
    "name",
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
}


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]], columns: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = columns or CSV_COLUMNS
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            output = {}
            for key in fields:
                value = row.get(key, "")
                text = "" if value is None else str(value)
                if key in TEXT_COLUMNS:
                    text = sanitize_spreadsheet_text(text)
                output[key] = text
            writer.writerow(output)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
