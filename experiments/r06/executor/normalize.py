"""Cleaning and normalization defaults shared by all R06 plans."""

from __future__ import annotations

import html
import math
import re
from typing import Any
from urllib.parse import urlparse

from lxml import etree
from lxml import html as lxml_html

ALLOWED_DESCRIPTION_TAGS = {
    "p",
    "h2",
    "h3",
    "h4",
    "ul",
    "ol",
    "li",
    "strong",
    "em",
    "b",
    "i",
    "br",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "dl",
    "dt",
    "dd",
}
DROP_TREE_TAGS = {
    "script",
    "style",
    "img",
    "video",
    "iframe",
    "form",
    "button",
    "input",
    "noscript",
}
READ_MORE_CLASSES = (
    "st_read_more",
    "st_showmore_btn",
    "st_showless_btn",
    "read-more",
    "readmore",
    "show-more",
    "showmore",
)
QUANTITY_NAMES = {
    "quantity",
    "qty",
    "quantité",
    "quantite",
    "cantidad",
    "menge",
    "数量",
    "数目",
}
PRICE_DELTA_RE = re.compile(
    r"\s*[（(]?\s*[+-]\s*(?:[€$£¥]|EUR|USD|GBP|CHF|CAD|AUD)?\s*"
    r"\d+(?:[.,]\d{1,2})?\s*[)）]?\s*$",
    re.IGNORECASE,
)
HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def strip_site_suffix(value: str, site_names: list[str] | tuple[str, ...]) -> str:
    """Remove a leading or trailing shop name from a title-like value."""
    result = clean_text(value)
    for site in site_names:
        site = clean_text(site)
        if not site:
            continue
        for separator in (" - ", " | ", " – ", " — ", " · ", " :: "):
            suffix = separator + site
            prefix = site + separator
            if result.lower().endswith(suffix.lower()):
                return result[: -len(suffix)].strip(" -|–—·:")
            if result.lower().startswith(prefix.lower()):
                return result[len(prefix) :].strip(" -|–—·:")
    return result


def clean_name(value: str, *, page_url: str = "", site_names: list[str] | tuple[str, ...] = ()) -> str:
    """Clean a product name without guessing or deleting brand words."""
    name = strip_site_suffix(value, site_names)
    if page_url:
        host = urlparse(page_url).netloc.lower()
        bare = host.removeprefix("www.")
        variants = {host, bare, f"www.{bare}"}
        for variant in variants:
            pattern = rf"\s*[-|–—·]\s*{re.escape(variant)}\s*$"
            name = re.sub(pattern, "", name, flags=re.IGNORECASE)
    return name.strip(" -|–—·:")


def looks_like_html(value: str) -> bool:
    return bool(HTML_TAG_RE.search(value))


def text_to_html(value: str) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks = []
    for paragraph in paragraphs:
        escaped = html.escape(paragraph).replace("\n", "<br>")
        chunks.append(f"<p>{escaped}</p>")
    return "".join(chunks)


def inner_html(element: etree._Element) -> str:
    parts = [element.text or ""]
    for child in element:
        parts.append(etree.tostring(child, encoding="unicode", method="html"))
    return "".join(parts)


def clean_description(raw_html: str) -> str:
    """Keep product copy and specifications; drop links, scripts and decoration."""
    if not raw_html.strip():
        return ""
    if not looks_like_html(raw_html):
        return text_to_html(raw_html)
    try:
        root = lxml_html.fragment_fromstring(raw_html, create_parent="div")
    except (ValueError, TypeError):
        return ""
    for element in list(root.iterdescendants()):
        if not isinstance(element.tag, str):
            continue
        classes = set((element.get("class") or "").split())
        if classes & set(READ_MORE_CLASSES):
            element.drop_tree()
    for element in list(root.iterdescendants()):
        if not isinstance(element.tag, str):
            parent = element.getparent()
            if parent is not None:
                tail = element.tail
                previous = element.getprevious()
                if tail:
                    if previous is not None:
                        previous.tail = (previous.tail or "") + tail
                    else:
                        parent.text = (parent.text or "") + tail
                parent.remove(element)
            continue
        tag = element.tag.lower()
        if tag in DROP_TREE_TAGS:
            element.drop_tree()
            continue
        if tag not in ALLOWED_DESCRIPTION_TAGS:
            element.drop_tag()
            continue
        element.attrib.clear()
    for element in list(root.iterdescendants()):
        tag = str(element.tag).lower() if isinstance(element.tag, str) else ""
        if tag in {"p", "li", "span", "div"} and not element.text_content().strip():
            element.drop_tree()
    cleaned = inner_html(root)
    cleaned = re.sub(r"<p>\s*</p>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<li>\s*</li>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n\s*\n+", "\n", cleaned)
    return cleaned.strip()


def parse_number(value: Any, *, locale: str = "", machine: bool = True) -> float | None:
    """Parse a positive finite price; reject zero, negatives, NaN and Infinity."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        text = text.replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
        text = re.sub(r"[^\d,.\-+]", "", text)
        if not text or text.count("-") > 1:
            return None
        text = _apply_separators(text, locale=locale, machine=machine)
        try:
            number = float(text)
        except ValueError:
            return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _apply_separators(text: str, *, locale: str, machine: bool) -> str:
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            return text.replace(".", "").replace(",", ".")
        return text.replace(",", "")
    if "," in text:
        parts = text.split(",")
        if machine:
            if len(parts) == 2 and len(parts[1]) == 3:
                return text.replace(",", "")
            return text.replace(",", ".")
        if len(parts) == 2 and len(parts[1]) == 2:
            return parts[0] + "." + parts[1]
        if len(parts[-1]) == 3 and len(parts[0]) <= 3:
            return text.replace(",", "")
        return text.replace(",", ".")
    if text.count(".") > 1:
        return text.replace(".", "")
    if "." in text and not machine:
        parts = text.split(".")
        if (
            len(parts) == 2
            and len(parts[1]) == 3
            and locale.lower().startswith(("fr", "de", "es", "it", "nl", "pt"))
        ):
            return text.replace(".", "")
    return text


def normalize_currency(value: Any) -> str:
    return clean_text(value).upper()


def format_price(amount: float) -> str:
    return f"{amount:.2f}"


def csv_safe(value: str) -> str:
    if value and value[0] in {"=", "+", "-", "@"}:
        return "'" + value
    return value


def strip_price_delta(value: str) -> str:
    return PRICE_DELTA_RE.sub("", value).strip()


def escape_option(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("#", "\\#")
        .replace("|", "\\|")
        .replace("~", "\\~")
    )


def serialize_option_groups(groups: list[tuple[str, list[str]]]) -> str:
    serialized: list[str] = []
    seen_names: set[str] = set()
    for name, values in groups:
        cleaned_name = clean_text(name)
        key = cleaned_name.casefold()
        if not cleaned_name or key in QUANTITY_NAMES or key in seen_names:
            continue
        seen_names.add(key)
        unique_values: list[str] = []
        seen_values: set[str] = set()
        for value in values:
            cleaned_value = strip_price_delta(clean_text(value))
            value_key = cleaned_value.casefold()
            if not cleaned_value or value_key in seen_values:
                continue
            seen_values.add(value_key)
            unique_values.append(cleaned_value)
        if unique_values:
            joined = "|".join(escape_option(value) for value in unique_values)
            serialized.append(f"{escape_option(cleaned_name)}#{joined}")
    return "~".join(serialized)
