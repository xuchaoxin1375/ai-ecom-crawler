"""Build probe: inspect one product page shape with Scrapling's parser."""
from __future__ import annotations

import json
import re
import sys
import time
from xml.etree import ElementTree as ET

from scrapling.fetchers import Fetcher

SM_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def product_urls() -> list[str]:
    sm = Fetcher.get(
        "https://javaestate.com/sitemap_products_1.xml?from=7233447460934&to=10283359469638",
        timeout=60,
    )
    root = ET.fromstring(sm.body)
    out = []
    for node in root.findall(f"{SM_NS}url"):
        loc = node.find(f"{SM_NS}loc")
        if loc is not None and loc.text and "/products/" in loc.text:
            out.append(loc.text.strip())
    return out


def main() -> int:
    urls = product_urls()
    print("product_urls", len(urls))
    print("first3", urls[:3])
    url = urls[0]
    t0 = time.time()
    page = Fetcher.get(url, timeout=45)
    print("page", page.status, len(page.body), f"{time.time() - t0:.2f}s", page.url)
    print("h1_count", len(page.css("h1")), "h1", page.css("h1::text").getall()[:3])
    print("title", page.css("title::text").get())
    ld = [s for s in page.css('script[type="application/ld+json"]::text').getall()]
    print("ld_json_blocks", len(ld), [len(x) for x in ld])
    for i, raw in enumerate(ld):
        try:
            data = json.loads(raw)
        except Exception as exc:
            print("  ld", i, "parse_error", exc)
            continue
        kind = data.get("@type") if isinstance(data, dict) else type(data).__name__
        print("  ld", i, "type", kind, "keys", list(data)[:12] if isinstance(data, dict) else "")
        if isinstance(data, dict) and data.get("@type") == "Product":
            offers = data.get("offers")
            print("    product keys", sorted(data.keys()))
            print("    offers", json.dumps(offers, ensure_ascii=False)[:600])
    selectors = [
        ".product__title",
        ".product__info-container",
        ".product__description",
        ".product-single__description",
        ".rte",
        "[class*=description]",
        ".price",
        ".price__container",
        "main",
    ]
    for sel in selectors:
        try:
            nodes = page.css(sel)
            print(f"sel {sel!r}: {len(nodes)} text={nodes[0].get_all_text(strip=True)[:100] if nodes else ''!r}")
        except Exception as exc:
            print(f"sel {sel!r}: error {exc}")
    imgs = page.css("img")
    print("img_count", len(imgs))
    for img in imgs[:6]:
        print("  img", img.attrib.get("src", "")[:120], img.attrib.get("alt", "")[:40])
    return 0


if __name__ == "__main__":
    sys.exit(main())
