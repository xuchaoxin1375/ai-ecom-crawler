"""Build probe: variant, image, description structure on a product page."""
from __future__ import annotations

import json
import re
import sys

from scrapling.fetchers import Fetcher

URL = "https://javaestate.com/products/ghirardelli-white-chocolate-sweet-ground-powder"


def main() -> int:
    page = Fetcher.get(URL, timeout=45)
    print("status", page.status, "len", len(page.body))
    sels = [
        "variant-selects",
        "variant-radios",
        "select[name=id]",
        "input[name=id]",
        ".product-form__input",
        "fieldset",
        ".product__media img",
        ".product__media-wrapper img",
        ".product-gallery img",
        ".product__info-wrapper",
        ".product__info-container",
        ".product__description",
        ".product__description.rte",
        ".product__accordion",
        "details",
        ".breadcrumb",
        "nav.breadcrumb",
        ".breadcrumbs",
        "script[type='application/ld+json']",
    ]
    for sel in sels:
        try:
            nodes = page.css(sel)
        except Exception as exc:
            print(sel, "ERR", exc)
            continue
        print(f"{sel!r}: {len(nodes)}")
        for n in nodes[:3]:
            txt = n.get_all_text(strip=True)
            print("   ", (txt[:160] if txt else "").replace("\n", " | "))
    # raw variant JSON in page scripts
    scripts = page.css("script:not([src])::text").getall()
    print("inline_scripts", len(scripts))
    needles = ["variant", "price", "inventory", "available"]
    for i, s in enumerate(scripts):
        if '"variants"' in s or "'variants'" in s or "productVariants" in s:
            print("variant_script", i, len(s), s[:300].replace("\n", " "))
    # liquid product JSON
    m = re.search(r'var\s+meta\s*=\s*(\{.*?\});', "\n".join(scripts), re.S)
    print("meta_var", bool(m))
    for i, s in enumerate(scripts):
        if len(s) > 500 and "Ghirardelli" in s:
            print("big_script", i, len(s), s[:200].replace("\n", " "))
    # breadcrumb items from ld+json
    for raw in page.css('script[type="application/ld+json"]::text').getall():
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("@type") == "BreadcrumbList":
            print("breadcrumb", [x.get("name") for x in data.get("itemListElement", [])])
    # description node html
    node = page.css(".product__description")
    if node:
        html = node[0].html_content
        print("description_html_len", len(html))
        print(html[:800].replace("\n", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
