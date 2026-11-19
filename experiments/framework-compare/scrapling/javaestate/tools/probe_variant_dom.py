"""Build probe: variant selection DOM on a multi-variant product."""
from __future__ import annotations

import sys

from scrapling.fetchers import Fetcher

URL = "https://javaestate.com/products/retail-special-pack-12oz-bag-5-pack-2"


def main() -> int:
    page = Fetcher.get(URL, timeout=45)
    print("status", page.status)
    for sel in [
        "form[action*='/cart/add']",
        "form[action*='cart'] select",
        "select",
        "input[type=radio]",
        "input[name^='options']",
        "[data-option]",
        "[data-variant]",
        "button[name='add']",
        ".product-form",
        ".product__info",
        ".variant-picker",
        ".product-options",
    ]:
        nodes = page.css(sel)
        print(f"{sel!r}: {len(nodes)}")
        for n in nodes[:3]:
            print("   ", n.tag, (n.attrib.get("class") or "")[:80], n.get_all_text(strip=True)[:80])
    return 0


if __name__ == "__main__":
    sys.exit(main())
