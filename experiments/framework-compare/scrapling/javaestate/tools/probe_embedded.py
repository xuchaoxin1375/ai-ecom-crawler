"""Build probe: inspect embedded product JSON and variant pricing."""
from __future__ import annotations

import json
import re
import sys

from scrapling.fetchers import Fetcher

URLS = [
    "https://javaestate.com/products/ghirardelli-white-chocolate-sweet-ground-powder",
    "https://javaestate.com/products/ghirardelli-sweet-ground-chocolate-sauce",
]


def main() -> int:
    for url in URLS:
        page = Fetcher.get(url, timeout=45)
        print("=" * 70)
        print(url, page.status, len(page.body))
        scripts = page.css("script:not([src])::text").getall()
        for i, s in enumerate(scripts):
            m = re.search(r"window\.wpdExtensionIsProductPage\s*=\s*(\{.*?\});", s, re.S)
            if m:
                data = json.loads(m.group(1))
                print("wpd keys", sorted(data.keys()))
                print("title", data.get("title"))
                print("type", data.get("type"), "vendor", data.get("vendor"), "tags", data.get("tags"))
                for v in data.get("variants", [])[:8]:
                    keep = {k: v.get(k) for k in ("id", "title", "option1", "option2", "option3", "price", "available", "sku")}
                    print("  variant", keep)
                print("options", data.get("options"))
                print("images", (data.get("images") or [])[:2])
                print("featured_image", data.get("featured_image"))
                print("description_len", len(data.get("description") or ""))
                break
        # currency
        for s in scripts:
            if "ShopifyAnalytics" in s and "currency" in s:
                print("currency_line", s.strip()[:200])
                break
        # images in gallery with srcset/src
        for n in page.css(".product-gallery img")[:4]:
            print("gallery_img", n.attrib.get("src"), "|", n.attrib.get("data-src"), "|", n.attrib.get("srcset", "")[:80])
        print("main_img", page.css("main img")[:3])
    return 0


if __name__ == "__main__":
    sys.exit(main())
