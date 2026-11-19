"""Build probe: find a multi-variant product via public Shopify products JSON."""
from __future__ import annotations

import json
import sys

from scrapling.fetchers import Fetcher


def main() -> int:
    resp = Fetcher.get("https://javaestate.com/products.json?limit=250", timeout=45)
    print("status", resp.status, "bytes", len(resp.body))
    if resp.status != 200:
        return 1
    data = json.loads(resp.body)
    products = data.get("products", [])
    print("products", len(products))
    multi = [p for p in products if len(p.get("variants", [])) > 1]
    print("multi_variant", len(multi))
    for p in multi[:5]:
        print(p["handle"], "variants", len(p["variants"]), "options", [(o["name"], o["values"]) for o in p.get("options", [])])
        print("  prices", sorted({v["price"] for v in p["variants"]}), "avail", [v["available"] for v in p["variants"]][:6])
    zero = [p for p in products if all(float(v["price"] or 0) <= 0 for v in p.get("variants", []))]
    print("zero_or_free", len(zero), [p["handle"] for p in zero[:5]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
