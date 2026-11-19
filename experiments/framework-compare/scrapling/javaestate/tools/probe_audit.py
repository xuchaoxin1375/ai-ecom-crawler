"""Build probe: structural audit across a spread of product pages."""
from __future__ import annotations

import json
import re
import sys
import time
from xml.etree import ElementTree as ET

from scrapling.fetchers import Fetcher

SM = "https://javaestate.com/sitemap_products_1.xml?from=7233447460934&to=10283359469638"
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def main() -> int:
    sm = Fetcher.get(SM, timeout=60)
    root = ET.fromstring(sm.body)
    urls = []
    for node in root.findall(f"{NS}url"):
        loc = node.find(f"{NS}loc")
        if loc is not None and loc.text and "/products/" in loc.text:
            urls.append(loc.text.strip())
    picks = [0, 1, 2, 50, 150, 300, 500, len(urls) - 1]
    urls = [urls[i] for i in picks]
    print("audit", len(urls))
    for idx, url in enumerate(urls):
        time.sleep(1.1)
        page = Fetcher.get(url, timeout=45)
        scripts = page.css("script:not([src])::text").getall()
        wpd = None
        for s in scripts:
            m = re.search(r"window\.wpdExtensionIsProductPage\s*=\s*(\{.*?\});", s, re.S)
            if m:
                wpd = json.loads(m.group(1))
                break
        ld_product = None
        for raw in page.css('script[type="application/ld+json"]::text').getall():
            try:
                data = json.loads(raw)
            except Exception:
                continue
            if isinstance(data, dict) and data.get("@type") == "Product":
                ld_product = data
                break
        desc = page.css(".product__description")
        h1 = page.css("h1::text").get()
        cur = (ld_product or {}).get("offers", {}).get("priceCurrency") if isinstance((ld_product or {}).get("offers"), dict) else None
        offers = (ld_product or {}).get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        print(
            f"[{idx}] {page.status} len={len(page.body)} h1={bool(h1)} ld={bool(ld_product)} "
            f"cur={cur} wpd={bool(wpd)} vars={len(wpd.get('variants', [])) if wpd else 0} "
            f"desc_node={len(desc)} desc_len={len(desc[0].html_content) if desc else 0} "
            f"wpd_desc={len(wpd.get('description') or '') if wpd else 0} "
            f"cat={(ld_product or {}).get('category')!r} vendor={(ld_product or {}).get('brand') or {} if isinstance((ld_product or {}).get('brand'), dict) else None} "
            f"price={(offers or {}).get('price')!r} avail={(offers or {}).get('availability')!r} imgs={len(page.css('.product-gallery img'))}"
        )
        if wpd:
            print("   wpd opts", [(o, len(v)) for o, v in [(x, y) for x, y in []]] if False else (wpd.get("options"), len(wpd.get("images") or [])))
            prices = sorted({v.get("price") for v in wpd.get("variants", [])})
            print("   wpd prices", prices[:5], "avail", sum(1 for v in wpd.get("variants", []) if v.get("available")), "/", len(wpd.get("variants", [])))
        print("   url", url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
