"""Sixmoondesigns public JSON probe using Scrapling's FetcherSession.

This is a bounded capability probe, not a full plan package. It fetches the
public Shopify products.json once and extracts up to 30 products into the
9-column business CSV plus a JSON audit.
"""

from __future__ import annotations

import csv
import json
import os
import re
import time
from pathlib import Path

from scrapling.fetchers import FetcherSession

SITE = "https://www.sixmoondesigns.com"
API = f"{SITE}/products.json?limit=250&page=1"
OUT_DIR = Path(__file__).parent
MAX_PRODUCTS = 30
PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
if not PROXY:
    raise SystemExit("请先设置 HTTPS_PROXY 或 HTTP_PROXY；本机实测出口见 probes/README.md")
CURRENCY = "USD"  # Shopify.currency active=USD from the storefront HTML.


def clean_html(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<!--.*?-->", "", value, flags=re.S)
    return value.strip()


def serialize_attributes(product: dict) -> str:
    variants = product.get("variants") or []
    parts: list[str] = []
    for index, option in enumerate(product.get("options") or [], start=1):
        name = option.get("name") or f"Option {index}"
        values: list[str] = []
        for variant in variants:
            value = variant.get(f"option{index}")
            if value and value not in values:
                values.append(value)
        if values:
            parts.append(f"{name}#{'|'.join(values)}")
    return "~".join(parts)


def extract_row(product: dict) -> dict | None:
    prices: list[float] = []
    for variant in product.get("variants") or []:
        raw = variant.get("price")
        try:
            price = float(raw)
        except (TypeError, ValueError):
            continue
        if price > 0:
            prices.append(price)
    if not prices:
        return None
    images = product.get("images") or []
    body = clean_html(product.get("body_html"))
    return {
        "name": product.get("title") or "",
        "price_amount": min(prices),
        "price_currency": CURRENCY,
        "primary_image_url": images[0].get("src") if images else "",
        "description_html": body,
        "category": product.get("product_type") or "",
        "brand": product.get("vendor") or "",
        "attributes": serialize_attributes(product),
        "source_url": f"{SITE}/products/{product.get('handle')}",
        "_description_status": "complete" if body else "not_provided",
        "_available": any(bool(v.get("available")) for v in product.get("variants") or []),
    }


def main() -> int:
    started = time.monotonic()
    audit: dict = {
        "framework": "scrapling",
        "version": "0.5.1",
        "site": SITE,
        "url": API,
        "proxy": PROXY,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        with FetcherSession(impersonate="chrome", proxy=PROXY, timeout=45, retries=3) as session:
            response = session.get(API)
            audit["status"] = response.status
            audit["first_response_s"] = round(time.monotonic() - started, 2)
            if response.status != 200:
                audit["error"] = f"HTTP {response.status}"
                (OUT_DIR / "sixmoondesigns-scrapling.json").write_text(
                    json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                return 2
            data = response.json()
    except Exception as exc:  # noqa: BLE001 - probe should record any transport failure
        audit["error"] = f"{type(exc).__name__}: {exc}"
        (OUT_DIR / "sixmoondesigns-scrapling.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return 2

    rows: list[dict] = []
    first_valid_s: float | None = None
    for product in (data.get("products") or [])[:MAX_PRODUCTS]:
        row = extract_row(product)
        if row is None:
            continue
        rows.append(row)
        if first_valid_s is None:
            first_valid_s = round(time.monotonic() - started, 2)

    csv_path = OUT_DIR / "sixmoondesigns-scrapling.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "name",
                "price_amount",
                "price_currency",
                "primary_image_url",
                "description_html",
                "category",
                "brand",
                "attributes",
                "source_url",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)

    audit.update(
        {
            "products_in_payload": len(data.get("products") or []),
            "valid_products": len(rows),
            "first_valid_product_s": first_valid_s,
            "total_s": round(time.monotonic() - started, 2),
            "csv": str(csv_path),
            "description_complete": sum(1 for r in rows if r["_description_status"] == "complete"),
            "description_not_provided": sum(1 for r in rows if r["_description_status"] == "not_provided"),
        }
    )
    (OUT_DIR / "sixmoondesigns-scrapling.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())