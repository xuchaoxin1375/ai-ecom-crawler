"""Product extraction for skatepro.es product pages (Scrapling Selector)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from scrapling.parser import Selector

from .config import CURRENCY
from .normalize import (
    build_options,
    clean_name,
    collapse_ws,
    format_amount,
    html_to_plain_text,
    normalize_image_url,
    sanitize_description,
    to_decimal,
)

PHP2JS_MARKER = "var PHP2JS = php2js = "
BREADCRUMB_SKIP = {"inicio", "atrás", "atras", "home", "back"}
CHALLENGE_MARKERS = (
    "just a moment",
    "cf-challenge",
    "checking your browser",
    "access denied",
    "captcha",
)

@dataclass
class ProductRecord:
    source_url: str = ""
    name: str = ""
    price_amount: Decimal | None = None
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
    exclusion_reason: str = ""
    exclusion_detail: str = ""
    extraction_error: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    variant_count: int = 0
    zero_price_variants: int = 0


def looks_like_challenge(response: Any) -> bool:
    try:
        body = (response.body or b"").decode("utf-8", "replace").lower()
    except Exception:
        return False
    if any(marker in body for marker in CHALLENGE_MARKERS) and "product_description" not in body:
        return True
    return False


def _decode(response: Any) -> str:
    raw = response.body or b""
    encoding = getattr(response, "encoding", None) or "utf-8"
    try:
        return raw.decode(encoding, errors="replace")
    except (LookupError, TypeError):
        return raw.decode("utf-8", errors="replace")


def _json_ld_products(page: Selector) -> list[dict[str, Any]]:
    """Return Product and ProductGroup entities (skatepro uses both)."""
    products: list[dict[str, Any]] = []
    for node in page.css('script[type="application/ld+json"]'):
        text = (node.text or "").strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if isinstance(item, dict) and item.get("@type") in {"Product", "ProductGroup"}:
                products.append(item)
    return products


def _offer_currencies(products: list[dict[str, Any]]) -> set[str]:
    currencies: set[str] = set()
    for product in products:
        offers = product.get("offers")
        if isinstance(offers, dict):
            currency = _clean_currency(offers.get("priceCurrency"))
            if currency:
                currencies.add(currency)
        for variant in product.get("hasVariant") or []:
            if not isinstance(variant, dict):
                continue
            variant_offers = variant.get("offers")
            if isinstance(variant_offers, dict):
                currency = _clean_currency(variant_offers.get("priceCurrency"))
                if currency:
                    currencies.add(currency)
    return currencies


def _php2js_product(raw_html: str) -> dict[str, Any] | None:
    """Pull the PHP2JS object, whose JSON section carries every variant price."""
    index = raw_html.find(PHP2JS_MARKER)
    if index < 0:
        return None
    start = index + len(PHP2JS_MARKER)
    depth = 0
    in_string = False
    escaped = False
    end: int | None = None
    for position in range(start, len(raw_html)):
        char = raw_html[position]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = position + 1
                break
    if end is None:
        return None
    try:
        payload = json.loads(raw_html[start:end])
    except (json.JSONDecodeError, ValueError):
        return None
    products = payload.get("product") or {}
    if not isinstance(products, dict) or not products:
        return None
    first_key = next(iter(products))
    product = products[first_key]
    if not isinstance(product, dict):
        return None
    product = dict(product)
    product["_product_id"] = first_key
    return product


def _spec_rows(page: Selector) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for row in page.css("#product_specifications .row"):
        columns = row.css(".columns")
        if len(columns) < 2:
            continue
        label = collapse_ws(columns[0].get_all_text(strip=True)).rstrip(":").strip()
        value = collapse_ws(columns[1].get_all_text(strip=True))
        if label and value:
            rows.append((label, value))
    return rows


def _spec_table_html(rows: list[tuple[str, str]]) -> str:
    if not rows:
        return ""
    body = "".join(f"<tr><th>{_escape(label)}</th><td>{_escape(value)}</td></tr>" for label, value in rows)
    return f"<h2>Especificaciones</h2><table><tbody>{body}</tbody></table>"


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _breadcrumb(page: Selector) -> str:
    names: list[str] = []
    for node in page.css("nav.breadcrumb a"):
        text = collapse_ws(node.get_all_text(strip=True))
        if not text or text.casefold() in BREADCRUMB_SKIP:
            continue
        if text not in names:
            names.append(text)
    return " > ".join(names)


def _clean_currency(value: object) -> str:
    text = collapse_ws(str(value or "")).upper()
    return text if re.fullmatch(r"[A-Z]{3}", text) else ""


def extract_product(response: Any) -> ProductRecord:
    raw_html = _decode(response)
    page = Selector(content=raw_html, url=str(getattr(response, "url", "")))
    record = ProductRecord(source_url=str(getattr(response, "url", "")))
    record.evidence["source_kind"] = "static_html"

    ld_products = _json_ld_products(page)
    php_product = _php2js_product(raw_html)

    # ---- name
    name = clean_name(php_product.get("name")) if php_product else ""
    if not name and ld_products:
        name = clean_name(ld_products[0].get("name"))
    if not name:
        h1 = page.css("h1")
        name = clean_name(h1[0].get_all_text(strip=True)) if h1 else ""
    record.name = name
    record.missing_reasons.pop("name", None)

    # ---- currency (same-offer evidence: JSON-LD priceCurrency)
    currencies = _offer_currencies(ld_products)
    if len(currencies) == 1:
        record.price_currency = next(iter(currencies))
        record.evidence["currency"] = f"json_ld_offer_priceCurrency={record.price_currency}"
    elif len(currencies) > 1:
        record.exclusion_reason = "currency_mismatch"
        record.exclusion_detail = f"JSON-LD offers carry multiple currencies: {sorted(currencies)}"
    else:
        record.missing_reasons["price.currency"] = "NOT_PROVIDED_IN_OFFER"

    # ---- price: lowest public current variant price (incl. out-of-stock variants)
    prices: list[Decimal] = []
    zero = 0
    variant_rows: list[dict[str, Any]] = []
    if php_product:
        variants = php_product.get("variants") or {}
        if isinstance(variants, dict):
            variant_rows = [v for v in variants.values() if isinstance(v, dict)]
        record.variant_count = len(variant_rows)
        for variant in variant_rows:
            amount = to_decimal(variant.get("price_number"))
            if amount is None:
                continue
            if amount <= 0:
                zero += 1
                continue
            prices.append(amount)
    if not prices:
        for product in ld_products:
            candidates: list[Any] = []
            offers = product.get("offers")
            if isinstance(offers, dict):
                candidates.append(offers.get("price"))
            for variant in product.get("hasVariant") or []:
                if isinstance(variant, dict) and isinstance(variant.get("offers"), dict):
                    candidates.append(variant["offers"].get("price"))
            for raw_price in candidates:
                amount = to_decimal(raw_price)
                if amount is not None and amount > 0:
                    prices.append(amount)
    record.zero_price_variants = zero
    if prices:
        record.price_amount = min(prices)
        record.evidence["price_source"] = (
            "php2js_variants_min_price_number" if variant_rows else "json_ld_offers_min"
        )
        record.evidence["variant_prices_considered"] = len(prices)
    else:
        record.exclusion_reason = "zero_price" if variant_rows else "missing_price"
        record.exclusion_detail = (
            f"{len(variant_rows)} variants, none with a finite positive price"
            if variant_rows
            else "no positive price in php2js variants or JSON-LD offers"
        )

    # ---- primary image (prefer the lightbox original-size URL)
    image = ""
    originals = page.css(".pi_main_image span[data-href]")
    if originals:
        image = normalize_image_url(originals[0].attrib.get("data-href"))
    if not image and ld_products:
        images = ld_products[0].get("image")
        if isinstance(images, list) and images:
            image = normalize_image_url(str(images[0]))
        elif isinstance(images, str):
            image = normalize_image_url(images)
    if not image:
        gallery = page.css(".product_primary_image img")
        if gallery:
            image = normalize_image_url(gallery[0].attrib.get("src"))
    record.primary_image_url = image
    if not image:
        record.missing_reasons["primary_image_url"] = "NOT_FOUND_IN_GALLERY_OR_JSON_LD"

    # ---- category
    category = ""
    if ld_products:
        category = collapse_ws(str(ld_products[0].get("category") or ""))
    if not category:
        category = _breadcrumb(page)
    if not category and php_product:
        category = " > ".join(
            part.strip() for part in str(php_product.get("category_path") or "").split("|") if part.strip()
        )
    record.category = category
    if not category:
        record.missing_reasons["category"] = "NOT_FOUND"

    # ---- brand
    brand = ""
    if ld_products:
        brand_obj = ld_products[0].get("brand")
        if isinstance(brand_obj, dict):
            brand = collapse_ws(str(brand_obj.get("name") or ""))
        elif isinstance(brand_obj, str):
            brand = collapse_ws(brand_obj)
    if not brand and php_product:
        brand = collapse_ws(str(php_product.get("brand") or ""))
    record.brand = brand
    if not brand:
        record.missing_reasons["brand"] = "NOT_PROVIDED"

    # ---- options
    record.options = build_options(variant_rows)
    if not record.options:
        record.missing_reasons["options"] = "NOT_PROVIDED"

    # ---- availability: JSON-LD schema.org flags across every variant offer
    availability_values: list[str] = []
    for product in ld_products:
        offers = product.get("offers")
        if isinstance(offers, dict) and offers.get("availability"):
            availability_values.append(str(offers["availability"]))
        for variant in product.get("hasVariant") or []:
            if isinstance(variant, dict) and isinstance(variant.get("offers"), dict):
                value = variant["offers"].get("availability")
                if value:
                    availability_values.append(str(value))
    in_stock = sum(1 for value in availability_values if value.endswith("InStock"))
    out_stock = sum(
        1 for value in availability_values if value.endswith(("OutOfStock", "SoldOut", "Discontinued"))
    )
    if in_stock:
        record.availability = "in_stock"
    elif out_stock and out_stock == len(availability_values):
        record.availability = "out_of_stock"
    else:
        record.availability = ""
        record.missing_reasons["availability"] = "NOT_PROVIDED_IN_OFFERS"
    available_variants = 0
    for variant in variant_rows:
        if str(variant.get("stock_level", "")).lower() in {"green", "yellow"}:
            available_variants += 1
    record.evidence["availability"] = {
        "json_ld_in_stock": in_stock,
        "json_ld_out_of_stock": out_stock,
        "available_variants": available_variants,
        "total_variants": len(variant_rows),
    }

    # ---- description: DOM body + specification table, JSON-LD only as fallback
    body_html = ""
    body_node = page.css("#product_description")
    if body_node:
        inner = "".join(child.html_content for child in body_node[0].children if isinstance(child.tag, str))
        body_html = sanitize_description(inner)
    specs = _spec_rows(page)
    spec_html = _spec_table_html(specs)
    ld_description = ""
    if ld_products:
        ld_description = collapse_ws(str(ld_products[0].get("description") or ""))
    body_text = html_to_plain_text(body_html)
    spec_text = " ".join(f"{label} {value}" for label, value in specs)

    if body_text and spec_html:
        record.description_html = f"{body_html}{spec_html}"
        record.description_format = "html"
        record.description_status = "complete"
    elif body_text:
        record.description_html = body_html
        record.description_format = "html"
        record.description_status = "complete"
        record.missing_reasons["specifications"] = "NOT_PROVIDED"
    elif spec_html:
        record.description_html = spec_html
        record.description_format = "html"
        record.description_status = "partial"
        record.partial_reason = (
            "Marketing description block was empty; only the specification table was retained."
        )
    elif ld_description:
        record.description_html = sanitize_description(f"<p>{_escape(ld_description)}</p>")
        record.description_format = "html"
        record.description_status = "fallback"
        record.partial_reason = (
            "Description DOM block and specification table were absent; used the JSON-LD product description."
        )
    else:
        record.description_status = "not_provided"
        record.description_html = ""
        record.description_format = ""
        record.missing_reasons["description_html"] = "SITE_PROVIDED_NO_DESCRIPTION_BLOCK"

    if record.description_status == "complete" and ld_description:
        dom_len = len(body_text)
        if len(ld_description) > 200 and dom_len < len(ld_description) * 0.5:
            record.description_status = "partial"
            record.partial_reason = (
                f"Rendered description ({dom_len} chars) is materially shorter than the "
                f"JSON-LD description ({len(ld_description)} chars)."
            )

    record.evidence["description"] = {
        "dom_body_chars": len(body_text),
        "spec_rows": len(specs),
        "json_ld_chars": len(ld_description),
    }
    record.evidence["tax_basis"] = "no_tax_inclusive_or_exclusive statement found in static HTML"
    record.evidence["ld_product_count"] = len(ld_products)
    return record


def format_audit(record: ProductRecord) -> dict[str, Any]:
    return {
        "source_url": record.source_url,
        "name": record.name,
        "price_amount": format_amount(record.price_amount),
        "price_currency": record.price_currency,
        "description_status": record.description_status,
        "description_chars": len(record.description_html or ""),
        "partial_reason": record.partial_reason,
        "category": record.category,
        "brand": record.brand,
        "options": [[name, values] for name, values in record.options],
        "availability": record.availability,
        "variant_count": record.variant_count,
        "zero_price_variants": record.zero_price_variants,
        "missing_reasons": record.missing_reasons,
        "evidence": record.evidence,
    }
