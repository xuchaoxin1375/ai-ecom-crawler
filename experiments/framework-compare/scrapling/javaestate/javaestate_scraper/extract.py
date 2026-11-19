"""Field extraction for javaestate.com product pages (Shopify HTML + embedded JSON)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable

from .config import CURRENCY_EXPECTED, STORE_NAME_TOKENS
from .normalize import (
    build_options,
    cents_to_amount,
    clean_name,
    collapse_ws,
    html_to_plain_text,
    normalize_url_image,
    parse_positive_money,
    sanitize_description,
    strip_price_delta,
    tax_basis_from_variants,
)

WPD_MARKER = "window.wpdExtensionIsProductPage"
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
SHOPIFY_CURRENCY_RE = re.compile(r'Shopify\.currency\s*=\s*\{\s*"active"\s*:\s*"([A-Z]{3})"')
ANALYTICS_CURRENCY_RE = re.compile(r"ShopifyAnalytics\.meta\.currency\s*=\s*['\"]([A-Z]{3})['\"]")
CHALLENGE_MARKERS = (
    "just a moment",
    "attention required! | cloudflare",
    "cf-challenge",
    "cf_chl_opt",
    "checking your browser before accessing",
)
AVAILABILITY_MAP = {
    "http://schema.org/instock": "in_stock",
    "https://schema.org/instock": "in_stock",
    "instock": "in_stock",
    "http://schema.org/outofstock": "out_of_stock",
    "https://schema.org/outofstock": "out_of_stock",
    "outofstock": "out_of_stock",
    "http://schema.org/preorder": "preorder",
    "https://schema.org/preorder": "preorder",
    "preorder": "preorder",
    "http://schema.org/backorder": "backorder",
    "https://schema.org/backorder": "backorder",
    "backorder": "backorder",
}


@dataclass
class ProductRecord:
    source_url: str
    name: str = ""
    price_cents: int | None = None
    price_currency: str = ""
    primary_image_url: str = ""
    description_html: str = ""
    description_format: str = ""
    description_status: str = ""
    partial_reason: str = ""
    category: str = ""
    brand: str = ""
    options: list[tuple[str, list[str]]] = field(default_factory=list)
    availability: str = ""
    tax_basis: str = "unknown_not_stated"
    missing_reasons: dict[str, str] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    exclusion_reason: str = ""
    exclusion_detail: str = ""
    extraction_error: str = ""


def _flatten_jsonld(node: Any) -> Iterable[dict]:
    if isinstance(node, list):
        for item in node:
            yield from _flatten_jsonld(item)
    elif isinstance(node, dict):
        graph = node.get("@graph")
        if isinstance(graph, list):
            yield from _flatten_jsonld(graph)
        yield node


def _is_type(node: dict, wanted: str) -> bool:
    value = node.get("@type")
    if isinstance(value, str):
        return value.lower() == wanted.lower()
    if isinstance(value, list):
        return any(str(item).lower() == wanted.lower() for item in value)
    return False


def find_jsonld_product(page: Any) -> dict | None:
    for raw in page.css('script[type="application/ld+json"]::text').getall():
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _flatten_jsonld(data):
            if _is_type(node, "Product"):
                return node
    return None


def find_embedded_product(page: Any) -> dict | None:
    decoder = json.JSONDecoder()
    for script in page.css("script:not([src])::text").getall():
        marker = script.find(WPD_MARKER)
        if marker < 0:
            continue
        eq = script.find("=", marker)
        start = script.find("{", eq)
        if start < 0:
            continue
        try:
            data, _end = decoder.raw_decode(script[start:])
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict) and ("variants" in data or "title" in data):
            return data
    return None


def _offers_of(product: dict | None) -> dict:
    if not product:
        return {}
    offers = product.get("offers")
    if isinstance(offers, list):
        for item in offers:
            if isinstance(item, dict) and item.get("price") is not None:
                return item
        return offers[0] if offers and isinstance(offers[0], dict) else {}
    return offers if isinstance(offers, dict) else {}


def _brand_name(product: dict | None) -> str:
    if not product:
        return ""
    brand = product.get("brand")
    if isinstance(brand, list):
        for item in brand:
            name = _brand_name({"brand": item})
            if name:
                return name
        return ""
    if isinstance(brand, dict):
        return collapse_ws(brand.get("name"))
    return collapse_ws(brand)


def _category_name(product: dict | None) -> str:
    if not product:
        return ""
    category = product.get("category")
    if isinstance(category, list):
        values = [collapse_ws(item) for item in category if collapse_ws(item)]
        return values[0] if values else ""
    return collapse_ws(category)


def _image_from_jsonld(product: dict | None) -> str:
    if not product:
        return ""
    image = product.get("image")
    if isinstance(image, list):
        for item in image:
            url = _image_from_jsonld({"image": item})
            if url:
                return url
        return ""
    if isinstance(image, dict):
        return normalize_url_image(image.get("url") or image.get("contentUrl"))
    return normalize_url_image(image)


def _meta(page: Any, selector: str) -> str:
    nodes = page.css(selector)
    if not nodes:
        return ""
    return collapse_ws(nodes[0].attrib.get("content"))


def _currency_evidence(page: Any, product: dict | None) -> tuple[str, str]:
    offers = _offers_of(product)
    currency = collapse_ws(offers.get("priceCurrency")).upper()
    if CURRENCY_RE.match(currency):
        return currency, "jsonld_offers_priceCurrency"
    currency = _meta(page, "meta[property='og:price:currency']").upper()
    if CURRENCY_RE.match(currency):
        return currency, "og_price_currency"
    for script in page.css("script:not([src])::text").getall():
        match = SHOPIFY_CURRENCY_RE.search(script)
        if match:
            return match.group(1).upper(), "shopify_currency_active"
        match = ANALYTICS_CURRENCY_RE.search(script)
        if match:
            return match.group(1).upper(), "shopify_analytics_meta_currency"
    return "", ""


def _dom_options(page: Any) -> list[tuple[str, list[str]]]:
    """Theme-specific public pickers, read as a fallback to embedded variants."""
    out: list[tuple[str, list[str]]] = []
    for select in page.css("select.product-variant-container"):
        select_id = select.attrib.get("id") or ""
        name = ""
        if select_id:
            labels = page.css(f"label[for='{select_id}']")
            if labels:
                name = collapse_ws(labels[0].get_all_text(strip=True))
        if not name:
            siblings = select.xpath("preceding-sibling::label[1]")
            if siblings:
                name = collapse_ws(siblings[0].get_all_text(strip=True))
        values = [collapse_ws(option.get_all_text(strip=True) or option.attrib.get("value")) for option in select.css("option")]
        values = [value for value in values if value]
        if name and values:
            out.append((name, values))
    return out


def _price_from_variants(variants: list[dict]) -> tuple[int | None, int | None, list[int]]:
    prices: list[int] = []
    zero_seen = False
    for variant in variants:
        raw = variant.get("price")
        if raw is None or isinstance(raw, bool):
            continue
        try:
            value = int(Decimal(str(raw)))
        except Exception:
            continue
        if value == 0:
            zero_seen = True
        if value > 0:
            prices.append(value)
    return (min(prices) if prices else None, (0 if zero_seen else None), sorted(set(prices))[:12])


def _description(page: Any, embedded: dict | None) -> tuple[str, str, str, str]:
    """Return (html, format, status, partial_reason)."""
    dom_nodes = page.css(".product__description")
    dom_html = dom_nodes[0].html_content if dom_nodes else ""
    dom_text = html_to_plain_text(dom_html)
    embedded_html = embedded.get("description") if embedded else ""
    embedded_html = embedded_html if isinstance(embedded_html, str) else ""
    embedded_text = html_to_plain_text(embedded_html)
    meta_desc = _meta(page, "meta[name='description']") or _meta(page, "meta[property='og:description']")

    primary = ""
    fmt = "html"
    status = ""
    partial_reason = ""

    if embedded_html.strip():
        primary = embedded_html
        if dom_html.strip() and dom_text:
            ratio = len(dom_text) / max(len(embedded_text), 1)
            if ratio < 0.85:
                status = "partial"
                partial_reason = (
                    "theme DOM description is shorter than the embedded product description "
                    f"(dom_chars={len(dom_text)}, embedded_chars={len(embedded_text)})"
                )
            else:
                status = "complete"
        elif dom_html.strip():
            status = "complete"
        else:
            status = "partial"
            partial_reason = (
                "product description block not found in rendered HTML; "
                "content recovered from the embedded product JSON"
            )
    elif dom_html.strip() and dom_text:
        primary = dom_html
        status = "complete"
    elif meta_desc:
        primary = meta_desc
        fmt = "text"
        status = "fallback"
        partial_reason = ""
    else:
        status = "not_provided"
        fmt = ""

    cleaned = sanitize_description(primary, fmt=fmt) if primary else ""
    if primary and not cleaned and status != "not_provided":
        status = "failed"
        partial_reason = "description source was non-empty but cleaning produced no content"
    return cleaned, (fmt if cleaned else ""), status, partial_reason


def _availability(embedded: dict | None, product: dict | None) -> str:
    variants = embedded.get("variants") if embedded else None
    if isinstance(variants, list) and variants:
        available = [item.get("available") for item in variants if isinstance(item, dict) and isinstance(item.get("available"), bool)]
        if any(available):
            return "in_stock"
        if available:
            return "out_of_stock"
    offers = _offers_of(product)
    raw = collapse_ws(offers.get("availability")).lower()
    if raw:
        for key, value in AVAILABILITY_MAP.items():
            if raw.endswith(key):
                return value
    return ""


def extract_product(page: Any, *, expected_currency: str = CURRENCY_EXPECTED) -> ProductRecord:
    source_url = str(getattr(page, "url", "") or "")
    product_jsonld = find_jsonld_product(page)
    embedded = find_embedded_product(page)

    record = ProductRecord(source_url=source_url)
    record.evidence["jsonld_product"] = bool(product_jsonld)
    record.evidence["embedded_product_json"] = bool(embedded)

    name_candidates = [
        ("jsonld_name", product_jsonld.get("name") if product_jsonld else ""),
        ("h1", page.css("h1::text").get()),
        ("embedded_title", embedded.get("title") if embedded else ""),
        ("og_title", _meta(page, "meta[property='og:title']")),
    ]
    for source, raw in name_candidates:
        name = clean_name(raw)
        if name:
            record.name = name
            record.evidence["name_source"] = source
            break

    variants = embedded.get("variants") if embedded else None
    variants = [item for item in variants if isinstance(item, dict)] if isinstance(variants, list) else []
    min_cents, zero_seen, price_samples = _price_from_variants(variants)
    record.evidence["variant_count"] = len(variants)
    record.evidence["variant_price_samples_usd_cents"] = price_samples

    if min_cents is not None:
        record.price_cents = min_cents
        record.evidence["price_source"] = "embedded_variants_min_positive"
    else:
        offers = _offers_of(product_jsonld)
        parsed = parse_positive_money(offers.get("price"))
        if parsed is not None and parsed == parsed.to_integral_value():
            record.price_cents = int(parsed) * 100
            record.evidence["price_source"] = "jsonld_offer_price"
        elif parsed is not None:
            record.price_cents = int((parsed * 100).to_integral_value())
            record.evidence["price_source"] = "jsonld_offer_price"
        else:
            embedded_min = embedded.get("price_min") if embedded else None
            try:
                embedded_min_int = int(Decimal(str(embedded_min))) if embedded_min is not None else None
            except Exception:
                embedded_min_int = None
            if embedded_min_int is not None and embedded_min_int > 0:
                record.price_cents = embedded_min_int
                record.evidence["price_source"] = "embedded_price_min"
            else:
                og_amount = parse_positive_money(_meta(page, "meta[property='og:price:amount']"))
                if og_amount is not None:
                    record.price_cents = int((og_amount * 100).to_integral_value())
                    record.evidence["price_source"] = "og_price_amount"

    currency, currency_source = _currency_evidence(page, product_jsonld)
    record.price_currency = currency
    record.evidence["currency_source"] = currency_source

    image = ""
    if embedded:
        image = normalize_url_image(embedded.get("featured_image"))
        if not image and isinstance(embedded.get("images"), list):
            for raw in embedded["images"]:
                image = normalize_url_image(raw)
                if image:
                    break
    if not image:
        image = _image_from_jsonld(product_jsonld)
    if not image:
        image = normalize_url_image(_meta(page, "meta[property='og:image']"))
    if not image:
        for node in page.css(".product-gallery img"):
            image = normalize_url_image(node.attrib.get("src") or node.attrib.get("data-src"))
            if image:
                break
    record.primary_image_url = image
    record.evidence["image_source"] = "embedded_featured_image" if image and embedded else ("jsonld_or_meta" if image else "")

    category = _category_name(product_jsonld)
    if not category and embedded:
        category = collapse_ws(embedded.get("type"))
    if category.lower() in {"home", "shop", "all", "products"}:
        category = ""
    record.category = category
    record.evidence["category_source"] = "jsonld_category" if _category_name(product_jsonld) else ("embedded_type" if category else "")
    if not category:
        record.missing_reasons["category"] = "not_found"

    brand = _brand_name(product_jsonld)
    brand_source = "jsonld_brand" if brand else ""
    if not brand and embedded:
        brand = collapse_ws(embedded.get("vendor"))
        brand_source = "embedded_vendor" if brand else ""
    if brand and brand.casefold() in STORE_NAME_TOKENS:
        record.missing_reasons["brand"] = "store_name_not_brand"
        brand = ""
        brand_source = "rejected_store_name"
    elif not brand:
        record.missing_reasons["brand"] = "not_provided"
    record.brand = brand
    record.evidence["brand_source"] = brand_source

    option_names = embedded.get("options") if embedded else None
    option_names = [str(item) for item in option_names] if isinstance(option_names, list) else []
    options = build_options(option_names, variants, dom_options=_dom_options(page))
    record.options = options
    record.evidence["options_source"] = "embedded_variants" if options and variants else ("dom_picker" if options else "none")
    if len(variants) > 1 and not options:
        record.missing_reasons["options"] = "not_extracted"
    elif not options and len(variants) <= 1:
        record.missing_reasons.pop("options", None)

    record.availability = _availability(embedded, product_jsonld)
    if not record.availability:
        record.missing_reasons["availability"] = "unknown_not_inferred"

    record.tax_basis, tax_basis_source = tax_basis_from_variants(variants)
    record.evidence["tax_basis_source"] = tax_basis_source

    description_html, description_format, description_status, partial_reason = _description(page, embedded)
    record.description_html = description_html
    record.description_format = description_format
    record.description_status = description_status
    record.partial_reason = partial_reason
    if description_status in {"fallback", "not_provided", "failed"}:
        record.missing_reasons["description"] = {
            "fallback": "summary_only_no_body",
            "not_provided": "not_provided_by_source",
            "failed": "extraction_failed",
        }[description_status]

    if not record.name:
        record.exclusion_reason = "missing_name"
    elif record.price_cents is None:
        if zero_seen == 0:
            record.exclusion_reason = "zero_price"
            record.exclusion_detail = f"all public variant prices are zero; samples={price_samples}"
        else:
            record.exclusion_reason = "missing_price"
            record.exclusion_detail = "no finite positive public price found"
    elif not record.price_currency:
        record.exclusion_reason = "missing_currency"
        record.exclusion_detail = "no same-offer currency evidence (JSON-LD/og/Shopify currency)"
    elif not record.primary_image_url:
        record.exclusion_reason = "missing_primary_image"
    elif not source_url:
        record.exclusion_reason = "missing_source_url"

    if record.price_currency and record.price_currency != expected_currency:
        record.exclusion_reason = "currency_mismatch"
        record.exclusion_detail = f"expected {expected_currency}, got {record.price_currency}"

    if record.price_cents is not None:
        record.evidence["price_amount"] = str(cents_to_amount(record.price_cents))

    return record


def looks_like_challenge(page: Any) -> bool:
    try:
        body = page.body.decode(getattr(page, "encoding", None) or "utf-8", errors="replace").lower()
    except Exception:
        body = ""
    if not any(marker in body for marker in CHALLENGE_MARKERS):
        return False
    return not page.css("h1")
