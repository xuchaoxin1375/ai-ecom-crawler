"""Normalization helpers: names, money, descriptions, options and CSV safety."""

from __future__ import annotations

import html as html_module
import re
from decimal import Decimal, InvalidOperation
from typing import Iterable, Sequence

from lxml import html as lxml_html

WS_RE = re.compile(r"[\s\u00a0\u202f]+")
BARE_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
QUANTITY_NAMES = {
    "quantity",
    "qty",
    "cantidad",
    "quantité",
    "quantite",
    "menge",
    "数量",
}
PRICE_DELTA_RE = re.compile(
    r"\s*(?:\(?\+?\s*(?:[$€£¥]\s*\d[\d.,]*|(?:USD|EUR|GBP|CAD|AUD)\s*\d[\d.,]*)\s*\)?)\s*$",
    re.IGNORECASE,
)
SITE_SUFFIX_RE = re.compile(
    r"\s*(?:[|–—]\s*|\s+-\s+)(?:java estate roastery|java estate|javaestate\.com)\s*$",
    re.IGNORECASE,
)
DROP_TAGS = {
    "script",
    "style",
    "noscript",
    "template",
    "iframe",
    "video",
    "audio",
    "canvas",
    "svg",
    "form",
    "button",
    "input",
    "select",
    "textarea",
    "img",
    "picture",
    "source",
    "object",
    "embed",
}
UNWRAP_TAGS = {"a", "span", "div", "font", "u", "small", "label", "figure", "figcaption"}
ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "b",
    "em",
    "i",
    "ul",
    "ol",
    "li",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "th",
    "td",
    "dl",
    "dt",
    "dd",
    "blockquote",
    "code",
    "pre",
    "hr",
}
KEEP_ATTRS = {"colspan", "rowspan", "scope"}


def collapse_ws(value: str | None) -> str:
    if not value:
        return ""
    return WS_RE.sub(" ", html_module.unescape(str(value))).strip()


def clean_name(value: str | None) -> str:
    name = collapse_ws(value)
    if not name:
        return ""
    name = SITE_SUFFIX_RE.sub("", name).strip()
    name = re.sub(r"(?i)\b(?:www\.)?javaestate\.com\b", "", name).strip(" -–—|,;:")
    return collapse_ws(name)


def strip_price_delta(value: str) -> str:
    value = collapse_ws(value)
    return PRICE_DELTA_RE.sub("", value).strip()


def parse_positive_money(raw: object) -> Decimal | None:
    """Parse a public price string without guessing ambiguous separators.

    Only plain decimal forms with an optional single thousands separator are
    accepted; a lone separator followed by three digits is ambiguous and is
    rejected rather than guessed.
    """
    if raw is None or isinstance(raw, bool):
        return None
    text = str(raw).strip().replace("\u00a0", " ").replace("\u202f", " ")
    text = re.sub(r"\s+", "", text)
    text = text.replace("'", "").replace("’", "")
    if not text:
        return None
    # A lone separator followed by exactly three digits is ambiguous without
    # page/locale evidence; reject it instead of guessing thousands vs decimal.
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", text) or re.fullmatch(r"\d{1,3}(?:\.\d{3})+", text):
        return None
    match = re.fullmatch(r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", text)
    if match:
        normal = text.replace(",", "")
    else:
        match = re.fullmatch(r"(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?", text)
        if not match:
            return None
        if "," in text and "." in text:
            # 1.234,56 -> dots are thousands, comma is decimal
            normal = text.replace(".", "").replace(",", ".")
        elif "," in text:
            head, tail = text.rsplit(",", 1)
            if len(tail) == 3 and head.replace(".", "").isdigit() and "." not in head:
                return None  # ambiguous lone separator with three digits
            normal = text.replace(",", ".")
        else:
            normal = text
    try:
        value = Decimal(normal)
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite() or value <= 0:
        return None
    return value


def cents_to_amount(cents: int) -> Decimal:
    return (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))


def tax_basis_from_variants(variant_rows: Sequence[dict]) -> tuple[str, str]:
    """Derive a only-evidenced tax basis.

    Shopify's `taxable` flag says whether the product is taxed; it does not
    prove tax-inclusive pricing. A false value therefore supports
    `no_tax_applied`, while true values keep `unknown_not_stated`.
    """
    values = [row.get("taxable") for row in variant_rows if isinstance(row.get("taxable"), bool)]
    if not values:
        return "unknown_not_stated", "no_taxable_flag"
    if all(value is False for value in values):
        return "no_tax_applied", "embedded_variants_taxable_false"
    if all(value is True for value in values):
        return "unknown_not_stated", "embedded_variants_taxable_true_no_inclusive_evidence"
    return "mixed_taxability", "embedded_variants_mixed_taxable"


def format_amount(value: Decimal | str | int | float | None) -> str:
    if value is None or value == "":
        return ""
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ""
    if not dec.is_finite():
        return ""
    return f"{dec.quantize(Decimal('0.01')):.2f}"


