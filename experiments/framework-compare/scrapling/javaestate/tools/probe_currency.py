"""Build probe: currency and image evidence when Product JSON-LD is absent."""
from __future__ import annotations

import re
import sys

from scrapling.fetchers import Fetcher

URL = "https://javaestate.com/products/retail-special-pack-12oz-bag-5-pack-2"


def main() -> int:
    page = Fetcher.get(URL, timeout=45)
    print("status", page.status)
    for sel in [
        "meta[property='og:price:currency']",
        "meta[property='og:price:amount']",
        "meta[property='product:price:currency']",
        "meta[property='product:price:amount']",
        "meta[itemprop='priceCurrency']",
        "meta[itemprop='price']",
        "meta[property='og:image']",
    ]:
        nodes = page.css(sel)
        print(sel, [n.attrib.get("content") for n in nodes])
    scripts = page.css("script:not([src])::text").getall()
    for s in scripts:
        if "Shopify.currency" in s:
            for m in re.finditer(r"Shopify\.currency\s*=\s*\{[^}]*\}", s):
                print("Shopify.currency", m.group(0)[:200])
        if "currency" in s and "ShopifyAnalytics" in s:
            print("analytics", s.strip()[:400].replace("\n", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
