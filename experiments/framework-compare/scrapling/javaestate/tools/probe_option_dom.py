"""Build probe: option labels around product-variant-container selects."""
from __future__ import annotations

import sys

from scrapling.fetchers import Fetcher

URL = "https://javaestate.com/products/retail-special-pack-12oz-bag-5-pack-2"


def main() -> int:
    page = Fetcher.get(URL, timeout=45)
    form = page.css("form[action*='/cart/add']")
    if not form:
        print("no form")
        return 1
    html = form[0].html_content
    print("form_len", len(html))
    print(html[:3000].replace("\n", " "))
    print("--- labels ---")
    for n in page.css("label")[:10]:
        print("label", n.attrib.get("for"), n.attrib.get("class"), repr(n.get_all_text(strip=True))[:120])
    print("--- selects ---")
    for n in page.css("select"):
        print("select", n.attrib.get("id"), n.attrib.get("name"), n.attrib.get("class"), n.attrib.get("aria-label"), n.attrib.get("data-option-name"))
        print("  options", [o.attrib.get("value") for o in n.css("option")][:8])
    return 0


if __name__ == "__main__":
    sys.exit(main())
