"""Field normalization for the skatepro.es Scrapy trial.

Rules are deliberately independent from Scrapy so they can be tested with
plain fixtures.  They map a product page (JSON-LD + server-rendered DOM +
the public ``php2js`` product payload) to the data contract in docs/02.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable

from lxml import etree
from lxml import html as lxml_html

PLAN_ID = "skatepro-es-scrapy"
PLAN_VERSION = "2026.11.19-2"

# docs/02 (round 2): the business CSV has exactly these 9 columns.
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

#: Attributes that describe a fixed product property, not a purchase choice.
#: A dimension with a single value is a specification, not an option.
_MIN_OPTION_VALUES = 2


class NormalizationError(ValueError):
    """Raised when a required field cannot be produced without guessing."""


def clean_name(raw: Any) -> str:
    """Clean the product title without inventing or deleting unknown brand words."""
    name = html_lib.unescape(str(raw or ""))
    name = re.sub(r"\s+", " ", name).strip()
    # Only remove an explicit store suffix, never a generic trailing word.
    name = re.sub(r"\s*[|｜]\s*SkatePro\s*$", "", name, flags=re.IGNORECASE).strip()
    return name


def parse_php2js(text: str) -> dict[str, Any] | None:
    """Read the server-rendered ``php2js`` product payload.

    The payload is a JSON object literal assigned to a JS variable.  It stays a
    public, non-authenticated response field; the rule never looks at private
    endpoints.  Returns ``None`` when the assignment is absent or malformed.
    """
    marker = text.find("php2js = ")
    if marker < 0:
        return None
    start = text.find("{", marker)
    if start < 0:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(text[start:])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def product_variants(php2js: dict[str, Any] | None, product_id: str) -> list[dict[str, Any]]:
    """Return the public variant list for one product id."""
    if not php2js:
        return []
    products = php2js.get("product") or {}
    if not isinstance(products, dict):
        return []
    record = products.get(str(product_id)) or {}
    variants = record.get("variants") or {}
    if not isinstance(variants, dict):
        return []
    return [v for v in variants.values() if isinstance(v, dict)]


def _price_decimal(raw: Any) -> Decimal | None:
    if raw is None or isinstance(raw, bool):
        return None
    text = str(raw).strip().replace("\u00a0", "").replace("\u202f", "")
    if not text or not re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", text):
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def lowest_positive_variant_price(
    variants: Iterable[dict[str, Any]] | None,
) -> tuple[Decimal | None, str | None, dict[str, Any]]:
    """Return the lowest public variant price, including unavailable variants.

    Zero or negative values are business exclusions, not values to skip.
    Invalid price strings are reported separately and never converted to 0.
    """
    parsed: list[Decimal] = []
    invalid: list[str] = []
    for variant in variants or []:
        raw = (variant or {}).get("price_number")
        value = _price_decimal(raw)
        if value is None:
            if raw is not None:
                invalid.append(str(raw))
            continue
        parsed.append(value)

    if not parsed:
        reason = "invalid_price" if invalid else "no_public_price"
        return None, reason, {"variant_count": 0, "invalid_variant_prices": invalid}
    lowest = min(parsed)
    if lowest <= 0:
        return None, "non_positive_price", {
            "variant_count": len(parsed),
            "lowest_variant_price": str(lowest),
            "invalid_variant_prices": invalid,
        }
    amount = lowest.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return amount, None, {
        "variant_count": len(parsed),
        "invalid_variant_prices": invalid,
        "price_source": "php2js_variants.price_number",
    }


def format_price(amount: Decimal) -> str:
    return format(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _escape_attribute_part(value: str) -> str:
    return value.replace("\\", "\\\\").replace("#", "\\#").replace("|", "\\|").replace("~", "\\~")


def collect_options(
    variants: Iterable[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Group public variant dimensions and values.

    Returns ``(groups, skipped_dimensions)``.  Dimensions with a single public
    value are specifications (for example one fixed deck height), not choices,
    so they are reported as skipped instead of being exported as options.
    """
    order: list[str] = []
    display: dict[str, str] = {}
    values: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for variant in variants or []:
        names = (variant or {}).get("attribute_text") or {}
        picks = (variant or {}).get("attribute_variant_text") or {}
        if not isinstance(names, dict) or not isinstance(picks, dict):
            continue
        for attr_id, name in names.items():
            name = str(name or "").strip()
            if not name or name.casefold() in _QUANTITY_OPTION_NAMES:
                continue
            value = str(picks.get(attr_id) or "").strip()
            value = _PRICE_DELTA_RE.sub("", value).strip()
            if not value:
                continue
            key = name.casefold()
            if key not in values:
                order.append(key)
                display[key] = name
                values[key] = []
                seen[key] = set()
            if value.casefold() in seen[key]:
                continue
            seen[key].add(value.casefold())
            values[key].append(value)

    groups: list[dict[str, Any]] = []
    skipped: list[str] = []
    for key in order:
        if len(values[key]) < _MIN_OPTION_VALUES:
            skipped.append(display[key])
            continue
        groups.append({"name": display[key], "values": values[key]})
    return groups, skipped


