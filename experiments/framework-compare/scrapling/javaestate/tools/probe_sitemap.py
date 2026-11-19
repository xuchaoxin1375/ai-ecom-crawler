"""Build probe: fetch the product sitemap and report shape. Not part of the runnable plan."""
from __future__ import annotations

import re
import sys
import time
from xml.etree import ElementTree as ET

from scrapling.fetchers import Fetcher


def main() -> int:
    started = time.time()
    index = Fetcher.get("https://javaestate.com/sitemap.xml", timeout=30)
    print("sitemap index", index.status, len(index.body), f"{time.time() - started:.2f}s")
    locs = [x.text for x in index.xml(root=True).xpath("//*[local-name()='loc']")] if False else []
    # ElementTree keeps this probe independent of selector details
    root = ET.fromstring(index.body)
    locs = [el.text.strip() for el in root.iter() if el.tag.endswith("loc")]
    print("index_loc_count", len(locs))
    products = [u for u in locs if "sitemap_products" in u]
    print("product_sitemaps", products)
    if not products:
        return 2
    sm = Fetcher.get(products[0], timeout=60)
    print("product sitemap", sm.status, len(sm.body))
    proot = ET.fromstring(sm.body)
    urls = [(el.text or "").strip() for el in proot.iter() if el.tag.endswith("loc")]
    print("product_url_count", len(urls))
    print("first5", urls[:5])
    print("last2", urls[-2:])
    print("sample_slugs", [re.sub(r"^https://javaestate\.com", "", u) for u in urls[:3]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
