#!/usr/bin/env python3
"""Bounded R04 pilot for familidoo.fr (PrestaShop, static HTML).

This is a comparison-pilot runner, not a production plan package. It fetches
the public homepage, takes the product links shown there, and extracts the
nine business columns defined by docs/02. It does not start a browser, log in,
submit forms, or store full page HTML.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from lxml import html as lxml_html
from protego import Protego
from scrapling.fetchers import FetcherSession
from scrapling.parser import Selector

ENTRY_URL = "https://www.familidoo.fr/fr/"
ROBOTS_URL = "https://www.familidoo.fr/robots.txt"
USER_AGENT = "ai-ecom-crawler-r04"
PLAN_ID = "familidoo-fr-r04"
PLAN_VERSION = "2026.11.20-1"
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
}
DROP_TREE_TAGS = {"script", "style", "img", "video", "iframe", "form", "button", "input", "noscript"}


class StopRun(Exception):
    """Base class for conditions that stop the whole run."""

    stop_reason = "OTHER"


class AccessDenied(StopRun):
    stop_reason = "ACCESS_DENIED"


class BudgetExhausted(StopRun):
    stop_reason = "BUDGET_EXHAUSTED"


class PlanError(StopRun):
    stop_reason = "PLAN_ERROR"


@dataclass
class ProductRecord:
    name: str
    price_amount: float
    price_currency: str
    primary_image_url: str
    description_html: str
    category: str
    brand: str
    attributes: str
    source_url: str
    sku: str = ""
    availability: str = ""
    name_source: str = ""
    price_displayed: float | None = None
    price_pretax: float | None = None
    tax_basis: str = ""
    description_status: str = "complete"
    quality_exceptions: list[dict[str, str]] = field(default_factory=list)

    def csv_row(self) -> list[str]:
        return [
            self.name,
            f"{self.price_amount:.2f}",
            self.price_currency,
            self.primary_image_url,
            self.description_html,
            self.category,
            self.brand,
            self.attributes,
            self.source_url,
        ]


class PacedClient:
    """Sequential fetch wrapper with a wall-clock budget and simple retries."""

    def __init__(
        self,
        session: Any,
        *,
        delay: float,
        max_seconds: float,
        timeout: float,
        max_attempts: int,
    ) -> None:
        self.session = session
        self.delay = max(delay, 1.0)
        self.deadline = time.monotonic() + max_seconds
        self.timeout = timeout
        self.max_attempts = max(max_attempts, 1)
        self.requests = 0
        self.retries = 0
        self.per_purpose: dict[str, int] = {}
        self.events: list[dict[str, Any]] = []

    def _event(self, payload: dict[str, Any]) -> None:
        self.events.append(payload)

    def _check_budget(self) -> None:
        if time.monotonic() >= self.deadline:
            raise BudgetExhausted("wall-clock budget exhausted before request")

    def get(self, url: str, *, purpose: str) -> Any:
        """Fetch one URL and return the Scrapling response; raise on stop conditions."""
        last_error: str | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._check_budget()
            self.requests += 1
            self.per_purpose[purpose] = self.per_purpose.get(purpose, 0) + 1
            if attempt > 1:
                self.retries += 1
            started = time.monotonic()
            try:
                response = self.session.get(
                    url,
                    timeout=self.timeout,
                    retries=1,
                    follow_redirects=True,
                )
            except Exception as exc:  # transport / TLS / timeout
                last_error = f"{type(exc).__name__}: {exc}"
                self._event(
                    {
                        "ts": utc_now(),
                        "event": "http_attempt",
                        "url": url,
                        "purpose": purpose,
                        "attempt": attempt,
                        "status": None,
                        "error": last_error,
                        "duration_s": round(time.monotonic() - started, 3),
                    }
                )
                if attempt < self.max_attempts:
                    time.sleep(min(2 ** (attempt - 1), 4))
                    continue
                raise AccessDenied(last_error) from exc

            status = int(getattr(response, "status", 0) or 0)
            body = getattr(response, "body", b"") or b""
            self._event(
                {
                    "ts": utc_now(),
                    "event": "http_attempt",
                    "url": url,
                    "purpose": purpose,
                    "attempt": attempt,
                    "status": status,
                    "final_url": str(getattr(response, "url", url)),
                    "bytes": len(body),
                    "duration_s": round(time.monotonic() - started, 3),
                }
            )
            if status == 429:
                if attempt < self.max_attempts:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise AccessDenied("HTTP 429 after retries")
            if status in {401, 403}:
                raise AccessDenied(f"HTTP {status}")
            if not 200 <= status < 300:
                raise PlanError(f"unexpected HTTP {status} for {url}")
            time.sleep(self.delay)
            return response
        raise AccessDenied(last_error or "fetch failed")


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def text_of(page: Selector, selector: str, default: str = "") -> str:
    value = page.css(f"{selector}::text").get()
    return clean_text(value) if value else default


def attr_of(page: Selector, selector: str, attribute: str, default: str = "") -> str:
    value = page.css(f"{selector}::attr({attribute})").get()
    return clean_text(value) if value else default


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def strip_site_suffix(value: str, page: Selector) -> str:
    """Remove a trailing/leading shop name from a title-like value."""
    site = attr_of(page, 'meta[property="og:site_name"]', "content")
    if not site:
        return value
    for separator in (" - ", " | ", " – ", " — "):
        suffix = separator + site
        prefix = site + separator
        if value.endswith(suffix):
            return value[: -len(suffix)].strip()
        if value.startswith(prefix):
            return value[len(prefix) :].strip()
    return value


def extract_name(page: Selector) -> tuple[str, str]:
    """Return (name, source) using the common e-commerce fallback order."""
    for selector, source in (
        ('h1[itemprop="name"]', "h1_itemprop"),
        ("h1", "h1"),
        ('meta[property="og:title"]', "og_title"),
        ("title", "title"),
    ):
        if selector.startswith("meta"):
            value = attr_of(page, selector, "content")
        else:
            value = text_of(page, selector)
        if value:
            if source in {"og_title", "title"}:
                value = strip_site_suffix(value, page)
            return value, source
    return "", ""


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if not text:
        return None
    text = text.replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def pick_price(page: Selector) -> tuple[float | None, str, str, float | None, float | None]:
    """Return (chosen, currency, basis, displayed, pretax)."""
    displayed = as_float(attr_of(page, 'meta[property="product:price:amount"]', "content"))
    if displayed is None:
        displayed = as_float(attr_of(page, 'span[itemprop="price"]', "content"))
    pretax = as_float(attr_of(page, 'meta[property="product:pretax_price:amount"]', "content"))
    currency = attr_of(page, 'meta[property="product:price:currency"]', "content")
    if not currency:
        currency = attr_of(page, 'meta[itemprop="priceCurrency"]', "content")
    candidates = [value for value in (pretax, displayed) if value is not None]
    if not candidates:
        return None, currency, "", displayed, pretax
    chosen = min(candidates)
    basis = "exclusive" if pretax is not None and chosen == pretax else "inclusive"
    return chosen, currency.upper(), basis, displayed, pretax


def clean_description(raw_html: str) -> str:
    """Keep product copy and specifications; drop links, scripts and decoration."""
    if not raw_html.strip():
        return ""
    try:
        root = lxml_html.fragment_fromstring(raw_html, create_parent="div")
    except (ValueError, TypeError):
        return ""
    for element in root.xpath(
        './/a[contains(@class, "st_read_more")]'
        ' | .//span[contains(@class, "st_showmore_btn")]'
        ' | .//span[contains(@class, "st_showless_btn")]'
    ):
        element.drop_tree()
    for element in list(root.iterdescendants()):
        tag = str(element.tag).lower() if isinstance(element.tag, str) else ""
        if tag in DROP_TREE_TAGS:
            element.drop_tree()
            continue
        if tag not in ALLOWED_DESCRIPTION_TAGS:
            element.drop_tag()
            continue
        element.attrib.clear()
    cleaned = lxml_html.tostring(root, encoding="unicode")
    cleaned = re.sub(r"^<div>|</div>$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<p>\s*</p>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<li>\s*</li>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n\s*\n+", "\n", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned.strip()


def serialize_options(page: Selector) -> str:
    groups: list[str] = []
    for group in page.css("div.product-variants .product-variants-item"):
        name = text_of(group, "label") or attr_of(group, "select", "name")
        values = [clean_text(value) for value in group.css("select option::text").getall()]
        values = [value for value in values if value and value != "--"]
        if not values:
            values = [clean_text(value) for value in group.css('input[type="radio"]::attr(value)').getall()]
            values = [value for value in values if value]
        if name and values:
            groups.append(f"{name}#{'|'.join(dict.fromkeys(values))}")
    return "~".join(groups)


def extract_product(page: Selector, source_url: str) -> ProductRecord:
    name, name_source = extract_name(page)
    price, currency, basis, displayed, pretax = pick_price(page)
    if price is None:
        raise PlanError("no positive price")
    if not currency:
        raise PlanError("no currency evidence")
    image = attr_of(page, 'meta[property="og:image"]', "content")
    if not image:
        raise PlanError("no primary image")
    description_raw = page.css("div.product_description_container").get() or page.css("div.product-description").get() or ""
    description = clean_description(description_raw)
    if not description:
        description = clean_description(page.css("div.product-description-short").get() or "")
    crumbs = [clean_text(value) for value in page.css('nav.breadcrumb_nav span[itemprop="name"]::text').getall()]
    category = ""
    for crumb in reversed(crumbs[:-1]):
        if crumb.lower() not in {"accueil", "home"}:
            category = crumb
            break
    brand = text_of(page, "div.product-manufacturer a")
    options = serialize_options(page)
    sku = text_of(page, 'div.product-reference [itemprop="sku"]')
    availability = attr_of(page, 'link[itemprop="availability"]', "content")
    canonical = attr_of(page, 'link[rel="canonical"]', "href") or source_url
    exceptions: list[dict[str, str]] = []
    if not brand:
        exceptions.append({"field": "brand", "reason": "not_exposed"})
    return ProductRecord(
        name=name,
        price_amount=price,
        price_currency=currency,
        primary_image_url=image,
        description_html=description,
        category=category,
        brand=brand,
        attributes=options,
        source_url=canonical,
        sku=sku,
        availability=availability,
        name_source=name_source,
        price_displayed=displayed,
        price_pretax=pretax,
        tax_basis=basis,
        description_status="complete" if description else "not_provided",
        quality_exceptions=exceptions,
    )


def discover_product_urls(page: Selector, *, limit: int) -> list[str]:
    links = page.css("a.product_img_link::attr(href)").getall()
    links += page.css("article.js-product-miniature h3 a::attr(href)").getall()
    seen: set[str] = set()
    result: list[str] = []
    for link in links:
        absolute = urljoin(ENTRY_URL, str(link).strip())
        if ".html" not in absolute or "controller=" in absolute:
            continue
        if absolute not in seen:
            seen.add(absolute)
            result.append(absolute)
        if len(result) >= limit:
            break
    return result


def csv_safe(value: str) -> str:
    if value and value[0] in {"=", "+", "-", "@"}:
        return "'" + value
    return value


def write_csv(path: Path, records: list[ProductRecord]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        for record in records:
            row = [csv_safe(value) for value in record.csv_row()]
            writer.writerow(row)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bounded R04 pilot for familidoo.fr; outputs the 9-column business CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example:\n"
            "  python experiments/r04/familidoo/run.py --out-dir experiments/r04/familidoo --label r04-run-001\n"
        ),
    )
    parser.add_argument("--out-dir", default=str(Path(__file__).resolve().parent), help="output directory")
    parser.add_argument("--label", default="r04-run-001", help="diagnostics label; use a new label for a rerun")
    parser.add_argument("--max-products", type=int, default=6, help="product cap; default 6 homepage products")
    parser.add_argument("--max-seconds", type=float, default=120.0, help="wall-clock budget in seconds")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests; never below 1.0")
    parser.add_argument("--timeout", type=float, default=45.0, help="per-request timeout in seconds")
    parser.add_argument("--max-attempts", type=int, default=2, help="total HTTP attempts, retries included")
    parser.add_argument("--build-started-at", default=None, help="optional ISO 8601 build-session start")
    args = parser.parse_args(argv)
    if args.max_products < 1:
        parser.error("--max-products must be >= 1")
    if args.max_seconds <= 0:
        parser.error("--max-seconds must be > 0")
    if args.delay < 1.0:
        parser.error("--delay must be >= 1.0 to respect the site")
    if args.max_attempts < 1:
        parser.error("--max-attempts must be >= 1")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = Path(args.out_dir).resolve()
    diagnostics = out_dir / "diagnostics" / args.label
    diagnostics.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    started_at = utc_now()
    events: list[dict[str, Any]] = []
    fetcher: PacedClient | None = None
    records: list[ProductRecord] = []
    audits: list[dict[str, Any]] = []
    first_valid_at: str | None = None
    stop_reason = "FINISHED"
    stop_detail = ""
    discovered: list[str] = []
    robots_text = ""
    try:
        with FetcherSession(impersonate="chrome", timeout=args.timeout, retries=1) as session:
            fetcher = PacedClient(
                session,
                delay=args.delay,
                max_seconds=args.max_seconds,
                timeout=args.timeout,
                max_attempts=args.max_attempts,
            )
            robots_response = fetcher.get(ROBOTS_URL, purpose="robots")
            robots_text = (robots_response.body or b"").decode("utf-8", "replace")
            (diagnostics / "robots.txt").write_text(robots_text, encoding="utf-8")
            parser = Protego.parse(robots_text.removeprefix("\ufeff"))
            if not parser.can_fetch(ENTRY_URL, "*"):
                raise AccessDenied("robots.txt disallows the entry URL")

            entry_response = fetcher.get(ENTRY_URL, purpose="entry")
            entry_page = Selector(content=entry_response.body, url=str(entry_response.url))
            discovered = discover_product_urls(entry_page, limit=args.max_products)
            if not discovered:
                raise PlanError("no product links found on homepage")
            (diagnostics / "discovered_urls.txt").write_text("\n".join(discovered) + "\n", encoding="utf-8")

            for url in discovered:
                if not parser.can_fetch(url, "*"):
                    audits.append({"source_url": url, "status": "excluded", "reason": "robots_disallowed"})
                    continue
                response = fetcher.get(url, purpose="product")
                page = Selector(content=response.body, url=str(response.url))
                try:
                    record = extract_product(page, str(response.url))
                except PlanError as exc:
                    audits.append({"source_url": url, "status": "failed", "reason": str(exc)})
                    continue
                records.append(record)
                if first_valid_at is None:
                    first_valid_at = utc_now()
                audits.append(
                    {
                        "source_url": record.source_url,
                        "status": "valid",
                        "name": record.name,
                        "name_source": record.name_source,
                        "price_amount": record.price_amount,
                        "price_currency": record.price_currency,
                        "price_displayed": record.price_displayed,
                        "price_pretax": record.price_pretax,
                        "tax_basis": record.tax_basis,
                        "sku": record.sku,
                        "availability": record.availability,
                        "category": record.category,
                        "brand": record.brand,
                        "description_status": record.description_status,
                        "quality_exceptions": record.quality_exceptions,
                    }
                )
    except StopRun as exc:
        stop_reason = exc.stop_reason
        stop_detail = str(exc)
    except Exception as exc:  # noqa: BLE001 - top-level run boundary records unexpected failures
        stop_reason = "ENVIRONMENT_ERROR"
        stop_detail = f"{type(exc).__name__}: {exc}"

    finished_at = utc_now()
    elapsed = round(time.monotonic() - started, 2)
    if fetcher is not None:
        events = fetcher.events
    (diagnostics / "events.ndjson").write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + ("\n" if events else ""),
        encoding="utf-8",
    )
    (diagnostics / "product-audit.jsonl").write_text(
        "\n".join(json.dumps(audit, ensure_ascii=False) for audit in audits) + ("\n" if audits else ""),
        encoding="utf-8",
    )
    write_csv(out_dir / "valid.csv", records)
    quality_exceptions = [
        {"source_url": record.source_url, **exception}
        for record in records
        for exception in record.quality_exceptions
    ]
    failed_products = sum(1 for audit in audits if audit["status"] == "failed")
    excluded_products = sum(1 for audit in audits if audit["status"] == "excluded")
    pending_products = max(len(discovered) - len(records) - failed_products - excluded_products, 0)
    task_result = {
        "task_id": f"r04-familidoo-{args.label}",
        "plan_id": PLAN_ID,
        "plan_version": PLAN_VERSION,
        "state": "FINISHED",
        "outcome": "PARTIAL" if records else "FAILED",
        "stop_reason": stop_reason,
        "stop_detail": stop_detail or "bounded homepage sample; not full-site coverage",
        "counts": {
            "discovered_urls": len(discovered),
            "pending_navigation_entries": 0,
            "product_candidates": len(discovered),
            "pending_products": pending_products,
            "in_flight_products": 0,
            "processed_products": len(records) + failed_products + excluded_products,
            "valid_products": len(records),
            "excluded_products": excluded_products,
            "failed_products": failed_products,
            "partial_description_products": sum(1 for r in records if r.description_status == "partial"),
        },
        "coverage": {
            "status": "PARTIAL",
            "denominator_source": "homepage product links",
            "denominator": len(discovered),
            "covered": len(records),
            "notes": "Only the product links shown on the homepage were in scope; this is not full-site coverage.",
        },
        "pricing": {
            "policy": "choose the smaller public pretax/gross pair per docs/02; basis is recorded per product",
            "products": [
                {
                    "source_url": record.source_url,
                    "displayed": record.price_displayed,
                    "pretax": record.price_pretax,
                    "chosen": record.price_amount,
                    "basis": record.tax_basis,
                }
                for record in records
            ],
        },
        "quality_exceptions": quality_exceptions,
        "access": {
            "entry_url": ENTRY_URL,
            "robots_url": ROBOTS_URL,
            "user_agent": USER_AGENT,
            "delay_s": max(args.delay, 1.0),
            "max_products": args.max_products,
            "max_seconds": args.max_seconds,
            "browser_launched": False,
            "login_used": False,
        },
        "limitations": [
            "Bounded to the product links shown on the homepage; not full-site coverage.",
            "Static HTML only; no browser rendering or JavaScript-only tabs.",
            "Price uses the smaller public pretax/gross pair (docs/02 default); tax basis is recorded per product.",
            "Brand is left empty when the page does not expose a manufacturer; it is not inferred from the product name.",
            "No login, cart, checkout, account, search, challenge or access-control bypass.",
        ],
    }
    write_json(out_dir / "task-result.json", task_result)
    first_valid_seconds: float | None = None
    if args.build_started_at and first_valid_at:
        try:
            build_start = datetime.fromisoformat(args.build_started_at)
            first_valid = datetime.fromisoformat(first_valid_at)
            first_valid_seconds = round((first_valid - build_start).total_seconds(), 1)
        except ValueError:
            first_valid_seconds = None
    run_summary = {
        "task_id": task_result["task_id"],
        "label": args.label,
        "plan_id": PLAN_ID,
        "plan_version": PLAN_VERSION,
        "run_started_at": started_at,
        "run_finished_at": finished_at,
        "elapsed_s": elapsed,
        "build_started_at": args.build_started_at,
        "first_valid_at": first_valid_at,
        "first_valid_product_s": first_valid_seconds,
        "requests": fetcher.requests if fetcher else 0,
        "retries": fetcher.retries if fetcher else 0,
        "per_purpose": fetcher.per_purpose if fetcher else {},
        "valid_products": len(records),
        "failed_products": task_result["counts"]["failed_products"],
        "excluded_products": task_result["counts"]["excluded_products"],
        "stop_reason": stop_reason,
        "stop_detail": task_result["stop_detail"],
        "http_engine": "scrapling.FetcherSession (curl_cffi, static HTML)",
    }
    write_json(out_dir / "run-summary.json", run_summary)
    print(f"valid={len(records)} failed={task_result['counts']['failed_products']} requests={run_summary['requests']} elapsed={elapsed}s")
    print(f"output: {out_dir}")
    return 0 if records else 2


if __name__ == "__main__":
    sys.exit(main())
