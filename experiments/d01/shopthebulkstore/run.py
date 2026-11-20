"""D01 S5 shopthebulkstore.com category-grid plan.

Fetches the Candy Unwrapped category page, takes up to 30 product links,
fetches those product pages, and writes the 9-column business CSV plus a task
result and diagnostics. No browser, login, cart or checkout endpoint is used.

Usage:
  python run.py --out-dir . --label d01-run-001
  python run.py --out-dir . --label dry-run-001 --max-products 3
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from lxml import etree, html as LH

SITE = "https://shopthebulkstore.com"
CATEGORY_URL = f"{SITE}/candy/bulk-candy-unwrapped"
SITEMAP_URL = f"{SITE}/sitemap.xml"
ROBOTS_URL = f"{SITE}/robots.txt"
MARKET = "US"
LOCALE = "en-US"
EXPECTED_CURRENCY = "USD"
CSV_COLUMNS = [
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
ALLOWED_TAGS = {
    "p", "br", "ul", "ol", "li", "strong", "b", "em", "i", "u", "s",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "table", "thead",
    "tbody", "tfoot", "tr", "th", "td", "caption", "pre", "code", "div", "span",
}
FORBIDDEN_TAGS = {
    "script", "style", "iframe", "img", "form", "input", "select", "textarea",
    "button", "noscript", "svg", "video", "audio", "source", "link", "meta",
}
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
TEXT_HANDLER_RE = re.compile(r"^[=+\-@]")
PRICE_UNIT_RE = re.compile(
    r"(?i)(price\s+is\s+per\s+(?:\d+\s*(?:oz|ounce|lb|pound)\.?\s*)?"
    r"(?:lb|pound|item|piece|each|ounce|oz|bag|box|dozen|pack)"
    r"|sold\s+by\s+the\s+(?:pound|lb)"
    r"|per\s+(?:pound|lb)\b"
    r"|/\s*(?:lb|pound)\b)"
)
PRICE_NUMBER_RE = re.compile(r"([0-9]+(?:[.,][0-9]+)?)")


class AccessDenied(RuntimeError):
    pass


class PlanError(RuntimeError):
    pass


class HttpError(RuntimeError):
    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"HTTP {status}: {url}")
        self.status = status
        self.url = url


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_space(value: object) -> str:
    return " ".join(str(value or "").split())


def response_html(response: object) -> str:
    """Scrapling HTML responses expose html_content; .text can be empty for large pages."""
    html = getattr(response, "html_content", None)
    if html is not None and len(html):
        return str(html)
    body = getattr(response, "body", None)
    if isinstance(body, bytes) and body:
        return body.decode("utf-8", errors="replace")
    return str(getattr(response, "text", ""))


def response_body_text(response: object) -> str:
    body = getattr(response, "body", None)
    if isinstance(body, bytes) and body:
        return body.decode("utf-8", errors="replace")
    return response_html(response)


def clean_html(raw: str | None) -> tuple[str, str]:
    """Return (cleaned_html, status). Status: complete/not_provided/failed."""
    if not raw or not str(raw).strip():
        return "", "not_provided"
    try:
        root = LH.fromstring(str(raw))
    except (etree.ParserError, ValueError):
        return "", "failed"
    for node in list(root.iter()):
        if not isinstance(node.tag, str):
            continue
        tag = node.tag.lower()
        parent = node.getparent()
        if tag in FORBIDDEN_TAGS:
            if parent is None:
                node.clear()
                node.tag = "div"
            else:
                node.drop_tree()
        elif tag == "a" or tag not in ALLOWED_TAGS:
            if parent is None:
                node.tag = "div"
            else:
                node.drop_tag()
        else:
            node.attrib.clear()
    for node in reversed(list(root.iter())):
        if not isinstance(node.tag, str):
            continue
        if node.tag.lower() in {"br", "hr"}:
            continue
        if not (node.text or "").strip() and len(node) == 0:
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
    if not normalize_space(root.text_content()):
        return "", "failed"
    html_text = etree.tostring(root, encoding="unicode", method="html").strip()
    return html_text, "complete" if html_text else "failed"


def parse_jsonld(doc) -> list:
    blocks = []
    for script in doc.xpath("//script[@type='application/ld+json']"):
        raw = script.text or ""
        if not raw.strip():
            continue
        try:
            blocks.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return blocks


def find_products(value, found: list[dict] | None = None) -> list[dict]:
    found = found if found is not None else []
    if isinstance(value, dict):
        types = value.get("@type")
        if types == "Product" or (isinstance(types, list) and "Product" in types):
            found.append(value)
        for child in value.values():
            find_products(child, found)
    elif isinstance(value, list):
        for child in value:
            find_products(child, found)
    return found


def select_product(products: list[dict], canonical: str) -> dict | None:
    if not products:
        return None
    best = None
    best_score = -1
    for product in products:
        score = 0
        if normalize_space(product.get("url")).rstrip("/") == canonical.rstrip("/"):
            score += 3
        if normalize_space(product.get("@id")).endswith("#product"):
            score += 2
        if normalize_space(product.get("name")):
            score += 1
        if score > best_score:
            best = product
            best_score = score
    return best


def offer_details(product: dict | None) -> tuple[float | None, str | None, str | None]:
    if not product:
        return None, None, None
    offers = product.get("offers")
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        return None, None, None
    pairs: list[tuple[float, str]] = []
    availability = None
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        raw_price = offer.get("lowPrice") if offer.get("@type") == "AggregateOffer" else offer.get("price")
        if raw_price is None and offer.get("@type") == "AggregateOffer":
            raw_price = offer.get("price")
        try:
            price = float(raw_price)
        except (TypeError, ValueError):
            price = None
        currency = normalize_space(offer.get("priceCurrency")).upper() or None
        if price is not None and math.isfinite(price) and price > 0 and currency:
            pairs.append((price, currency))
        if availability is None and normalize_space(offer.get("availability")):
            availability = normalize_space(offer.get("availability"))
    if not pairs:
        return None, None, availability
    pairs.sort(key=lambda item: item[0])
    return pairs[0][0], pairs[0][1], availability


def parse_meta(doc, name: str) -> str | None:
    values = doc.xpath(f"//meta[@property='{name}']/@content | //meta[@name='{name}']/@content")
    if values:
        return normalize_space(values[0]) or None
    return None


def parse_price_number(text: str | None) -> float | None:
    if not text:
        return None
    match = PRICE_NUMBER_RE.search(str(text).replace(",", ""))
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return value if math.isfinite(value) and value > 0 else None


def dom_price(doc) -> tuple[float | None, str | None]:
    amount = parse_meta(doc, "product:price:amount")
    currency = parse_meta(doc, "product:price:currency")
    if amount:
        return parse_price_number(amount), (currency.upper() if currency else None)
    wrappers = doc.xpath("//*[contains(@class,'product-info-price')]//*[@data-price-amount]")
    for wrapper in wrappers:
        value = parse_price_number(wrapper.get("data-price-amount"))
        if value is not None:
            return value, (currency.upper() if currency else None)
    price_nodes = doc.xpath("//*[contains(@class,'product-info-price')]//*[contains(@class,'price')]")
    for node in price_nodes:
        value = parse_price_number(node.text_content())
        if value is not None:
            return value, (currency.upper() if currency else None)
    return None, (currency.upper() if currency else None)


def parse_image(product: dict | None, doc) -> str:
    raw = None
    if product:
        image = product.get("image")
        if isinstance(image, list) and image:
            raw = image[0]
            if isinstance(raw, dict):
                raw = raw.get("url") or raw.get("contentUrl")
        elif isinstance(image, dict):
            raw = image.get("url") or image.get("contentUrl")
        elif isinstance(image, str):
            raw = image
    if not raw:
        values = doc.xpath("//meta[@property='og:image']/@content")
        raw = values[0] if values else None
    if not raw:
        values = doc.xpath(
            "//*[contains(@class,'gallery-placeholder')]//img/@src"
            " | //*[@itemprop='image']/@src"
            " | //*[contains(@class,'product-image-main')]//img/@src"
        )
        raw = values[0] if values else None
    if not raw:
        return ""
    raw = normalize_space(raw)
    if raw.startswith("//"):
        raw = "https:" + raw
    elif raw.startswith("/"):
        raw = SITE + raw
    if raw.startswith("http://"):
        raw = "https://" + raw[len("http://"):]
    return raw


def parse_brand(product: dict | None, doc) -> str:
    if product:
        brand = product.get("brand")
        if isinstance(brand, list) and brand:
            brand = brand[0]
        if isinstance(brand, dict):
            brand = brand.get("name")
        value = normalize_space(brand)
        if value:
            return value
    values = doc.xpath("//*[@itemprop='brand']//text()")
    value = normalize_space(" ".join(values))
    if value:
        return value
    values = doc.xpath("//*[contains(@class,'product-brand')]//text()")
    value = normalize_space(" ".join(values))
    if value:
        return value
    for row in doc.xpath("//table[contains(@class,'additional-attributes')]//tr"):
        label = normalize_space(" ".join(row.xpath("./th//text()"))).lower()
        if label in {"brand", "manufacturer"}:
            value = normalize_space(" ".join(row.xpath("./td//text()")))
            if value:
                return value
    return ""


def parse_breadcrumbs(doc) -> list[str]:
    values = doc.xpath(
        "//*[contains(@class,'breadcrumbs')]//a//text()"
        " | //*[contains(@class,'breadcrumbs')]//strong//text()"
    )
    result = []
    for value in values:
        text = normalize_space(value)
        if text and text.lower() != "home" and text not in result:
            result.append(text)
    return result


def description_blocks(doc, product: dict | None, name: str) -> tuple[str, str, str, str | None]:
    """Return (html, text, status, partial_reason)."""
    nodes = doc.xpath(
        "//*[@class='product attribute overview']//*[@class='value']"
        " | //*[@class='product attribute description']//*[@class='value']"
    )
    blocks: list[tuple[str, str]] = []
    for node in nodes:
        raw = LH.tostring(node, encoding="unicode")
        cleaned, status = clean_html(raw)
        if status == "complete" and normalize_space(cleaned):
            text = normalize_space(LH.fromstring(cleaned).text_content())
            blocks.append((cleaned, text))
    kept: list[tuple[str, str]] = []
    for index, (html, text) in enumerate(blocks):
        keep = True
        for other_index, (_, other_text) in enumerate(blocks):
            if index == other_index:
                continue
            if text and text.lower() == other_text.lower() and index > other_index:
                keep = False
                break
            if text and text.lower() in other_text.lower() and len(text) < len(other_text):
                keep = False
                break
        if keep:
            kept.append((html, text))
    if kept:
        html = "\n".join(item[0] for item in kept)
        text = normalize_space(" ".join(item[1] for item in kept))
        status = "complete"
        partial_reason = None
    else:
        raw = normalize_space((product or {}).get("description"))
        if raw:
            if "<" in raw:
                html, status = clean_html(raw)
            else:
                html = f"<p>{escape(raw)}</p>"
                status = "complete"
            text = normalize_space(LH.fromstring(html).text_content()) if html else ""
            status = "fallback"
            partial_reason = "仅取得 JSON-LD 描述，未取得 DOM 正文"
        else:
            return "", "", "not_provided", None
    substantive = text
    if name:
        substantive = re.sub(re.escape(name), " ", substantive, flags=re.I)
    substantive = PRICE_UNIT_RE.sub(" ", substantive)
    substantive = re.sub(r"[^A-Za-z0-9]+", "", substantive)
    if status == "complete" and len(substantive) < 20:
        status = "partial"
        partial_reason = "描述仅含商品名或计价单位说明，未提供独立商品正文"
    return html, text, status, partial_reason


def detect_price_unit(texts: list[str]) -> tuple[str | None, str | None]:
    for text in texts:
        if not text:
            continue
        match = PRICE_UNIT_RE.search(text)
        if not match:
            continue
        phrase = normalize_space(match.group(0))
        phrase = re.sub(r"(?i)^price\s+is\s+per\s+", "Price is per ", phrase)
        phrase = re.sub(r"(?i)^sold\s+by\s+the\s+", "Sold by the ", phrase)
        phrase = re.sub(r"(?i)^per\s+", "per ", phrase)
        phrase = re.sub(r"(?i)^/\s*", "per ", phrase)
        lower = phrase.lower()
        if re.search(r"\bbag\b", lower):
            return "per_bag", phrase
        if re.search(r"\bbox\b", lower):
            return "per_box", phrase
        if re.search(r"\bdozen\b", lower):
            return "per_dozen", phrase
        if re.search(r"\bpack\b", lower):
            return "per_pack", phrase
        if re.search(r"\b(item|piece|each)\b", lower):
            return "per_item", phrase
        if re.search(r"\b(lb|pound)\b", lower):
            return "per_lb", phrase
        if re.search(r"\b(ounce|oz)\b", lower):
            return "per_oz", phrase
    return None, None


def ensure_unit(
    html: str, text: str, status: str, partial_reason: str | None, unit_text: str | None
) -> tuple[str, str, str, str | None]:
    if not unit_text:
        return html, text, status, partial_reason
    if unit_text.lower() in text.lower():
        return html, text, status, partial_reason
    sentence = unit_text.rstrip(".") + "."
    block = f"<p>{escape(sentence)}</p>"
    html = block + ("\n" + html if html else "")
    text = normalize_space(sentence + " " + text)
    if status == "not_provided":
        status = "partial"
        partial_reason = "仅补充售价旁计价单位，原站未提供独立正文"
    return html, text, status, partial_reason


def escape_option(value: str) -> str:
    return value.replace("\\", "\\\\").replace("#", "\\#").replace("|", "\\|").replace("~", "\\~")


def add_option(parts: list[tuple[str, list[str]]], label: str, values: list[str]) -> None:
    label = normalize_space(label)
    if not label or label.lower() in {"quantity", "qty"}:
        return
    cleaned = []
    for value in values:
        text = normalize_space(value)
        if text and text.lower() not in {"choose an option...", "choose an option"} and text not in cleaned:
            cleaned.append(text)
    if not cleaned:
        return
    for index, (existing_label, existing_values) in enumerate(parts):
        if existing_label.lower() == label.lower():
            for value in cleaned:
                if value not in existing_values:
                    existing_values.append(value)
            return
    parts.append((label, cleaned))


def parse_options(doc) -> str:
    parts: list[tuple[str, list[str]]] = []
    for select in doc.xpath("//select[starts-with(@name,'super_attribute')]"):
        label = normalize_space(select.get("aria-label"))
        if not label:
            labels = select.xpath("preceding::label[1]//text()")
            label = normalize_space(" ".join(labels))
        if not label:
            labels = select.xpath("ancestor::*[contains(@class,'field')][1]//label//text()")
            label = normalize_space(" ".join(labels))
        values = []
        for option in select.xpath("./option"):
            if not normalize_space(option.get("value")):
                continue
            values.append(normalize_space(option.text_content()))
        add_option(parts, label, values)
    for node in doc.xpath("//*[contains(@class,'swatch-attribute')][@data-attribute-code]"):
        label = normalize_space(" ".join(node.xpath(".//*[contains(@class,'swatch-attribute-label')]//text()")))
        if not label:
            label = normalize_space(node.get("data-attribute-code"))
        values = []
        for option in node.xpath(".//*[contains(@class,'swatch-option')]"):
            values.append(normalize_space(option.get("aria-label") or option.get("data-option-label") or option.text_content()))
        add_option(parts, label, values)
    for script in doc.xpath("//script[@type='text/x-magento-init']"):
        raw = script.text or ""
        if "jsonConfig" not in raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        stack = [payload]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                config = value.get("jsonConfig")
                if isinstance(config, dict):
                    attributes = config.get("attributes")
                    if isinstance(attributes, dict):
                        for attribute in attributes.values():
                            if not isinstance(attribute, dict):
                                continue
                            label = normalize_space(attribute.get("label") or attribute.get("code"))
                            values = [
                                normalize_space(option.get("label") or option.get("name"))
                                for option in attribute.get("options") or []
                                if isinstance(option, dict)
                            ]
                            add_option(parts, label, values)
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
    return "~".join(
        f"{escape_option(label)}#{'|'.join(escape_option(value) for value in values)}"
        for label, values in parts
    )


def canonical_url(doc, fetched_url: str) -> str:
    values = doc.xpath("//link[@rel='canonical']/@href")
    candidate = normalize_space(values[0]) if values else fetched_url
    candidate = urljoin(fetched_url, candidate)
    parts = urlsplit(candidate)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def product_links(doc) -> list[str]:
    links = []
    seen = set()
    for anchor in doc.xpath("//a[contains(@class,'product-item-link')][@href]"):
        href = urljoin(SITE + "/", normalize_space(anchor.get("href")))
        parts = urlsplit(href)
        normalized = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
        if normalized and normalized not in seen:
            seen.add(normalized)
            links.append(normalized)
    return links


def category_total(doc) -> int | None:
    values = doc.xpath("//*[contains(@class,'toolbar-amount')]//text()")
    text = normalize_space(" ".join(values))
    match = re.search(r"(?i)items?\s+\d+\s*-\s*\d+\s+of\s+(\d+)", text)
    if match:
        return int(match.group(1))
    return None


def format_amount(value: float) -> str:
    return f"{value:.2f}"


def protect_text(value: str) -> str:
    return "'" + value if TEXT_HANDLER_RE.match(value) else value


def build_row(
    product: dict | None,
    doc,
    canonical: str,
    fetched_url: str,
    expected_currency: str,
) -> tuple[dict | None, dict]:
    name = normalize_space((product or {}).get("name"))
    if not name:
        name = normalize_space(doc.xpath("string(//h1)"))
    if not name:
        name = normalize_space(parse_meta(doc, "og:title"))
    price, currency, availability = offer_details(product)
    if price is None or not currency:
        dom_amount, dom_currency = dom_price(doc)
        if price is None:
            price = dom_amount
        if not currency:
            currency = dom_currency
    image = parse_image(product, doc)
    breadcrumbs = parse_breadcrumbs(doc)
    category = breadcrumbs[-1] if breadcrumbs else ""
    if category and name and category.lower() == name.lower():
        category = breadcrumbs[-2] if len(breadcrumbs) > 1 else ""
    brand = parse_brand(product, doc)
    description_html, description_text, description_status, partial_reason = description_blocks(doc, product, name)
    unit_texts = [description_text]
    for node in doc.xpath("//*[contains(@class,'product attribute overview')]//*[@class='value']"):
        unit_texts.append(normalize_space(node.text_content()))
    unit_texts.append(normalize_space(" ".join(doc.xpath("//*[contains(@class,'product-info-price')]//text()"))))
    unit_texts.append(normalize_space(" ".join(doc.xpath("//*[contains(@class,'price-box')]//text()"))))
    price_unit, price_unit_text = detect_price_unit(unit_texts)
    description_html, description_text, description_status, partial_reason = ensure_unit(
        description_html, description_text, description_status, partial_reason, price_unit_text
    )
    attributes = parse_options(doc)
    missing: dict[str, str] = {}
    if not category:
        missing["category"] = "not_provided"
    if not brand:
        missing["brand"] = "not_provided"
    if description_status != "complete":
        missing["description"] = description_status
    audit = {
        "source_url": canonical,
        "fetched_url": fetched_url,
        "name": name,
        "price_amount": format_amount(price) if price is not None else "",
        "price_currency": currency or "",
        "description_status": description_status,
        "description_chars": len(description_html),
        "category": category,
        "brand": brand,
        "price_unit": price_unit or "unknown",
        "price_unit_text": price_unit_text,
        "availability": availability or "",
        "sku": normalize_space((product or {}).get("sku")),
        "attributes": attributes,
        "breadcrumbs": breadcrumbs,
        "missing_reasons": missing,
    }
    if partial_reason:
        audit["partial_reason"] = partial_reason
    if not canonical:
        return None, {**audit, "outcome": "excluded", "reason": "missing_source_url"}
    if not name:
        return None, {**audit, "outcome": "excluded", "reason": "missing_name"}
    if price is None:
        return None, {**audit, "outcome": "excluded", "reason": "zero_or_missing_price"}
    if not currency or not CURRENCY_RE.match(currency):
        return None, {**audit, "outcome": "excluded", "reason": "missing_currency"}
    if currency != expected_currency:
        return None, {**audit, "outcome": "excluded", "reason": "unexpected_currency"}
    if not image or not image.startswith("https://"):
        return None, {**audit, "outcome": "excluded", "reason": "missing_primary_image"}
    row = {
        "name": name,
        "price_amount": format_amount(price),
        "price_currency": currency,
        "primary_image_url": image,
        "description_html": description_html,
        "category": category,
        "brand": brand,
        "attributes": attributes,
        "source_url": canonical,
    }
    return row, {**audit, "outcome": "valid"}


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: protect_text(str(row.get(key, ""))) if key != "price_amount" else row.get(key, "")
                    for key in CSV_COLUMNS
                }
            )


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv_rows(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded S5 shopthebulkstore category-grid plan")
    parser.add_argument("--out-dir", default=".", help="output directory for valid.csv/task-result.json")
    parser.add_argument("--label", default="d01-run-001", help="diagnostics subdirectory label")
    parser.add_argument("--max-products", type=int, default=30)
    parser.add_argument("--max-seconds", type=float, default=600.0)
    parser.add_argument("--delay", type=float, default=1.1, help="seconds between request starts")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--max-retry-after", type=float, default=60.0)
    parser.add_argument("--max-consecutive-failures", type=int, default=5)
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    run_dir = out_dir / "diagnostics" / args.label
    run_dir.mkdir(parents=True, exist_ok=True)
    events_path = run_dir / "events.ndjson"
    events_handle = events_path.open("w", encoding="utf-8", newline="\n")

    def emit(event: str, **payload) -> None:
        events_handle.write(
            json.dumps({"ts": iso(utc_now()), "event": event, **payload}, ensure_ascii=False) + "\n"
        )
        events_handle.flush()

    started = utc_now()
    started_mono = time.monotonic()
    deadline = started_mono + args.max_seconds
    last_request_at: float | None = None
    requests = 0
    retries = 0
    per_purpose: dict[str, int] = {}
    per_status: dict[str, int] = {}
    errors: list[dict] = []
    warnings: list[str] = []
    stop_reason = "NATURAL_END"
    stop_detail = ""
    category_total_value: int | None = None
    category_links: list[str] = []
    selected: list[str] = []
    sitemap_locs: set[str] = set()
    sitemap_status = "SKIPPED"
    sitemap_matched = 0
    discovery_urls = 0

    def fetch(session: object, url: str, purpose: str):
        nonlocal last_request_at, requests, retries
        if last_request_at is not None:
            wait = args.delay - (time.monotonic() - last_request_at)
            if wait > 0:
                time.sleep(wait)
        for attempt in range(1, int(args.max_attempts) + 1):
            if time.monotonic() >= deadline:
                raise TimeoutError("wall-clock budget exhausted")
            try:
                response = session.get(url)
            except Exception as exc:  # noqa: BLE001 - record transport detail
                if attempt >= args.max_attempts:
                    raise RuntimeError(f"{purpose}: transport error: {type(exc).__name__}: {exc}") from exc
                retries += 1
                time.sleep(min(2.0 * attempt, 10.0))
                continue
            requests += 1
            per_purpose[purpose] = per_purpose.get(purpose, 0) + 1
            status = int(getattr(response, "status", 0) or 0)
            per_status[str(status)] = per_status.get(str(status), 0) + 1
            emit("request", purpose=purpose, url=url, status=status, attempt=attempt)
            if status == 429:
                retry_after = 5.0
                try:
                    retry_after = float(getattr(response, "headers", {}).get("retry-after", 5) or 5)
                except (TypeError, ValueError):
                    pass
                if retry_after > args.max_retry_after:
                    raise AccessDenied(f"{purpose}: HTTP 429 Retry-After {retry_after}s exceeds limit")
                if attempt >= args.max_attempts:
                    raise AccessDenied(f"{purpose}: HTTP 429 after {attempt} attempts")
                retries += 1
                time.sleep(min(retry_after, args.max_retry_after))
                continue
            if status in {401, 403}:
                raise AccessDenied(f"{purpose}: HTTP {status}")
            if status >= 500 and attempt < args.max_attempts:
                retries += 1
                time.sleep(min(2.0 * attempt, 10.0))
                continue
            if status != 200:
                raise HttpError(status, url)
            last_request_at = time.monotonic()
            return response
        raise RuntimeError(f"{purpose}: retries exhausted")

    rows: list[dict] = []
    audits: list[dict] = []
    excluded: list[dict] = []
    failed: list[dict] = []
    pending: list[dict] = []
    consecutive_failures = 0
    try:
        from scrapling.fetchers import FetcherSession

        with FetcherSession(impersonate="chrome", timeout=args.timeout, retries=1) as session:
            emit(
                "run_start",
                plan_id="shopthebulkstore-us-d01",
                max_products=args.max_products,
                max_seconds=args.max_seconds,
            )
            robots = fetch(session, ROBOTS_URL, "robots")
            (run_dir / "robots.txt").write_text(response_body_text(robots), encoding="utf-8")
            discovery_urls += 1

            try:
                sitemap_response = fetch(session, SITEMAP_URL, "sitemap")
                sitemap_text = response_body_text(sitemap_response)
                sitemap_locs = {
                    loc.rstrip("/")
                    for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sitemap_text)
                }
                sitemap_status = "FETCHED"
                discovery_urls += 1
            except (AccessDenied, PlanError, RuntimeError, HttpError, TimeoutError) as exc:
                warnings.append(f"sitemap cross-check skipped: {type(exc).__name__}: {exc}")
                emit("sitemap_skipped", detail=str(exc))

            category_response = fetch(session, CATEGORY_URL, "category")
            category_html = response_html(category_response)
            category_doc = LH.fromstring(category_html)
            category_total_value = category_total(category_doc)
            category_links = product_links(category_doc)
            discovery_urls += 1
            (run_dir / "category-summary.json").write_text(
                json.dumps(
                    {
                        "url": CATEGORY_URL,
                        "status": getattr(category_response, "status", None),
                        "bytes": len(category_html),
                        "toolbar_total": category_total_value,
                        "product_links": len(category_links),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (run_dir / "category-product-urls.txt").write_text(
                "\n".join(category_links) + ("\n" if category_links else ""), encoding="utf-8"
            )
            if not category_links:
                raise PlanError("category page returned no product links")
            selected = category_links[: max(0, int(args.max_products))]
            if not selected:
                raise PlanError("max-products resulted in no candidates")
            if sitemap_locs:
                sitemap_matched = sum(1 for url in selected if url.rstrip("/") in sitemap_locs)
            (run_dir / "sitemap-crosscheck.json").write_text(
                json.dumps(
                    {
                        "status": sitemap_status,
                        "sitemap_url": SITEMAP_URL,
                        "sitemap_locs": len(sitemap_locs),
                        "selected_products": len(selected),
                        "matched": sitemap_matched,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            for index, url in enumerate(selected):
                if time.monotonic() >= deadline:
                    stop_reason = "BUDGET_EXHAUSTED"
                    stop_detail = f"wall-clock budget exhausted after {index} products"
                    pending = [{"source_url": remaining, "reason": "budget_exhausted"} for remaining in selected[index:]]
                    break
                try:
                    product_response = fetch(session, url, "product")
                except AccessDenied:
                    raise
                except HttpError as exc:
                    failed.append({"source_url": url, "reason": f"http_{exc.status}", "detail": str(exc)})
                    audits.append({"source_url": url, "outcome": "failed", "reason": f"http_{exc.status}"})
                    emit("product_failed", source_url=url, reason=f"http_{exc.status}")
                    consecutive_failures += 1
                    if consecutive_failures >= args.max_consecutive_failures:
                        raise RuntimeError(f"{consecutive_failures} consecutive product failures")
                    continue
                except (RuntimeError, TimeoutError) as exc:
                    failed.append({"source_url": url, "reason": "request_failed", "detail": str(exc)})
                    audits.append({"source_url": url, "outcome": "failed", "reason": "request_failed"})
                    emit("product_failed", source_url=url, reason="request_failed")
                    consecutive_failures += 1
                    if consecutive_failures >= args.max_consecutive_failures:
                        raise RuntimeError(f"{consecutive_failures} consecutive product failures")
                    continue
                consecutive_failures = 0
                product_html = response_html(product_response)
                try:
                    product_doc = LH.fromstring(product_html)
                except (etree.ParserError, ValueError) as exc:
                    failed.append({"source_url": url, "reason": "html_parse_error", "detail": str(exc)})
                    audits.append({"source_url": url, "outcome": "failed", "reason": "html_parse_error"})
                    emit("product_failed", source_url=url, reason="html_parse_error")
                    continue
                canonical = canonical_url(product_doc, url)
                products = find_products(parse_jsonld(product_doc))
                product = select_product(products, canonical)
                row, audit = build_row(product, product_doc, canonical, url, EXPECTED_CURRENCY)
                audit["jsonld_products"] = len(products)
                duplicate = any(item.get("source_url") == canonical for item in rows) or any(
                    item.get("source_url") == canonical for item in excluded
                )
                if row is None or duplicate:
                    if duplicate:
                        audit["reason"] = "duplicate_source_url"
                        audit["outcome"] = "excluded"
                    excluded.append(audit)
                    audits.append(audit)
                    emit("product_excluded", source_url=canonical, reason=audit.get("reason"))
                else:
                    rows.append(row)
                    audits.append(audit)
                    emit(
                        "product_valid",
                        source_url=canonical,
                        price=row["price_amount"],
                        currency=row["price_currency"],
                        description_status=audit["description_status"],
                        price_unit=audit["price_unit"],
                    )
            if stop_reason == "NATURAL_END" and category_total_value and len(selected) < category_total_value:
                stop_reason = "BUDGET_EXHAUSTED"
                stop_detail = (
                    f"task cap reached: processed {len(selected)} products; "
                    f"category page declares {category_total_value}"
                )
    except (AccessDenied, PlanError, RuntimeError, TimeoutError) as exc:
        stop_reason = "ACCESS_DENIED" if isinstance(exc, AccessDenied) else "PLAN_ERROR"
        stop_detail = str(exc)
        errors.append({"class": type(exc).__name__, "message": str(exc)})
        emit("run_stop", reason=stop_reason, detail=stop_detail)
    finally:
        events_handle.close()

    finished = utc_now()
    elapsed = round((finished - started).total_seconds(), 2)
    valid = len(rows)
    processed = valid + len(excluded) + len(failed)
    candidates = len(selected)
    unit_counts: dict[str, int] = {}
    for audit in audits:
        if audit.get("outcome") == "valid":
            key = str(audit.get("price_unit") or "unknown")
            unit_counts[key] = unit_counts.get(key, 0) + 1
    quality_exceptions = [
        {
            "source_url": audit["source_url"],
            "description_status": audit.get("description_status"),
            "partial_reason": audit.get("partial_reason"),
            "missing_reasons": audit.get("missing_reasons") or {},
        }
        for audit in audits
        if audit.get("outcome") == "valid"
        and (audit.get("description_status") != "complete" or audit.get("missing_reasons"))
    ]
    if stop_reason == "NATURAL_END" and not errors and not failed and processed == candidates:
        outcome = "COMPLETED"
    elif valid == 0:
        outcome = "FAILED"
    else:
        outcome = "PARTIAL"
    coverage = {
        "status": "PARTIAL" if category_total_value and valid < category_total_value else "KNOWN",
        "denominator_source": "Candy Unwrapped category page toolbar item count",
        "denominator": category_total_value,
        "covered": valid,
        "notes": (
            "Candy Unwrapped category page 1; bounded 30-product sample. "
            "Build-time /all-products page showed 'Items 1-30 of 2381'; "
            "that is not this run's discovery denominator and is not a full-site claim."
        ),
    }
    task_result = {
        "task_id": f"d01-shopthebulkstore-{args.label}-{finished.strftime('%Y%m%dT%H%M%SZ')}",
        "plan_id": "shopthebulkstore-us-d01",
        "plan_version": "2026.11.20-1",
        "market": MARKET,
        "locale": LOCALE,
        "state": "FINISHED",
        "outcome": outcome,
        "stop_reason": stop_reason,
        "stop_detail": stop_detail,
        "started_at": iso(started),
        "finished_at": iso(finished),
        "counts": {
            "discovered_urls": discovery_urls + candidates,
            "pending_navigation_entries": 0,
            "product_candidates": candidates,
            "pending_products": len(pending),
            "in_flight_products": 0,
            "processed_products": processed,
            "valid_products": valid,
            "excluded_products": len(excluded),
            "failed_products": len(failed),
            "partial_description_products": sum(
                1 for audit in audits
                if audit.get("outcome") == "valid" and audit.get("description_status") == "partial"
            ),
            "description_not_provided_products": sum(
                1 for audit in audits
                if audit.get("outcome") == "valid" and audit.get("description_status") == "not_provided"
            ),
            "description_fallback_products": sum(
                1 for audit in audits
                if audit.get("outcome") == "valid" and audit.get("description_status") == "fallback"
            ),
        },
        "coverage": coverage,
        "business_acceptance": {
            "status": "NOT_REVIEWED",
            "accepted_by": None,
            "accepted_at": None,
            "reason": None,
            "scope": "bounded 30-product shopthebulkstore.com Candy Unwrapped category run",
        },
        "runtime": {
            "llm_calls": 0,
            "raw_pages_retained": False,
            "browser_launched": False,
            "http_engine": "scrapling.FetcherSession (curl_cffi, static HTML)",
            "concurrency": 1,
            "request_interval_seconds": args.delay,
            "max_attempts": args.max_attempts,
        },
        "quality_exceptions": quality_exceptions,
        "errors": errors,
        "warnings": warnings,
        "limitations": [
            "Category page 1 only; 30 of 62 Candy Unwrapped products, not a full-site claim.",
            "Static HTML path only; no browser fingerprint or challenge handling was exercised.",
            "Price is recorded as the public per-unit price (often per lb); it is not multiplied by package weight.",
            "Out-of-stock products with a public price remain valid; add-to-cart visibility is not a validity rule.",
            "Descriptions come from the overview/description DOM blocks; JSON-LD descriptions are fallback only.",
            "No login, cart, checkout, account, review or catalogsearch endpoints are requested.",
        ],
        "artifacts": {
            "valid_csv": "valid.csv",
            "run_summary": "run-summary.json",
            "diagnostics_dir": f"diagnostics/{args.label}/",
        },
        "discovery": {
            "entry_url": CATEGORY_URL,
            "category_url": CATEGORY_URL,
            "category_total": category_total_value,
            "category_page_products": len(category_links),
            "selected_products": len(selected),
            "sitemap_url": SITEMAP_URL,
            "sitemap_status": sitemap_status,
            "sitemap_locs": len(sitemap_locs),
            "sitemap_cross_check": {
                "matched": sitemap_matched,
                "total": len(selected),
            },
            "price_unit_counts": unit_counts,
        },
    }
    summary = {
        "task_id": task_result["task_id"],
        "label": args.label,
        "plan_id": task_result["plan_id"],
        "plan_version": task_result["plan_version"],
        "run_started_at": iso(started),
        "run_finished_at": iso(finished),
        "elapsed_s": elapsed,
        "state": "FINISHED",
        "outcome": outcome,
        "stop_reason": stop_reason,
        "stop_detail": stop_detail,
        "counts": task_result["counts"],
        "coverage": coverage,
        "requests": requests,
        "retries": retries,
        "per_purpose": per_purpose,
        "per_status": per_status,
        "errors": errors,
        "warnings": warnings,
        "discovery": task_result["discovery"],
        "product_audits": audits,
    }
    meta = {
        "task_id": task_result["task_id"],
        "label": args.label,
        "command": " ".join(sys.argv),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "proxy_env_present": bool(os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")),
    }
    write_csv(out_dir / "valid.csv", rows)
    write_json(out_dir / "task-result.json", task_result)
    write_json(out_dir / "run-summary.json", summary)
    write_json(run_dir / "run-summary.json", summary)
    write_json(run_dir / "run-meta.json", meta)
    write_jsonl(run_dir / "product-audit.jsonl", audits)
    write_csv_rows(
        run_dir / "excluded_products.csv",
        excluded,
        ["source_url", "reason", "name", "price_amount", "price_currency"],
    )
    write_csv_rows(run_dir / "failed_products.csv", failed, ["source_url", "reason", "detail"])
    write_csv_rows(run_dir / "pending_products.csv", pending, ["source_url", "reason"])
    print(
        json.dumps(
            {
                "task_id": task_result["task_id"],
                "outcome": outcome,
                "stop_reason": stop_reason,
                "counts": task_result["counts"],
                "requests": requests,
                "elapsed_s": elapsed,
                "discovery": task_result["discovery"],
                "valid_csv": str(out_dir / "valid.csv"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
