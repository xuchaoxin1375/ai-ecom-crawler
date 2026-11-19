"""Entry, robots and sitemap discovery for javaestate.com."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree as ET

from protego import Protego

from .config import ALLOWED_HOSTS, ORIGIN
from .http import AccessDenied, PacedFetcher, PlanError
from .normalize import collapse_ws

PRODUCT_PATH_RE = re.compile(r"^/products/[^/]+/?$")
EXCLUDED_PRODUCT_PATHS = {
    "/products/account",
    "/products/orders",
    "/products/checkout",
}
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


@dataclass
class Discovery:
    entry_url: str
    entry_final_url: str = ""
    html_lang: str = ""
    html_title: str = ""
    site_name: str = ""
    sitemap_index_url: str = ""
    product_sitemap_url: str = ""
    product_sitemap_count: int = 0
    product_urls: list[str] = field(default_factory=list)
    duplicate_urls: int = 0
    filtered_urls: int = 0
    robots_status: int | None = None
    robots_text: str = ""
    robots_parser: Any = None
    notes: list[str] = field(default_factory=list)


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _loc_values(node: ET.Element, *, direct: bool = True) -> list[str]:
    out: list[str] = []
    for child in node:
        if _localname(child.tag) == "loc" and child.text:
            out.append(child.text.strip())
        elif not direct:
            out.extend(_loc_values(child, direct=False))
    return out


def parse_sitemap_index(xml_bytes: bytes) -> list[str]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise PlanError(f"cannot parse sitemap index: {exc}") from exc
    urls: list[str] = []
    for node in root.iter():
        if _localname(node.tag) == "sitemap":
            urls.extend(_loc_values(node, direct=True))
    if not urls:
        urls = [text.strip() for text in root.itertext() if text.strip().startswith("http")]
    return urls


def parse_product_sitemap(xml_bytes: bytes) -> list[str]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise PlanError(f"cannot parse product sitemap: {exc}") from exc
    urls: list[str] = []
    for node in root.iter():
        if _localname(node.tag) == "url":
            urls.extend(_loc_values(node, direct=True))
    return urls


def normalize_product_url(url: str) -> tuple[str, str] | None:
    from urllib.parse import urlsplit, urlunsplit

    parsed = urlsplit(url.strip())
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        return None
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if not PRODUCT_PATH_RE.match(path):
        return None
    path = path.rstrip("/")
    if path in EXCLUDED_PRODUCT_PATHS:
        return None
    canonical = urlunsplit(("https", "javaestate.com", path, "", ""))
    return canonical, path.casefold()


def discover(
    client: PacedFetcher,
    *,
    entry_url: str,
    sitemap_index_url: str,
    max_products: int,
) -> Discovery:
    result = Discovery(entry_url=entry_url, sitemap_index_url=sitemap_index_url)

    robots = client.get(f"{ORIGIN}/robots.txt", purpose="robots")
    result.robots_status = robots.status
    if robots.ok:
        result.robots_text = robots.response.body.decode(robots.response.encoding or "utf-8", errors="replace")
        result.robots_parser = Protego.parse(result.robots_text.removeprefix("\ufeff"))
    elif robots.status is not None and 400 <= robots.status < 500:
        result.notes.append(f"robots.txt returned {robots.status}; parsing empty rules (standard allow-all).")
        result.robots_parser = Protego.parse("")
    else:
        raise AccessDenied(f"robots.txt unavailable ({robots.status or robots.error}); refusing to crawl")

    entry_check = _robots_allows(result, entry_url)
    if not entry_check:
        raise AccessDenied(f"robots.txt disallows entry URL: {entry_url}")

    entry = client.get(entry_url, purpose="entry")
    if not entry.ok:
        raise PlanError(f"entry URL returned HTTP {entry.status or entry.error}")
    entry_page = entry.response
    result.entry_final_url = str(getattr(entry_page, "url", entry_url))
    html_nodes = entry_page.css("html")
    result.html_lang = collapse_ws(html_nodes[0].attrib.get("lang")) if html_nodes else ""
    result.html_title = collapse_ws(entry_page.css("title::text").get())
    result.site_name = collapse_ws(entry_page.css("meta[property='og:site_name']::attr(content)").get())

    index = client.get(sitemap_index_url, purpose="sitemap_index")
    if not index.ok:
        raise PlanError(f"sitemap index returned HTTP {index.status or index.error}")
    sitemap_urls = parse_sitemap_index(index.response.body)
    product_sitemap = next((url for url in sitemap_urls if "sitemap_products" in url), "")
    if not product_sitemap:
        raise PlanError("sitemap index has no product sitemap entry")
    result.product_sitemap_url = product_sitemap

    product_sitemap_resp = client.get(product_sitemap, purpose="sitemap_products")
    if not product_sitemap_resp.ok:
        raise PlanError(f"product sitemap returned HTTP {product_sitemap_resp.status or product_sitemap_resp.error}")
    raw_urls = parse_product_sitemap(product_sitemap_resp.response.body)
    result.product_sitemap_count = len(raw_urls)

    seen: set[str] = set()
    products: list[str] = []
    for raw in raw_urls:
        normalized = normalize_product_url(raw)
        if not normalized:
            result.filtered_urls += 1
            continue
        canonical, identity = normalized
        if identity in seen:
            result.duplicate_urls += 1
            continue
        seen.add(identity)
        products.append(canonical)
        if len(products) >= max_products:
            break

    result.product_urls = products
    result.notes.append(
        f"product sitemap declared {result.product_sitemap_count} <url> entries; "
        f"kept first {len(products)} unique product URLs within the {max_products}-page cap."
    )
    if not products:
        raise PlanError("no product URLs survived sitemap filtering")
    return result


def _robots_allows(discovery: Discovery, url: str) -> bool:
    parser = discovery.robots_parser
    if parser is None:
        return False
    try:
        return bool(parser.can_fetch(url, "*"))
    except Exception:
        return False


def robots_allows(discovery: Discovery, url: str) -> bool:
    return _robots_allows(discovery, url)
