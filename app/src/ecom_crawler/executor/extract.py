"""Declarative field extraction with the common e-commerce fallback order."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from lxml import etree
from lxml import html as lxml_html

from .errors import PlanError
from .normalize import (
    clean_description,
    clean_name,
    clean_text,
    inner_html,
    normalize_currency,
    parse_number,
    serialize_option_groups,
    strip_site_suffix,
    text_to_html,
)

JSON_LD_TYPE_XPATH = (
    '//script[translate(@type, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", '
    '"abcdefghijklmnopqrstuvwxyz")="application/ld+json"]'
)


@dataclass
class FieldHit:
    value: Any
    source: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractedProduct:
    values: dict[str, Any]
    sources: dict[str, str]
    extras: dict[str, dict[str, Any]]
    description_status: str
    partial_reason: str | None
    missing_reasons: dict[str, str]

    @property
    def price_amount(self) -> float | None:
        value = self.values.get("price.amount")
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    @property
    def price_currency(self) -> str:
        return str(self.values.get("price.currency", ""))


class HtmlPage:
    """Small wrapper around lxml with CSS selectors and JSON-LD helpers."""

    def __init__(self, body: bytes | str, url: str) -> None:
        self.url = url
        parser = lxml_html.HTMLParser(recover=True, encoding="utf-8")
        try:
            payload = body.encode("utf-8") if isinstance(body, str) else body
            self.tree = lxml_html.document_fromstring(payload, parser=parser)
        except (etree.ParserError, ValueError):
            self.tree = lxml_html.document_fromstring("<html></html>", parser=parser)
        self._json_ld_product: dict[str, Any] | None | bool = False

    def css(self, selector: str) -> list[etree._Element]:
        try:
            return self.tree.cssselect(selector)
        except Exception as exc:  # lxml/cssselect raises several parser errors
            raise PlanError(f"invalid CSS selector {selector!r}: {exc}") from exc

    def first(self, selector: str) -> etree._Element | None:
        elements = self.css(selector)
        return elements[0] if elements else None

    def json_ld_product(self) -> dict[str, Any] | None:
        if self._json_ld_product is not False:
            return self._json_ld_product  # type: ignore[return-value]
        candidates: list[dict[str, Any]] = []
        for node in _iter_json_ld(self.tree):
            node_type = node.get("@type")
            types = [node_type] if isinstance(node_type, str) else node_type
            if isinstance(types, list) and "Product" in types:
                candidates.append(node)
        product = None
        for candidate in candidates:
            if "name" in candidate or "offers" in candidate:
                product = candidate
                break
        if product is None and candidates:
            product = candidates[0]
        self._json_ld_product = product
        return product


def _iter_json_ld(tree: etree._Element) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for script in tree.xpath(JSON_LD_TYPE_XPATH):
        raw = script.text or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        _walk_json(data, nodes)
    return nodes


def _walk_json(node: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        out.append(node)
        for value in node.values():
            if isinstance(value, (dict, list)):
                _walk_json(value, out)
    elif isinstance(node, list):
        for item in node:
            _walk_json(item, out)


def _resolve_json_path(node: Any, parts: list[str]) -> list[Any]:
    if not parts:
        if isinstance(node, list):
            resolved: list[Any] = []
            for item in node:
                resolved.extend(_resolve_json_path(item, []))
            return resolved
        return [node]
    key = parts[0]
    if isinstance(node, dict):
        if key not in node:
            return []
        return _resolve_json_path(node[key], parts[1:])
    if isinstance(node, list):
        if key.isdigit():
            index = int(key)
            if index < len(node):
                return _resolve_json_path(node[index], parts[1:])
            return []
        resolved = []
        for item in node:
            resolved.extend(_resolve_json_path(item, parts))
        return resolved
    return []


def _json_text(value: Any) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("name", "url", "contentUrl", "@id", "value", "price"):
            if key in value:
                text = _json_text(value[key])
                if text:
                    return text
    if isinstance(value, list):
        for item in value:
            text = _json_text(item)
            if text:
                return text
    return ""


def _json_numbers(values: list[Any], locale: str) -> list[float]:
    numbers: list[float] = []
    for value in values:
        if isinstance(value, dict):
            numbers.extend(_json_numbers(list(value.values()), locale))
        elif isinstance(value, list):
            numbers.extend(_json_numbers(value, locale))
        else:
            number = parse_number(value, locale=locale, machine=True)
            if number is not None:
                numbers.append(number)
    return numbers


def _site_names(page: HtmlPage, plan: dict[str, Any]) -> list[str]:
    names: list[str] = []
    element = page.first('meta[property="og:site_name"]')
    if element is not None:
        names.append(clean_text(element.get("content")))
    names.append(clean_text(plan["site"].get("name")))
    return [name for name in dict.fromkeys(names) if name]


def extract_field(
    page: HtmlPage,
    field_name: str,
    spec: dict[str, Any],
    plan: dict[str, Any],
) -> FieldHit | None:
    for fallback in spec["fallbacks"]:
        hit = _run_extractor(page, field_name, fallback, plan)
        if hit is not None and _has_value(hit.value):
            return hit
    return None


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return True


def _run_extractor(
    page: HtmlPage,
    field_name: str,
    fallback: dict[str, Any],
    plan: dict[str, Any],
) -> FieldHit | None:
    extractor_type = fallback["type"]
    label = str(fallback.get("label") or extractor_type)
    if extractor_type == "json_ld":
        return _extract_json_ld(page, field_name, fallback, plan, label)
    if extractor_type == "css_text":
        return _extract_css_text(page, field_name, fallback, plan, label)
    if extractor_type == "css_attr":
        return _extract_css_attr(page, fallback, label)
    if extractor_type == "css_html":
        return _extract_css_html(page, fallback, label)
    if extractor_type == "title":
        title = page.first("title")
        if title is None:
            return None
        text = strip_site_suffix(clean_text(title.text_content()), _site_names(page, plan))
        return FieldHit(text, label) if text else None
    if extractor_type == "breadcrumb":
        return _extract_breadcrumb(page, fallback, label)
    if extractor_type == "option_groups":
        return _extract_option_groups(page, fallback, label)
    if extractor_type == "price_pair":
        return _extract_price_pair(page, fallback, plan, label)
    if extractor_type == "canonical":
        element = page.first('link[rel~="canonical"]')
        href = element.get("href") if element is not None else ""
        value = urljoin(page.url, clean_text(href)) if href else page.url
        return FieldHit(value, label)
    if extractor_type == "constant":
        return FieldHit(fallback["value"], label)
    raise PlanError(f"unsupported extractor type: {extractor_type!r}")


def _extract_json_ld(
    page: HtmlPage,
    field_name: str,
    fallback: dict[str, Any],
    plan: dict[str, Any],
    label: str,
) -> FieldHit | None:
    product = page.json_ld_product()
    if product is None:
        return None
    values = _resolve_json_path(product, str(fallback["path"]).split("."))
    if not values:
        return None
    take = fallback.get("take")
    if field_name == "price.amount" or take in {"min_positive", "first_positive"}:
        numbers = _json_numbers(values, plan["site"].get("locale", ""))
        if not numbers:
            return None
        positive = [number for number in numbers if number > 0]
        if take == "first_positive":
            if not positive:
                return None
            amount = positive[0]
        else:
            amount = min(numbers)
        return FieldHit(
            amount,
            label,
            {"basis": fallback.get("tax_basis", "unspecified"), "machine": True},
        )
    if field_name == "description_html":
        raw = _json_text(values)
        if not raw:
            return None
        return FieldHit(
            clean_description(raw),
            label,
            {"description_status": fallback.get("description_status", "complete")},
        )
    if field_name == "options":
        return None
    text = _json_text(values)
    return FieldHit(text, label) if text else None


def _extract_css_text(
    page: HtmlPage,
    field_name: str,
    fallback: dict[str, Any],
    plan: dict[str, Any],
    label: str,
) -> FieldHit | None:
    element = page.first(fallback["selector"])
    if element is None:
        return None
    text = clean_text(element.text_content())
    if not text:
        return None
    if fallback.get("strip_site_suffix"):
        text = strip_site_suffix(text, _site_names(page, plan))
    extra: dict[str, Any] = {"machine": False}
    if field_name == "description_html":
        extra["description_status"] = fallback.get("description_status", "complete")
    return FieldHit(text, label, extra)


def _extract_css_attr(
    page: HtmlPage,
    fallback: dict[str, Any],
    label: str,
) -> FieldHit | None:
    element = page.first(fallback["selector"])
    if element is None:
        return None
    value = clean_text(element.get(fallback["attr"]))
    if not value:
        return None
    if fallback.get("absolute") or fallback["attr"] in {"href", "src"}:
        value = urljoin(page.url, value)
    return FieldHit(value, label, {"machine": True})


def _extract_css_html(
    page: HtmlPage,
    fallback: dict[str, Any],
    label: str,
) -> FieldHit | None:
    element = page.first(fallback["selector"])
    if element is None:
        return None
    raw = inner_html(element)
    if not raw.strip():
        return None
    return FieldHit(
        raw,
        label,
        {"description_status": fallback.get("description_status", "complete")},
    )


def _extract_breadcrumb(
    page: HtmlPage,
    fallback: dict[str, Any],
    label: str,
) -> FieldHit | None:
    texts = [clean_text(element.text_content()) for element in page.css(fallback["selector"])]
    texts = [text for text in texts if text]
    if fallback.get("drop_last"):
        texts = texts[:-1]
    excluded = {clean_text(value).casefold() for value in fallback.get("exclude", [])}
    texts = [text for text in texts if text.casefold() not in excluded]
    return FieldHit(texts[-1], label) if texts else None


def _extract_option_groups(
    page: HtmlPage,
    fallback: dict[str, Any],
    label: str,
) -> FieldHit | None:
    groups: list[tuple[str, list[str]]] = []
    for group in page.css(fallback["group_selector"]):
        label_element = group.cssselect(fallback.get("label_selector", "label"))
        name = clean_text(label_element[0].text_content()) if label_element else ""
        if not name:
            name = clean_text(group.get("data-name"))
        values: list[str] = []
        for option in group.cssselect(fallback.get("option_selector", "select option")):
            text = clean_text(option.text_content())
            if text and text not in {"--", "-", "—"}:
                values.append(text)
        if not values:
            for radio in group.cssselect(
                fallback.get("radio_selector", 'input[type="radio"]')
            ):
                value = clean_text(radio.get("value") or radio.get("aria-label"))
                if value:
                    values.append(value)
        if name and values:
            groups.append((name, values))
    serialized = serialize_option_groups(groups)
    return FieldHit(serialized, label) if serialized else None


def _extract_price_pair(
    page: HtmlPage,
    fallback: dict[str, Any],
    plan: dict[str, Any],
    label: str,
) -> FieldHit | None:
    locale = plan["site"].get("locale", "")

    def read_side(side: dict[str, Any]) -> float | None:
        element = page.first(side["selector"])
        if element is None:
            return None
        return parse_number(element.get(side.get("attr", "content")), locale=locale, machine=True)

    gross = read_side(fallback["gross"])
    pretax = read_side(fallback["pretax"])
    candidates: list[tuple[float, str]] = []
    if gross is not None:
        candidates.append((gross, "inclusive"))
    if pretax is not None:
        candidates.append((pretax, "exclusive"))
    if not candidates:
        return None
    chosen, basis = min(candidates, key=lambda item: item[0])
    return FieldHit(
        chosen,
        label,
        {"displayed": gross, "pretax": pretax, "basis": basis, "machine": True},
    )


def extract_product(page: HtmlPage, plan: dict[str, Any]) -> ExtractedProduct:
    fields = plan["extract"]["fields"]
    values: dict[str, Any] = {}
    sources: dict[str, str] = {}
    extras: dict[str, dict[str, Any]] = {}
    for field_name, spec in fields.items():
        hit = extract_field(page, field_name, spec, plan)
        if hit is None:
            continue
        values[field_name] = hit.value
        sources[field_name] = hit.source
        extras[field_name] = hit.extra

    raw_price = values.get("price.amount")
    price: float | None = None
    if isinstance(raw_price, (int, float)) and not isinstance(raw_price, bool):
        price = float(raw_price)
    elif raw_price is not None:
        price = parse_number(
            raw_price,
            locale=plan["site"].get("locale", ""),
            machine=bool(extras.get("price.amount", {}).get("machine", True)),
        )
    values["price.amount"] = price
    values["price.currency"] = normalize_currency(values.get("price.currency"))

    image = clean_text(values.get("primary_image_url"))
    values["primary_image_url"] = urljoin(page.url, image) if image else ""

    description_raw = values.get("description_html") or ""
    description = clean_description(str(description_raw)) if description_raw else ""
    status = "not_provided" if not description else extras.get("description_html", {}).get(
        "description_status", "complete"
    )
    if description and status == "not_provided":
        status = "complete"
    partial_reason = None
    if status == "partial":
        partial_reason = "Fallback description container used; the full description was not available."
    values["description_html"] = description

    values["name"] = clean_name(
        str(values.get("name", "")),
        page_url=page.url,
        site_names=_site_names(page, plan),
    )
    source_url = clean_text(values.get("source_url")) or page.url
    values["source_url"] = urljoin(page.url, source_url)
    values["category"] = clean_text(values.get("category"))
    values["brand"] = clean_text(values.get("brand"))
    values["options"] = clean_text(values.get("options"))

    missing_reasons: dict[str, str] = {}
    if not values["brand"]:
        missing_reasons["brand"] = "NOT_PROVIDED"
    if not values["category"]:
        missing_reasons["category"] = "NOT_FOUND"
    if not description:
        missing_reasons["description_html"] = "NOT_PROVIDED"

    return ExtractedProduct(
        values=values,
        sources=sources,
        extras=extras,
        description_status=status,
        partial_reason=partial_reason,
        missing_reasons=missing_reasons,
    )


def html_from_text(value: str) -> str:
    """Kept as a named helper for tests and future extractors."""
    return text_to_html(value)