def serialize_options(options: Iterable[dict[str, Any]] | None) -> str:
    """Serialize public options as ``Size#S|M~Color#Red`` (docs/02)."""
    groups: list[str] = []
    for option in options or []:
        name = str((option or {}).get("name") or "").strip()
        values = [str(v).strip() for v in (option or {}).get("values") or [] if str(v).strip()]
        if not name or not values:
            continue
        groups.append(
            f"{_escape_attribute_part(name)}#{'|'.join(_escape_attribute_part(v) for v in values)}"
        )
    return "~".join(groups)


def product_offers(product: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return the offer objects for a Product or ProductGroup page.

    Variable products are emitted as ``ProductGroup`` with ``hasVariant``
    children; fixed products carry ``offers`` directly.
    """
    product = product or {}
    offers = product.get("offers")
    if isinstance(offers, dict):
        return [offers]
    if isinstance(offers, list):
        return [o for o in offers if isinstance(o, dict)]
    collected: list[dict[str, Any]] = []
    for variant in product.get("hasVariant") or []:
        if not isinstance(variant, dict):
            continue
        variant_offers = variant.get("offers")
        if isinstance(variant_offers, dict):
            collected.append(variant_offers)
        elif isinstance(variant_offers, list):
            collected.extend(o for o in variant_offers if isinstance(o, dict))
    return collected


def _variant_images(product: dict[str, Any] | None) -> list[str]:
    images: list[str] = []
    for variant in (product or {}).get("hasVariant") or []:
        if not isinstance(variant, dict):
            continue
        image = variant.get("image")
        if isinstance(image, str):
            image = [image]
        for src in image or []:
            src = str(src or "").strip()
            if src:
                images.append(src)
    return images


def availability_from_offer(
    product: dict[str, Any] | None, variants: Iterable[dict] | None
) -> str:
    tails: set[str] = set()
    for offer in product_offers(product):
        raw = str((offer or {}).get("availability") or "").strip()
        if raw:
            tails.add(raw.rsplit("/", 1)[-1].casefold())
    if "instock" in tails:
        return "in_stock"
    if tails & {"outofstock", "soldout"}:
        return "out_of_stock"
    if tails & {"preorder", "backorder"}:
        return "preorder"
    levels = {
        str((v or {}).get("stock_level") or "").strip().casefold()
        for v in variants or []
        if str((v or {}).get("stock_level") or "").strip()
    }
    if levels & {"green", "green_soon", "yellow"}:
        return "in_stock"
    if levels & {"red"}:
        return "out_of_stock"
    return ""


def _remove_node(node: etree._Element) -> None:
    parent = node.getparent()
    if parent is not None:
        parent.remove(node)


def _normalize_text_nodes(root: etree._Element) -> None:
    for node in root.iter():
        if node.text:
            node.text = _SPACE_RE.sub(" ", _URL_RE.sub("", node.text))
        if node.tail:
            node.tail = _SPACE_RE.sub(" ", _URL_RE.sub("", node.tail))


def _dump_inner_html(root: etree._Element) -> str:
    return "".join(
        [root.text or ""]
        + [lxml_html.tostring(child, encoding="unicode", method="html") for child in root]
    ).strip()


def clean_html_fragment(raw: Any) -> str:
    """Clean one HTML fragment with a tag allow-list and drop presentation."""
    body = "" if raw is None else str(raw)
    if not body.strip():
        return ""
    try:
        root = lxml_html.fragment_fromstring(body, create_parent="div")
    except (etree.ParserError, ValueError) as exc:
        raise NormalizationError(f"description_parse_error: {exc}") from exc

    for comment in root.xpath("//comment()"):
        _remove_node(comment)
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
        for attr in list(node.attrib):
            if tag in ("td", "th") and attr.lower() in _KEEP_TABLE_ATTRS:
                continue
            del node.attrib[attr]

    _normalize_text_nodes(root)

    for node in reversed(list(root.iterdescendants())):
        if not isinstance(node.tag, str):
            continue
        tag = node.tag.lower()
        if tag in ("br", "td", "th", "tr", "tbody", "thead"):
            continue
        if len(node) == 0 and not (node.text or "").strip():
            _remove_node(node)

    return _dump_inner_html(root)


def _text_of(raw_html: str) -> str:
    if not raw_html:
        return ""
    return lxml_html.fragment_fromstring(raw_html, create_parent="div").text_content().strip()


def extract_spec_table(doc: etree._Element) -> tuple[str, int]:
    """Build a clean two-column table from ``#product_specifications`` rows."""
    rows = doc.xpath("//div[@id='product_specifications']/div[contains(@class,'row')]")
    body: list[str] = []
    for row in rows:
        columns = row.xpath("./div")
        if len(columns) < 2:
            continue
        label = " ".join(columns[0].text_content().split()).strip()
        value = " ".join(columns[1].text_content().split()).strip()
        if not label or not value:
            continue
        body.append(
            "<tr><td>"
            + html_lib.escape(label.rstrip(":").strip())
            + "</td><td>"
            + html_lib.escape(value)
            + "</td></tr>"
        )
    if not body:
        return "", 0
    return "<table><tbody>" + "".join(body) + "</tbody></table>", len(body)


def build_description(doc: etree._Element) -> tuple[str, str, str, dict[str, Any]]:
    """Return ``(html, status, partial_reason, details)``.

    Status semantics follow docs/02: a product page that carries both the
    editorial description and the specification table is ``complete``; one of
    the two missing is ``partial``; a page that exposes neither container is
    ``not_provided`` (the template proves the section is absent).
    """
    desc_nodes = doc.xpath("//div[@id='product_description']")
    spec_table, spec_rows = extract_spec_table(doc)

    description_html = ""
    if desc_nodes:
        description_html = clean_html_fragment(_dump_inner_html(desc_nodes[0]))
    description_text = _text_of(description_html)

    details = {
        "description_container": bool(desc_nodes),
        "spec_rows": spec_rows,
    }

    if not description_text and not spec_rows:
        if not desc_nodes and not doc.xpath("//div[@id='product_specifications']"):
            return "", "not_provided", "", details
        return "", "failed", "description_containers_present_but_empty", details

    parts = [p for p in (description_html, spec_table) if p]
    combined = "\n".join(parts)

    if description_text and spec_rows:
        return combined, "complete", "", details
    if description_text:
        return combined, "partial", "specifications_section_missing_or_empty", details
    return combined, "partial", "editorial_description_section_missing", details


def normalize_category(product: dict[str, Any], doc: etree._Element) -> str:
    category = str(product.get("category") or "").strip()
    if category:
        parts = [p.strip() for p in re.split(r"\s*(?:>|›)\s*", category) if p.strip()]
        generic = {"home", "inicio", "shop", "tienda", "all", "productos"}
        parts = [p for p in parts if p.casefold() not in generic]
        if parts:
            return " > ".join(parts)
    crumbs = [
        " ".join(a.text_content().split()).strip()
        for a in doc.xpath("//nav[contains(@class,'breadcrumb')]//a")
    ]
    crumbs = [c for c in crumbs if c and c.casefold() not in {"inicio", "home", "atrás", "atras"}]
    return " > ".join(crumbs[-2:]) if crumbs else ""


def normalize_brand(product: dict[str, Any]) -> str:
    """Return the brand the page states; never infer it from the store domain."""
    brand = product.get("brand") or {}
    name = str(brand.get("name") if isinstance(brand, dict) else brand).strip()
    return " ".join(name.split())


def primary_image(product: dict[str, Any]) -> str:
    image = product.get("image")
    if isinstance(image, str):
        image = [image]
    candidates = list(image or []) + _variant_images(product)
    for src in candidates:
        src = str(src or "").strip()
        if not src:
            continue
        if src.startswith("//"):
            src = "https:" + src
        if src.startswith("http://"):
            src = "https://" + src[len("http://") :]
        return src
    return ""


def currency_evidence(doc: etree._Element, product: dict[str, Any]) -> tuple[str, str]:
    """Return ``(code, evidence)`` from the same public quote object(s).

    The ISO code is only accepted when it is bound to the same offer value(s);
    a ``€`` glyph alone is never used.  Variable products repeat the currency
    on every variant offer, so a single distinct code across offers is required.
    """
    offers = product_offers(product)
    codes = {
        str((offer or {}).get("priceCurrency") or "").strip().upper()
        for offer in offers
        if str((offer or {}).get("priceCurrency") or "").strip()
    }
    if len(codes) == 1:
        code = codes.pop()
        if re.fullmatch(r"[A-Z]{3}", code):
            prices = [offer.get("price") for offer in offers if offer.get("price") is not None]
            return code, (
                "json_ld offers.priceCurrency="
                f"{code} bound to {len(offers)} offer price(s) {prices[:4]}"
            )
    meta_code = (doc.xpath("//meta[@property='product:sale_price:currency']/@content") or [""])[0].strip().upper()
    meta_amount = (doc.xpath("//meta[@property='product:sale_price:amount']/@content") or [""])[0].strip()
    if re.fullmatch(r"[A-Z]{3}", meta_code) and meta_amount:
        return meta_code, f"product meta sale_price {meta_amount} {meta_code}"
    return "", ""


def build_missing_reasons(
    *,
    description_status: str,
    category: str,
    brand: str,
) -> dict[str, str]:
    """Reasons for fields that are absent from the source itself.

    ``attributes`` is not listed here: an empty option set on a single-variant
    product is a real "no public choice", not a data gap, and it is recorded in
    the internal per-product record instead.
    """
    reasons: dict[str, str] = {}
    if description_status == "not_provided":
        reasons["description_html"] = "NOT_PROVIDED"
    elif description_status == "fallback":
        reasons["description_html"] = "SUMMARY_FALLBACK"
    elif description_status == "failed":
        reasons["description_html"] = "EXTRACTION_FAILED"
    if not category:
        reasons["category"] = "NOT_PROVIDED"
    if not brand:
        reasons["brand"] = "NOT_PROVIDED"
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
