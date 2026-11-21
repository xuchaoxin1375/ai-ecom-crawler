"""Bridge R06 runtime task output into the D02 export input.

The runtime writes its own ``products.jsonl`` and ``task-result.json``.  This
module maps those accepted products to the app candidate shape without
re-fetching or re-extracting pages.
"""

from __future__ import annotations

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


def export_description_status(value: Any) -> str:
    """Map the runtime's lowercase statuses to the D02 export vocabulary."""
    text = str(value).strip().upper().replace(" ", "_")
    return {
        "FALLBACK": "SUMMARY_FALLBACK",
        "SUMMARY": "SUMMARY_FALLBACK",
        "FULL": "COMPLETE",
        "MISSING": "NOT_PROVIDED",
        "UNAVAILABLE": "NOT_PROVIDED",
        "PARTIAL_EXTRACTION": "PARTIAL",
    }.get(text, text)


def to_candidate(
    product: dict[str, Any],
    task: dict[str, Any],
    *,
    partial_reason: str | None = None,
) -> dict[str, Any]:
    raw_status = product.get("description_status")
    if not raw_status:
        raise ValueError(
            f"product has no explicit description_status: {product.get('source_url')}"
        )
    status = export_description_status(raw_status)
    reason = product.get("partial_reason")
    if status == "PARTIAL" and partial_reason:
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
        "market": task.get("market", ""),
        "locale": task.get("locale", ""),
        "extracted_at": task.get("finished_at"),
        "field_sources": product.get("field_sources") or {},
    }


def convert_task_to_run_dir(
    task_result_path: Path,
    products_path: Path,
    out_dir: Path,
    *,
    partial_reason: str | None = None,
) -> int:
    """Write task.json and candidates.jsonl for the app export pipeline."""
    task = json.loads(Path(task_result_path).read_text(encoding="utf-8"))
    if not Path(products_path).exists():
        products: list[dict[str, Any]] = []
    else:
        products = [
            json.loads(line)
            for line in Path(products_path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    candidates = [
        to_candidate(product, task, partial_reason=partial_reason)
        for product in products
    ]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "task.json").write_text(
        json.dumps(task, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (out_dir / "candidates.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in candidates) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return len(candidates)
