#!/usr/bin/env python3
"""Convert an R06 product task output into the app D02 run directory.

The R06 runtime is still the fetch/extract prototype.  This adapter only maps
its accepted product records into the production export input; it does not
fetch pages or re-implement extraction.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def split_escaped(value: str, separator: str) -> list[str]:
    """Split on an unescaped separator, keeping escape sequences intact."""
    parts: list[str] = []
    buffer: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character == "\\" and index + 1 < len(value):
            buffer.append(character)
            buffer.append(value[index + 1])
            index += 2
            continue
        if character == separator:
            parts.append("".join(buffer))
            buffer = []
            index += 1
            continue
        buffer.append(character)
        index += 1
    parts.append("".join(buffer))
    return parts


def unescape(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == "\\" and index + 1 < len(value):
            result.append(value[index + 1])
            index += 2
            continue
        result.append(value[index])
        index += 1
    return "".join(result)


def parse_attributes(value: str) -> list[dict[str, Any]]:
    """Parse the docs/02 compatibility string back into option groups."""
    if not value.strip():
        return []
    groups: list[dict[str, Any]] = []
    for raw_group in split_escaped(value, "~"):
        if not raw_group:
            continue
        parts = split_escaped(raw_group, "#")
        if len(parts) != 2:
            continue
        name = unescape(parts[0]).strip()
        values = [
            unescape(item).strip()
            for item in split_escaped(parts[1], "|")
            if unescape(item).strip()
        ]
        if name and values:
            groups.append({"name": name, "values": values})
    return groups


def to_candidate(
    product: dict[str, Any],
    task: dict[str, Any],
    *,
    partial_reason: str | None = None,
) -> dict[str, Any]:
    status = product.get("description_status")
    if not status:
        raise SystemExit(
            f"product has no explicit description_status: {product.get('source_url')}"
        )
    reason = product.get("partial_reason")
    if status.lower() == "partial" and partial_reason:
        reason = partial_reason
    category = str(product.get("category") or "").strip()
    return {
        "source_url": product["source_url"],
        "name": product["name"],
        "price": {
            "amount": product["price_amount"],
            "currency": product["price_currency"],
            "tax_basis": product.get("tax_basis"),
            "displayed": product.get("price_displayed"),
            "pretax": product.get("price_pretax"),
        },
        "primary_image_url": product["primary_image_url"],
        "description_html": product.get("description_html") or "",
        "description_format": "html",
        "description_status": status,
        "partial_reason": reason,
        "missing_reasons": product.get("missing_reasons") or {},
        "categories": [category] if category else [],
        "brand": product.get("brand") or None,
        "options": parse_attributes(str(product.get("attributes") or "")),
        "market": task.get("market", "FR"),
        "locale": task.get("locale", "fr-FR"),
        "extracted_at": task.get("finished_at"),
        "field_sources": product.get("field_sources") or {},
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert R06 products.jsonl and task-result.json into app candidates.",
    )
    parser.add_argument("--task-result", required=True, type=Path)
    parser.add_argument("--products", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument(
        "--partial-reason",
        default=None,
        help="override the generic R06 partial-description reason",
    )
    args = parser.parse_args()

    task = json.loads(args.task_result.read_text(encoding="utf-8"))
    products = [
        json.loads(line)
        for line in args.products.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    candidates = [
        to_candidate(product, task, partial_reason=args.partial_reason)
        for product in products
    ]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "task.json").write_text(
        json.dumps(task, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.out_dir / "candidates.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in candidates) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(candidates)} candidates to {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
