"""Field normalization for the javaestate.com Scrapy trial.

The module is deliberately independent from Scrapy so its rules can be tested
with plain fixtures.  It maps the public Shopify catalog record to the data
contract in docs/02.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable

from lxml import etree
from lxml import html as lxml_html

PLAN_ID = "javaestate-scrapy-us"
PLAN_VERSION = "2026.11.19-1"

# docs/02: the CSV has exactly these 22 columns.
CSV_FIELDS = [
    "name",
    "price_amount",
    "price_currency",
    "primary_image_url",
    "description_html",
    "category",
    "brand",
    "attributes",
    "source_url",
    "description_format",
    "description_status",
    "partial_reason",
    "missing_reasons",
    "market",
    "locale",
    "availability",
    "tax_basis",
    "price_basis",
    "task_id",
    "plan_id",
    "plan_version",
    "extracted_at",
]

DESCRIPTION_STATUSES = ("complete", "partial", "fallback", "not_provided", "failed")

_DROP_TAGS = (
    "script",
    "style",
    "noscript",
    "template",
    "iframe",
    "frame",
    "form",
    "input",
    "button",
    "select",
    "textarea",
    "label",
    "img",
    "picture",
    "source",
    "video",
    "audio",
    "svg",
    "canvas",
    "object",
    "embed",
    "meta",
    "link",
    "base",
)

_KEEP_TABLE_ATTRS = {"colspan", "rowspan", "scope"}

_QUANTITY_OPTION_NAMES = {
    "quantity",
    "qty",
    "cantidad",
    "quantité",
    "quantite",
    "menge",
    "数量",
}

_PRICE_DELTA_RE = re.compile(
    r"\s*(?:[+＋]\s*(?:[€£$¥]\s*)?\d+(?:[.,]\d+)?"
    r"|(?:EUR|USD|GBP|CNY|RMB)\s*\d+(?:[.,]\d+)?)\s*$",
    re.IGNORECASE,
)

_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_SPACE_RE = re.compile(r"[ \t\r\f\v]+")
_BLANKLINE_RE = re.compile(r"\n{3,}")


class NormalizationError(ValueError):
    """Raised when a required field cannot be produced without guessing."""


def clean_name(raw: Any) -> str:
    """Clean the product title without inventing or deleting unknown brand words."""
    name = html_lib.unescape(str(raw or ""))
    name = re.sub(r"\s+", " ", name).strip()
    # Only remove an explicit store suffix, never a generic trailing word.
    name = re.sub(
        r"\s*(?:[|｜–—-]\s*Java Estate Roastery)\s*$",
        "",
        name,
        flags=re.IGNORECASE,
    ).strip()
    return name


def _price_decimal(raw: Any) -> Decimal | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    # Shopify catalog values are plain decimals.  Reject booleans and
    # values that would need a locale guess.
    if isinstance(raw, bool):
        return None
    text = text.replace("\u00a0", "").replace("\u202f", "")
    if not re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", text):
        return None
    # A single comma is accepted only when it is the decimal separator and
    # the source did not use a thousands separator.  Shopify emits dots.
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite():
        return None
    return value


def lowest_positive_variant_price(variants: Iterable[dict] | None) -> tuple[Decimal | None, str | None, dict]:
    """Return the lowest public variant price, including unavailable variants.

    A zero or negative minimum is a business exclusion, not a value to skip:
    docs/02 says the displayed minimum must be positive.  Invalid price strings
    are recorded separately and never converted to 0.
    """
    parsed: list[Decimal] = []
    invalid: list[str] = []
    for variant in variants or []:
        value = _price_decimal((variant or {}).get("price"))
        if value is None:
            raw = (variant or {}).get("price")
            if raw is not None:
                invalid.append(str(raw))
            continue
        parsed.append(value)

    if not parsed:
        reason = "invalid_price" if invalid else "no_public_price"
        return None, reason, {"invalid_variant_prices": invalid}
    lowest = min(parsed)
    if lowest <= 0:
        return None, "non_positive_price", {"lowest_variant_price": str(lowest)}
    amount = lowest.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return amount, None, {"variant_count": len(parsed), "invalid_variant_prices": invalid}


def format_price(amount: Decimal) -> str:
    """Format a positive decimal without thousands separators or exponents."""
    return format(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _escape_attribute_part(value: str) -> str:
    return value.replace("\\", "\\\\").replace("#", "\\#").replace("|", "\\|").replace("~", "\\~")


def serialize_options(options: Iterable[dict] | None) -> str:
    """Serialize public options as ``Name#A|B~Color#Red`` (docs/02)."""
    groups: list[tuple[str, list[str]]] = []
    seen_names: dict[str, int] = {}
    for option in options or []:
        name = str((option or {}).get("name") or "").strip()
        if not name or name.lower() in _QUANTITY_OPTION_NAMES:
            continue
        values: list[str] = []
        seen_values: set[str] = set()
        for raw_value in (option or {}).get("values") or []:
            value = _PRICE_DELTA_RE.sub("", str(raw_value)).strip()
            if not value:
                continue
            key = value.casefold()
            if key in seen_values:
                continue
            seen_values.add(key)
            values.append(value)
        if not values:
            continue
        if name.casefold() == "title" and values == ["Default Title"]:
            continue
        key = name.casefold()
        if key in seen_names:
            # Same option group repeated: merge values, keep first spelling.
            index = seen_names[key]
            existing = {v.casefold() for v in groups[index][1]}
            groups[index][1].extend(v for v in values if v.casefold() not in existing)
        else:
            seen_names[key] = len(groups)
            groups.append((name, values))
    if not groups:
        return ""
    return "~".join(
        f"{_escape_attribute_part(name)}#{'|'.join(_escape_attribute_part(v) for v in values)}"
        for name, values in groups
    )


