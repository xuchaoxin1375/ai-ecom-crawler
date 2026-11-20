"""Entry, category/pagination and sitemap discovery for skatepro.es."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree as ET

from protego import Protego

from .config import ALLOWED_HOSTS, ORIGIN
from .http import AccessDenied, PacedFetcher, PlanError
from .normalize import collapse_ws

PRODUCT_PATH_RE = re.compile(r"^/\d+-\d+\.htm$")
CATEGORY_PATH_RE = re.compile(r"^/c\d+\.htm$")
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


@dataclass
class Discovery:
    entry_url: str
    entry_final_url: str = ""
    html_lang: str = ""
    html_title: str = ""
    site_name: str = ""
    sitemap_url: str = ""
    sitemap_product_count: int = 0
    category_urls: list[str] = field(default_factory=list)
    visited_categories: list[str] = field(default_factory=list)
    product_urls: list[str] = field(default_factory=list)
    duplicate_urls: int = 0
    filtered_urls: int = 0
    pending_navigation: list[str] = field(default_factory=list)
    robots_status: int | None = None
    robots_text: str = ""
    robots_parser: Any = None
    notes: list[str] = field(default_factory=list)


def normalize_product_url(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url.strip())
    if (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        return None
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if not PRODUCT_PATH_RE.match(path):
        return None
    canonical = urlunsplit(("https", "www.skatepro.es", path, "", ""))
    return canonical, path.casefold()


def normalize_category_url(url: str) -> str | None:
    parsed = urlsplit(url.strip())
    if (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        return None
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if not CATEGORY_PATH_RE.match(path):
        return None
    return urlunsplit(("https", "www.skatepro.es", path, "", ""))


def parse_sitemap_product_count(xml_bytes: bytes) -> int:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise PlanError(f"cannot parse sitemap: {exc}") from exc
    count = 0
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1] if "}" in node.tag else node.tag
        if tag != "url":
            continue
        for child in node:
            ctag = child.tag.rsplit("}", 1)[-1] if "}" in child.tag else child.tag
            if ctag == "loc" and child.text and PRODUCT_PATH_RE.match(urlsplit(child.text.strip()).path):
                count += 1
                break
    return count


def _category_links(page: Any) -> list[str]:
    """Collect main-menu category seeds in document order (c<digits>.htm)."""
    urls: list[str] = []
    seen: set[str] = set()
    for node in page.css('a[href*="/c"]'):
        href = node.attrib.get("href") or ""
        normalized = normalize_category_url(href)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        urls.append(normalized)
    return urls


def _product_links(page: Any) -> list[tuple[str, str]]:
    """Return (canonical_url, identity) for product cards on a category page."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for node in page.css("a.product_card[href]"):
        normalized = normalize_product_url(node.attrib.get("href") or "")
        if not normalized:
            continue
        canonical, identity = normalized
        if identity in seen:
            continue
        seen.add(identity)
        out.append((canonical, identity))
    return out


def _has_pagination(page: Any) -> bool:
    """The category grid grows through the page_load_more web component."""
    try:
        if page.css('script[src*="page_load_more"]'):
            return True
    except Exception:
        pass
    return False


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


def discover(
    client: PacedFetcher,
    *,
    entry_url: str,
    sitemap_url: str,
    max_products: int,
    max_category_pages: int = 2,
    max_category_seeds: int = 3,
    fetch_sitemap: bool = True,
) -> Discovery:
    from scrapling.parser import Selector

    result = Discovery(entry_url=entry_url, sitemap_url=sitemap_url)

    robots = client.get(f"{ORIGIN}/robots.txt", purpose="robots")
    result.robots_status = robots.status
    if robots.ok:
        result.robots_text = robots.response.body.decode(robots.response.encoding or "utf-8", errors="replace")
        result.robots_parser = Protego.parse(result.robots_text.removeprefix("\ufeff"))
    elif robots.status is not None and 400 <= robots.status < 500:
        result.notes.append(f"robots.txt returned {robots.status}; parsing empty rules (allow-all default).")
        result.robots_parser = Protego.parse("")
    else:
        raise AccessDenied(f"robots.txt unavailable ({robots.status or robots.error}); refusing to crawl")

    if not _robots_allows(result, entry_url):
        raise AccessDenied(f"robots.txt disallows entry URL: {entry_url}")

    entry = client.get(entry_url, purpose="entry")
    if not entry.ok:
        raise PlanError(f"entry URL returned HTTP {entry.status or entry.error}")
    entry_page = Selector(content=entry.response.body, url=str(entry.response.url))
    result.entry_final_url = str(entry.response.url)
    html_nodes = entry_page.css("html")
    result.html_lang = collapse_ws(html_nodes[0].attrib.get("lang")) if html_nodes else ""
    title_nodes = entry_page.css("title::text")
    result.html_title = collapse_ws(title_nodes.get() if title_nodes else "")
    site_nodes = entry_page.css("meta[property='og:site_name']::attr(content)")
    result.site_name = collapse_ws(site_nodes.get() if site_nodes else "")
    result.category_urls = _category_links(entry_page)
    if not result.category_urls:
        raise PlanError("no c<id>.htm category links found on the entry page")

    products: list[str] = []
    seen_products: set[str] = set()
    frontier = result.category_urls[:max_category_seeds]
    for category_url in frontier:
        if len(products) >= max_products:
            break
        if not _robots_allows(result, category_url):
            result.filtered_urls += 1
            result.notes.append(f"robots.txt disallows category {category_url}; skipped")
            continue
        result.visited_categories.append(category_url)
        for page_number in range(1, max_category_pages + 1):
            page_url = category_url if page_number == 1 else f"{category_url}?page={page_number}"
            page_outcome = client.get(page_url, purpose="category")
            if not page_outcome.ok:
                result.notes.append(
                    f"category page {page_url} returned HTTP {page_outcome.status or page_outcome.error}"
                )
                break
            page = Selector(content=page_outcome.response.body, url=str(page_outcome.response.url))
            links = _product_links(page)
            if not links:
                result.notes.append(f"category page {page_url} exposed no product cards; stopping this branch")
                break
            for canonical, identity in links:
                if identity in seen_products:
                    result.duplicate_urls += 1
                    continue
                seen_products.add(identity)
                products.append(canonical)
                if len(products) >= max_products:
                    break
            if len(products) >= max_products:
                result.pending_navigation.extend(
                    [url for url in frontier if url not in result.visited_categories]
                )
                if _has_pagination(page):
                    result.pending_navigation.insert(0, f"{category_url}?page={page_number + 1}")
                break
            if not _has_pagination(page):
                break
        if len(products) >= max_products:
            break

    result.product_urls = products
    if not products:
        raise PlanError("no product URLs were discovered from the entry page categories")

    if fetch_sitemap:
        sitemap = client.get(sitemap_url, purpose="sitemap")
        if sitemap.ok:
            result.sitemap_product_count = parse_sitemap_product_count(sitemap.response.body)
            result.notes.append(
                f"sitemap.xml declares {result.sitemap_product_count} product URLs; "
                "it is a site-level denominator, not this bounded category scope."
            )
        else:
            result.notes.append(f"sitemap.xml returned HTTP {sitemap.status or sitemap.error}; denominator unavailable.")

    result.notes.append(
        f"discovery used {len(result.visited_categories)} category page(s) and kept "
        f"{len(products)} unique products within the {max_products}-page cap."
    )
    return result
