"""Build diagnostic: verify the zero-price exclusion branch on a known free item.

This is not part of the bounded 30-product run and never enters valid.csv.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapling.fetchers import Fetcher  # noqa: E402
from javaestate_scraper.extract import extract_product  # noqa: E402

URL = "https://javaestate.com/products/java-jacket-drink-sleeves-8-24-oz-copy"


def main() -> int:
    page = Fetcher.get(URL, timeout=45, retries=1)
    record = extract_product(page)
    payload = {
        "probe": "zero_price_exclusion",
        "source_url": URL,
        "http_status": page.status,
        "name": record.name,
        "price_cents": record.price_cents,
        "price_currency": record.price_currency,
        "exclusion_reason": record.exclusion_reason,
        "exclusion_detail": record.exclusion_detail,
        "description_status": record.description_status,
        "evidence": record.evidence,
        "note": "Build diagnostic only; this product is outside the bounded run and is not in valid.csv.",
    }
    path = ROOT / "diagnostics" / "zero-price-probe.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