def normalize_url_image(value: str | None) -> str:
    url = collapse_ws(value)
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    if not re.match(r"^https?://", url):
        return ""
    lowered = url.lower()
    if any(token in lowered for token in ("main-logo", "/logo", "logo.", "placeholder", "spacer.gif")):
        return ""
    return url


def _text_of(node: lxml_html.HtmlElement) -> str:
    return collapse_ws(node.text_content())


def sanitize_description(raw_html: str, *, fmt: str = "html") -> str:
    """Whitelist-clean a description fragment and drop unsafe or noisy markup."""
    if not raw_html or not raw_html.strip():
        return ""
    if fmt == "text":
        text = html_module.unescape(raw_html)
        text = BARE_URL_RE.sub("", text)
        return collapse_ws(text)

    try:
        wrapper = lxml_html.fragment_fromstring(raw_html, create_parent="div")
    except (ValueError, TypeError):
        return collapse_ws(BARE_URL_RE.sub("", html_module.unescape(raw_html)))

    for bad in wrapper.xpath(".//comment()"):
        bad.getparent().remove(bad)

    for node in list(wrapper.iterdescendants()):
        if not isinstance(node.tag, str):
            continue
        tag = node.tag.lower()
        if tag in DROP_TAGS:
            node.drop_tree()
            continue
        if tag in UNWRAP_TAGS and tag not in ALLOWED_TAGS:
            node.drop_tag()
            continue
        if tag not in ALLOWED_TAGS:
            node.drop_tag()
            continue
        for attr in list(node.attrib):
            if attr.lower() not in KEEP_ATTRS:
                del node.attrib[attr]
        if tag not in {"br", "hr", "td", "th"} and not _text_of(node) and len(node) == 0:
            node.drop_tree()

    for node in wrapper.iter():
        if not isinstance(node.tag, str):
            continue
        if node.text:
            node.text = BARE_URL_RE.sub("", node.text)
        if node.tail:
            node.tail = BARE_URL_RE.sub("", node.tail)

    parts: list[str] = []
    for child in wrapper:
        if not isinstance(child.tag, str):
            continue
        parts.append(lxml_html.tostring(child, encoding="unicode", method="html"))
    cleaned = "".join(parts).strip()
    cleaned = re.sub(r"(?is)<(p|li|h[2-6])>\s*</\1>", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def html_to_plain_text(raw_html: str) -> str:
    if not raw_html:
        return ""
    try:
        node = lxml_html.fragment_fromstring(raw_html, create_parent="div")
    except (ValueError, TypeError):
        return collapse_ws(html_module.unescape(raw_html))
    return collapse_ws(node.text_content())


def build_options(
    option_names: Sequence[str],
    variant_rows: Sequence[dict],
    *,
    dom_options: Sequence[tuple[str, Sequence[str]]] | None = None,
) -> list[tuple[str, list[str]]]:
    """Build public option dimensions from embedded variants, then DOM fallback."""
    result: list[tuple[str, list[str]]] = []
    if option_names and variant_rows:
        for index, raw_name in enumerate(option_names[:3]):
            name = collapse_ws(str(raw_name))
            if not name or name.lower() in QUANTITY_NAMES:
                continue
            values: list[str] = []
            seen: set[str] = set()
            for row in variant_rows:
                raw_value = row.get(f"option{index + 1}")
                value = strip_price_delta(str(raw_value)) if raw_value is not None else ""
                if not value or value.lower() in {"default title", "default name"}:
                    continue
                key = value.casefold()
                if key in seen:
                    continue
                seen.add(key)
                values.append(value)
            if not values:
                continue
            if len(option_names) == 1 and name.lower() in {"title", "name"} and set(
                v.casefold() for v in values
            ) <= {"default title", "default name"}:
                continue
            result.append((name, values))
    if not result and dom_options:
        for name, values in dom_options:
            cleaned_name = collapse_ws(name)
            if not cleaned_name or cleaned_name.lower() in QUANTITY_NAMES:
                continue
            cleaned_values: list[str] = []
            seen: set[str] = set()
            for raw in values:
                value = strip_price_delta(str(raw))
                if not value or value.lower() in {"default title", "default name"}:
                    continue
                key = value.casefold()
                if key in seen:
                    continue
                seen.add(key)
                cleaned_values.append(value)
            if cleaned_values:
                result.append((cleaned_name, cleaned_values))
    return result


def serialize_options(options: Iterable[tuple[str, Sequence[str]]]) -> str:
    def esc(value: str) -> str:
        return (
            value.replace("\\", "\\\\")
            .replace("#", "\\#")
            .replace("|", "\\|")
            .replace("~", "\\~")
        )

    parts = []
    for name, values in options:
        if not name or not values:
            continue
        parts.append(f"{esc(name)}#{'|'.join(esc(v) for v in values)}")
    return "~".join(parts)


def sanitize_spreadsheet_text(value: str) -> str:
    """Neutralize spreadsheet formulas in untrusted text cells only."""
    if value and value[0] in ("=", "+", "-", "@"):
        return "'" + value
    return value
