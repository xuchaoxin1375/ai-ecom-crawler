"""Normalization helpers for skatepro.es: money, names, descriptions, options.

The HTML whitelist cleaner, option serialization and spreadsheet guard follow
the Scrapling javaestate plan (same framework); the money and option builders
are rewritten for skatepro's numeric variant feed.
"""

from __future__ import annotations

import html as html_module
import re
from decimal import Decimal, InvalidOperation
from typing import Iterable, Sequence

from lxml import html as lxml_html

WS_RE = re.compile(r"[\s\u00a0\u202f]+")
BARE_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
QUANTITY_NAMES = {"quantity", "qty", "cantidad", "quantité", "quantite", "menge", "数量"}
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
EU_PRICE_RE = re.compile(r"^(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?$")


def collapse_ws(value: str | None) -> str:
    if not value:
        return ""
    return WS_RE.sub(" ", html_module.unescape(str(value))).strip()


def clean_name(value: str | None) -> str:
    """Collapse whitespace and drop only the site's own domain, never the brand."""
    name = collapse_ws(value)
    if not name:
        return ""
    name = re.sub(r"(?i)\b(?:www\.)?skatepro\.es\b", "", name).strip(" -–—|,;:")
    return collapse_ws(name)


def to_decimal(raw: object) -> Decimal | None:
    """Convert a numeric variant price or an es-ES price string to Decimal."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float, Decimal)):
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            return None
    else:
        text = collapse_ws(str(raw)).replace("€", "").replace("EUR", "").strip()
        text = text.replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
        match = EU_PRICE_RE.fullmatch(text)
        if not match:
            return None
        whole = match.group(1).replace(".", "")
        cents = match.group(2) or "0"
        try:
            value = Decimal(f"{whole}.{cents}")
        except InvalidOperation:
            return None
    if not value.is_finite():
        return None
    return value


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


def normalize_image_url(value: str | None) -> str:
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
    if any(token in lowered for token in ("/logo", "logo.", "placeholder", "spacer.gif", "loader.svg")):
        return ""
    return url


def _text_of(node: lxml_html.HtmlElement) -> str:
    return collapse_ws(node.text_content())


def sanitize_description(raw_html: str | None) -> str:
    """Whitelist-clean a description fragment and drop unsafe or noisy markup."""
    if not raw_html or not raw_html.strip():
        return ""
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
    cleaned = re.sub(r"\r\n?", "\n", cleaned)
    cleaned = re.sub(r"\n{2,}", "\n", cleaned)
    if not collapse_ws(lxml_html.fromstring(f"<div>{cleaned}</div>").text_content()):
        return ""
    return cleaned.strip()


def html_to_plain_text(raw_html: str | None) -> str:
    if not raw_html:
        return ""
    try:
        node = lxml_html.fragment_fromstring(raw_html, create_parent="div")
    except (ValueError, TypeError):
        return collapse_ws(html_module.unescape(raw_html))
    return collapse_ws(node.text_content())


def build_options(variants: Sequence[dict]) -> list[tuple[str, list[str]]]:
    """Union public option dimensions/values across all variants.

    Dimensions stay in first-seen order; values keep the site's first spelling.
    Quantity-like dimensions and empty values are dropped.
    """
    order: list[str] = []
    values: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for variant in variants:
        names = variant.get("attribute_text") or {}
        values_by_id = variant.get("attribute_variant_text") or {}
        for key, raw_name in names.items():
            name = collapse_ws(str(raw_name))
            if not name or name.casefold() in QUANTITY_NAMES:
                continue
            value = collapse_ws(str(values_by_id.get(key, "")))
            if not value:
                continue
            if name not in values:
                order.append(name)
                values[name] = []
                seen[name] = set()
            fold = value.casefold()
            if fold in seen[name]:
                continue
            seen[name].add(fold)
            values[name].append(value)
    return [(name, values[name]) for name in order if values[name]]


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
