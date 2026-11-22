"""Bounded skatepro.es spider.

Discovery starts from the entry's robots.txt sitemap declaration, reads the
public sitemap once and keeps the first ``max_products`` product URLs.  One
category page is fetched as navigation evidence (the listing paginates only in
the browser); products are not crawled through the whole catalogue.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import scrapy
from lxml import html as lxml_html
from scrapy import Request
from scrapy.http import Response

from skatepro.normalize import (
    PLAN_ID,
    PLAN_VERSION,
    NormalizationError,
    availability_from_offer,
    build_description,
    build_missing_reasons,
    clean_name,
    collect_options,
    currency_evidence,
    format_price,
    json_compact,
    lowest_positive_variant_price,
    normalize_brand,
    normalize_category,
    parse_php2js,
    primary_image,
    product_offers,
    product_variants,
    serialize_options,
)

DEFAULT_BASE_URL = "https://www.skatepro.es"
SITEMAP_PATH = "/sitemap.xml"
CATEGORY_PROBE_PATH = "/c2.htm"
PRODUCT_RE = re.compile(r"^(?P<base>https://www\.skatepro\.es)/(?P<num>\d+)-(?P<pid>\d+)\.htm$")

MAX_BACKOFF_ATTEMPTS = 3
MAX_BACKOFF_SECONDS = 60.0
DEFAULT_BACKOFF_SECONDS = 30.0


def select_candidates(
    ordered: list[dict[str, str]],
    max_products: int,
    shared_urls: list[str] | None = None,
) -> list[dict[str, str]]:
    """Select the first N sitemap rows, or exactly the shared URL sample."""

    if not shared_urls:
        return ordered[:max_products]
    by_url = {candidate["url"]: candidate for candidate in ordered}
    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    for url in shared_urls:
        candidate = by_url.get(url)
        if candidate is None or url in seen:
            continue
        seen.add(url)
        selected.append(candidate)
    return selected[:max_products]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")


class ProductsSpider(scrapy.Spider):
    name = "skatepro-products"
    allowed_domains = ["skatepro.es"]
    handle_httpstatus_list = [429, 403, 404, 500, 502, 503, 504]

    def __init__(
        self,
        max_products: int | str = 30,
        max_seconds: int | str = 600,
        base_url: str = DEFAULT_BASE_URL,
        shared_urls: list[str] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.max_products = int(max_products)
        self.max_seconds = int(max_seconds)
        self.base_url = base_url.rstrip("/")
        self.shared_urls = list(shared_urls or [])
        self.sitemap_url = f"{self.base_url}{SITEMAP_PATH}"
        self.category_url = f"{self.base_url}{CATEGORY_PROBE_PATH}"
        self.allowed_domains = [urlparse(self.base_url).hostname or "www.skatepro.es"]

        self.started_at = utcnow()
        self.finished_at: datetime | None = None
        self.close_reason: str | None = None

        self.events: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []

        self.denominator = 0
        self.sitemap_status: int | None = None
        self.category_status: int | None = None
        self.selection_note = "not selected"
        self.selected: list[dict[str, str]] = []
        self.category_cards = 0
        self.category_product_links = 0

        self.valid: list[dict[str, Any]] = []
        self.excluded: list[dict[str, Any]] = []
        self.failed: list[dict[str, Any]] = []
        self.processed_urls: set[str] = set()
        self.first_valid_at: str | None = None

        self.access_denied = False
        self.plan_error = False
        self.environment_error = False
        self.timed_out = False
        self.currency_mismatch = False
        self.currency_codes: dict[str, int] = {}

    # ------------------------------------------------------------------ start

    async def start(self):
        yield Request(
            self.sitemap_url,
            callback=self.parse_sitemap,
            meta={"stage": "sitemap"},
            priority=20,
            dont_filter=True,
        )

    # -------------------------------------------------------------- discovery

    async def parse_sitemap(self, response: Response):
        self.sitemap_status = response.status
        if response.status == 429:
            retry = await self.backoff(response, "sitemap")
            if retry is not None:
                yield retry
            else:
                self.access_denied = True
            return
        if response.status in (401, 403):
            self.access_denied = True
            self.record_error("sitemap", f"http_{response.status}", response.url)
            return
        if response.status != 200:
            self.plan_error = True
            self.record_error("sitemap", f"http_{response.status}", response.url)
            return

        ordered: list[dict[str, str]] = []
        seen: set[str] = set()
        for loc in response.xpath("//*[local-name()='loc']/text()").getall():
            url = loc.strip()
            match = PRODUCT_RE.fullmatch(url)
            if not match:
                continue
            canonical = f"{match.group('base')}/{match.group('num')}-{match.group('pid')}.htm"
            if canonical in seen:
                continue
            seen.add(canonical)
            ordered.append(
                {
                    "url": canonical,
                    "product_id": match.group("pid"),
                    "category_id": match.group("num"),
                }
            )

        self.denominator = len(ordered)
        self.selected = select_candidates(
            ordered, self.max_products, self.shared_urls
        )
        if self.shared_urls:
            self.selection_note = (
                f"shared URL file: {len(self.selected)} URLs "
                "(same sample across frameworks)"
            )
        else:
            self.selection_note = (
                f"first {len(self.selected)} product URLs in sitemap order"
            )
        if self.shared_urls and len(self.selected) < len(self.shared_urls):
            self.record_error(
                "sitemap",
                "shared_urls_missing",
                f"{len(self.shared_urls) - len(self.selected)} shared URL(s) not in sitemap",
            )
        self.logger.info(
            "sitemap products=%s selected=%s shared=%s",
            self.denominator,
            len(self.selected),
            len(self.shared_urls),
        )
        if not self.selected:
            self.plan_error = True
            self.record_error("sitemap", "no_product_urls", response.url)
            return

        # One category page proves the listing path and its static page size.
        yield Request(
            self.category_url,
            callback=self.parse_category,
            meta={"stage": "category"},
            priority=5,
            dont_filter=True,
        )
        for candidate in self.selected:
            yield Request(
                candidate["url"],
                callback=self.parse_product,
                meta={"stage": "product", "product_id": candidate["product_id"]},
                priority=10,
            )

    async def parse_category(self, response: Response):
        self.category_status = response.status
        if response.status == 429:
            retry = await self.backoff(response, "category")
            if retry is not None:
                yield retry
            return
        if response.status != 200:
            self.record_error("category", f"http_{response.status}", response.url)
            return
        cards = response.xpath("//a[contains(@class,'product_card')]")
        self.category_cards = len(cards)
        self.category_product_links = len(
            {
                href
                for href in (card.attrib.get("href", "") for card in cards)
                if PRODUCT_RE.fullmatch(href.split("?")[0])
            }
        )
        self.logger.info(
            "category status=200 cards=%s product_links=%s (static page; load-more is JS)",
            self.category_cards,
            self.category_product_links,
        )

    # ------------------------------------------------------------- extraction

    async def parse_product(self, response: Response):
        candidate = {
            "url": response.request.url,
            "product_id": response.request.meta.get("product_id", ""),
        }
        if response.status == 429:
            retry = await self.backoff(response, "product")
            if retry is not None:
                yield retry
            else:
                self.access_denied = True
                self.add_failure(
                    candidate,
                    stage="fetch",
                    reason="http_429_after_retries",
                    details="Retry-After exhausted; not retried further",
                )
            return
        if response.status in (401, 403):
            self.access_denied = True
            self.add_failure(
                candidate, stage="fetch", reason=f"http_{response.status}", details="access denied"
            )
            return
        if response.status != 200:
            self.add_failure(
                candidate, stage="fetch", reason=f"http_{response.status}", details="non-200 product page"
            )
            return

        if self.elapsed() > self.max_seconds:
            self.timed_out = True
            self.logger.warning("time budget reached before processing %s", response.url)
            return

        try:
            row, excluded = self.extract(row_url=response.url, text=response.text)
        except NormalizationError as exc:
            self.add_failure(
                candidate, stage="extract", reason=str(exc).split(":", 1)[0], details=str(exc)
            )
            return
        except Exception as exc:  # noqa: BLE001 - recorded, never silently dropped
            self.environment_error = True
            self.add_failure(
                candidate, stage="extract", reason="extraction_exception", details=repr(exc)
            )
            return

        if excluded is not None:
            self.excluded.append(excluded)
            self.processed_urls.add(response.url)
            yield {"_kind": "excluded", "record": excluded}
            return

        if row is None:
            self.add_failure(
                candidate, stage="validate", reason="empty_row", details="extractor returned no row"
            )
            return

        self.valid.append(row)
        self.processed_urls.add(response.url)
        if self.first_valid_at is None:
            self.first_valid_at = iso_now()
            self.logger.info("first valid product at %s: %s", self.first_valid_at, response.url)
        yield {"_kind": "valid", "row": row}

    def extract(
        self, *, row_url: str, text: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Return ``(valid_row, excluded_record)``; raise on technical failure."""
        doc = lxml_html.fromstring(text)

        product: dict[str, Any] | None = None
        for raw in doc.xpath("//script[@type='application/ld+json']/text()"):
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            for item in data if isinstance(data, list) else [data]:
                if isinstance(item, dict) and item.get("@type") in {"Product", "ProductGroup"}:
                    product = item
                    break
            if product is not None:
                break
        if product is None:
            raise NormalizationError("product_json_ld_missing")

        name = clean_name(product.get("name"))
        if not name:
            h1 = " ".join(doc.xpath("//h1//text()")).strip()
            name = clean_name(h1)
        if not name:
            raise NormalizationError("name_missing_after_clean")

        php2js = parse_php2js(text)
        variants = product_variants(php2js, self.product_id_from_url(row_url))

        amount, price_reason, price_details = lowest_positive_variant_price(variants)
        price_basis = "lowest_public_variant_price_incl_unavailable"
        if amount is None and not variants:
            offers = product_offers(product)
            raw_price = (offers[0] or {}).get("price") if offers else None
            fallback, fallback_reason, fallback_details = lowest_positive_variant_price(
                [{"price_number": raw_price}]
            )
            if fallback is not None:
                amount = fallback
                price_details = fallback_details
                price_basis = "json_ld_offer_price_variant_list_unavailable"
                price_details["fallback"] = "php2js variants unavailable"
            else:
                price_reason = fallback_reason or price_reason
                price_details = fallback_details

        if amount is None:
            return None, self.excluded_record(
                row_url,
                name=name,
                reason=price_reason or "no_public_price",
                details=json_compact(price_details),
            )

        currency, evidence = currency_evidence(doc, product)
        if not currency:
            return None, self.excluded_record(
                row_url,
                name=name,
                reason="currency_unproven",
                details="no ISO 4217 code bound to the displayed offer",
            )
        self.currency_codes[currency] = self.currency_codes.get(currency, 0) + 1
        if currency != "EUR":
            self.currency_mismatch = True

        image = primary_image(product)
        if not image:
            og = (doc.xpath("//meta[@property='og:image']/@content") or [""])[0].strip()
            image = og
        if not image:
            return None, self.excluded_record(
                row_url, name=name, reason="missing_required_image", details="no product image"
            )

        description_html, description_status, partial_reason, desc_details = build_description(doc)
        if description_status == "failed":
            raise NormalizationError("description_extract_failed")
        category = normalize_category(product, doc)
        brand = normalize_brand(product)
        groups, skipped_dimensions = collect_options(variants)
        attributes = serialize_options(groups)
        availability = availability_from_offer(product, variants)

        missing = build_missing_reasons(
            description_status=description_status,
            category=category,
            brand=brand,
        )

        row = {
            "name": name,
            "price_amount": format_price(amount),
            "price_currency": currency,
            "primary_image_url": image,
            "description_html": description_html,
            "category": category,
            "brand": brand,
            "attributes": attributes,
            "source_url": row_url,
            # internal traceability (never written to the 9-column CSV)
            "_description_format": "html" if description_html else "",
            "_description_status": description_status,
            "_partial_reason": partial_reason,
            "_missing_reasons": missing,
            "_availability": availability,
            "_tax_basis": "NOT_STATED",
            "_price_basis": price_basis,
            "_currency_evidence": evidence,
            "_skipped_option_dimensions": skipped_dimensions,
            "_option_note": "" if attributes else "NO_PUBLIC_CHOICE",
            "_product_ld_type": product.get("@type"),
            "_spec_rows": desc_details.get("spec_rows", 0),
            "_extracted_at": iso_now(),
        }
        return row, None

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def product_id_from_url(url: str) -> str:
        match = PRODUCT_RE.fullmatch(url)
        return match.group("pid") if match else ""

    def excluded_record(
        self, source_url: str, *, name: str, reason: str, details: str = ""
    ) -> dict[str, Any]:
        return {
            "source_url": source_url,
            "name": name,
            "reason": reason,
            "details": details,
            "extracted_at": iso_now(),
        }

    def add_failure(self, candidate: dict[str, str], *, stage: str, reason: str, details: str = ""):
        record = {
            "source_url": candidate.get("url", ""),
            "product_id": candidate.get("product_id", ""),
            "stage": stage,
            "reason": reason,
            "details": details,
            "extracted_at": iso_now(),
        }
        self.failed.append(record)
        self.processed_urls.add(candidate.get("url", ""))
        self.record_error(stage, reason, candidate.get("url", ""), details)
        return record

    async def backoff(self, response: Response, stage: str) -> Request | None:
        attempt = int(response.request.meta.get("backoff_attempt", 0))
        retry_after = response.headers.get(b"Retry-After")
        delay = DEFAULT_BACKOFF_SECONDS
        if retry_after:
            try:
                delay = float(retry_after.decode("ascii").strip())
            except (ValueError, UnicodeDecodeError):
                delay = DEFAULT_BACKOFF_SECONDS
        delay = max(1.0, min(delay, MAX_BACKOFF_SECONDS))

        if attempt >= MAX_BACKOFF_ATTEMPTS:
            self.events.append(
                {
                    "at": iso_now(),
                    "stage": stage,
                    "url": response.url,
                    "status": response.status,
                    "action": "give_up",
                    "attempt": attempt,
                    "delay_s": None,
                    "retry_after": retry_after.decode("ascii", "replace") if retry_after else None,
                }
            )
            self.record_error(
                stage, "http_429_after_retries", response.url, f"{attempt} retries exhausted"
            )
            return None

        self.events.append(
            {
                "at": iso_now(),
                "stage": stage,
                "url": response.url,
                "status": response.status,
                "action": "backoff",
                "attempt": attempt + 1,
                "delay_s": delay,
                "retry_after": retry_after.decode("ascii", "replace") if retry_after else None,
            }
        )
        self.logger.warning(
            "HTTP 429 stage=%s url=%s sleeping %.1fs (attempt %s/%s)",
            stage,
            response.url,
            delay,
            attempt + 1,
            MAX_BACKOFF_ATTEMPTS,
        )
        await asyncio.sleep(delay)
        meta = dict(response.request.meta)
        meta.pop("download_latency", None)
        meta.pop("download_fingerprint", None)
        meta["backoff_attempt"] = attempt + 1
        return response.request.replace(dont_filter=True, meta=meta)

    def record_error(self, stage: str, code: str, url: str, message: str = "") -> None:
        self.errors.append(
            {"at": iso_now(), "stage": stage, "code": code, "url": url, "message": message}
        )
        self.logger.error("stage=%s code=%s url=%s %s", stage, code, url, message)

    def elapsed(self) -> float:
        return (utcnow() - self.started_at).total_seconds()

    def closed(self, reason: str) -> None:
        self.close_reason = reason
        if self.finished_at is None:
            self.finished_at = utcnow()
        if "timeout" in (reason or "").lower():
            self.timed_out = True

    # ----------------------------------------------------------------- results

    def quality_exceptions(self) -> list[dict[str, Any]]:
        exceptions: list[dict[str, Any]] = []
        for row in self.valid:
            missing = row.get("_missing_reasons") or {}
            status = row.get("_description_status") or ""
            if status == "complete" and not missing:
                continue
            exceptions.append(
                {
                    "source_url": row["source_url"],
                    "description_status": status,
                    "partial_reason": row.get("_partial_reason") or None,
                    "missing_reasons": missing,
                }
            )
        return exceptions

    def task_result(self) -> dict[str, Any]:
        processed = len(self.valid) + len(self.excluded) + len(self.failed)
        candidates = self.denominator or 0
        selected = len(self.selected)
        pending = max(0, selected - processed)
        partial = sum(
            1 for row in self.valid if row.get("_description_status") in {"partial", "fallback"}
        )
        status_counts: dict[str, int] = {}
        for row in self.valid:
            status = row.get("_description_status") or "unknown"
            status_counts[status] = status_counts.get(status, 0) + 1

        if self.access_denied:
            outcome, stop_reason = ("PARTIAL" if self.valid else "FAILED"), "ACCESS_DENIED"
        elif self.plan_error:
            outcome, stop_reason = ("PARTIAL" if self.valid else "FAILED"), "PLAN_ERROR"
        elif self.environment_error:
            outcome, stop_reason = ("PARTIAL" if self.valid else "FAILED"), "ENVIRONMENT_ERROR"
        elif pending > 0 or self.timed_out:
            outcome, stop_reason = ("PARTIAL" if self.valid else "FAILED"), "BUDGET_EXHAUSTED"
        else:
            outcome, stop_reason = "COMPLETED", "NATURAL_END"

        started = self.started_at.isoformat(timespec="seconds").replace("+00:00", "Z")
        finished = (self.finished_at or utcnow()).isoformat(timespec="seconds").replace("+00:00", "Z")

        return {
            "task_id": self.settings.get("TASK_ID") or "",
            "plan_id": PLAN_ID,
            "plan_version": PLAN_VERSION,
            "market": "ES",
            "locale": "es-ES",
            "state": "FINISHED",
            "outcome": outcome,
            "stop_reason": stop_reason,
            "started_at": started,
            "finished_at": finished,
            "counts": {
                "discovered_urls": candidates + 2 if candidates else 0,
                "sitemap_products": candidates,
                "selected_products": selected,
                "pending_navigation_entries": 0,
                "product_candidates": selected,
                "pending_products": pending,
                "in_flight_products": 0,
                "processed_products": processed,
                "valid_products": len(self.valid),
                "excluded_products": len(self.excluded),
                "failed_products": len(self.failed),
                "partial_description_products": partial,
            },
            "coverage": {
                "status": "KNOWN" if candidates else "UNKNOWN",
                "denominator_source": (
                    "https://www.skatepro.es/sitemap.xml product URL count, "
                    f"observed {iso_now()}"
                    if candidates
                    else None
                ),
                "denominator": candidates or None,
                "selected": selected,
                "selection": self.selection_note,
                "covered": processed,
                "notes": (
                    f"Bounded sample: {self.selection_note}; "
                    f"{max(0, candidates - selected)} sitemap product URLs remain "
                    "outside this run. Not full-site coverage."
                    if candidates
                    else "The sitemap did not yield product URLs; no reliable denominator."
                ),
            },
            "business_acceptance": {
                "status": "NOT_REVIEWED",
                "accepted_by": None,
                "accepted_at": None,
                "reason": None,
                "scope": "bounded framework-comparison trial",
            },
            "quality_exceptions": self.quality_exceptions(),
            "runtime": {
                "framework": "Scrapy",
                "framework_version": "2.20.0",
                "python_version": "3.13.13",
                "llm_calls": 0,
                "raw_pages_retained": False,
                "concurrency": 1,
                "download_delay_s": 10.0,
                "retry_limit": 3,
                "robots": "ROBOTSTXT_OBEY=True; Crawl-delay: 10",
            },
            "currency": {
                "codes": self.currency_codes,
                "mismatch": self.currency_mismatch,
                "evidence": "JSON-LD Product.offers.priceCurrency bound to the offer price",
            },
            "description_status_counts": status_counts,
            "errors": self.errors,
            "limitations": self.limitations(),
        }

    def limitations(self) -> list[str]:
        return [
            f"Bounded sample: {self.selection_note}. "
            "It is not full-site coverage; the sitemap is the only denominator.",
            "Category listing is server-rendered for one page only (30 cards); "
            "'?page=2' returns the same page and further pages load through a JS "
            "component, so the plan discovers products from the public sitemap.",
            "Descriptions are the editorial description plus the specification table. "
            "The 'Piezas compatibles' related-parts block and recommendation rails are "
            "not product copy and are excluded.",
            "Tax basis is not stated on the product page; rows record NOT_STATED.",
            "Prices come from the public php2js variant payload; the ISO currency "
            "comes from JSON-LD offers bound to the same offer value.",
            "No LLM is called at runtime; field rules are deterministic Python.",
        ]

    def run_meta(self) -> dict[str, Any]:
        stats = self.crawler.stats.get_stats() if self.crawler else {}
        keep = {
            key: stats.get(key)
            for key in (
                "downloader/request_count",
                "downloader/response_count",
                "downloader/response_status_count/200",
                "downloader/response_status_count/429",
                "downloader/response_status_count/403",
                "downloader/response_status_count/404",
                "retry/count",
                "log_count/ERROR",
                "log_count/WARNING",
                "robots_txt/request_count",
            )
        }
        return {
            "started_at": self.started_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "finished_at": (self.finished_at or utcnow())
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            "first_valid_at": self.first_valid_at,
            "close_reason": self.close_reason,
            "max_products": self.max_products,
            "max_seconds": self.max_seconds,
            "selected": self.selected,
            "denominator": self.denominator,
            "category_probe": {
                "url": self.category_url,
                "status": self.category_status,
                "cards": self.category_cards,
                "product_links": self.category_product_links,
            },
            "events": self.events,
            "errors": self.errors,
            "stats": keep,
            "statuses": {"sitemap": self.sitemap_status, "category": self.category_status},
            "counts": self.task_result()["counts"],
            "task_result": self.task_result(),
        }
