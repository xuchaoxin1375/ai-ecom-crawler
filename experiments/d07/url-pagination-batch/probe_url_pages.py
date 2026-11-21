#!/usr/bin/env python3
"""Compare page 1 and page 2 of selected benchmark listings.

The probe is read-only and bounded: two requests per site. It answers the
question "does the next-page state have a URL that returns different products?"
before a rule is written with clicks or scrolling.

Run from the repository root:

    python -m uv run --project app python experiments/d07/url-pagination-batch/probe_url_pages.py

Use ``--site`` to check one site.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from urllib.parse import urljoin, urlsplit

from curl_cffi import requests

SITES = {
    "mapetitemercerie": {
        "page1": "https://www.mapetitemercerie.com/fr/1499-tissus-mode",
        "page2": "https://www.mapetitemercerie.com/fr/1499-tissus-mode?page=2",
        "status": "PrestaShop ?page=2",
        "product": re.compile(r"^/fr/[^/]+/\d+.*\.html$"),
        "key": re.compile(r"/(\d+)(?:-\d+)?-[^/]+\.html$"),
    },
    "gaspardetleonie": {
        "page1": "https://www.gaspardetleonie.com/collections/tissus",
        "page2": "https://www.gaspardetleonie.com/collections/tissus?page=2",
        "status": "Shopify ?page=2",
        "product": re.compile(r"^/products/[^/]+/?$"),
        "key": None,
        "ignore": {"/products/carte-cadeau"},
    },
    "touchatou": {
        "page1": "https://touchatou.fr/categorie-produit/tissus-de-noel/",
        "page2": "https://touchatou.fr/categorie-produit/tissus-de-noel/page/2/",
        "status": "WooCommerce /page/2/",
        "product": re.compile(r"^/boutique/[^/]+/?$"),
        "key": None,
    },
    "atelier-leonie": {
        "page1": "https://atelier-leonie.fr/product-category/tissus/les-tisses-legers/popeline/",
        "page2": "https://atelier-leonie.fr/product-category/tissus/les-tisses-legers/popeline/page/2/",
        "status": "single page; /page/2/ expected 404",
        "product": re.compile(r"^/product/[^/]+/?$"),
        "key": None,
    },
    "tissus": {
        "page1": "https://www.tissus.net/tissus/types-de-tissus/mesh/",
        "page2": "https://www.tissus.net/tissus/types-de-tissus/mesh/?p=2",
        "status": "Shopware; listing rendered by JS/API",
        "product": re.compile(r"^/detail/|/\d{5,}(?:[?#]|$)"),
        "key": None,
    },
}

LINK_RE = re.compile(r'<a\b[^>]*\bhref="([^"]+)"', re.IGNORECASE)
NEXT_RE = re.compile(
    r'<(?:link|a)\b[^>]*\brel="[^"]*\bnext\b[^"]*"[^>]*\bhref="([^"]+)"'
    r'|<(?:link|a)\b[^>]*\bhref="([^"]+)"[^>]*\brel="[^"]*\bnext\b[^"]*"',
    re.IGNORECASE,
)


def fetch(
    session: requests.Session, url: str, timeout: int
) -> tuple[int, str, str, str]:
    response = session.get(
        url,
        timeout=timeout,
        allow_redirects=True,
        headers={"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"},
    )
    html = response.text
    title_match = re.search(
        r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE
    )
    title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
    return response.status_code, response.url, title, html


def product_keys(html: str, base: str, spec: dict) -> set[str]:
    keys: set[str] = set()
    for href in LINK_RE.findall(html):
        absolute = urljoin(base, href)
        path = urlsplit(absolute).path
        if not spec["product"].search(path):
            continue
        if path.rstrip("/") in spec.get("ignore", set()):
            continue
        if spec["key"] is not None:
            match = spec["key"].search(path)
            if match:
                keys.add(match.group(1))
        else:
            keys.add(path.rstrip("/"))
    return keys


def next_link(html: str) -> str | None:
    match = NEXT_RE.search(html)
    if not match:
        return None
    return match.group(1) or match.group(2)


def check_site(name: str, spec: dict, timeout: int) -> dict:
    session = requests.Session(impersonate="chrome")
    record: dict = {"page_url": spec["page2"], "status": spec["status"]}
    try:
        status1, final1, title1, html1 = fetch(session, spec["page1"], timeout)
        page1 = product_keys(html1, final1, spec)
        record.update(
            {
                "page1_status": status1,
                "page1_final": final1,
                "page1_title": title1,
                "page1_products": len(page1),
                "page1_next": next_link(html1),
            }
        )
        status2, final2, title2, html2 = fetch(session, spec["page2"], timeout)
        page2 = product_keys(html2, final2, spec) if status2 < 400 else set()
        record.update(
            {
                "page2_status": status2,
                "page2_final": final2,
                "page2_title": title2,
                "page2_products": len(page2),
                "page2_next": next_link(html2),
                "overlap": len(page1 & page2),
                "new_on_page2": len(page2 - page1),
            }
        )
    except Exception as exc:  # noqa: BLE001 - probe records transport failures
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", choices=sorted(SITES), action="append", help="check only this site")
    parser.add_argument("--timeout", type=int, default=30, help="per-request timeout in seconds")
    args = parser.parse_args()
    selected = args.site or sorted(SITES)
    result = {
        "checked_at": date.today().isoformat(),
        "client": "curl_cffi requests, impersonate=chrome",
        "sites": {name: check_site(name, SITES[name], args.timeout) for name in selected},
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
