"""Bounded javaestate.com spider.

Discovery is the Shopify product sitemap.  Product data comes from the public
``products.json`` catalog because product HTML returned HTTP 429 during the
build probes.  The trial processes the first 30 sitemap product URLs only.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterator
from urllib.parse import urlparse

import scrapy
from scrapy import Request
from scrapy.http import Response

from javaestate.normalize import (
    PLAN_ID,
    PLAN_VERSION,
    NormalizationError,
    build_valid_row,
    clean_name,
    format_price,
    lowest_positive_variant_price,
)

DEFAULT_BASE_URL = "https://javaestate.com"
SITEMAP_PATH = "/sitemap.xml"
HOME_PATH = "/"
CATALOG_PATH = "/products.json?limit=250&page={page}"
PRODUCT_HANDLE_RE = re.compile(r"/products/([^/?#]+)$")

MAX_BACKOFF_ATTEMPTS = 3
MAX_BACKOFF_SECONDS = 90.0
DEFAULT_BACKOFF_SECONDS = 60.0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")


class ProductsSpider(scrapy.Spider):
    name = "javaestate-products"
    allowed_domains = ["javaestate.com"]
    handle_httpstatus_list = [429, 403, 404, 500, 502, 503, 504]

    def __init__(
        self,
        max_products: int | str = 30,
        max_seconds: int | str = 600,
        base_url: str = DEFAULT_BASE_URL,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.max_products = int(max_products)
        self.max_seconds = int(max_seconds)
        self.base_url = base_url.rstrip("/")
        self.sitemap_index_url = f"{self.base_url}{SITEMAP_PATH}"
        self.home_url = f"{self.base_url}{HOME_PATH}"
        self.catalog_url_template = f"{self.base_url}{CATALOG_PATH}"
        self.product_re = re.compile(
            r"^" + re.escape(self.base_url) + r"/products/[^/?#]+$"
        )
        self.allowed_domains = [urlparse(self.base_url).hostname or "javaestate.com"]
        self.started_at = utcnow()
        self.finished_at: datetime | None = None
        self.close_reason: str | None = None

        self.events: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self.sitemap_parts: dict[int, list[str]] = {}
        self.sitemap_total = 0
        self.sitemap_done = 0
        self.selected: list[dict[str, str]] = []
        self.denominator = 0
        self.catalog: dict[str, dict[str, Any]] = {}
        self.catalog_pages: list[dict[str, Any]] = []
        self.catalog_page_order = [3, 2, 4, 1]
        self.catalog_index = 0

        self.valid: list[dict[str, str]] = []
        self.excluded: list[dict[str, Any]] = []
        self.failed: list[dict[str, Any]] = []
        self.pending_selected: list[dict[str, str]] = []
        self.first_valid_at: str | None = None
        self.processed_urls: set[str] = set()

        self.currency = "USD"
        self.currency_evidence = "task_market_default (US/en-US/USD)"
        self.currency_mismatch = False
        self.homepage_status: int | None = None
        self.sitemap_index_status: int | None = None
        self.product_sitemap_status: int | None = None
        self.catalog_status: int | None = None

        self.access_denied = False
        self.plan_error = False
        self.environment_error = False
        self.timed_out = False
        self._data_started = False

    # ------------------------------------------------------------------ start

    async def start(self):
        yield Request(
            self.sitemap_index_url,
            callback=self.parse_sitemap_index,
            meta={"stage": "sitemap_index"},
            priority=20,
        )

    # -------------------------------------------------------------- discovery

    async def parse_sitemap_index(self, response: Response):
        self.sitemap_index_status = response.status
        if response.status == 429:
            retry = await self.backoff(response, "sitemap_index")
            if retry is not None:
                yield retry
            return
        if response.status in (401, 403):
            self.access_denied = True
            self.record_error("sitemap_index", f"http_{response.status}", response.url)
            return
        if response.status != 200:
            self.plan_error = True
            self.record_error("sitemap_index", f"http_{response.status}", response.url)
            return

        sitemap_urls = [
            loc.strip()
            for loc in response.xpath("//*[local-name()='loc']/text()").getall()
            if "sitemap_products_" in loc
        ]
        if not sitemap_urls:
            self.plan_error = True
            self.record_error("sitemap_index", "product_sitemap_not_found", response.url)
            return

        self.sitemap_total = len(sitemap_urls)
        for index, url in enumerate(sitemap_urls):
            yield Request(
                url,
                callback=self.parse_product_sitemap,
                meta={"stage": "product_sitemap", "sitemap_part": index},
                priority=19,
            )

    async def parse_product_sitemap(self, response: Response):
        self.product_sitemap_status = response.status
        part = int(response.request.meta.get("sitemap_part", 0))
        if response.status == 429:
            retry = await self.backoff(response, "product_sitemap")
            if retry is not None:
                yield retry
                return
            self.access_denied = True
        elif response.status in (401, 403):
            self.access_denied = True
            self.record_error("product_sitemap", f"http_{response.status}", response.url)
        elif response.status != 200:
            self.plan_error = True
            self.record_error("product_sitemap", f"http_{response.status}", response.url)
        else:
            locs = [
                loc.strip()
                for loc in response.xpath("//*[local-name()='loc']/text()").getall()
                if self.product_re.fullmatch(loc.strip())
            ]
            self.sitemap_parts[part] = locs

        self.sitemap_done += 1
        if self.sitemap_done >= self.sitemap_total and not self._data_started:
            for request in self.start_data_phase():
                yield request

    def start_data_phase(self) -> Iterator[Request]:
        if self._data_started:
            return
        self._data_started = True

        ordered: list[str] = []
        seen: set[str] = set()
        for part in sorted(self.sitemap_parts):
            for url in self.sitemap_parts[part]:
                match = PRODUCT_HANDLE_RE.search(url)
                if not match:
                    continue
                handle = match.group(1)
                if handle in seen:
                    continue
                seen.add(handle)
                ordered.append(url)

        self.denominator = len(ordered)
        self.selected = [
            {"url": url, "handle": PRODUCT_HANDLE_RE.search(url).group(1)}
            for url in ordered[: self.max_products]
        ]
        if not self.selected:
            self.plan_error = True
            self.record_error("product_sitemap", "no_product_urls", self.sitemap_index_url)
            return

        self.logger.info(
            "sitemap products=%s selected=%s", self.denominator, len(self.selected)
        )

        yield Request(
            self.home_url,
            callback=self.parse_homepage,
            meta={"stage": "homepage"},
            priority=12,
            dont_filter=True,
        )
        first_page = self.catalog_page_order[0]
        yield Request(
            self.catalog_url_template.format(page=first_page),
            callback=self.parse_catalog,
            meta={"stage": "catalog", "catalog_page": first_page},
            priority=10,
            dont_filter=True,
        )

    # --------------------------------------------------------------- currency

    async def parse_homepage(self, response: Response):
        self.homepage_status = response.status
        if response.status == 429:
            retry = await self.backoff(response, "homepage")
            if retry is not None:
                yield retry
            else:
                self.record_error(
                    "homepage",
                    "http_429_currency_probe_failed",
                    response.url,
                    "proceeding with the fixed task market USD",
                )
            return
        if response.status != 200:
            self.record_error("homepage", f"http_{response.status}", response.url)
            return

        match = re.search(r"Shopify\.currency\s*=\s*(\{[^;]+\})", response.text)
        active = None
        if match:
            try:
                active = json.loads(match.group(1)).get("active")
            except (ValueError, TypeError):
                active = None
        if not active:
            match = re.search(r'"currency"\s*:\s*"([A-Z]{3})"', response.text)
            if match:
                active = match.group(1)
        if active:
            self.currency = active.upper()
            self.currency_evidence = (
                f"homepage Shopify.currency.active={self.currency} (status 200, {iso_now()})"
            )
            if self.currency != "USD":
                self.currency_mismatch = True
                self.plan_error = True
                self.record_error(
                    "homepage",
                    "currency_not_usd",
                    response.url,
                    f"storefront active currency is {self.currency}; task market is USD",
                )
        self.logger.info("currency=%s evidence=%s", self.currency, self.currency_evidence)

    # ---------------------------------------------------------------- catalog

    async def parse_catalog(self, response: Response):
        page = int(response.request.meta.get("catalog_page", 0))
        self.catalog_status = response.status
        if response.status == 429:
            retry = await self.backoff(response, f"catalog_page_{page}")
            if retry is not None:
                yield retry
                return
            self.access_denied = True
            self.catalog_pages.append(
                {"page": page, "status": 429, "count": 0, "result": "http_429_after_retries"}
            )
            # The access boundary is explicit: stop catalog attempts instead of
            # walking more pages.  Selected handles are recorded as failures.
            self.record_error(
                "catalog",
                "catalog_access_denied_http_429",
                response.url,
                "stopping catalog attempts after retry limit",
            )
            for item in self.finish_catalog():
                yield item
            return

        if response.status in (401, 403):
            self.access_denied = True
            self.record_error("catalog", f"http_{response.status}", response.url)
            self.catalog_pages.append(
                {"page": page, "status": response.status, "count": 0, "result": "access_denied"}
            )
            for item in self.finish_catalog():
                yield item
            return

        if response.status != 200:
            self.record_error("catalog", f"http_{response.status}", response.url)
            self.catalog_pages.append(
                {"page": page, "status": response.status, "count": 0, "result": "http_error"}
            )
            for request in self.next_catalog_page():
                yield request
            return

        try:
            payload = json.loads(response.text)
            products = payload.get("products")
            if not isinstance(products, list):
                raise ValueError("products is not a list")
        except (ValueError, TypeError) as exc:
            self.plan_error = True
            self.record_error("catalog", "json_parse_error", response.url, str(exc))
            self.catalog_pages.append(
                {"page": page, "status": 200, "count": 0, "result": "json_parse_error"}
            )
            for request in self.next_catalog_page():
                yield request
            return

        added = 0
        for product in products:
            handle = str((product or {}).get("handle") or "").strip()
            if not handle:
                continue
            if handle not in self.catalog:
                self.catalog[handle] = product
                added += 1
        self.catalog_pages.append(
            {"page": page, "status": 200, "count": len(products), "added": added, "result": "ok"}
        )
        found = sum(1 for candidate in self.selected if candidate["handle"] in self.catalog)
        self.logger.info(
            "catalog page=%s records=%s added=%s selected_found=%s/%s",
            page,
            len(products),
            added,
            found,
            len(self.selected),
        )
        if found >= len(self.selected):
            for item in self.finish_catalog():
                yield item
            return
        for request in self.next_catalog_page():
            yield request

    def next_catalog_page(self) -> Iterator[Request]:
        self.catalog_index += 1
        if self.catalog_index < len(self.catalog_page_order):
            page = self.catalog_page_order[self.catalog_index]
            yield Request(
                self.catalog_url_template.format(page=page),
                callback=self.parse_catalog,
                meta={"stage": "catalog", "catalog_page": page},
                priority=10,
                dont_filter=True,
            )
            return
        for item in self.finish_catalog():
            yield item

    # ------------------------------------------------------------- extraction

    def finish_catalog(self) -> Iterator[dict[str, Any]]:
        if self.processed_urls:
            # Already finished (defensive guard against duplicate scheduling).
            return
        self.logger.info(
            "finishing catalog: selected=%s catalog_records=%s",
            len(self.selected),
            len(self.catalog),
        )
        for index, candidate in enumerate(self.selected):
            if self.elapsed() > self.max_seconds:
                self.timed_out = True
                self.pending_selected.extend(self.selected[index:])
                self.record_error(
                    "budget",
                    "time_budget_exhausted",
                    candidate["url"],
                    f"elapsed {self.elapsed():.1f}s > {self.max_seconds}s",
                )
                break
            product = self.catalog.get(candidate["handle"])
            if product is None:
                reason = (
                    "catalog_access_denied_http_429"
                    if self.access_denied
                    else "handle_not_found_in_fetched_catalog_pages"
                )
                record = self.failed_record(
                    candidate,
                    stage="catalog",
                    reason=reason,
                    details="; ".join(
                        f"page {p['page']}: status={p['status']} result={p['result']}"
                        for p in self.catalog_pages
                    ),
                )
                self.failed.append(record)
                self.processed_urls.add(candidate["url"])
                yield {"_kind": "failed", "record": record}
                continue
            for item in self.process_product(product, candidate):
                yield item
        self.finished_at = utcnow()
        self.close_reason = self.close_reason or "finished"

    def process_product(
        self, product: dict[str, Any], candidate: dict[str, str]
    ) -> Iterator[dict[str, Any]]:
        now = iso_now()
        source_url = candidate["url"]
        handle = candidate["handle"]
        name = clean_name(product.get("title"))

        amount, price_reason, price_details = lowest_positive_variant_price(
            product.get("variants")
        )
        if amount is None:
            record = {
                "source_url": source_url,
                "handle": handle,
                "name": name,
                "price_amount": price_details.get("lowest_variant_price", ""),
                "reason": price_reason or "no_public_price",
                "details": json.dumps(price_details, ensure_ascii=False, sort_keys=True),
                "extracted_at": now,
            }
            self.excluded.append(record)
            self.processed_urls.add(source_url)
            yield {"_kind": "excluded", "record": record}
            return

        if self.currency != "USD":
            record = {
                "source_url": source_url,
                "handle": handle,
                "name": name,
                "price_amount": format_price(amount),
                "reason": "currency_mismatch",
                "details": f"storefront currency {self.currency}; task requires USD",
                "extracted_at": now,
            }
            self.excluded.append(record)
            self.processed_urls.add(source_url)
            yield {"_kind": "excluded", "record": record}
            return

        try:
            row = build_valid_row(
                product=product,
                source_url=source_url,
                task_id=self.settings.get("TASK_ID") or "",
                extracted_at=now,
                market="US",
                locale="en-US",
                currency=self.currency,
            )
        except NormalizationError as exc:
            message = str(exc)
            if message == "primary_image_missing":
                record = {
                    "source_url": source_url,
                    "handle": handle,
                    "name": name,
                    "price_amount": format_price(amount),
                    "reason": "missing_required_image",
                    "details": message,
                    "extracted_at": now,
                }
                self.excluded.append(record)
                self.processed_urls.add(source_url)
                yield {"_kind": "excluded", "record": record}
                return
            record = self.failed_record(
                candidate, stage="extract", reason=message, details="required field missing"
            )
            self.failed.append(record)
            self.processed_urls.add(source_url)
            yield {"_kind": "failed", "record": record}
            return
        except Exception as exc:  # noqa: BLE001 - record and keep the sample bounded
            self.environment_error = True
            record = self.failed_record(
                candidate, stage="extract", reason="extraction_exception", details=repr(exc)
            )
            self.failed.append(record)
            self.processed_urls.add(source_url)
            yield {"_kind": "failed", "record": record}
            return

        row["price_amount"] = format_price(amount)
        if Decimal(row["price_amount"]) <= 0:
            # Defensive: the price helper should already have rejected this.
            record = {
                "source_url": source_url,
                "handle": handle,
                "name": name,
                "price_amount": row["price_amount"],
                "reason": "non_positive_price",
                "details": "validated price is not positive",
                "extracted_at": now,
            }
            self.excluded.append(record)
            self.processed_urls.add(source_url)
            yield {"_kind": "excluded", "record": record}
            return

        if not row["source_url"] or not row["name"]:
            record = self.failed_record(
                candidate, stage="validate", reason="required_field_empty", details="name or source_url"
            )
            self.failed.append(record)
            self.processed_urls.add(source_url)
            yield {"_kind": "failed", "record": record}
            return

        self.valid.append(row)
        self.processed_urls.add(source_url)
        if self.first_valid_at is None:
            self.first_valid_at = now
            self.logger.info("first valid product at %s: %s", now, source_url)
        yield {"_kind": "valid", "row": row}

    # ----------------------------------------------------------------- helpers

    def failed_record(
        self,
        candidate: dict[str, str],
        *,
        stage: str,
        reason: str,
        details: str = "",
    ) -> dict[str, Any]:
        return {
            "source_url": candidate.get("url", ""),
            "handle": candidate.get("handle", ""),
            "stage": stage,
            "reason": reason,
            "details": details,
            "extracted_at": iso_now(),
        }

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
                stage,
                "http_429_after_retries",
                response.url,
                f"{attempt} retries exhausted; Retry-After={delay}s",
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
            "HTTP 429 stage=%s url=%s; sleeping %.1fs (attempt %s/%s)",
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
            {
                "at": iso_now(),
                "stage": stage,
                "code": code,
                "url": url,
                "message": message,
            }
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

    # ---------------------------------------------------------------- results

    def task_result(self) -> dict[str, Any]:
        processed = len(self.valid) + len(self.excluded) + len(self.failed)
        denominator = self.denominator or 0
        pending = max(0, denominator - processed) if denominator else 0
        partial = sum(1 for row in self.valid if row.get("description_status") == "partial")

        if self.valid and (self.plan_error or self.access_denied or self.environment_error):
            outcome = "PARTIAL"
        elif self.valid and pending == 0 and not self.failed:
            outcome = "COMPLETED"
        elif self.valid:
            outcome = "PARTIAL"
        elif self.access_denied or self.plan_error or self.environment_error or self.timed_out:
            outcome = "FAILED"
        else:
            outcome = "FAILED" if not self.valid else "PARTIAL"

        if self.access_denied:
            stop_reason = "ACCESS_DENIED"
        elif self.plan_error:
            stop_reason = "PLAN_ERROR"
        elif self.environment_error:
            stop_reason = "ENVIRONMENT_ERROR"
        elif pending > 0 or self.timed_out:
            stop_reason = "BUDGET_EXHAUSTED"
        else:
            stop_reason = "NATURAL_END"

        started = self.started_at.isoformat(timespec="seconds").replace("+00:00", "Z")
        finished = (self.finished_at or utcnow()).isoformat(timespec="seconds").replace("+00:00", "Z")
        denominator_source = (
            "Shopify product sitemap loc count (sitemap_products_1.xml)" if denominator else None
        )
        coverage_status = "KNOWN" if denominator else "UNKNOWN"
        coverage_notes = (
            f"Bounded sample: first {len(self.selected)} product URLs in sitemap order; "
            f"{pending} product URLs remain outside this run. "
            "Coverage is not full-site coverage."
            if denominator
            else "No reliable product denominator: the product sitemap was not read."
        )

        return {
            "task_id": self.settings.get("TASK_ID") or "",
            "plan_id": PLAN_ID,
            "plan_version": PLAN_VERSION,
            "market": "US",
            "locale": "en-US",
            "state": "FINISHED",
            "outcome": outcome,
            "stop_reason": stop_reason,
            "started_at": started,
            "finished_at": finished,
            "counts": {
                "discovered_urls": denominator,
                "pending_navigation_entries": 0,
                "product_candidates": denominator,
                "pending_products": pending,
                "in_flight_products": 0,
                "processed_products": processed,
                "valid_products": len(self.valid),
                "excluded_products": len(self.excluded),
                "failed_products": len(self.failed),
                "partial_description_products": partial,
            },
            "coverage": {
                "status": coverage_status,
                "denominator_source": denominator_source,
                "denominator": denominator or None,
                "covered": processed,
                "notes": coverage_notes,
            },
            "business_acceptance": {
                "status": "NOT_REVIEWED",
                "accepted_by": None,
                "accepted_at": None,
                "reason": None,
                "scope": "bounded framework-comparison trial",
            },
            "runtime": {
                "framework": "Scrapy",
                "framework_version": "2.20.0",
                "python_version": "3.13.13",
                "llm_calls": 0,
                "raw_pages_retained": False,
                "concurrency": 1,
                "download_delay_s": 2.0,
                "retry_limit": 3,
            },
            "currency": {
                "code": self.currency,
                "evidence": self.currency_evidence,
                "mismatch": self.currency_mismatch,
            },
            "errors": self.errors,
            "limitations": self.limitations(),
        }

    def limitations(self) -> list[str]:
        return [
            "Product HTML pages returned HTTP 429 during build probes (Retry-After: 60); "
            "the run uses the public products.json catalog. Descriptions are marked partial "
            "because page-only theme blocks and metafields were not verified.",
            "The catalog JSON does not carry a per-quote currency field; USD comes from the "
            "storefront active currency on the homepage and the fixed US/en-US/USD task market.",
            "Tax basis is not stated on the source; rows record tax_basis=NOT_STATED.",
            "Bounded sample: the first 30 product URLs in product-sitemap order; 676 product "
            "URLs remain outside this run, so coverage is not full-site coverage.",
            "Catalog page order is a site-specific heuristic [3, 2, 4, 1]; if the catalog size "
            "changes, the selected sitemap products may require another page.",
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
            "catalog_pages": self.catalog_pages,
            "events": self.events,
            "errors": self.errors,
            "stats": keep,
            "currency": self.currency,
            "currency_evidence": self.currency_evidence,
            "statuses": {
                "sitemap_index": self.sitemap_index_status,
                "product_sitemap": self.product_sitemap_status,
                "homepage": self.homepage_status,
                "catalog": self.catalog_status,
            },
            "counts": self.task_result()["counts"],
            "task_result": self.task_result(),
        }
