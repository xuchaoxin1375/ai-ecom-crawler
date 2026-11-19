"""Build probe: look for spec/accordion sections outside the main description."""
from __future__ import annotations

import sys

from scrapling.fetchers import Fetcher

URL = "https://javaestate.com/products/big-train-mocha-blended-ice-coffee-beverage-mix"


def main() -> int:
    page = Fetcher.get(URL, timeout=45)
    print("status", page.status, "len", len(page.body))
    for sel in [
        "main h2",
        "main h3",
        "main h4",
        "details",
        "summary",
        "[class*=accordion]",
        "[class*=tab]",
        "[class*=spec]",
        "[class*=nutrition]",
        "[class*=ingredient]",
        ".product__description",
        ".product__description ~ *",
        "main section",
        "main .rte",
    ]:
        nodes = page.css(sel)
        print(f"{sel!r}: {len(nodes)}")
        for n in nodes[:5]:
            text = n.get_all_text(strip=True)
            print("   ", (n.attrib.get("class") or "")[:60], repr(text[:140]))
    # list headings in order
    print("--- headings ---")
    for n in page.css("h1,h2,h3,h4"):
        print(n.tag, repr(n.get_all_text(strip=True))[:150])
    return 0


if __name__ == "__main__":
    sys.exit(main())
