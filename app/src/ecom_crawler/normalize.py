"""Normalization rules for the D02 data contract.

The functions here turn observed candidate fields into the internal record
defined by ``docs/02``.  They deliberately do not guess currency, brand,
category or description completeness: missing evidence becomes an explicit
reason, not a fabricated value.
"""

from __future__ import annotations

import html as html_lib
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

from lxml import etree
from lxml import html as lxml_html

from .model import DESCRIPTION_STATUSES, OptionGroup, RecordIssue

ALLOWED_DESCRIPTION_TAGS = {
    "p",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "strong",
    "em",
    "b",
    "i",
    "u",
    "br",
    "hr",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "th",
    "td",
    "caption",
    "dl",
    "dt",
    "dd",
    "blockquote",
    "pre",
    "code",
    "sub",
    "sup",
}

DROP_TREE_TAGS = {
    "script",
    "style",
    "img",
    "picture",
    "source",
    "video",
    "audio",
    "iframe",
    "object",
    "embed",
    "form",
    "button",
    "input",
    "select",
    "textarea",
    "noscript",
    "link",
    "meta",
}

READ_MORE_CLASSES = {
    "st_read_more",
    "st_showmore_btn",
    "st_showless_btn",
    "read-more",
    "readmore",
    "show-more",
    "showmore",
}

QUANTITY_NAMES = {
    "quantity",
    "qty",
    "qty.",
    "quantité",
    "quantite",
    "cantidad",
    "menge",
    "数量",
    "数目",
}

GENERIC_CATEGORIES = {
    "home",
    "shop",
    "all",
    "products",
    "catalog",
    "catalogue",
    "collections",
    "women",
    "men",
    "clothing",
    "apparel",
}

DECIMAL_COMMA_LANGUAGES = {
    "bg",
    "cs",
    "da",
    "de",
    "el",
    "es",
    "fi",
    "fr",
    "hr",
    "hu",
    "id",
    "is",
    "it",
    "lt",
    "lv",
    "nl",
    "no",
    "nb",
    "pl",
    "pt",
    "ro",
    "ru",
    "sk",
    "sl",
    "sv",
    "tr",
    "uk",
    "vi",
}

PRICE_DELTA_RE = re.compile(
    r"\s*[（(]?\s*[+-]\s*(?:[€$£¥]|EUR|USD|GBP|CHF|CAD|AUD)?\s*"
    r"\d+(?:[.,]\d{1,2})?\s*[)）]?\s*$",
    re.IGNORECASE,
)
HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
CURRENCY_CODE_RE = re.compile(
    r"\b(?:EUR|USD|GBP|CHF|CAD|AUD|NZD|JPY|CNY|RMB|SEK|NOK|DKK|PLN|CZK|HUF|"
    r"RON|BGN|HRK|TRY|RUB|UAH|INR|BRL|MXN|ZAR|SGD|HKD|TWD|KRW|THB|IDR|MYR|"
    r"PHP|VND|ILS|AED|SAR)\b",
    re.IGNORECASE,
)
CURRENCY_SYMBOL_RE = re.compile(r"[€$£¥₩₹₽₺₴₦₱฿]")
PLACEHOLDER_IMAGE_RE = re.compile(
    r"(?:none|no[-_]?image|placeholder|place[-_]?holder|default|dummy|spacer|"
    r"pixel|1x1|transparent)(?:[-_].*)?"
)
NUMBER_SHAPE_RE = re.compile(r"[0-9][0-9.,]*")

BLOCK_KINDS = {
    "marketing",
    "specs",
    "other",
    "compatibility",
    "package",
    "ingredients",
    "policy",
    "internal",
}
KEPT_BLOCK_KINDS = {"marketing", "specs", "other"}
RELATION_BLOCK_KINDS = {"compatibility", "package", "ingredients"}


@dataclass(frozen=True)
class NormalizedDescription:
    html: str
    status: str
    partial_reason: str | None
    missing_reasons: dict[str, str]
    relations: tuple[dict[str, str], ...] = ()