def primary_image_url(product: dict) -> str:
    """Return the first product image, preferring the original Shopify URL."""
    for image in product.get("images") or []:
        src = str((image or {}).get("src") or "").strip()
        if not src:
            continue
        if src.startswith("//"):
            src = "https:" + src
        if src.startswith("http://"):
            src = "https://" + src[len("http://") :]
        return src
    return ""


def availability_from_variants(variants: Iterable[dict] | None) -> str:
    variants = list(variants or [])
    if not variants:
        return ""
    return "in_stock" if any(bool((v or {}).get("available")) for v in variants) else "out_of_stock"


def _remove_node(node: etree._Element) -> None:
    parent = node.getparent()
    if parent is not None:
        parent.remove(node)


def _normalize_text_nodes(root: etree._Element) -> None:
    for node in root.iter():
        if node.text:
            node.text = _URL_RE.sub("", node.text)
            node.text = _SPACE_RE.sub(" ", node.text)
        if node.tail:
            node.tail = _URL_RE.sub("", node.tail)
            node.tail = _SPACE_RE.sub(" ", node.tail)


def _dump_inner_html(root: etree._Element) -> str:
    parts = [root.text or ""]
    for child in root:
        parts.append(lxml_html.tostring(child, encoding="unicode", method="html"))
    return "".join(parts).strip()


def _clean_html_fragment(raw: str) -> str:
    root = lxml_html.fragment_fromstring(raw, create_parent="div")

    # Comments are not content.
    for comment in root.xpath("//comment()"):
        _remove_node(comment)

    # Admin-only bundle warnings must not be exported as product copy.
    for node in root.xpath(".//*[contains(@class, 'byob-bundle-description-warning')]"):
        _remove_node(node)

    etree.strip_elements(root, *_DROP_TAGS, with_tail=False)

    for anchor in root.xpath(".//a"):
        anchor.drop_tag()
    for inline in root.xpath(".//span | .//font | .//small | .//center"):
        inline.drop_tag()

    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        tag = node.tag.lower()
        if tag in ("h1", "h2"):
            node.tag = "h3"
        # Keep only table semantics; all other attributes are presentation.
        for attr in list(node.attrib):
            if tag in ("td", "th") and attr.lower() in _KEEP_TABLE_ATTRS:
                continue
            del node.attrib[attr]

    _normalize_text_nodes(root)

    # Remove tags that became empty after cleanup, keeping table cells and br.
    for node in reversed(list(root.iterdescendants())):
        if not isinstance(node.tag, str):
            continue
        tag = node.tag.lower()
        if tag in ("br", "td", "th", "tr", "tbody", "thead"):
            continue
        if len(node) == 0 and not (node.text or "").strip():
            _remove_node(node)

    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        text = (node.text or "").strip()
        if text:
            node.text = text if node.text is None else node.text
    return _dump_inner_html(root)


