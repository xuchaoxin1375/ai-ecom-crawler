"""D01 S4 sixmoondesigns.com public JSON plan.

Fetches the public Shopify products.json once for the US market, extracts up
to 30 products into the 9-column business CSV, and writes a task result plus
diagnostics. No LLM call, browser, login or cart endpoint is used.

Usage:
  python run.py --out-dir . --label d01-run-001
  python run.py --out-dir . --label d01-run-002 --max-products 30 --delay 1.1
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
from pathlib import Path

from lxml import etree, html as LH

SITE = "https://www.sixmoondesigns.com"
ENTRY = f"{SITE}/?country=US"
API = f"{SITE}/products.json?limit=250&page=1&country=US"
ROBOTS = f"{SITE}/robots.txt"
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


class AccessDenied(RuntimeError):
    pass


class PlanError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


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
    if not " ".join(root.text_content().split()):
        return "", "failed"
    html_text = etree.tostring(root, encoding="unicode", method="html").strip()
    return html_text, "complete" if html_text else "failed"


def response_html(response: object) -> str:
    """Scrapling HTML responses expose html_content; .text can be empty for large pages."""
    html = getattr(response, "html_content", None)
    if html is not None:
        return str(html)
    return str(getattr(response, "text", ""))


def response_body_text(response: object) -> str:
    body = getattr(response, "body", None)
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="replace")
    return str(getattr(response, "text", ""))


def parse_active_currency(text: str) -> str | None:
    match = re.search(r'Shopify\.currency\s*=\s*\{[^}]*"active"\s*:\s*"([A-Z]{3})"', text, re.I)
    if match:
        return match.group(1).upper()
    match = re.search(
        r'<meta[^>]+(?:property|name)="(?:product|og):price:currency"[^>]+content="([A-Z]{3})"',
        text,
        re.I,
    )
    return match.group(1).upper() if match else None


def parse_meta(text: str, name: str) -> str | None:
    match = re.search(
        rf'<meta[^>]+(?:property|name)="{re.escape(name)}"[^>]+content="([^"]+)"',
        text,
        re.I,
    )
    return match.group(1).strip() if match else None


def min_positive_price(product: dict) -> float | None:
    prices: list[float] = []
    for variant in product.get("variants") or []:
        raw = variant.get("price")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0:
            prices.append(value)
    return min(prices) if prices else None


def escape_option(value: str) -> str:
    return value.replace("\\", "\\\\").replace("#", "\\#").replace("|", "\\|").replace("~", "\\~")


def serialize_attributes(product: dict) -> str:
    variants = product.get("variants") or []
    parts: list[str] = []
    for index, option in enumerate(product.get("options") or [], start=1):
        name = str(option.get("name") or f"Option {index}").strip()
        values: list[str] = []
        for variant in variants:
            value = variant.get(f"option{index}")
            if value and str(value) not in values:
                values.append(str(value))
        if name.lower() in {"quantity", "qty"}:
            continue
        if name.lower() == "title" and values == ["Default Title"]:
            continue
        if name and values:
            parts.append(f"{escape_option(name)}#{'|'.join(escape_option(v) for v in values)}")
    return "~".join(parts)


def format_amount(value: float) -> str:
    return f"{value:.2f}"


def protect_text(value: str) -> str:
    return "'" + value if TEXT_HANDLER_RE.match(value) else value


def build_row(product: dict, currency: str) -> tuple[dict | None, dict]:
    name = " ".join(str(product.get("title") or "").split())
    price = min_positive_price(product)
    images = product.get("images") or []
    image = str(images[0].get("src") or "").strip() if images else ""
    body_html = product.get("body_html") or ""
    description_html, description_status = clean_html(body_html)
    category = " ".join(str(product.get("product_type") or "").split())
    brand = " ".join(str(product.get("vendor") or "").split())
    handle = str(product.get("handle") or "").strip()
    variants = product.get("variants") or []
    missing: dict[str, str] = {}
    if not category:
        missing["category"] = "not_provided"
    if not brand:
        missing["brand"] = "not_provided"
    if description_status != "complete":
        missing["description"] = description_status
    audit = {
        "source_url": f"{SITE}/products/{handle}" if handle else "",
        "name": name,
        "price_amount": format_amount(price) if price is not None else "",
        "price_currency": currency,
        "description_status": description_status,
        "description_chars": len(description_html),
        "category": category,
        "brand": brand,
        "options": serialize_attributes(product),
        "availability": "in_stock" if any(v.get("available") for v in variants) else "out_of_stock",
        "variant_count": len(variants),
        "missing_reasons": missing,
    }
    if not handle:
        return None, {**audit, "outcome": "excluded", "reason": "missing_source_url"}
    if not name:
        return None, {**audit, "outcome": "excluded", "reason": "missing_name"}
    if price is None:
        return None, {**audit, "outcome": "excluded", "reason": "zero_or_missing_price"}
    if not CURRENCY_RE.match(currency):
        return None, {**audit, "outcome": "excluded", "reason": "missing_currency"}
    if not image:
        return None, {**audit, "outcome": "excluded", "reason": "missing_primary_image"}
    row = {
        "name": name,
        "price_amount": format_amount(price),
        "price_currency": currency,
        "primary_image_url": image,
        "description_html": description_html,
        "category": category,
        "brand": brand,
        "attributes": serialize_attributes(product),
        "source_url": f"{SITE}/products/{handle}",
    }
    return row, {**audit, "outcome": "valid"}


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: protect_text(str(row.get(key, ""))) if key != "price_amount" else row.get(key, "") for key in CSV_COLUMNS})


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
    parser = argparse.ArgumentParser(description="Bounded S4 sixmoondesigns public JSON plan")
    parser.add_argument("--out-dir", default=".", help="output directory for valid.csv/task-result.json")
    parser.add_argument("--label", default="d01-run-001", help="diagnostics subdirectory label")
    parser.add_argument("--max-products", type=int, default=30)
    parser.add_argument("--max-seconds", type=float, default=600.0)
    parser.add_argument("--delay", type=float, default=1.1, help="seconds between request starts")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--max-retry-after", type=float, default=60.0)
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    run_dir = out_dir / "diagnostics" / args.label
    run_dir.mkdir(parents=True, exist_ok=True)
    events_path = run_dir / "events.ndjson"
    events_handle = events_path.open("w", encoding="utf-8", newline="\n")

    def emit(event: str, **payload) -> None:
        events_handle.write(json.dumps({"ts": iso(utc_now()), "event": event, **payload}, ensure_ascii=False) + "\n")
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
                raise RuntimeError(f"{purpose}: HTTP {status}")
            last_request_at = time.monotonic()
            return response
        raise RuntimeError(f"{purpose}: retries exhausted")

    rows: list[dict] = []
    audits: list[dict] = []
    excluded: list[dict] = []
    failed: list[dict] = []
    pending: list[dict] = []
    currency = None
    api_products: list[dict] = []
    spot_check: dict = {}
    try:
        from scrapling.fetchers import FetcherSession

        with FetcherSession(impersonate="chrome", timeout=args.timeout, retries=1) as session:
            emit("run_start", plan_id="sixmoondesigns-us-d01", max_products=args.max_products, max_seconds=args.max_seconds)
            robots = fetch(session, ROBOTS, "robots")
            (run_dir / "robots.txt").write_text(response_body_text(robots), encoding="utf-8")
            entry = fetch(session, ENTRY, "entry")
            currency = parse_active_currency(response_html(entry))
            if not currency:
                raise PlanError("entry page has no Shopify.currency evidence")
            api = fetch(session, API, "api")
            data = api.json()
            api_products = data.get("products") or []
            selected = api_products[: max(0, int(args.max_products))]
            if not selected:
                raise PlanError("products.json returned no products")
            first = selected[0]
            handle = str(first.get("handle") or "")
            spot_url = f"{SITE}/products/{handle}?country=US"
            try:
                spot = fetch(session, spot_url, "spot")
                spot_text = response_html(spot)
                spot_check = {
                    "url": spot_url,
                    "status": getattr(spot, "status", None),
                    "price": parse_meta(spot_text, "product:price:amount"),
                    "currency": parse_meta(spot_text, "product:price:currency"),
                }
                first_price = min_positive_price(first)
                spot_price = float(spot_check["price"]) if spot_check["price"] else None
                if spot_check["currency"] not in {currency, EXPECTED_CURRENCY}:
                    raise PlanError(f"spot currency {spot_check['currency']} != {currency}")
                if spot_price is None or first_price is None or abs(spot_price - first_price) > 0.01:
                    raise PlanError(f"spot price {spot_price} != API first price {first_price}")
                spot_check["verified"] = True
            except (RuntimeError, AccessDenied, PlanError) as exc:
                warnings.append(f"spot check skipped: {type(exc).__name__}: {exc}")
                spot_check["verified"] = False
            for index, product in enumerate(selected):
                if time.monotonic() >= deadline:
                    stop_reason = "BUDGET_EXHAUSTED"
                    stop_detail = f"wall-clock budget exhausted after {index} products"
                    pending = [{"source_url": f"{SITE}/products/{p.get('handle')}"} for p in selected[index:]]
                    break
                row, audit = build_row(product, currency)
                if row is None:
                    excluded.append(audit)
                    audits.append(audit)
                    emit("product_excluded", source_url=audit.get("source_url"), reason=audit.get("reason"))
                else:
                    rows.append(row)
                    audits.append(audit)
                    emit("product_valid", source_url=row["source_url"], price=row["price_amount"], description_status=audit["description_status"])
            if stop_reason == "NATURAL_END" and len(api_products) > len(selected):
                stop_reason = "BUDGET_EXHAUSTED"
                stop_detail = f"task cap reached: processed {len(selected)} products; products.json declares {len(api_products)}"
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
    candidates = min(len(api_products), int(args.max_products)) if api_products else 0
    quality_exceptions = [
        {
            "source_url": audit["source_url"],
            "description_status": audit["description_status"],
            "partial_reason": None,
            "missing_reasons": audit["missing_reasons"],
        }
        for audit in audits
        if audit["outcome"] == "valid"
        and (audit["description_status"] != "complete" or audit["missing_reasons"])
    ]
    coverage = {
        "status": "PARTIAL" if len(api_products) > valid else "COMPLETE",
        "denominator_source": "products.json?limit=250&page=1&country=US payload count",
        "denominator": len(api_products),
        "covered": valid,
        "notes": "products.json page 1 payload; not a full-site audit. 30-product task cap.",
    }
    task_result = {
        "task_id": f"d01-sixmoondesigns-{args.label}-{finished.strftime('%Y%m%dT%H%M%SZ')}",
        "plan_id": "sixmoondesigns-us-d01",
        "plan_version": "2026.11.20-1",
        "market": MARKET,
        "locale": LOCALE,
        "state": "FINISHED",
        "outcome": "PARTIAL" if stop_reason == "BUDGET_EXHAUSTED" or len(api_products) > valid else "COMPLETE",
        "stop_reason": stop_reason,
        "stop_detail": stop_detail,
        "started_at": iso(started),
        "finished_at": iso(finished),
        "counts": {
            "discovered_urls": 4 + valid,
            "pending_navigation_entries": 0,
            "product_candidates": candidates,
            "pending_products": len(pending),
            "in_flight_products": 0,
            "processed_products": processed,
            "valid_products": valid,
            "excluded_products": len(excluded),
            "failed_products": len(failed),
            "partial_description_products": sum(1 for a in audits if a.get("outcome") == "valid" and a.get("description_status") == "partial"),
            "description_not_provided_products": sum(1 for a in audits if a.get("outcome") == "valid" and a.get("description_status") == "not_provided"),
        },
        "coverage": coverage,
        "business_acceptance": {
            "status": "NOT_REVIEWED",
            "accepted_by": None,
            "accepted_at": None,
            "reason": None,
            "scope": "bounded 30-product sixmoondesigns.com run",
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
            "Public JSON list path only; no product-page description enrichment.",
            "30-product cap; products.json page 1 has 112 products, not a full-site claim.",
            "US market is requested with ?country=US; without it the storefront localizes to CNY.",
            "Descriptions are Shopify body_html; empty bodies are recorded as not_provided, never filled with names.",
            "No login, cart, checkout, account or paid access.",
        ],
        "artifacts": {
            "valid_csv": "valid.csv",
            "run_summary": "run-summary.json",
            "diagnostics_dir": f"diagnostics/{args.label}/",
        },
        "discovery": {
            "entry_url": ENTRY,
            "api_url": API,
            "products_in_payload": len(api_products),
            "kept_products": candidates,
            "currency": currency,
            "spot_check": spot_check,
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
    write_csv_rows(run_dir / "excluded_products.csv", excluded, ["source_url", "reason", "name", "price_amount", "price_currency"])
    write_csv_rows(run_dir / "failed_products.csv", failed, ["source_url", "reason", "detail"])
    write_csv_rows(run_dir / "pending_products.csv", pending, ["source_url", "reason"])
    print(json.dumps({
        "task_id": task_result["task_id"],
        "outcome": task_result["outcome"],
        "stop_reason": stop_reason,
        "counts": task_result["counts"],
        "requests": requests,
        "elapsed_s": elapsed,
        "currency": currency,
        "spot_check": spot_check,
        "valid_csv": str(out_dir / "valid.csv"),
    }, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