def clean_text(value: Any) -> str:
    """Collapse whitespace without changing words or punctuation."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def clean_name(value: Any, *, source_url: str = "") -> str:
    """Clean a product name without guessing or deleting brand words."""
    name = clean_text(value)
    host = urlparse(source_url).netloc.lower()
    if host and name:
        bare = host.removeprefix("www.")
        variants = {host, bare, f"www.{bare}"}
        for variant in variants:
            for separator in (" - ", " | ", " – ", " — ", " · ", " :: "):
                suffix = separator + variant
                prefix = variant + separator
                if name.lower().endswith(suffix.lower()):
                    candidate = name[: -len(suffix)].strip(" -|–—·:")
                    if candidate:
                        return candidate
                if name.lower().startswith(prefix.lower()):
                    candidate = name[len(prefix) :].strip(" -|–—·:")
                    if candidate:
                        return candidate
    return name.strip(" -|–—·:")


def normalize_source_url(value: Any) -> str:
    """Return a stable public product URL or raise a diagnostic issue."""
    text = clean_text(value)
    if not text:
        raise RecordIssue("MISSING_SOURCE_URL")
    parsed = urlparse(text)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise RecordIssue("INVALID_SOURCE_URL", text)
    if parsed.username or parsed.password:
        raise RecordIssue("INVALID_SOURCE_URL", "URL must not contain credentials")
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise RecordIssue("INVALID_SOURCE_URL", str(exc)) from exc
    netloc = parsed.netloc.lower()
    if parsed_port in {80, 443}:
        netloc = re.sub(r":(?:80|443)$", "", netloc)
    path = parsed.path or "/"
    return urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query, ""))


def is_placeholder_image(value: str) -> bool:
    """Detect common placeholder assets without rejecting thumbnails."""
    path = urlparse(value).path.lower()
    if re.search(r"/(?:placeholders?|no[-_]?image)/", path):
        return True
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return bool(PLACEHOLDER_IMAGE_RE.fullmatch(stem))


def normalize_image_url(value: Any, *, source_url: str) -> str:
    text = clean_text(value)
    if not text:
        raise RecordIssue("MISSING_IMAGE")
    absolute = urljoin(source_url, text)
    parsed = urlparse(absolute)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise RecordIssue("INVALID_IMAGE", text)
    if is_placeholder_image(absolute):
        raise RecordIssue("PLACEHOLDER_IMAGE", absolute)
    return absolute


def normalize_currency(value: Any) -> str:
    text = clean_text(value).upper()
    if not text:
        raise RecordIssue("MISSING_CURRENCY")
    if not re.fullmatch(r"[A-Z]{3}", text):
        raise RecordIssue("INVALID_CURRENCY", text)
    return text


def normalize_tax_basis(value: Any) -> str:
    text = clean_text(value).upper().replace(" ", "_")
    aliases = {
        "": "UNSPECIFIED",
        "INCL": "INCLUSIVE",
        "INCLUDED": "INCLUSIVE",
        "TAX_INCLUDED": "INCLUSIVE",
        "EXCL": "EXCLUSIVE",
        "EXCLUDED": "EXCLUSIVE",
        "TAX_EXCLUDED": "EXCLUSIVE",
        "NOT_SPECIFIED": "NOT_SPECIFIED",
        "UNSPECIFIED": "UNSPECIFIED",
    }
    if text in aliases:
        return aliases[text]
    if text in {"INCLUSIVE", "EXCLUSIVE"}:
        return text
    return "UNSPECIFIED"


def normalize_availability(value: Any) -> tuple[str | None, str | None]:
    """Return ``(stock_status, observed_value)``.

    Channel values such as ``OnlineOnly`` are not stock statuses; they are
    preserved only as the observed value.
    """
    observed = clean_text(value)
    if not observed:
        return None, None
    key = observed.upper().replace(" ", "_")
    aliases = {
        "INSTOCK": "IN_STOCK",
        "IN_STOCK": "IN_STOCK",
        "AVAILABLE": "IN_STOCK",
        "OUTOFSTOCK": "OUT_OF_STOCK",
        "OUT_OF_STOCK": "OUT_OF_STOCK",
        "SOLD_OUT": "OUT_OF_STOCK",
        "SOLD_OUT_OF_STOCK": "OUT_OF_STOCK",
        "UNAVAILABLE": "OUT_OF_STOCK",
        "BACKORDER": "BACKORDER",
        "BACK_ORDER": "BACKORDER",
        "PREORDER": "PREORDER",
        "PRE_ORDER": "PREORDER",
        "DISCONTINUED": "DISCONTINUED",
    }
    return aliases.get(key), observed


def _locale_language(locale: str) -> str:
    return clean_text(locale).replace("_", "-").split("-", 1)[0].lower()


def _uses_decimal_comma(locale: str) -> bool:
    return _locale_language(locale) in DECIMAL_COMMA_LANGUAGES


def parse_price(value: Any, *, locale: str = "") -> tuple[Decimal | None, str | None]:
    """Parse a positive finite price.

    Returns ``(amount, None)`` or ``(None, reason)``.  Ambiguous single
    separators with three trailing digits are rejected unless the locale says
    which side is decimal.
    """
    if value is None:
        return None, "MISSING_PRICE"
    if isinstance(value, bool):
        return None, "INVALID_PRICE"
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            return None, "INVALID_PRICE"
        number = Decimal(str(value))
    else:
        text = clean_text(value)
        if not text:
            return None, "MISSING_PRICE"
        number, reason = _parse_price_text(text, locale=locale)
        if reason is not None:
            return None, reason
    assert number is not None
    if not number.is_finite() or number <= 0:
        return None, "NON_POSITIVE_PRICE"
    return number, None


def _parse_price_text(text: str, *, locale: str) -> tuple[Decimal | None, str | None]:
    text = text.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2009", " ")
    text = CURRENCY_CODE_RE.sub("", text)
    text = CURRENCY_SYMBOL_RE.sub("", text)
    text = text.replace("'", "").replace("’", "").replace(" ", "")
    text = text.strip()
    if not text:
        return None, "INVALID_PRICE"
    negative = text.startswith("-")
    if text[:1] in {"+", "-"}:
        text = text[1:]
    if not text or not NUMBER_SHAPE_RE.fullmatch(text):
        return None, "INVALID_PRICE"
    normalized, reason = _normalize_separators(text, locale=locale)
    if reason is not None:
        return None, reason
    assert normalized is not None
    try:
        number = Decimal(normalized)
    except InvalidOperation:
        return None, "INVALID_PRICE"
    if negative:
        number = -number
    return number, None


def _normalize_separators(text: str, *, locale: str) -> tuple[str | None, str | None]:
    has_comma = "," in text
    has_dot = "." in text
    if has_comma and has_dot:
        if text.rfind(",") > text.rfind("."):
            integer, decimal = text.rsplit(",", 1)
            integer = integer.replace(".", "")
        else:
            integer, decimal = text.rsplit(".", 1)
            integer = integer.replace(",", "")
        if not integer.isdigit() or not decimal.isdigit():
            return None, "INVALID_PRICE"
        return f"{integer}.{decimal}", None
    if has_comma:
        return _normalize_single_separator(text, ",", locale=locale)
    if has_dot:
        return _normalize_single_separator(text, ".", locale=locale)
    if text.isdigit():
        return text, None
    return None, "INVALID_PRICE"


def _normalize_single_separator(
    text: str, separator: str, *, locale: str
) -> tuple[str | None, str | None]:
    parts = text.split(separator)
    if len(parts) > 2:
        if (
            parts[0].isdigit()
            and 1 <= len(parts[0]) <= 3
            and all(part.isdigit() and len(part) == 3 for part in parts[1:])
        ):
            if not locale:
                return None, "AMBIGUOUS_PRICE"
            if separator == "." and not _uses_decimal_comma(locale):
                return None, "INVALID_PRICE"
            return "".join(parts), None
        return None, "AMBIGUOUS_PRICE" if not locale else "INVALID_PRICE"

    left, right = parts
    if not left.isdigit() or not right.isdigit():
        return None, "INVALID_PRICE"

    decimal_comma = _uses_decimal_comma(locale)
    known_locale = bool(clean_text(locale))
    if len(right) == 3:
        if not known_locale:
            return None, "AMBIGUOUS_PRICE"
        if separator == ",":
            return (f"{left}.{right}" if decimal_comma else left + right), None
        return (left + right if decimal_comma else f"{left}.{right}"), None

    if len(right) in {1, 2}:
        if separator == "," and known_locale and not decimal_comma:
            return None, "INVALID_PRICE"
        return f"{left}.{right}", None

    return None, "AMBIGUOUS_PRICE" if not known_locale else "INVALID_PRICE"


def looks_like_html(value: str) -> bool:
    return bool(HTML_TAG_RE.search(value))


def text_to_html(value: str) -> str:
    """Wrap real plain text into paragraphs without inventing structure."""
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks = []
    for paragraph in paragraphs:
        escaped = html_lib.escape(paragraph, quote=False).replace("\n", "<br>")
        chunks.append(f"<p>{escaped}</p>")
    return "".join(chunks)


def _inner_html(element: etree._Element) -> str:
    parts = [element.text or ""]
    for child in element:
        parts.append(etree.tostring(child, encoding="unicode", method="html"))
    return "".join(parts)


def _drop_node(element: etree._Element) -> None:
    parent = element.getparent()
    if parent is None:
        return
    tail = element.tail
    previous = element.getprevious()
    if tail:
        if previous is not None:
            previous.tail = (previous.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail
    parent.remove(element)


def clean_description_html(value: str) -> str:
    """Whitelist-clean description HTML and keep product structure."""
    raw = value.strip()
    if not raw:
        return ""
    if not looks_like_html(raw):
        return text_to_html(raw)
    try:
        root = lxml_html.fragment_fromstring(raw, create_parent="div")
    except (etree.ParserError, ValueError, TypeError):
        return ""

    for element in list(root.iterdescendants()):
        if not isinstance(element.tag, str):
            _drop_node(element)
            continue
        classes = set((element.get("class") or "").split())
        if classes & READ_MORE_CLASSES:
            _drop_node(element)

    for element in list(root.iterdescendants()):
        if element.getparent() is None:
            continue
        if not isinstance(element.tag, str):
            _drop_node(element)
            continue
        tag = element.tag.lower()
        if tag in DROP_TREE_TAGS:
            _drop_node(element)
            continue
        if tag not in ALLOWED_DESCRIPTION_TAGS:
            element.drop_tag()
            continue
        element.attrib.clear()

    for element in list(root.iterdescendants()):
        if element.getparent() is None:
            continue
        if not isinstance(element.tag, str):
            continue
        tag = element.tag.lower()
        if tag in {"p", "li"} and not element.text_content().strip():
            _drop_node(element)

    cleaned = _inner_html(root)
    cleaned = re.sub(r"<p>\s*</p>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<li>\s*</li>", "", cleaned, flags=re.IGNORECASE)
    return cleaned.replace("\xa0", " ").strip()


def _normalize_description_status(value: Any) -> str | None:
    text = clean_text(value).upper().replace(" ", "_")
    if not text:
        return None
    aliases = {
        "FULL": "COMPLETE",
        "SUMMARY": "SUMMARY_FALLBACK",
        "MISSING": "NOT_PROVIDED",
        "UNAVAILABLE": "NOT_PROVIDED",
        "PARTIAL_EXTRACTION": "PARTIAL",
    }
    status = aliases.get(text, text)
    if status not in DESCRIPTION_STATUSES:
        raise RecordIssue("INVALID_DESCRIPTION_STATUS", clean_text(value))
    return status


def _normalize_missing_reasons(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise RecordIssue("INVALID_MISSING_REASONS")
    result: dict[str, str] = {}
    for key, reason in value.items():
        field = clean_text(key)
        text = clean_text(reason)
        if field and text:
            result[field] = text
    return result


def normalize_description(candidate: Mapping[str, Any]) -> NormalizedDescription:
    """Normalize complete/summary/partial/missing description states."""
    nested = candidate.get("description")
    if nested is not None and not isinstance(nested, Mapping):
        raise RecordIssue("INVALID_DESCRIPTION_SHAPE")

    if isinstance(nested, Mapping):
        raw_html = nested.get("html")
        raw_text = nested.get("text")
        fmt = clean_text(nested.get("format") or candidate.get("description_format")).lower()
        blocks = nested.get("blocks")
        status_raw = nested.get("status") or candidate.get("description_status")
        partial_reason = nested.get("partial_reason", candidate.get("partial_reason"))
        missing_reasons = nested.get("missing_reasons", candidate.get("missing_reasons"))
    else:
        raw_html = candidate.get("description_html")
        raw_text = None
        fmt = clean_text(candidate.get("description_format")).lower()
        blocks = None
        status_raw = candidate.get("description_status")
        partial_reason = candidate.get("partial_reason")
        missing_reasons = candidate.get("missing_reasons")

    if fmt and fmt not in {"html", "text"}:
        raise RecordIssue("INVALID_DESCRIPTION_FORMAT", fmt)

    relations: list[dict[str, str]] = []
    if blocks is not None:
        if not isinstance(blocks, list):
            raise RecordIssue("INVALID_DESCRIPTION_BLOCKS")
        kept: list[str] = []
        for index, block in enumerate(blocks, start=1):
            if not isinstance(block, Mapping):
                raise RecordIssue("INVALID_DESCRIPTION_BLOCK", f"block {index}")
            kind = clean_text(block.get("kind")).lower()
            if kind not in BLOCK_KINDS:
                raise RecordIssue("INVALID_DESCRIPTION_BLOCK_KIND", kind or f"block {index}")
            block_html = block.get("html")
            block_text = block.get("text")
            if block_html:
                cleaned_block = clean_description_html(_as_text(block_html))
            elif block_text:
                cleaned_block = text_to_html(_as_text(block_text))
            else:
                continue
            if not cleaned_block:
                continue
            if kind in KEPT_BLOCK_KINDS:
                kept.append(cleaned_block)
            elif kind in RELATION_BLOCK_KINDS:
                relations.append({"kind": kind, "html": cleaned_block})
            # policy/internal blocks are intentionally dropped
        cleaned = "".join(kept)
    else:
        html_source = _as_text(raw_html)
        text_source = _as_text(raw_text)
        if fmt == "text" and text_source:
            cleaned = text_to_html(text_source)
        elif html_source:
            cleaned = clean_description_html(html_source)
        elif text_source:
            cleaned = text_to_html(text_source)
        else:
            cleaned = ""

    status = _normalize_description_status(status_raw)
    if status is None:
        status = "COMPLETE" if cleaned else "NOT_PROVIDED"
    reason = clean_text(partial_reason) or None
    missing = _normalize_missing_reasons(missing_reasons)

    if status == "COMPLETE":
        if not cleaned:
            raise RecordIssue("DESCRIPTION_COMPLETE_BUT_EMPTY")
        if reason is not None:
            raise RecordIssue("DESCRIPTION_COMPLETE_WITH_PARTIAL_REASON")
    elif status == "PARTIAL":
        if not cleaned:
            raise RecordIssue("DESCRIPTION_PARTIAL_BUT_EMPTY")
        if reason is None:
            raise RecordIssue("PARTIAL_DESCRIPTION_WITHOUT_REASON")
    elif status == "SUMMARY_FALLBACK":
        if not cleaned:
            raise RecordIssue("DESCRIPTION_SUMMARY_BUT_EMPTY")
        missing.setdefault("description_html", "SUMMARY_FALLBACK")
    elif status == "NOT_PROVIDED":
        if cleaned:
            raise RecordIssue("DESCRIPTION_STATUS_CONFLICT", "NOT_PROVIDED with content")
        reason = None
        missing.setdefault("description_html", "NOT_PROVIDED")

    if status == "COMPLETE" and "description_html" in missing:
        raise RecordIssue("DESCRIPTION_COMPLETE_WITH_MISSING_REASON")

    return NormalizedDescription(
        html=cleaned,
        status=status,
        partial_reason=reason,
        missing_reasons=missing,
        relations=tuple(relations),
    )


def apply_sales_unit(description_html: str, sales_unit: Any) -> str:
    """Prepend an explicit public sales unit when it is not already present."""
    unit = clean_text(sales_unit)
    if not unit or not description_html:
        return description_html
    text = re.sub(r"<[^>]+>", " ", description_html)
    if unit.casefold() in text.casefold():
        return description_html
    return f"<p>{html_lib.escape(unit, quote=False)}</p>{description_html}"


def strip_price_delta(value: str) -> str:
    return PRICE_DELTA_RE.sub("", value).strip()


def _clean_option_name(value: Any) -> str | None:
    name = clean_text(value)
    if not name:
        return None
    if name.casefold() in QUANTITY_NAMES:
        return None
    return name


def _clean_option_value(value: Any) -> str | None:
    text = strip_price_delta(clean_text(value))
    return text or None


def _coerce_option_groups(value: Any) -> list[tuple[str, list[Any]]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [(str(name), _as_values(values)) for name, values in value.items()]
    if not isinstance(value, (list, tuple)):
        raise RecordIssue("INVALID_OPTIONS")
    groups: list[tuple[str, list[Any]]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise RecordIssue("INVALID_OPTIONS")
        name = item.get("name", item.get("label"))
        values = item.get("values", item.get("value"))
        groups.append((_as_text(name), _as_values(values)))
    return groups


def _as_values(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def normalize_options(value: Any) -> tuple[OptionGroup, ...]:
    """Merge option dimensions case-insensitively, keeping first form/order."""
    merged: dict[str, tuple[str, list[str]]] = {}
    for raw_name, raw_values in _coerce_option_groups(value):
        name = _clean_option_name(raw_name)
        if name is None:
            continue
        key = name.casefold()
        if key not in merged:
            merged[key] = (name, [])
        existing = merged[key][1]
        seen = {item.casefold() for item in existing}
        for raw_value in raw_values:
            cleaned = _clean_option_value(raw_value)
            if cleaned is None or cleaned.casefold() in seen:
                continue
            seen.add(cleaned.casefold())
            existing.append(cleaned)
    return tuple(
        OptionGroup(name=name, values=tuple(values))
        for name, values in merged.values()
        if values
    )


def merge_options(
    base: Iterable[OptionGroup], extra: Iterable[OptionGroup]
) -> tuple[OptionGroup, ...]:
    merged: dict[str, tuple[str, list[str]]] = {}
    for group in list(base) + list(extra):
        key = group.name.casefold()
        if key not in merged:
            merged[key] = (group.name, [])
        values = merged[key][1]
        seen = {item.casefold() for item in values}
        for value in group.values:
            if value.casefold() in seen:
                continue
            seen.add(value.casefold())
            values.append(value)
    return tuple(
        OptionGroup(name=name, values=tuple(values))
        for name, values in merged.values()
        if values
    )


def escape_option(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("#", "\\#")
        .replace("|", "\\|")
        .replace("~", "\\~")
    )


def serialize_options(groups: Iterable[OptionGroup]) -> str:
    return "~".join(
        f"{escape_option(group.name)}#{'|'.join(escape_option(value) for value in group.values)}"
        for group in groups
    )


def normalize_categories(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise RecordIssue("INVALID_CATEGORIES")
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        category = clean_text(item)
        key = category.casefold()
        if not category or key in seen or key in GENERIC_CATEGORIES:
            continue
        seen.add(key)
        result.append(category)
    return tuple(result)


def format_price(amount: Decimal) -> str:
    """Format a price with at least two decimals and no binary artifacts."""
    text = format(amount.normalize(), "f")
    if "." not in text:
        return text + ".00"
    whole, fraction = text.split(".", 1)
    if len(fraction) < 2:
        return f"{whole}.{fraction.ljust(2, '0')}"
    return text


def csv_safe(value: str) -> str:
    """Protect spreadsheet consumers from formula-like text cells."""
    if value and value[0] in {"=", "+", "-", "@"}:
        return "'" + value
    return value
