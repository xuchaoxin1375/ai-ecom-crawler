"""D01 S6 campsaver.com extraction plan.

The challenge-site fetch is done by the resilient-browser-fetch late-attach
tools (system Chrome, no headless matrix). This program reads those saved HTML
pages and produces the 9-column business CSV without another network request.

Usage:
  python run.py --batch-dir <batch-001> --batch-dir <batch-002> `
    --order-file category-product-urls.txt --out-dir . --label d01-run-001
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from lxml import etree, html as LH

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
EXPECTED_CURRENCY = "USD"
MARKET = "US"
LOCALE = "en-US"
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
CHALLENGE_TITLES = ("access denied", "before we continue", "just a moment", "attention required")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_space(value: object) -> str:
    return " ".join(str(value or "").split())


def clean_html(raw: str | None) -> tuple[str, str]:
    """Return (cleaned_html, status). Status: complete/not_provided/failed."""
    if not raw or not str(raw).strip():
        return "", "not_provided"
    try:
        root = LH.fromstring(f"<div>{raw}</div>")
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
            # Some review bodies contain literal newlines; strict=False accepts them.
            blocks.append(json.loads(raw, strict=False))
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
        if normalize_space(product.get("name")):
            score += 1
        if score > best_score:
            best = product
            best_score = score
    return best


def offers_list(product: dict | None) -> list[dict]:
    if not product:
        return []
    offers = product.get("offers")
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        return []
    return [offer for offer in offers if isinstance(offer, dict)]


def offer_summary(offers: list[dict]) -> dict:
    prices: list[tuple[float, str]] = []
    availability: list[str] = []
    conditions: list[str] = []
    skus: list[str] = []
    for offer in offers:
        raw = offer.get("lowPrice") if offer.get("@type") == "AggregateOffer" else offer.get("price")
        if raw is None and offer.get("@type") == "AggregateOffer":
            raw = offer.get("price")
        try:
            price = float(raw)
        except (TypeError, ValueError):
            price = None
        currency = normalize_space(offer.get("priceCurrency")).upper() or None
        if price is not None and math.isfinite(price) and price > 0 and currency:
            prices.append((price, currency))
        value = normalize_space(offer.get("availability"))
        if value and value not in availability:
            availability.append(value)
        value = normalize_space(offer.get("itemCondition"))
        if value and value not in conditions:
            conditions.append(value)
        value = normalize_space(offer.get("sku"))
        if value and value not in skus:
            skus.append(value)
    prices.sort(key=lambda item: item[0])
    return {
        "price": prices[0][0] if prices else None,
        "currency": prices[0][1] if prices else None,
        "availability": availability,
        "conditions": conditions,
        "skus": skus,
    }


def parse_image(product: dict | None) -> str:
    if not product:
        return ""
    image = product.get("image")
    if isinstance(image, list) and image:
        image = image[0]
    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")
    if not isinstance(image, str):
        return ""
    image = normalize_space(image)
    if image.startswith("//"):
        image = "https:" + image
    if image.startswith("http://"):
        image = "https://" + image[len("http://"):]
    return image if image.startswith("https://") else ""


def parse_brand(product: dict | None) -> str:
    if not product:
        return ""
    brand = product.get("brand")
    if isinstance(brand, list) and brand:
        brand = brand[0]
    if isinstance(brand, dict):
        brand = brand.get("name")
    value = normalize_space(brand)
    if value:
        return value
    return normalize_space(product.get("manufacturer"))


def parse_breadcrumbs(doc) -> list[str]:
    values = []
    for anchor in doc.xpath("//*[contains(@class,'breadcrumb')]//a"):
        text = normalize_space(anchor.text_content())
        if text and text.lower() != "home" and text not in values:
            values.append(text)
    return values


def parse_description(product: dict | None, doc, name: str) -> tuple[str, str, str | None]:
    raw = normalize_space((product or {}).get("description"))
    if raw:
        cleaned, status = clean_html(raw)
        if status == "complete":
            text = normalize_space(LH.fromstring(cleaned).text_content())
            if len(re.sub(r"[^A-Za-z0-9]+", "", text)) >= 80:
                return cleaned, "complete", None
            return cleaned, "partial", "JSON-LD 描述过短，未提供独立商品正文"
        return "", "failed", "JSON-LD 描述清洗失败"
    for node in doc.xpath("//*[@itemprop='description'] | //*[contains(@class,'product-description')]"):
        cleaned, status = clean_html(LH.tostring(node, encoding="unicode"))
        if status == "complete":
            return cleaned, "fallback", "未取得 JSON-LD 描述，使用 DOM 描述"
    return "", "not_provided", None


def escape_option(value: str) -> str:
    return value.replace("\\", "\\\\").replace("#", "\\#").replace("|", "\\|").replace("~", "\\~")


def add_option(parts: list[tuple[str, list[str]]], label: str, values: list[str]) -> None:
    label = normalize_space(label)
    if not label or label.lower() in {"quantity", "qty"}:
        return
    cleaned = []
    for value in values:
        text = normalize_space(value)
        if text and text not in cleaned:
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


def parse_variant_attributes(doc) -> tuple[str, int]:
    for script in doc.xpath("//script[@type='application/json']"):
        raw = script.text or ""
        if '"variantSelector"' not in raw:
            continue
        try:
            payload = json.loads(raw, strict=False)
        except json.JSONDecodeError:
            continue
        variants = ((payload.get("variantSelector") or {}).get("variants")) or []
        if not isinstance(variants, list):
            continue
        values_by_name: dict[str, list[str]] = {}
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            for spec in variant.get("specifications") or []:
                if not isinstance(spec, dict):
                    continue
                if not spec.get("is_differential"):
                    continue
                name = normalize_space(spec.get("name"))
                for value in spec.get("values") or []:
                    if not isinstance(value, dict):
                        continue
                    text = normalize_space(value.get("value"))
                    uom = normalize_space(value.get("uom"))
                    if text:
                        text = f"{text} {uom}" if uom else text
                    if name and text:
                        values_by_name.setdefault(name, [])
                        if text not in values_by_name[name]:
                            values_by_name[name].append(text)
        parts: list[tuple[str, list[str]]] = []
        for name, values in values_by_name.items():
            add_option(parts, name, values)
        if parts:
            return "~".join(
                f"{escape_option(label)}#{'|'.join(escape_option(value) for value in values)}"
                for label, values in parts
            ), len(variants)
    return "", 0


def canonical_url(doc, fetched_url: str) -> str:
    values = doc.xpath("//link[@rel='canonical']/@href")
    candidate = normalize_space(values[0]) if values else fetched_url
    candidate = candidate or fetched_url
    parts = urlsplit(candidate)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def format_amount(value: float) -> str:
    return f"{value:.2f}"


def protect_text(value: str) -> str:
    return "'" + value if TEXT_HANDLER_RE.match(value) else value


def build_row(product: dict | None, doc, canonical: str) -> tuple[dict | None, dict]:
    name = normalize_space((product or {}).get("name"))
    offers = offers_list(product)
    summary = offer_summary(offers)
    image = parse_image(product)
    breadcrumbs = parse_breadcrumbs(doc)
    category = breadcrumbs[-1] if breadcrumbs else ""
    if category and name and category.lower() == name.lower() and len(breadcrumbs) > 1:
        category = breadcrumbs[-2]
    brand = parse_brand(product)
    description_html, description_status, partial_reason = parse_description(product, doc, name)
    attributes, variant_count = parse_variant_attributes(doc)
    missing: dict[str, str] = {}
    if not category:
        missing["category"] = "not_provided"
    if not brand:
        missing["brand"] = "not_provided"
    if description_status != "complete":
        missing["description"] = description_status
    audit = {
        "source_url": canonical,
        "name": name,
        "price_amount": format_amount(summary["price"]) if summary["price"] is not None else "",
        "price_currency": summary["currency"] or "",
        "description_status": description_status,
        "description_chars": len(description_html),
        "category": category,
        "brand": brand,
        "attributes": attributes,
        "availability": summary["availability"],
        "offer_count": len(offers),
        "offer_conditions": summary["conditions"],
        "variant_count": variant_count,
        "missing_reasons": missing,
    }
    if partial_reason:
        audit["partial_reason"] = partial_reason
    if not canonical:
        return None, {**audit, "outcome": "excluded", "reason": "missing_source_url"}
    if not name:
        return None, {**audit, "outcome": "excluded", "reason": "missing_name"}
    if summary["price"] is None:
        return None, {**audit, "outcome": "excluded", "reason": "zero_or_missing_price"}
    if not summary["currency"] or not CURRENCY_RE.match(summary["currency"]):
        return None, {**audit, "outcome": "excluded", "reason": "missing_currency"}
    if summary["currency"] != EXPECTED_CURRENCY:
        return None, {**audit, "outcome": "excluded", "reason": "unexpected_currency"}
    if not image:
        return None, {**audit, "outcome": "excluded", "reason": "missing_primary_image"}
    row = {
        "name": name,
        "price_amount": format_amount(summary["price"]),
        "price_currency": summary["currency"],
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


def _sanitized_command(argv: list[str]) -> str:
    cleaned = list(argv)
    for index, value in enumerate(cleaned):
        if index > 0 and cleaned[index - 1] == "--batch-dir":
            cleaned[index] = "<batch-dir>"
    return " ".join(cleaned)


def load_batches(batch_dirs: list[Path]) -> tuple[list[dict], list[str]]:
    entries: list[dict] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for directory in batch_dirs:
        manifest = directory / "batch.json"
        if not manifest.is_file():
            warnings.append(f"missing batch.json: {directory}")
            continue
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            warnings.append(f"batch.json is not a list: {directory}")
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            url = normalize_space(item.get("url"))
            if not url or url in seen:
                continue
            seen.add(url)
            item = dict(item)
            item["source_file"] = str(item.get("file") or "")
            item["batch_dir"] = Path(directory).name
            item["file"] = Path(item["source_file"]).name
            entries.append(item)
    return entries, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract the campsaver 9-column CSV from saved late-attach HTML")
    parser.add_argument("--batch-dir", action="append", required=True, help="directory containing batch.json and saved HTML")
    parser.add_argument("--order-file", help="category-order URL list; default sort by name")
    parser.add_argument("--category-summary", default="category-summary.json", help="category metadata JSON")
    parser.add_argument("--out-dir", default=".", help="output directory")
    parser.add_argument("--label", default="d01-run-001", help="diagnostics subdirectory label")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    run_dir = out_dir / "diagnostics" / args.label
    run_dir.mkdir(parents=True, exist_ok=True)
    started = utc_now()
    errors: list[dict] = []
    warnings: list[str] = []
    rows: list[dict] = []
    audits: list[dict] = []
    excluded: list[dict] = []
    failed: list[dict] = []
    pending: list[dict] = []

    entries, load_warnings = load_batches([Path(item) for item in args.batch_dir])
    warnings.extend(load_warnings)
    by_url = {item["url"]: item for item in entries}
    if args.order_file:
        order = [
            line.strip()
            for line in Path(args.order_file).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        ordered = [url for url in order if url in by_url]
        missing = [url for url in order if url not in by_url]
        for url in missing:
            failed.append({"source_url": url, "reason": "missing_saved_page", "detail": "no batch entry"})
            audits.append({"source_url": url, "outcome": "failed", "reason": "missing_saved_page"})
    else:
        ordered = sorted(by_url, key=lambda url: ((by_url[url].get("title") or "").lower(), url))
    if not ordered:
        errors.append({"class": "PlanError", "message": "no saved pages found"})

    for url in ordered:
        entry = by_url[url]
        state = normalize_space(entry.get("state"))
        title = normalize_space(entry.get("title"))
        if state != "content" or any(marker in title.lower() for marker in CHALLENGE_TITLES):
            failed.append(
                {
                    "source_url": url,
                    "reason": "challenge_or_empty",
                    "detail": f"state={state!r} title={title!r}",
                }
            )
            audits.append(
                {
                    "source_url": url,
                    "outcome": "failed",
                    "reason": "challenge_or_empty",
                    "title": title,
                    "state": state,
                }
            )
            continue
        path = Path(entry.get("source_file") or entry.get("file") or "")
        if not path.is_file():
            failed.append({"source_url": url, "reason": "missing_html", "detail": str(path)})
            audits.append({"source_url": url, "outcome": "failed", "reason": "missing_html"})
            continue
        try:
            doc = LH.fromstring(path.read_text(encoding="utf-8"))
        except (OSError, etree.ParserError, ValueError) as exc:
            failed.append({"source_url": url, "reason": "html_parse_error", "detail": str(exc)})
            audits.append({"source_url": url, "outcome": "failed", "reason": "html_parse_error"})
            continue
        canonical = canonical_url(doc, url)
        products = find_products(parse_jsonld(doc))
        product = select_product(products, canonical)
        if product is None:
            failed.append({"source_url": canonical, "reason": "no_product_jsonld", "detail": title})
            audits.append(
                {
                    "source_url": canonical,
                    "outcome": "failed",
                    "reason": "no_product_jsonld",
                    "title": title,
                    "jsonld_products": len(products),
                }
            )
            continue
        row, audit = build_row(product, doc, canonical)
        audit["title"] = title
        audit["batch_dir"] = entry.get("batch_dir")
        audit["jsonld_products"] = len(products)
        duplicate = any(item.get("source_url") == canonical for item in rows) or any(
            item.get("source_url") == canonical for item in excluded
        )
        if row is None or duplicate:
            if duplicate:
                audit["outcome"] = "excluded"
                audit["reason"] = "duplicate_source_url"
            excluded.append(audit)
            audits.append(audit)
        else:
            rows.append(row)
            audits.append(audit)

    finished = utc_now()
    elapsed = round((finished - started).total_seconds(), 2)
    category_summary: dict = {}
    summary_path = Path(args.category_summary)
    if not summary_path.is_absolute():
        summary_path = out_dir / summary_path
    if summary_path.is_file():
        category_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    category_total = category_summary.get("total")
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
    valid = len(rows)
    processed = valid + len(excluded) + len(failed)
    coverage = {
        "status": "PARTIAL" if category_total and valid < category_total else "KNOWN",
        "denominator_source": category_summary.get("denominator_source", "Sleeping Pads category page total"),
        "denominator": category_total,
        "covered": valid,
        "notes": (
            "Sleeping Pads category page 1; bounded 30-product sample. "
            "The category page title said 144 products; this is not a full-site claim."
        ),
    }
    task_result = {
        "task_id": f"d01-campsaver-{args.label}-{finished.strftime('%Y%m%dT%H%M%SZ')}",
        "plan_id": "campsaver-us-d01",
        "plan_version": "2026.11.20-1",
        "market": MARKET,
        "locale": LOCALE,
        "state": "FINISHED",
        "outcome": "PARTIAL",
        "stop_reason": "BUDGET_EXHAUSTED",
        "stop_detail": "task cap reached: processed 30 of 144 Sleeping Pads products",
        "started_at": iso(started),
        "finished_at": iso(finished),
        "counts": {
            "discovered_urls": 1 + len(ordered),
            "pending_navigation_entries": 0,
            "product_candidates": len(ordered),
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
            "scope": "bounded 30-product campsaver.com Sleeping Pads category run",
        },
        "runtime": {
            "llm_calls": 0,
            "raw_pages_retained": False,
            "browser_launched": True,
            "http_engine": "system Chrome via chrome-late late attach (resilient-browser-fetch); extraction offline",
            "concurrency": "3-10 tabs per batch (pilot); recommended 3-5",
            "browser_batch_sizes": category_summary.get("batch_sizes") or [3, 10, 10, 7],
            "early_readiness": "title change + Product JSON-LD; no image/networkidle wait",
            "requests": category_summary.get("target_requests"),
        },
        "quality_exceptions": quality_exceptions,
        "errors": errors,
        "warnings": warnings,
        "limitations": [
            "Sleeping Pads category page 1 only; 30 of 144 products, not a full-site claim.",
            "Challenge-site fetch depends on the resilient-browser-fetch late-attach tools and system Chrome; the extraction is offline.",
            "Pilot batches were 3/10/10/7 tabs; 10-tab batches exceed the recommended 3-5 and are recorded as a limitation.",
            "Raw HTML pages are kept in temporary storage only and are not committed.",
            "Product variants are not split into separate rows; price is the minimum public offer and attributes list differential options when present.",
            "Prices, availability and BackOrder dates are a snapshot; no login, cart, checkout or account access was used.",
        ],
        "artifacts": {
            "valid_csv": "valid.csv",
            "run_summary": "run-summary.json",
            "diagnostics_dir": f"diagnostics/{args.label}/",
        },
        "discovery": {
            "entry_url": category_summary.get("url"),
            "category_total": category_total,
            "category_page_cards": category_summary.get("page_cards"),
            "selected_products": len(ordered),
            "batch_sizes": category_summary.get("batch_sizes"),
            "product_sample_url": category_summary.get("product_sample_url"),
            "target_requests": category_summary.get("target_requests"),
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
        "outcome": task_result["outcome"],
        "stop_reason": task_result["stop_reason"],
        "counts": task_result["counts"],
        "coverage": coverage,
        "requests": category_summary.get("target_requests"),
        "errors": errors,
        "warnings": warnings,
        "discovery": task_result["discovery"],
        "product_audits": audits,
    }
    meta = {
        "task_id": task_result["task_id"],
        "label": args.label,
        "command": _sanitized_command(sys.argv),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "batch_dirs": [Path(item).name for item in args.batch_dir],
    }
    write_csv(out_dir / "valid.csv", rows)
    write_json(out_dir / "task-result.json", task_result)
    write_json(out_dir / "run-summary.json", summary)
    write_json(run_dir / "run-summary.json", summary)
    write_json(run_dir / "run-meta.json", meta)
    write_json(run_dir / "batch-summary.json", [
        {key: value for key, value in entry.items() if key != "source_file"}
        for entry in entries
    ])
    write_json(run_dir / "category-summary.json", category_summary)
    write_jsonl(run_dir / "product-audit.jsonl", audits)
    write_csv_rows(run_dir / "excluded_products.csv", excluded, ["source_url", "reason", "name", "price_amount", "price_currency"])
    write_csv_rows(run_dir / "failed_products.csv", failed, ["source_url", "reason", "detail"])
    write_csv_rows(run_dir / "pending_products.csv", pending, ["source_url", "reason"])
    print(
        json.dumps(
            {
                "task_id": task_result["task_id"],
                "outcome": task_result["outcome"],
                "counts": task_result["counts"],
                "coverage": coverage,
                "valid_csv": str(out_dir / "valid.csv"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
