"""Product extraction and normalisation for javaestate.com (Shopify)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html import unescape
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from parsel import Selector

from .clean import clean_html_fragment, html_to_text

SITE_HOST = "javaestate.com"
STORE_BRAND_NAMES = {
    "java estate",
    "java estate roastery",
    "javaestate",
    "javaestate.com",
    "www.javaestate.com",
}
GENERIC_CATEGORIES = {
    "",
    "all",
    "collections",
    "default",
    "featured",
    "frontpage",
    "home",
    "home page",
    "products",
    "shop",
    "shop all",
}
QUANTITY_OPTION_NAMES = {"quantity", "qty", "cantidad", "quantité", "menge", "数量"}
PLACEHOLDER_OPTIONS = {"default title", "title", "default"}

JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
EMBEDDED_PRODUCT_RE = re.compile(r"window\.wpdExtensionIsProductPage\s*=\s*")
SHOPIFY_CURRENCY_RE = re.compile(r"Shopify\.currency\s*=\s*(\{[^}]*\})")
SHOPIFY_COUNTRY_RE = re.compile(r"Shopify\.country\s*=\s*['\"]([A-Za-z]{2})['\"]")
SHOPIFY_LOCALE_RE = re.compile(r"Shopify\.locale\s*=\s*['\"]([^'\"]+)['\"]")
ANALYTICS_CURRENCY_RE = re.compile(
    r"ShopifyAnalytics\.meta\.currency\s*=\s*['\"]([A-Za-z]{3})['\"]"
)
CONTENT_LANGUAGE_RE = re.compile(
    r"<meta[^>]+http-equiv=[\"']content-language[\"'][^>]+content=[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
TAX_INCLUDED_RE = re.compile(r"(?i)\btax(?:es)?\s+(?:are\s+)?included\b")
TAX_EXCLUDED_RE = re.compile(r"(?i)\btax(?:es)?\s+(?:are\s+)?(?:excluded|not\s+included)\b")
PRICE_DELTA_RE = re.compile(
    r"\s*(?:\(\s*[+\-]\s*[^)]*\)|\+\s*[$€£]?\s*\d[\d.,]*|-\s*[$€£]?\s*\d[\d.,]*)\s*$"
)


class ProductExcluded(Exception):
    """The page is a product but must not enter the valid set (business rule)."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class ProductFailed(Exception):
    """The page is a product but a required field could not be established."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class ProductResult:
    row: dict[str, str]
    evidence: dict[str, Any]


def normalize_url(url: str) -> str:
    """Canonicalise a product URL for identity and output."""

    parts = urlsplit(url.strip())
    scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
    host = (parts.hostname or "").lower()
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, host, path, "", ""))


def resolve_image_url(value: str | None, base_url: str) -> str | None:
    if not value:
        return None
    value = value.strip()
    if value.startswith("//"):
        value = "https:" + value
    elif not value.startswith(("http://", "https://")):
        value = urljoin(base_url, value)
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    # Shopify CDN resizes through width/height query parameters.  Dropping
    # them keeps the version parameter but removes the requested resize.
    query = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in {"width", "height"}
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), "")
    )


def _iter_objects(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_objects(child)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_objects(item)


def _type_names(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {item for item in value if isinstance(item, str)}
    return set()


def parse_jsonld_products(raw: str) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    for match in JSONLD_RE.finditer(raw):
        text = unescape(match.group(1)).strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        for obj in _iter_objects(payload):
            if "Product" in _type_names(obj.get("@type")):
                products.append(obj)
    return products


def parse_embedded_product(raw: str) -> dict[str, Any] | None:
    """Parse the theme's full product JSON.

    The value is a JavaScript object literal assigned to a window variable;
    it is not a JSON script tag, so brace matching is used instead of a regex
    that would break on nested objects.
    """

    match = EMBEDDED_PRODUCT_RE.search(raw)
    if not match:
        return None
    start = match.end()
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(raw)):
        char = raw[index]
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
                try:
                    value = json.loads(raw[start : index + 1])
                except json.JSONDecodeError:
                    return None
                return value if isinstance(value, dict) else None
    return None


def parse_shopify_context(raw: str) -> dict[str, str | None]:
    currency = None
    match = SHOPIFY_CURRENCY_RE.search(raw)
    if match:
        try:
            currency = json.loads(match.group(1)).get("active")
        except json.JSONDecodeError:
            currency = None
    country_match = SHOPIFY_COUNTRY_RE.search(raw)
    locale_match = SHOPIFY_LOCALE_RE.search(raw)
    analytics_match = ANALYTICS_CURRENCY_RE.search(raw)
    language_match = CONTENT_LANGUAGE_RE.search(raw)
    return {
        "currency": currency.upper() if isinstance(currency, str) else None,
        "country": country_match.group(1).upper() if country_match else None,
        "locale": locale_match.group(1) if locale_match else None,
        "analytics_currency": (
            analytics_match.group(1).upper() if analytics_match else None
        ),
        "content_language": language_match.group(1) if language_match else None,
    }


def _option_names(embedded: dict[str, Any]) -> list[str]:
    raw_options = embedded.get("options") or []
    names: list[str] = []
    for option in raw_options:
        if isinstance(option, dict):
            name = option.get("name")
        else:
            name = option
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


def _clean_option_value(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    value = PRICE_DELTA_RE.sub("", value).strip()
    return value


def extract_options(embedded: dict[str, Any]) -> dict[str, list[str]]:
    variants = embedded.get("variants") or []
    names = _option_names(embedded)
    if not names or not variants:
        return {}

    result: dict[str, list[str]] = {}
    for index, name in enumerate(names):
        if name.strip().lower() in QUANTITY_OPTION_NAMES:
            continue
        values: list[str] = []
        seen: set[str] = set()
        for variant in variants:
            raw_values = variant.get("options")
            if isinstance(raw_values, list) and index < len(raw_values):
                candidate = raw_values[index]
            else:
                candidate = variant.get(f"option{index + 1}")
            if not isinstance(candidate, str):
                continue
            cleaned = _clean_option_value(candidate)
            if not cleaned or cleaned.lower() in PLACEHOLDER_OPTIONS:
                continue
            key = cleaned.casefold()
            if key in seen:
                continue
            seen.add(key)
            values.append(cleaned)
        if values:
            result[name] = values
    return result


def serialize_options(options: dict[str, list[str]]) -> str:
    """Serialize options with the escaping rules from docs/02."""

    def escape(value: str) -> str:
        return (
            value.replace("\\", "\\\\")
            .replace("#", "\\#")
            .replace("|", "\\|")
            .replace("~", "\\~")
        )

    return "~".join(
        f"{escape(name)}#{'|'.join(escape(value) for value in values)}"
        for name, values in options.items()
    )


def _jsonld_offer(offers: Any) -> dict[str, Any] | None:
    if isinstance(offers, dict):
        return offers
    if isinstance(offers, list):
        for item in offers:
            if isinstance(item, dict):
                return item
    return None


def _jsonld_price(offers: Any) -> tuple[Decimal | None, str | None, str | None]:
    """Return (amount, currency, kind) from JSON-LD offers."""

    offer = _jsonld_offer(offers)
    if not offer:
        return None, None, None
    offer_type = _type_names(offer.get("@type"))
    currency = offer.get("priceCurrency")
    if isinstance(currency, str):
        currency = currency.upper()
    else:
        currency = None

    candidates: list[Decimal] = []
    for key in ("price", "lowPrice", "highPrice"):
        value = offer.get(key)
        if value in (None, ""):
            continue
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            continue
        if amount.is_finite():
            candidates.append(amount)
    spec = offer.get("priceSpecification")
    if isinstance(spec, dict):
        for key in ("price", "minPrice"):
            value = spec.get(key)
            if value in (None, ""):
                continue
            try:
                amount = Decimal(str(value))
            except (InvalidOperation, ValueError):
                continue
            if amount.is_finite():
                candidates.append(amount)

    positive = [amount for amount in candidates if amount > 0]
    if positive:
        kind = "AggregateOffer" if "AggregateOffer" in offer_type else "Offer"
        return min(positive), currency, kind
    if candidates:
        return min(candidates), currency, "Offer"
    return None, currency, None


def _price_from_embedded(embedded: dict[str, Any]) -> dict[str, Any] | None:
    variants = embedded.get("variants") or []
    if not variants:
        return None
    prices: list[tuple[Decimal, dict[str, Any]]] = []
    zero_count = 0
    negative_count = 0
    for variant in variants:
        raw_price = variant.get("price")
        if raw_price in (None, ""):
            continue
        try:
            cents = Decimal(str(raw_price))
        except (InvalidOperation, ValueError):
            continue
        if not cents.is_finite():
            continue
        if cents == 0:
            zero_count += 1
            continue
        if cents < 0:
            negative_count += 1
            continue
        # Shopify's embedded product JSON expresses prices in minor units.
        prices.append((cents / Decimal(100), variant))
    return {
        "prices": prices,
        "zero_count": zero_count,
        "negative_count": negative_count,
        "variant_count": len(variants),
    }


def _description_from_page(selector: Selector) -> tuple[str, str | None, bool]:
    """Return (html, selector, empty_container_hit).

    The theme renders an empty ``div.product__description.rte`` (with an HTML
    comment) on products that have no body description.  A selector hit must
    therefore be checked for actual text; an empty hit is evidence for the
    "source has no description" state, not evidence of a captured DOM body.
    """

    for css in (
        ".product__description.rte",
        ".product__description",
        ".product-description",
        "[data-product-description]",
    ):
        element = selector.css(css)
        if not element:
            continue
        html = element.get() or ""
        text = element.xpath("string(.)").get() or ""
        if re.sub(r"\s+", " ", text).strip():
            return html, css, False
        return "", css, True
    return "", None, False


def _extra_description_selectors(selector: Selector) -> list[str]:
    found: list[str] = []
    candidates = (
        ".product-specs",
        ".product__specs",
        "[class*='specification']",
        "[class*='additional-information']",
        "[id*='specification']",
        "[class*='ingredients']",
        "[class*='nutrition']",
    )
    for css in candidates:
        for element in selector.css(css):
            text = element.xpath("string(.)").get() or ""
            if len(re.sub(r"\s+", " ", text).strip()) < 20:
                continue
            inside = element.xpath(
                "ancestor::*[contains(@class, 'product__description')]"
            )
            if inside:
                continue
            if css not in found:
                found.append(css)
    return found


def _tax_basis(raw: str) -> str:
    if TAX_INCLUDED_RE.search(raw):
        return "INCLUSIVE"
    if TAX_EXCLUDED_RE.search(raw):
        return "EXCLUSIVE"
    return "UNKNOWN"


def _clean_name(value: str | None) -> str:
    if not value:
        return ""
    name = re.sub(r"\s+", " ", value).strip()
    name = re.sub(
        r"\s*[|–—,-]\s*(?:www\.)?javaestate\.com\s*$", "", name, flags=re.IGNORECASE
    )
    name = re.sub(r"(?:www\.)?javaestate\.com", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^[\s|–—,-]+|[\s|–—,-]+$", "", name)
    return name.strip()


def _brand(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("name")
    if not isinstance(value, str):
        return ""
    value = re.sub(r"\s+", " ", value).strip()
    if not value or value.casefold() in STORE_BRAND_NAMES:
        return ""
    if SITE_HOST in value.casefold():
        return ""
    return value


def _category(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"\s+", " ", value).strip()
    if value.casefold() in GENERIC_CATEGORIES:
        return ""
    return value


def _price_from_jsonld(
    jsonld: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not jsonld:
        return None
    amount, currency, kind = _jsonld_price(jsonld.get("offers"))
    if amount is None:
        return None
    return {
        "amount": amount,
        "currency": currency,
        "kind": kind,
        "positive": amount > 0,
    }


def _first_image(embedded: dict[str, Any], jsonld: dict[str, Any] | None) -> tuple[str | None, str]:
    candidates: list[tuple[str, str]] = []
    featured = embedded.get("featured_image")
    if isinstance(featured, str) and featured.strip():
        candidates.append((featured, "embedded.featured_image"))
    for image in embedded.get("images") or []:
        if isinstance(image, str) and image.strip():
            candidates.append((image, "embedded.images"))
    if jsonld:
        image = jsonld.get("image")
        if isinstance(image, str):
            candidates.append((image, "jsonld.image"))
        elif isinstance(image, dict) and isinstance(image.get("url"), str):
            candidates.append((image["url"], "jsonld.image.url"))
        elif isinstance(image, list):
            for item in image:
                if isinstance(item, str):
                    candidates.append((item, "jsonld.image[]"))
                elif isinstance(item, dict) and isinstance(item.get("url"), str):
                    candidates.append((item["url"], "jsonld.image[].url"))
    for value, source in candidates:
        resolved = resolve_image_url(value, "https://javaestate.com/")
        if not resolved:
            continue
        lowered = resolved.casefold()
        if "logo" in lowered or "placeholder" in lowered:
            continue
        return resolved, source
    return None, "none"


def extract_product(
    raw_html: str,
    page_url: str,
    *,
    market: str,
    locale: str,
    extracted_at: str,
) -> ProductResult:
    selector = Selector(text=raw_html)
    embedded = parse_embedded_product(raw_html)
    jsonld_products = parse_jsonld_products(raw_html)
    jsonld = jsonld_products[0] if jsonld_products else None
    shopify = parse_shopify_context(raw_html)

    if embedded is None and jsonld is None:
        raise ProductFailed(
            "PRODUCT_DATA_JSON_MISSING",
            "Neither window.wpdExtensionIsProductPage nor a Product JSON-LD block was found.",
        )

    name = _clean_name(
        (embedded or {}).get("title")
        or (jsonld or {}).get("name")
        or selector.css("h1::text").get()
    )
    if not name:
        raise ProductFailed("NAME_MISSING", "No product title in embedded JSON, JSON-LD or h1.")

    embedded_price = _price_from_embedded(embedded or {})
    jsonld_price = _price_from_jsonld(jsonld)
    price_amount: Decimal | None = None
    price_source = ""
    price_kind = ""
    variant_count = 0
    min_variant_title = ""
    zero_count = 0
    negative_count = 0

    if embedded_price and embedded_price["prices"]:
        price_amount, min_variant = min(
            embedded_price["prices"], key=lambda item: item[0]
        )
        price_source = "embedded_product_json"
        price_kind = "variant"
        variant_count = embedded_price["variant_count"]
        min_variant_title = str(min_variant.get("title") or "")
        zero_count = embedded_price["zero_count"]
        negative_count = embedded_price["negative_count"]
    elif embedded_price and embedded_price["variant_count"] and (
        embedded_price["zero_count"] or embedded_price["negative_count"]
    ):
        # The page published variants, but none had a positive price.  Do not
        # substitute a JSON-LD offer for a different variant; this is a
        # business exclusion, not a fallback opportunity.
        if embedded_price["zero_count"]:
            raise ProductExcluded(
                "ZERO_PRICE",
                f"All {embedded_price['zero_count']} embedded variant price(s) were zero.",
            )
        raise ProductExcluded(
            "NEGATIVE_PRICE",
            f"All {embedded_price['negative_count']} embedded variant price(s) were negative.",
        )
    elif jsonld_price and jsonld_price["positive"]:
        price_amount = jsonld_price["amount"]
        price_source = "jsonld"
        price_kind = str(jsonld_price["kind"] or "offer")
    else:
        # Distinguish the business reasons.  A product whose only variants are
        # zero-priced is excluded, not counted as a technical failure.
        if embedded_price and embedded_price["zero_count"]:
            raise ProductExcluded(
                "ZERO_PRICE",
                f"All {embedded_price['zero_count']} embedded variant price(s) were zero.",
            )
        if embedded_price and embedded_price["negative_count"]:
            raise ProductExcluded(
                "NEGATIVE_PRICE",
                f"{embedded_price['negative_count']} embedded variant price(s) were negative.",
            )
        if jsonld_price and jsonld_price["amount"] is not None:
            amount = jsonld_price["amount"]
            if amount == 0:
                raise ProductExcluded("ZERO_PRICE", "JSON-LD offer price was zero.")
            if amount < 0:
                raise ProductExcluded("NEGATIVE_PRICE", "JSON-LD offer price was negative.")
        raise ProductExcluded("NO_PRICE", "No finite numeric price was published.")

    if price_amount is None or not price_amount.is_finite() or price_amount <= 0:
        raise ProductExcluded(
            "NO_POSITIVE_PRICE", f"Resolved price was {price_amount!r}."
        )

    # Currency must come from the same quotation object.  Collect every
    # independent source and reject a conflict rather than guessing.
    currency_candidates: dict[str, str] = {}
    if shopify.get("currency"):
        currency_candidates["shopify.currency"] = str(shopify["currency"])
    if shopify.get("analytics_currency"):
        currency_candidates["shopify_analytics.meta.currency"] = str(
            shopify["analytics_currency"]
        )
    if jsonld_price and jsonld_price.get("currency"):
        currency_candidates["jsonld.offer.priceCurrency"] = str(jsonld_price["currency"])
    if not currency_candidates:
        raise ProductFailed(
            "CURRENCY_EVIDENCE_MISSING",
            "No shop currency or JSON-LD offer currency was found.",
        )
    distinct_currencies = {value for value in currency_candidates.values()}
    if len(distinct_currencies) > 1:
        raise ProductFailed(
            "CURRENCY_CONFLICT",
            f"Currency sources disagree: {currency_candidates}",
        )
    currency = next(iter(distinct_currencies))
    if not re.fullmatch(r"[A-Z]{3}", currency or ""):
        raise ProductFailed(
            "CURRENCY_INVALID", f"Currency was not a three-letter ISO code: {currency!r}"
        )
    if currency != "USD":
        raise ProductExcluded(
            "CURRENCY_NOT_TARGET",
            f"Expected USD for the US/javaestate task, got {currency}.",
        )

    shopify_country = shopify.get("country")
    if shopify_country and shopify_country != market:
        raise ProductExcluded(
            "MARKET_MISMATCH",
            f"Shopify.country was {shopify_country}, expected {market}.",
        )
    shopify_locale = shopify.get("locale")
    if shopify_locale and shopify_locale.lower() not in {"en", "en-us"}:
        raise ProductExcluded(
            "LOCALE_MISMATCH",
            f"Shopify.locale was {shopify_locale!r}, expected en/en-US.",
        )

    image_url, image_source = _first_image(embedded or {}, jsonld)
    if not image_url:
        raise ProductFailed("PRIMARY_IMAGE_MISSING", "No usable product image URL.")

    # Description.  The embedded body_html is the merchant's own description;
    # the DOM variant is used only when the embedded value is absent.
    warnings: list[str] = []
    description_source = "none"
    description_html = ""
    page_description, description_selector, empty_container_hit = _description_from_page(
        selector
    )
    page_description_present = bool(page_description and page_description.strip())
    page_description_cleaned_empty = False
    raw_description = (embedded or {}).get("description")
    if isinstance(raw_description, str) and raw_description.strip():
        description_html = clean_html_fragment(raw_description)
        description_source = "embedded_product_json"
    if not description_html and page_description_present:
        cleaned = clean_html_fragment(page_description)
        if cleaned:
            description_html = cleaned
            description_source = "product_page_dom"
            warnings.append("Embedded product description missing; used DOM description.")
        else:
            page_description_cleaned_empty = True
            warnings.append("DOM description container had content but cleaned to empty.")
    if not description_html and jsonld:
        jsonld_description = jsonld.get("description")
        if isinstance(jsonld_description, str) and jsonld_description.strip():
            if "<" in jsonld_description:
                description_html = clean_html_fragment(jsonld_description)
            else:
                description_html = jsonld_description.strip()
            description_source = "jsonld"
            warnings.append("Body description missing; used JSON-LD fallback.")

    extra_selectors = _extra_description_selectors(selector)
    if not description_html and extra_selectors:
        blocks = []
        for css in extra_selectors:
            for element in selector.css(css):
                html = clean_html_fragment(element.get() or "")
                if html and html not in blocks:
                    blocks.append(html)
        description_html = "".join(blocks)
        description_source = "related_blocks"
        description_status = "partial"
        partial_reason = (
            "Main body description was not found; related blocks were used: "
            + ", ".join(extra_selectors)
        )
    elif not description_html and empty_container_hit:
        description_status = "not_provided"
        description_source = "empty_description_container"
        partial_reason = ""
    elif not description_html and page_description_cleaned_empty:
        raise ProductFailed(
            "DESCRIPTION_CLEAN_FAILED",
            f"Description container {description_selector!r} had content but cleaned to empty.",
        )
    elif not description_html and description_selector:
        description_status = "not_provided"
        description_source = "empty_description_container"
        partial_reason = ""
    elif not description_html:
        raise ProductFailed(
            "DESCRIPTION_BLOCK_NOT_FOUND",
            "No body description, JSON-LD description, related block or known description container.",
        )
    elif extra_selectors:
        description_status = "partial"
        partial_reason = (
            "Additional description/specification blocks were present but not merged: "
            + ", ".join(extra_selectors)
        )
    elif description_source == "jsonld":
        description_status = "fallback"
        partial_reason = ""
    else:
        description_status = "complete"
        partial_reason = ""

    description_format = ""
    if description_html:
        description_format = "html" if re.search(r"<[a-zA-Z][^>]*>", description_html) else "text"

    options = extract_options(embedded or {})
    option_attributes = serialize_options(options)

    category_candidates = []
    product_type = (embedded or {}).get("type")
    if isinstance(product_type, str):
        category_candidates.append(product_type)
    if jsonld and isinstance(jsonld.get("category"), str):
        category_candidates.append(jsonld["category"])
    categories: list[str] = []
    seen_categories: set[str] = set()
    for candidate in category_candidates:
        cleaned = _category(candidate)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen_categories:
            continue
        seen_categories.add(key)
        categories.append(cleaned)
    category = categories[0] if categories else ""

    brand_candidate = (embedded or {}).get("vendor")
    brand = _brand(brand_candidate)
    if not brand and jsonld:
        brand = _brand(jsonld.get("brand"))

    availability = ""
    if isinstance((embedded or {}).get("available"), bool):
        availability = "in_stock" if embedded["available"] else "out_of_stock"
    elif embedded and embedded.get("variants"):
        availability = (
            "in_stock"
            if any(bool(variant.get("available")) for variant in embedded["variants"])
            else "out_of_stock"
        )

    canonical = selector.css('link[rel="canonical"]::attr(href)').get()
    source_url = normalize_url(canonical or page_url)

    tax_basis = _tax_basis(raw_html)

    missing_reasons: dict[str, str] = {}
    if not options:
        missing_reasons["options"] = "NO_MEANINGFUL_OPTIONS"
    if not brand:
        if isinstance(brand_candidate, str) and brand_candidate.strip().casefold() in STORE_BRAND_NAMES:
            missing_reasons["brand"] = "STORE_NAME_NOT_BRAND"
        else:
            missing_reasons["brand"] = "BRAND_NOT_PROVIDED"
    if not category:
        missing_reasons["categories"] = "CATEGORY_NOT_FOUND"
    if not availability:
        missing_reasons["availability"] = "AVAILABILITY_NOT_PROVIDED"
    if tax_basis == "UNKNOWN":
        missing_reasons["tax_basis"] = "NOT_SPECIFIED_BY_SOURCE"
    if description_status == "not_provided":
        missing_reasons["description_html"] = "SOURCE_HAS_NO_DESCRIPTION"

    price_basis = (
        "lowest_public_current_variant_price"
        if price_source == "embedded_product_json"
        else "public_offer_price"
    )

    row = {
        "name": name,
        "price_amount": f"{price_amount.quantize(Decimal('0.01')):.2f}",
        "price_currency": currency,
        "primary_image_url": image_url,
        "description_html": description_html,
        "category": category,
        "brand": brand,
        "attributes": option_attributes,
        "source_url": source_url,
        "description_format": description_format,
        "description_status": description_status,
        "partial_reason": partial_reason,
        "missing_reasons": json.dumps(
            missing_reasons, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
        "market": market,
        "locale": locale,
        "availability": availability,
        "tax_basis": tax_basis,
        "price_basis": price_basis,
        "extracted_at": extracted_at,
    }

    evidence = {
        "product_json_present": embedded is not None,
        "jsonld_product_present": jsonld is not None,
        "variant_count": variant_count,
        "zero_variant_count": zero_count,
        "negative_variant_count": negative_count,
        "min_variant_title": min_variant_title,
        "price_source": price_source,
        "price_kind": price_kind,
        "jsonld_price": str(jsonld_price["amount"]) if jsonld_price else None,
        "jsonld_currency": jsonld_price.get("currency") if jsonld_price else None,
        "currency_sources": currency_candidates,
        "shopify_country": shopify_country,
        "shopify_locale": shopify_locale,
        "shopify_currency": shopify.get("currency"),
        "content_language": shopify.get("content_language"),
        "image_source": image_source,
        "description_source": description_source,
        "description_selector": description_selector,
        "description_container_found": description_selector is not None,
        "description_empty_container_hit": empty_container_hit,
        "description_page_content_present": page_description_present,
        "description_length": len(description_html),
        "description_text_length": len(html_to_text(description_html)),
        "category_candidates": category_candidates,
        "category_selected": category,
        "brand_candidate": brand_candidate if isinstance(brand_candidate, str) else None,
        "brand_selected": brand,
        "availability_source": "embedded.available",
        "tax_basis": tax_basis,
        "extra_description_selectors": extra_selectors,
        "warnings": warnings,
    }
    return ProductResult(row=row, evidence=evidence)
