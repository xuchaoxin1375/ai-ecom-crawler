"""Product extraction and normalisation for skatepro.es.

The site is a server-rendered PHP shop.  Two structured sources carry the
product facts and both are used, because they answer different questions:

* JSON-LD ``ProductGroup`` (multi-variant) or ``Product`` (single variant)
  publishes one entry per purchasable variant with its own price, currency and
  availability.  That is the only place where variant prices are stated, so the
  lowest positive variant price can be taken without enumerating SKUs.
* The rendered DOM names the description and specification blocks and shows
  the current selling price, which is cross-checked against the variant prices.

Nothing here calls a model; every value comes from the response body.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from parsel import Selector

from .clean import clean_html_fragment, html_to_text
from .config import CURRENCY

SITE_HOST = "skatepro.es"
STORE_BRAND_NAMES = {
    "skatepro",
    "skatepro es",
    "skatepro.es",
    "skatepro.com",
    "www.skatepro.es",
}
GENERIC_CATEGORIES = {"", "inicio", "home", "portada", "shop", "tienda"}
QUANTITY_OPTION_NAMES = {"quantity", "qty", "cantidad", "quantité", "menge", "数量"}
PRODUCT_GROUP_TYPE = "ProductGroup"

JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
BUTTON_OPEN_RE = re.compile(r"<button\b[^>]*>", re.IGNORECASE)
BUTTON_CLOSE_RE = re.compile(r"</button\s*>", re.IGNORECASE)
TAX_INCLUDED_RE = re.compile(r"(?i)\b(?:iva|impuestos?)\s+incluid[oa]s?\b")
TAX_EXCLUDED_RE = re.compile(r"(?i)\b(?:iva|impuestos?)\s+(?:no\s+incluid[oa]s?|excluid[oa]s?)\b")
PRICE_TEXT_RE = re.compile(r"(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{1,2}))?")

# Description/specification containers, in the order they appear on the page.
DESCRIPTION_CONTAINERS = (
    ("product_description", "body"),
    ("model_specifications", "specs"),
    ("product_specifications", "specs"),
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
    row: dict[str, Any]
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
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def parse_jsonld_blocks(raw: str) -> tuple[list[Any], int]:
    """Return (payloads, unparsable_block_count)."""

    payloads: list[Any] = []
    unparsable = 0
    for match in JSONLD_RE.finditer(raw):
        text = match.group(1).strip()
        if not text:
            continue
        try:
            payloads.append(json.loads(text))
        except json.JSONDecodeError:
            unparsable += 1
    return payloads, unparsable


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


def _first_offer(offers: Any) -> dict[str, Any] | None:
    if isinstance(offers, dict):
        return offers
    if isinstance(offers, list):
        for item in offers:
            if isinstance(item, dict):
                return item
    return None


def _schema_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.rsplit("/", 1)[-1]


def parse_price_text(value: str | None) -> Decimal | None:
    """Parse a Spanish-format price such as ``1.234,95 €``.

    The site renders the price with the locale's decimal comma and dot
    thousands separator.  Nothing is guessed when the text has no digits.
    """

    if not value:
        return None
    text = value.replace("\u00a0", " ").replace("\u202f", " ").strip()
    match = PRICE_TEXT_RE.search(text)
    if not match:
        return None
    # The page is served in es-ES, where "." groups thousands and "," separates
    # decimals.  A separator left unconsumed right after the integer part is
    # therefore ambiguous (for example "19.95"), and guessing would either
    # truncate the amount or multiply it; return no price instead.
    tail = text[match.end() :]
    if tail.startswith((".", ",")):
        return None
    integer = match.group(1).replace(".", "")
    decimals = match.group(2) or "0"
    try:
        amount = Decimal(f"{integer}.{decimals}")
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def _variant_records(group: dict[str, Any] | None, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one dict per purchasable variant, with its offer fields."""

    records: list[dict[str, Any]] = []
    variants: list[dict[str, Any]] = []
    if group:
        raw_variants = group.get("hasVariant")
        if isinstance(raw_variants, list):
            variants = [item for item in raw_variants if isinstance(item, dict)]
    if not variants:
        variants = products[:1]
    for variant in variants:
        offer = _first_offer(variant.get("offers"))
        amount: Decimal | None = None
        currency = ""
        availability = ""
        if offer:
            raw_price = offer.get("price")
            if raw_price not in (None, ""):
                try:
                    candidate = Decimal(str(raw_price))
                except (InvalidOperation, ValueError):
                    candidate = None
                if candidate is not None and candidate.is_finite():
                    amount = candidate
            raw_currency = offer.get("priceCurrency")
            if isinstance(raw_currency, str):
                currency = raw_currency.strip().upper()
            availability = _schema_name(offer.get("availability"))
        records.append(
            {
                "sku": variant.get("sku"),
                "mpn": variant.get("mpn"),
                "name": variant.get("name"),
                "size": (variant.get("size") or "").strip() if isinstance(variant.get("size"), str) else "",
                "color": (variant.get("color") or "").strip() if isinstance(variant.get("color"), str) else "",
                "price": amount,
                "currency": currency,
                "availability": availability,
                "image": variant.get("image"),
            }
        )
    return records


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