def clean_description(
    raw: Any,
    *,
    catalog_only: bool = True,
    page_status: int | None = None,
) -> tuple[str, str, str, str]:
    """Return ``(description, format, status, partial_reason)``.

    ``catalog_only`` is true when only the public catalog ``body_html`` was
    available.  In that case a non-empty description is marked ``partial``
    because page-only blocks (theme sections/metafields) were not verified.
    """
    body = "" if raw is None else str(raw)
    if not body.strip():
        return "", "", "not_provided", ""

    looks_like_html = bool(re.search(r"<\s*[a-zA-Z][^>]*>", body))
    if looks_like_html:
        try:
            cleaned = _clean_html_fragment(body)
        except (etree.ParserError, ValueError) as exc:
            raise NormalizationError(f"description_parse_error: {exc}") from exc
        text = (
            lxml_html.fragment_fromstring(cleaned, create_parent="div").text_content()
            if cleaned
            else ""
        )
        if not text.strip():
            return "", "", "not_provided", ""
        status = "partial" if catalog_only else "complete"
        reason = ""
        if status == "partial":
            status_note = f"product_html_http_{page_status}" if page_status else "product_html_not_fetched"
            reason = (
                f"{status_note}; description_source=products.json body_html; "
                "page-only theme blocks and metafields unverified"
            )
        return cleaned, "html", status, reason

    text = html_lib.unescape(body).replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _BLANKLINE_RE.sub("\n\n", text).strip()
    text = _URL_RE.sub("", text)
    if not text:
        return "", "", "not_provided", ""
    status = "partial" if catalog_only else "complete"
    reason = ""
    if status == "partial":
        status_note = f"product_html_http_{page_status}" if page_status else "product_html_not_fetched"
        reason = (
            f"{status_note}; description_source=products.json body_html; "
            "page-only theme blocks and metafields unverified"
        )
    return text, "text", status, reason


def normalize_category(product: dict) -> str:
    category = str(product.get("product_type") or "").strip()
    if category.casefold() in {"home", "shop", "all", "products"}:
        return ""
    return category


def normalize_brand(product: dict) -> str:
    vendor = str(product.get("vendor") or "").strip()
    if vendor.casefold() in {"", "byob"}:
        return ""
    return vendor


def build_missing_reasons(
    *,
    description_status: str,
    category: str,
    brand: str,
    attributes: str,
    availability: str,
) -> dict[str, str]:
    reasons: dict[str, str] = {}
    if description_status == "not_provided":
        reasons["description_html"] = "not_provided"
    if not category:
        reasons["category"] = "not_provided"
    if not brand:
        reasons["brand"] = "not_provided"
    if not attributes:
        reasons["attributes"] = "not_provided"
    if not availability:
        reasons["availability"] = "unknown"
    return reasons


def json_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def csv_safe(value: Any) -> Any:
    """Guard spreadsheet formula prefixes without touching numeric values."""
    if not isinstance(value, str):
        return value
    if value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def build_valid_row(
    *,
    product: dict,
    source_url: str,
    task_id: str,
    extracted_at: str,
    market: str = "US",
    locale: str = "en-US",
    currency: str = "USD",
) -> dict[str, str]:
    """Map a catalog product to the 22-column valid row.

    Raises ``NormalizationError`` for missing required identity fields; price
    failures are returned by the caller so they can be recorded as exclusions.
    """
    name = clean_name(product.get("title"))
    if not name:
        raise NormalizationError("name_missing_after_clean")

    image = primary_image_url(product)
    if not image:
        raise NormalizationError("primary_image_missing")

    handle = str(product.get("handle") or "").strip()
    if not handle:
        raise NormalizationError("handle_missing")

    description, description_format, description_status, partial_reason = clean_description(
        product.get("body_html"),
        catalog_only=True,
        page_status=429,
    )

    category = normalize_category(product)
    brand = normalize_brand(product)
    attributes = serialize_options(product.get("options"))
    availability = availability_from_variants(product.get("variants"))
    tax_basis = "NOT_STATED"

    missing = build_missing_reasons(
        description_status=description_status,
        category=category,
        brand=brand,
        attributes=attributes,
        availability=availability,
    )

    return {
        "name": name,
        "price_amount": "",  # filled by the caller after price validation
        "price_currency": currency,
        "primary_image_url": image,
        "description_html": description,
        "category": category,
        "brand": brand,
        "attributes": attributes,
        "source_url": source_url,
        "description_format": description_format,
        "description_status": description_status,
        "partial_reason": partial_reason,
        "missing_reasons": json_compact(missing),
        "market": market,
        "locale": locale,
        "availability": availability,
        "tax_basis": tax_basis,
        "price_basis": "lowest_public_current_variant_price",
        "task_id": task_id,
        "plan_id": PLAN_ID,
        "plan_version": PLAN_VERSION,
        "extracted_at": extracted_at,
    }
