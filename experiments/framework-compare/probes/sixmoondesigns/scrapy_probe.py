"""Sixmoondesigns public JSON probe using Scrapy.

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

import scrapy
from scrapy.crawler import CrawlerProcess

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


class SixMoonSpider(scrapy.Spider):
    name = "sixmoon"
    rows: list[dict] = []
    statuses: list[int] = []
    products_in_payload: int = 0
    first_valid_s: float | None = None
    started: float = 0.0

    async def start(self):
        SixMoonSpider.started = time.monotonic()
        yield scrapy.Request(API, callback=self.parse, meta={"proxy": PROXY})

    def parse(self, response):
        SixMoonSpider.statuses.append(response.status)
        if response.status != 200:
            return
        data = json.loads(response.text)
        SixMoonSpider.products_in_payload = len(data.get("products") or [])
        for product in (data.get("products") or [])[:MAX_PRODUCTS]:
            row = extract_row(product)
            if row is None:
                continue
            SixMoonSpider.rows.append(row)
            if SixMoonSpider.first_valid_s is None:
                SixMoonSpider.first_valid_s = round(time.monotonic() - SixMoonSpider.started, 2)


def main() -> int:
    audit: dict = {
        "framework": "scrapy",
        "version": scrapy.__version__,
        "site": SITE,
        "url": API,
        "proxy": PROXY,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    process = CrawlerProcess(
        settings={
            "ROBOTSTXT_OBEY": True,
            "DOWNLOAD_DELAY": 1,
            "CONCURRENT_REQUESTS": 1,
            "RETRY_TIMES": 3,
            "RETRY_HTTP_CODES": [429, 500, 502, 503, 504],
            "LOG_LEVEL": "WARNING",
            "TELNETCONSOLE_ENABLED": False,
            "REQUEST_FINGERPRINTER_IMPLEMENTATION": "2.7",
        }
    )
    try:
        process.crawl(SixMoonSpider)
        process.start()
    except Exception as exc:  # noqa: BLE001 - probe should record any transport failure
        audit["error"] = f"{type(exc).__name__}: {exc}"
        (OUT_DIR / "sixmoondesigns-scrapy.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return 2

    rows = SixMoonSpider.rows
    csv_path = OUT_DIR / "sixmoondesigns-scrapy.csv"
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
            "statuses": SixMoonSpider.statuses,
            "products_in_payload": SixMoonSpider.products_in_payload,
            "valid_products": len(rows),
            "first_valid_product_s": SixMoonSpider.first_valid_s,
            "csv": str(csv_path),
            "description_complete": sum(1 for r in rows if r["_description_status"] == "complete"),
            "description_not_provided": sum(1 for r in rows if r["_description_status"] == "not_provided"),
        }
    )
    (OUT_DIR / "sixmoondesigns-scrapy.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())