def _clean_name(value: str | None) -> str:
    if not value:
        return ""
    name = re.sub(r"\s+", " ", value).strip()
    name = re.sub(
        r"\s*[|–—,-]\s*(?:www\.)?skatepro\.es\s*$", "", name, flags=re.IGNORECASE
    )
    name = re.sub(r"(?:www\.)?skatepro\.es", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^[\s|–—,-]+|[\s|–—,-]+$", "", name)
    return name.strip()


def _category_path(group: dict[str, Any] | None, products: list[dict[str, Any]], selector: Selector) -> list[str]:
    raw = ""
    if group and isinstance(group.get("category"), str):
        raw = group["category"]
    if not raw:
        for product in products:
            if isinstance(product.get("category"), str) and product["category"].strip():
                raw = product["category"]
                break
    if raw:
        return [part.strip() for part in raw.split(">") if part.strip()]
    names = []
    for li in selector.css("nav.breadcrumb li"):
        text = re.sub(r"\s+", " ", "".join(li.css("::text").getall())).strip()
        if text and text.casefold() not in {"atrás", "inicio"}:
            names.append(text)
    return names


def _select_category(path: list[str]) -> str:
    for candidate in reversed(path):
        if candidate.casefold() not in GENERIC_CATEGORIES:
            return candidate
    return ""


def _option_values(records: list[dict[str, Any]], selector: Selector) -> dict[str, list[str]]:
    """Build public option dimensions from the variant records.

    A dimension with a single value is not a choice, so single-value
    dimensions are dropped unless the page renders a size selector with more
    than one row.  Quantity groups never exist on this site and price deltas are
    not printed next to the values.
    """

    resulting: dict[str, list[str]] = {}

    def add(name: str, values: list[str]) -> None:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            value = re.sub(r"\s+", " ", value).strip()
            if not value:
                continue
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(value)
        if cleaned:
            resulting[name] = cleaned

    size_label = "Talla"
    for element in selector.css(".selected_variant_size"):
        label = element.attrib.get("data-size_name")
        if label and label.strip():
            size_label = label.strip()
            break

    sizes = [record["size"] for record in records if record["size"]]
    if len(sizes) < 2:
        dom_sizes = [
            (row.attrib.get("aria-label") or "").strip()
            for row in selector.css(".pi_size_selector .variant_selector_row")
        ]
        dom_sizes = [value for value in dom_sizes if value]
        if len(dom_sizes) >= 2:
            sizes = dom_sizes
    add(size_label, sizes)
    add("Color", [record["color"] for record in records if record["color"]])
    return {
        name: values
        for name, values in resulting.items()
        if len(values) >= 2 or name != "Color"
    }


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


def _unwrap_buttons(fragment: str) -> str:
    """Turn ``<button>label</button>`` into ``<span>label</span>``.

    Specification labels and values on this site are rendered inside
    ``button.spec_desc_button`` elements.  The cleaner removes buttons (they are
    controls), so their text would be lost; unwrapping keeps the label while
    still discarding the control.
    """

    if not fragment:
        return fragment
    fragment = BUTTON_OPEN_RE.sub("<span>", fragment)
    fragment = BUTTON_CLOSE_RE.sub("</span>", fragment)
    return fragment


def _section_heading(element: Any) -> str:
    section = element.xpath("ancestor::section[1]")
    if not section:
        return ""
    direct = section[0].xpath("./h2/text()").getall()
    return re.sub(r"\s+", " ", " ".join(direct)).strip()


def _description(selector: Selector, jsonld_description: str) -> dict[str, Any]:
    """Assemble the description from the body block and the specification blocks."""

    parts: list[str] = []
    sources: list[str] = []
    empty_hits: list[str] = []
    seen_text: set[str] = set()
    body_present = False
    specs_present = False
    container_found = False

    for container_id, kind in DESCRIPTION_CONTAINERS:
        elements = selector.css(f"#{container_id}")
        if not elements:
            continue
        container_found = True
        element = elements[0]
        raw_html = element.get() or ""
        text = re.sub(r"\s+", " ", element.xpath("string(.)").get() or "").strip()
        if not text:
            empty_hits.append(container_id)
            continue
        cleaned = clean_html_fragment(_unwrap_buttons(raw_html))
        cleaned_text = html_to_text(cleaned)
        if not cleaned_text:
            if kind == "body":
                raise ProductFailed(
                    "DESCRIPTION_CLEAN_FAILED",
                    f"Container #{container_id} had text but cleaned to empty.",
                )
            empty_hits.append(container_id)
            continue
        if cleaned_text in seen_text:
            continue
        seen_text.add(cleaned_text)
        heading = _section_heading(element)
        block = f"<p><strong>{heading}</strong></p>" if heading else ""
        parts.append(block + cleaned)
        sources.append(container_id)
        if kind == "body":
            body_present = True
        else:
            specs_present = True

    description_html = "".join(parts)
    if body_present:
        return {
            "html": description_html,
            "source": "+".join(sources),
            "status": "complete",
            "partial_reason": "",
            "missing_reasons": {},
            "empty_hits": empty_hits,
        }
    if specs_present:
        return {
            "html": description_html,
            "source": "+".join(sources),
            "status": "partial",
            "partial_reason": (
                "The page has no body description block; only the specification "
                "blocks (" + ", ".join(sources) + ") were available."
            ),
            "missing_reasons": {},
            "empty_hits": empty_hits,
        }
    if jsonld_description.strip():
        cleaned = clean_html_fragment(jsonld_description)
        return {
            "html": cleaned,
            "source": "jsonld.description",
            "status": "fallback",
            "partial_reason": "",
            "missing_reasons": {"description_html": "JSONLD_FALLBACK"},
            "empty_hits": empty_hits,
        }
    if container_found and empty_hits:
        return {
            "html": "",
            "source": "empty_description_container",
            "status": "not_provided",
            "partial_reason": "",
            "missing_reasons": {"description_html": "SOURCE_HAS_NO_DESCRIPTION"},
            "empty_hits": empty_hits,
        }
    raise ProductFailed(
        "DESCRIPTION_BLOCK_NOT_FOUND",
        "No description container, specification container or JSON-LD description.",
    )


def _tax_basis(raw: str) -> str:
    if TAX_INCLUDED_RE.search(raw):
        return "INCLUSIVE"
    if TAX_EXCLUDED_RE.search(raw):
        return "EXCLUSIVE"
    return "UNKNOWN"


SCHEMA_AVAILABILITY = {
    "instock": "in_stock",
    "limitedavailability": "in_stock",
    "onlineonly": "in_stock",
    "instoreonly": "in_stock",
    "outofstock": "out_of_stock",
    "soldout": "out_of_stock",
    "discontinued": "out_of_stock",
    "preorder": "preorder",
    "presale": "preorder",
    "backorder": "backorder",
}
DOM_AVAILABILITY = (
    ("disponible", "in_stock"),
    ("en stock", "in_stock"),
    ("agotado", "out_of_stock"),
    ("sin stock", "out_of_stock"),
    ("reserv", "preorder"),
    ("próximamente", "preorder"),
    ("proximamente", "preorder"),
)


def _schema_availability(values: list[str]) -> str:
    """Map schema.org availability names published by the variant offers."""

    states = [
        SCHEMA_AVAILABILITY.get(value.lower().rsplit("/", 1)[-1], "")
        for value in values
    ]
    states = [state for state in states if state]
    if not states:
        return ""
    if any(state == "in_stock" for state in states):
        return "in_stock"
    if all(state == "out_of_stock" for state in states):
        return "out_of_stock"
    # Mixed pre-order/back-order states: report the most actionable one.
    if "preorder" in states:
        return "preorder"
    if "backorder" in states:
        return "backorder"
    return states[0]


def _dom_availability(selector: Selector) -> tuple[str, str]:
    """Read the visible stock line when the structured data has no state.

    ``.urgency[data-stockcode]`` is rendered server-side for every purchasable
    variant ("Disponible (5+ pares)", "Agotado", ...).  Only the visible text of
    the selected variant row is used, and only as a fallback.
    """

    for element in selector.css(".urgency_text .urgency"):
        text = re.sub(r"\s+", " ", element.xpath("string(.)").get() or "").strip().lower()
        if not text or element.attrib.get("style", "").replace(" ", "").startswith(
            "display:none"
        ):
            continue
        for needle, state in DOM_AVAILABILITY:
            if needle in text:
                return state, text
    return "", ""


def _primary_image(selector: Selector, group: dict[str, Any] | None, records: list[dict[str, Any]], page_url: str) -> tuple[str | None, str]:
    candidates: list[tuple[str, str]] = []
    # The lightbox href is the un-resized original.
    for element in selector.css(".pi_main_image [data-href]"):
        value = element.attrib.get("data-href")
        if value:
            candidates.append((value, "pi_main_image.data_href"))
    og_image = selector.css('meta[property="og:image"]::attr(content)').get()
    if og_image:
        candidates.append((og_image, "og:image"))
    if group:
        images = group.get("image")
        if isinstance(images, str):
            candidates.append((images, "jsonld.image"))
        elif isinstance(images, list):
            for item in images:
                if isinstance(item, str):
                    candidates.append((item, "jsonld.image[]"))
                    break
    for record in records:
        images = record.get("image")
        if isinstance(images, str):
            candidates.append((images, "jsonld.variant.image"))
            break
        if isinstance(images, list):
            for item in images:
                if isinstance(item, str):
                    candidates.append((item, "jsonld.variant.image[]"))
                    break
            break
    for value, source in candidates:
        resolved = resolve_image_url(value, page_url)
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
    payloads, unparsable = parse_jsonld_blocks(raw_html)

    group: dict[str, Any] | None = None
    products: list[dict[str, Any]] = []
    for payload in payloads:
        for obj in _iter_objects(payload):
            types = _type_names(obj.get("@type"))
            if PRODUCT_GROUP_TYPE in types and group is None:
                group = obj
            elif "Product" in types:
                products.append(obj)

    if group is None and not products:
        raise ProductFailed(
            "PRODUCT_JSONLD_MISSING",
            "No ProductGroup or Product JSON-LD block was found; "
            f"{unparsable} block(s) were unparsable.",
        )

    base = group or products[0]
    records = _variant_records(group, products)
    if not records:
        raise ProductFailed("PRODUCT_VARIANTS_MISSING", "No purchasable variant entry.")

    name = _clean_name(
        (base.get("name") if isinstance(base.get("name"), str) else None)
        or selector.css("h1 span::text").get()
        or selector.css("h1::text").get()
    )
    if not name:
        raise ProductFailed("NAME_MISSING", "No product name in JSON-LD or h1.")

    # ---- price: lowest positive variant price, variants included even when
    # ---- out of stock.  Strikethrough prices are never read.
    priced = [record for record in records if record["price"] is not None]
    positive = [record for record in priced if record["price"] and record["price"] > 0]
    if not positive:
        zero = sum(1 for record in priced if record["price"] == 0)
        negative = sum(1 for record in priced if record["price"] is not None and record["price"] < 0)
        if zero:
            raise ProductExcluded("ZERO_PRICE", f"All {zero} variant price(s) were zero.")
        if negative:
            raise ProductExcluded("NEGATIVE_PRICE", f"{negative} variant price(s) were negative.")
        raise ProductExcluded(
            "NO_PRICE",
            f"No finite positive price across {len(records)} variant(s).",
        )
    chosen = min(positive, key=lambda record: record["price"])
    price_amount: Decimal = chosen["price"]

    currencies = {record["currency"] for record in priced if record["currency"]}
    if not chosen["currency"]:
        raise ProductFailed(
            "CURRENCY_EVIDENCE_MISSING",
            "The chosen variant offer carried no priceCurrency.",
        )
    if len(currencies) > 1:
        raise ProductFailed(
            "CURRENCY_CONFLICT",
            f"Variant offers disagree on currency: {sorted(currencies)}",
        )
    currency = chosen["currency"]
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ProductFailed("CURRENCY_INVALID", f"Not an ISO code: {currency!r}")
    if currency != CURRENCY:
        raise ProductExcluded(
            "CURRENCY_NOT_TARGET",
            f"Expected {CURRENCY} for the ES task, got {currency}.",
        )

    # ---- the rendered selling price must corroborate the structured offer.
    displayed_text = selector.css(".product_prices .pi_price .price::text").get()
    displayed = parse_price_text(displayed_text)
    variant_amounts = {record["price"].quantize(Decimal("0.01")) for record in priced}
    display_matches = (
        displayed is not None
        and price_amount.quantize(Decimal("0.01")) == displayed.quantize(Decimal("0.01"))
    )
    display_in_variants = (
        displayed is not None and displayed.quantize(Decimal("0.01")) in variant_amounts
    )
    if displayed is not None and not display_in_variants:
        raise ProductFailed(
            "PRICE_EVIDENCE_CONFLICT",
            f"Rendered price {displayed} is not one of the variant prices "
            f"{sorted(str(value) for value in variant_amounts)}.",
        )

    og_locale = selector.css('meta[property="og:locale"]::attr(content)').get() or ""
    html_lang = selector.css("html::attr(lang)").get() or ""
    if og_locale and not og_locale.lower().startswith("es"):
        raise ProductExcluded(
            "LOCALE_MISMATCH", f"og:locale was {og_locale!r} for the es-ES task."
        )
    if html_lang and not html_lang.lower().startswith("es"):
        raise ProductExcluded(
            "LOCALE_MISMATCH", f"html lang was {html_lang!r} for the es-ES task."
        )

    image_url, image_source = _primary_image(selector, group, records, page_url)
    if not image_url:
        raise ProductFailed("PRIMARY_IMAGE_MISSING", "No usable product image URL.")

    # ---- description: body + specification blocks in page order.
    jsonld_description = ""
    if isinstance(base.get("description"), str):
        jsonld_description = base["description"]
    description = _description(selector, jsonld_description)

    options = _option_values(records, selector)
    attributes = serialize_options(options)

    category_list = _category_path(group, products, selector)
    category = _select_category(category_list)

    brand = _brand(base.get("brand"))
    if not brand:
        brand = _clean_name(selector.css("#brand_name::text").get())
        if brand.casefold() in STORE_BRAND_NAMES:
            brand = ""

    availability_values = [record["availability"] for record in records if record["availability"]]
    availability = _schema_availability(availability_values)
    availability_source = "jsonld.offer.availability" if availability else ""
    dom_availability_text = ""
    if not availability:
        availability, dom_availability_text = _dom_availability(selector)
        if availability:
            availability_source = ".urgency[data-stockcode] visible text"

    canonical = selector.css('link[rel="canonical"]::attr(href)').get()
    source_url = normalize_url(canonical or page_url)

    tax_basis = _tax_basis(raw_html)

    missing_reasons: dict[str, str] = dict(description["missing_reasons"])
    if not options:
        missing_reasons["options"] = "NO_MEANINGFUL_OPTIONS"
    if not brand:
        missing_reasons["brand"] = "BRAND_NOT_PROVIDED"
    if not category:
        missing_reasons["categories"] = "CATEGORY_NOT_FOUND"
    if not availability:
        missing_reasons["availability"] = "AVAILABILITY_NOT_PROVIDED"
    tax_basis_note = "NOT_SPECIFIED_BY_SOURCE" if tax_basis == "UNKNOWN" else ""

    description_format = ""
    if description["html"]:
        description_format = "html"

    row: dict[str, Any] = {
        "name": name,
        "price_amount": f"{price_amount.quantize(Decimal('0.01')):.2f}",
        "price_currency": currency,
        "primary_image_url": image_url,
        "description_html": description["html"],
        "category": category,
        "brand": brand,
        "attributes": attributes,
        "source_url": source_url,
        "description_format": description_format,
        "description_status": description["status"],
        "partial_reason": description["partial_reason"],
        "missing_reasons": missing_reasons,
        "category_path": category_list,
        "market": market,
        "locale": locale,
        "availability": availability,
        "availability_source": availability_source,
        "tax_basis": tax_basis,
        "tax_basis_note": tax_basis_note,
        "price_basis": (
            "lowest_public_current_variant_price"
            if len(records) > 1
            else "single_public_current_price"
        ),
        "extracted_at": extracted_at,
        "variant_count": len(records),
    }

    evidence: dict[str, Any] = {
        "jsonld_group_present": group is not None,
        "jsonld_product_count": len(products),
        "jsonld_unparsable_blocks": unparsable,
        "variant_count": len(records),
        "variant_prices": [
            {
                "sku": record["sku"],
                "size": record["size"],
                "color": record["color"],
                "price": str(record["price"]) if record["price"] is not None else None,
                "currency": record["currency"],
                "availability": record["availability"],
            }
            for record in records
        ],
        "chosen_variant": {
            "sku": chosen["sku"],
            "size": chosen["size"],
            "color": chosen["color"],
            "price": str(price_amount),
        },
        "price_currency": currency,
        "displayed_price_text": displayed_text,
        "displayed_price": str(displayed) if displayed is not None else None,
        "displayed_price_matches_chosen": display_matches,
        "price_specification_ignored": True,
        "image_source": image_source,
        "description_source": description["source"],
        "description_status": description["status"],
        "description_empty_containers": description["empty_hits"],
        "description_length": len(description["html"]),
        "description_text_length": len(html_to_text(description["html"])),
        "category_path": category_list,
        "og_locale": og_locale,
        "html_lang": html_lang,
        "tax_basis": tax_basis,
        "option_dimensions": options,
        "availability_values": availability_values,
        "availability_source": availability_source,
        "dom_availability_text": dom_availability_text,
    }
    return ProductResult(row=row, evidence=evidence)
