"""Crawlee runner for the skatepro.es bounded trial.

Crawlee owns the queue, the browser pool, the robots check, retries and the
per-domain throttling on 429.  The only thing this runner adds on top is an
explicit 10-second gap between top-level requests, because the site publishes
``Crawl-delay: 10``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from crawlee import ConcurrencySettings, Request
from crawlee.configuration import Configuration
from crawlee.crawlers import PlaywrightCrawler
from crawlee.errors import PersistentRateLimitError
from crawlee.request_loaders import ThrottlingRequestManager
from crawlee.storages import RequestQueue

from .clean import html_to_text
from .config import (
    CURRENCY,
    DEFAULT_TASK_ID,
    LOCALE,
    MARKET,
    MAX_429_STALL_SECONDS,
    MAX_PRODUCTS,
    MAX_REQUEST_RETRIES,
    MIN_REQUEST_INTERVAL_SECONDS,
    NAVIGATION_TIMEOUT_MS,
    PLAN_ID,
    PLAN_VERSION,
    PRODUCT_URL_RE,
    SITE_ORIGIN,
    SITEMAP_URLS,
    TIME_BUDGET_SECONDS,
)
from .export import (
    DESCRIPTION_STATUSES,
    REQUIRED_ROW_FIELDS,
    append_jsonl,
    build_task_result,
    quality_exceptions,
    read_jsonl,
    write_json,
    write_jsonl,
    write_valid_csv,
)
from .extract import (
    ProductExcluded,
    ProductFailed,
    extract_product,
    normalize_url,
)

LOGGER = logging.getLogger("skatepro.runner")

OUTCOME_COMPLETED = "COMPLETED"
OUTCOME_PARTIAL = "PARTIAL"
OUTCOME_FAILED = "FAILED"
OUTCOME_CANCELLED = "CANCELLED"

PRODUCT_PATTERN = re.compile(PRODUCT_URL_RE)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def seconds_between(start: str | None, end: str | None) -> float | None:
    start_dt = parse_iso(start)
    end_dt = parse_iso(end)
    if not start_dt or not end_dt:
        return None
    return round((end_dt - start_dt).total_seconds(), 3)


def parse_sitemap(xml_text: str) -> tuple[str, list[str]]:
    """Return ("index"|"urlset", locs) for a sitemap document."""

    root = ET.fromstring(xml_text)
    namespace = ""
    if root.tag.startswith("{"):
        namespace = root.tag[1:].split("}", 1)[0]
    prefix = f"{{{namespace}}}" if namespace else ""
    sitemap_nodes = root.findall(f"{prefix}sitemap")
    url_nodes = root.findall(f"{prefix}url")
    kind = "index" if sitemap_nodes else "urlset"
    nodes = sitemap_nodes or url_nodes
    locs: list[str] = []
    for node in nodes:
        loc = node.find(f"{prefix}loc")
        if loc is not None and loc.text:
            locs.append(loc.text.strip())
    return kind, locs


def product_urls_from_sitemap(locs: list[str]) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for loc in locs:
        normalized = normalize_url(loc)
        if not PRODUCT_PATTERN.match(normalized):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        urls.append(normalized)
    return urls


def select_evenly(urls: list[str], limit: int) -> list[str]:
    """Deterministic systematic sample across the sitemap order."""

    if len(urls) <= limit:
        return list(urls)
    step = len(urls) / limit
    selected: list[str] = []
    seen: set[str] = set()
    for index in range(limit):
        candidate = urls[min(int(index * step), len(urls) - 1)]
        if candidate not in seen:
            seen.add(candidate)
            selected.append(candidate)
    return selected


def validate_row(row: dict[str, Any]) -> None:
    missing = [field_name for field_name in REQUIRED_ROW_FIELDS if not row.get(field_name)]
    if missing:
        raise ProductFailed("REQUIRED_FIELD_MISSING", f"Missing fields: {missing}")
    try:
        amount = Decimal(row["price_amount"])
    except (InvalidOperation, ValueError) as exc:
        raise ProductFailed("PRICE_INVALID", str(exc)) from exc
    if not amount.is_finite() or amount <= 0:
        raise ProductFailed("PRICE_INVALID", f"Non-positive price {row['price_amount']!r}")
    if not re.fullmatch(r"[A-Z]{3}", row["price_currency"]):
        raise ProductFailed("CURRENCY_INVALID", row["price_currency"])
    for field_name in ("primary_image_url", "source_url"):
        parts = urlsplit(row[field_name])
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ProductFailed("URL_INVALID", f"{field_name}={row[field_name]!r}")
    if row["description_status"] not in DESCRIPTION_STATUSES:
        raise ProductFailed("DESCRIPTION_STATUS_INVALID", row["description_status"])
    if row["description_status"] == "complete" and not html_to_text(
        row["description_html"]
    ):
        raise ProductFailed("DESCRIPTION_EMPTY_BUT_COMPLETE", row["source_url"])
    if row["description_status"] == "partial" and not row["partial_reason"]:
        raise ProductFailed("PARTIAL_WITHOUT_REASON", row["source_url"])
    reasons = row.get("missing_reasons")
    if not isinstance(reasons, dict):
        raise ProductFailed("MISSING_REASONS_INVALID", f"{reasons!r}")


@dataclass
class RunState:
    run_id: str
    task_id: str
    output_dir: Path
    diag_dir: Path
    started_at: str
    build_started_at: str | None
    plan_ready_at: str | None
    implementation_revisions: int
    max_products: int = MAX_PRODUCTS
    time_budget_seconds: int = TIME_BUDGET_SECONDS
    candidates: list[str] = field(default_factory=list)
    processed: dict[str, str] = field(default_factory=dict)
    valid_rows: list[dict[str, Any]] = field(default_factory=list)
    valid_evidence: list[dict[str, Any]] = field(default_factory=list)
    excluded: list[dict[str, Any]] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)
    in_flight: int = 0
    first_valid_at: str | None = None
    request_events: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stop_reason: str | None = None
    blocked: bool = False
    budget_stop: bool = False
    cancelled: bool = False
    denominator: int | None = None
    denominator_source: str = ""
    selection_rule: str = ""
    sitemap_seen: bool = False
    sitemap_kind: str = ""
    navigation_urls: list[str] = field(default_factory=list)
    deadline: float = 0.0
    done: bool = False
    rate_last: float = 0.0
    rate_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stats: dict[str, Any] = field(default_factory=dict)
    browser_launches: int = 0

    @property
    def checkpoint_path(self) -> Path:
        return self.diag_dir / "checkpoint.jsonl"

    def load_checkpoint(self) -> None:
        latest: dict[str, dict[str, Any]] = {}
        for line in read_jsonl(self.checkpoint_path):
            key = line.get("product_key")
            if key:
                latest[key] = line
        for key, line in latest.items():
            status = line.get("status")
            record = line.get("record")
            if status == "valid" and isinstance(record, dict):
                self.valid_rows.append(record)
                self.valid_evidence.append(line.get("evidence") or {})
                self.processed[key] = "valid"
            elif status == "excluded" and isinstance(record, dict):
                self.excluded.append(record)
                self.processed[key] = "excluded"
            elif status == "failed" and isinstance(record, dict):
                self.failed.append(record)
                self.processed[key] = "failed"

    def checkpoint(
        self,
        product_key: str,
        status: str,
        record: dict[str, Any],
        evidence: dict[str, Any] | None = None,
    ) -> None:
        append_jsonl(
            self.checkpoint_path,
            {
                "product_key": product_key,
                "status": status,
                "record": record,
                "evidence": evidence or {},
                "plan_version": PLAN_VERSION,
                "updated_at": utc_now(),
            },
        )

    async def rate_limit(self) -> None:
        async with self.rate_lock:
            now = time.monotonic()
            wait = self.rate_last + MIN_REQUEST_INTERVAL_SECONDS - now
            if wait > 0:
                await asyncio.sleep(wait)
            self.rate_last = time.monotonic()

    def counts(self) -> dict[str, int]:
        processed = len(self.processed)
        return {
            "product_candidates": len(self.candidates),
            "pending_products": max(0, len(self.candidates) - processed),
            "in_flight_products": 0,
            "processed_products": processed,
            "valid_products": len(self.valid_rows),
            "excluded_products": len(self.excluded),
            "failed_products": len(self.failed),
            "partial_description_products": sum(
                1
                for row in self.valid_rows
                if row.get("description_status") == "partial"
            ),
        }

    def coverage(self) -> dict[str, Any]:
        counts = self.counts()
        if self.denominator is not None and self.denominator > 0:
            return {
                "status": "KNOWN",
                "denominator_source": self.denominator_source,
                "denominator": self.denominator,
                "covered": counts["processed_products"],
                "scope": (
                    f"bounded trial: {len(self.candidates)} sampled product pages "
                    "out of the product URLs in sitemap.xml"
                ),
                "notes": (
                    "The denominator is the number of product URLs matched by "
                    "^/\\d+-\\d+\\.htm$ in sitemap.xml at discovery time. Covered "
                    "counts sampled candidates with a processed verdict in this "
                    "bounded task, not the whole catalogue; the sitemap can change "
                    "between runs and is not independently audited."
                ),
            }
        return {
            "status": "UNKNOWN",
            "denominator_source": None,
            "denominator": None,
            "covered": None,
            "scope": "bounded trial",
            "notes": "No reliable product denominator was obtained from sitemap.xml.",
        }


async def pre_navigation_hook(state: RunState, context: Any) -> None:
    await state.rate_limit()

    async def route_filter(route: Any, request: Any) -> None:
        # The product facts are server-rendered (inline JSON-LD and static DOM),
        # so assets and third-party scripts are aborted before they are
        # requested.  Besides saving bandwidth, this removes the class of
        # navigation hangs seen when a slow external script holds
        # DOMContentLoaded until the navigation timeout.
        if request.resource_type in {
            "image",
            "media",
            "font",
            "stylesheet",
            "script",
        }:
            await route.abort()
        else:
            await route.continue_()

    await context.page.route("**/*", route_filter)
    context.goto_options["wait_until"] = "domcontentloaded"


def configure_logging(diag_dir: Path) -> None:
    diag_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.FileHandler(diag_dir / "run.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )
    for name in ("crawlee", "playwright", "asyncio"):
        logging.getLogger(name).setLevel(logging.INFO)


async def run(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = args.run_id
    diag_dir = output_dir / "diagnostics" / run_id
    diag_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(diag_dir)

    started_at = utc_now()
    state = RunState(
        run_id=run_id,
        task_id=args.task_id or f"{DEFAULT_TASK_ID}-{run_id}",
        output_dir=output_dir,
        diag_dir=diag_dir,
        started_at=started_at,
        build_started_at=args.build_started_at,
        plan_ready_at=args.plan_ready_at,
        implementation_revisions=args.implementation_revisions,
        max_products=min(args.max_products, MAX_PRODUCTS),
        time_budget_seconds=min(args.time_budget_seconds, TIME_BUDGET_SECONDS),
    )
    state.deadline = time.monotonic() + state.time_budget_seconds
    if state.max_products < args.max_products:
        state.warnings.append(
            f"Requested {args.max_products} products; capped at plan limit {MAX_PRODUCTS}."
        )
    if state.time_budget_seconds < args.time_budget_seconds:
        state.warnings.append(
            f"Requested {args.time_budget_seconds}s; capped at plan limit {TIME_BUDGET_SECONDS}s."
        )
    if args.resume:
        state.load_checkpoint()
        LOGGER.info("Resumed checkpoint with %d processed products.", len(state.processed))

    LOGGER.info(
        "Run %s start; task_id=%s plan=%s version=%s max_products=%d budget=%ds interval=%.1fs",
        run_id,
        state.task_id,
        PLAN_ID,
        PLAN_VERSION,
        state.max_products,
        state.time_budget_seconds,
        MIN_REQUEST_INTERVAL_SECONDS,
    )

    configuration = Configuration(
        storage_dir=str(diag_dir / "crawlee_storage"),
        purge_on_start=True,
    )
    queue = await RequestQueue.open(
        alias=f"skatepro-{run_id}", configuration=configuration
    )
    throttler = ThrottlingRequestManager(
        inner=queue,
        domains=["skatepro.es", "www.skatepro.es"],
        request_manager_opener=RequestQueue.open,
        base_delay=timedelta(seconds=MIN_REQUEST_INTERVAL_SECONDS),
        max_delay=timedelta(seconds=60),
        max_domain_stall=timedelta(seconds=MAX_429_STALL_SECONDS),
    )

    async def handler(context: Any) -> None:
        request = context.request
        label = request.label or "unknown"
        event: dict[str, Any] = {
            "url": request.url,
            "label": label,
            "attempt": request.retry_count + 1,
            "started_at": utc_now(),
            "started_monotonic": time.monotonic(),
        }
        try:
            if label == "sitemap":
                await handle_sitemap(state, context)
            elif label == "product":
                await handle_product(state, context)
            else:
                raise RuntimeError(f"Unknown request label: {label}")
            event["outcome"] = "ok"
        except PersistentRateLimitError:
            raise
        except Exception as exc:  # noqa: BLE001 - recorded, then retried
            event["outcome"] = "error"
            event["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            event["finished_at"] = utc_now()
            event["duration_ms"] = round(
                (time.monotonic() - event["started_monotonic"]) * 1000, 1
            )
            event.pop("started_monotonic", None)
            response = getattr(context, "response", None)
            event["http_status"] = getattr(response, "status", None)
            state.request_events.append(event)
            append_jsonl(diag_dir / "requests.jsonl", event)

    crawler = PlaywrightCrawler(
        request_manager=throttler,
        configuration=configuration,
        request_handler=handler,
        max_request_retries=MAX_REQUEST_RETRIES,
        max_requests_per_crawl=state.max_products + 12,
        max_crawl_depth=5,
        concurrency_settings=ConcurrencySettings(
            min_concurrency=1,
            max_concurrency=1,
            max_tasks_per_minute=12,
        ),
        request_handler_timeout=timedelta(seconds=120),
        ignore_http_error_status_codes=[404, 410],
        respect_robots_txt_file=True,
        headless=not args.headful,
        browser_new_context_options={
            "locale": LOCALE,
            "extra_http_headers": {"Accept-Language": "es-ES,es;q=0.9"},
        },
        navigation_timeout=timedelta(milliseconds=NAVIGATION_TIMEOUT_MS),
        configure_logging=False,
    )
    crawler.pre_navigation_hook(lambda context: pre_navigation_hook(state, context))
    state.browser_launches = 1

    async def watchdog() -> None:
        while not state.done:
            await asyncio.sleep(1)
            if time.monotonic() >= state.deadline:
                state.budget_stop = True
                state.stop_reason = "BUDGET_EXHAUSTED"
                LOGGER.warning("Time budget reached; stopping crawler.")
                crawler.stop("10-minute time budget exhausted")
                return

    watchdog_task = asyncio.create_task(watchdog())
    final_stats = None
    try:
        final_stats = await crawler.run(
            requests=[Request.from_url(SITEMAP_URLS[0], label="sitemap")],
            purge_request_queue=True,
        )
    except PersistentRateLimitError as exc:
        state.blocked = True
        state.stop_reason = "ACCESS_DENIED"
        state.errors.append(
            {
                "type": "PersistentRateLimitError",
                "message": str(exc),
                "at": utc_now(),
                "hint": "429/Retry-After persisted beyond the configured stall window.",
            }
        )
        LOGGER.error("Persistent rate limit: %s", exc)
    except asyncio.CancelledError:
        state.cancelled = True
        state.stop_reason = "USER_CANCELLED"
        LOGGER.warning("Crawler cancelled.")
        raise
    except KeyboardInterrupt:
        state.cancelled = True
        state.stop_reason = "USER_CANCELLED"
        LOGGER.warning("Keyboard interrupt; stopping crawler.")
        crawler.stop("user interrupt")
    except Exception as exc:  # noqa: BLE001 - final classification
        state.stop_reason = "ENVIRONMENT_ERROR"
        state.errors.append(
            {
                "type": type(exc).__name__,
                "message": str(exc),
                "at": utc_now(),
            }
        )
        LOGGER.exception("Crawler failed.")
    finally:
        state.done = True
        watchdog_task.cancel()
        try:
            await watchdog_task
        except BaseException:  # noqa: BLE001 - cancellation and loop teardown
            pass
        if final_stats is not None:
            state.stats = final_stats.to_dict()
        finalize(state, program_exit=0)
    return 0


async def handle_sitemap(state: RunState, context: Any) -> None:
    response = context.response
    if response is None or response.status != 200:
        raise RuntimeError(f"Sitemap status {getattr(response, 'status', None)}")
    xml_text = await response.text()
    kind, locs = parse_sitemap(xml_text)
    state.sitemap_seen = True
    state.sitemap_kind = kind
    state.navigation_urls.append(context.request.url)
    if kind == "index":
        child_sitemaps = [
            loc for loc in locs if urlsplit(loc).path.lower().endswith(".xml")
        ][:5]
        state.warnings.append(
            f"sitemap.xml is an index with {len(locs)} entries; followed {len(child_sitemaps)}."
        )
        LOGGER.info("Sitemap index entries=%d following=%d", len(locs), len(child_sitemaps))
        await context.add_requests(
            [Request.from_url(loc, label="sitemap") for loc in child_sitemaps]
        )
        return

    all_urls = product_urls_from_sitemap(locs)
    if not all_urls:
        raise RuntimeError("sitemap.xml had no URLs matching the product pattern")
    if state.denominator is None or len(all_urls) > state.denominator:
        state.denominator = len(all_urls)
        state.denominator_source = (
            "sitemap.xml: unique <loc> entries matching ^https://www.skatepro.es/\\d+-\\d+\\.htm$"
        )
    if state.candidates:
        selected = state.candidates
        state.selection_rule = "resume: candidate list from checkpoint"
    else:
        selected = select_evenly(all_urls, state.max_products)
        state.candidates = selected
        state.selection_rule = (
            f"systematic sample: every {len(all_urls) / state.max_products:.2f}th "
            f"product URL, {state.max_products} of {len(all_urls)}"
            if len(all_urls) > state.max_products
            else "all product URLs (fewer than the product cap)"
        )
    write_json(
        state.diag_dir / "sitemap-summary.json",
        {
            "sitemap_url": context.request.url,
            "sitemap_kind": kind,
            "loc_entries": len(locs),
            "product_urls": len(all_urls),
            "selected_count": len(selected),
            "selection_rule": state.selection_rule,
            "first_url": all_urls[0] if all_urls else None,
            "last_url": all_urls[-1] if all_urls else None,
            "fetched_at": utc_now(),
        },
    )
    write_json(
        state.diag_dir / "selected_urls.json",
        {
            "sitemap_url": context.request.url,
            "selection_rule": state.selection_rule,
            "selected_count": len(selected),
            "selected_urls": selected,
            "fetched_at": utc_now(),
        },
    )
    LOGGER.info("Sitemap kind=%s product URLs=%d selected=%d", kind, len(all_urls), len(selected))
    await context.add_requests(
        [
            Request.from_url(url, label="product", user_data={"product_index": index})
            for index, url in enumerate(selected)
        ]
    )


async def handle_product(state: RunState, context: Any) -> None:
    url = normalize_url(context.request.url)
    if url in state.processed:
        LOGGER.info("Skipping already processed product %s", url)
        return
    state.in_flight += 1
    status = None
    try:
        response = context.response
        status = getattr(response, "status", None)
        if status in (404, 410):
            record_failed(
                state,
                url,
                "HTTP_NOT_FOUND",
                f"HTTP {status}",
                http_status=status,
            )
            return
        if status != 200:
            raise RuntimeError(f"Unexpected HTTP status {status} for {url}")

        # The data is server-rendered; the h1 wait only keeps the DOM snapshot
        # honest when the theme defers part of the page to JavaScript.
        try:
            await context.page.wait_for_selector("h1", timeout=5_000)
        except Exception:  # noqa: BLE001 - extraction below reports the failure
            pass
        raw_html = await context.page.content()
        extracted_at = utc_now()
        result = extract_product(
            raw_html,
            context.request.url,
            market=MARKET,
            locale=LOCALE,
            extracted_at=extracted_at,
        )
        row = dict(result.row)
        row["task_id"] = state.task_id
        row["plan_id"] = PLAN_ID
        row["plan_version"] = PLAN_VERSION
        validate_row(row)
        record_valid(state, url, row, result.evidence)
    except ProductExcluded as exc:
        record_excluded(state, url, exc.reason, exc.detail, http_status=status)
    except ProductFailed as exc:
        record_failed(state, url, exc.reason, exc.detail, http_status=status)
    except Exception as exc:  # noqa: BLE001 - retryable unless exhausted
        if context.request.retry_count >= MAX_REQUEST_RETRIES:
            record_failed(
                state,
                url,
                "UNEXPECTED_ERROR",
                f"{type(exc).__name__}: {exc}",
                http_status=status,
            )
            LOGGER.exception("Product failed after retries: %s", url)
            return
        raise
    finally:
        state.in_flight = max(0, state.in_flight - 1)


def record_valid(
    state: RunState, url: str, row: dict[str, Any], evidence: dict[str, Any]
) -> None:
    if url in state.processed:
        return
    state.processed[url] = "valid"
    state.valid_rows.append(row)
    state.valid_evidence.append(evidence)
    if state.first_valid_at is None:
        state.first_valid_at = utc_now()
        LOGGER.info(
            "FIRST_VALID_PRODUCT at %s url=%s", state.first_valid_at, row["source_url"]
        )
    append_jsonl(
        state.diag_dir / "products.jsonl",
        {
            "product_key": url,
            "status": "valid",
            "row": row,
            "evidence": evidence,
            "recorded_at": utc_now(),
        },
    )
    state.checkpoint(url, "valid", row, evidence)
    write_valid_csv(state.output_dir / "valid.csv", state.valid_rows)
    LOGGER.info(
        "VALID %s price=%s %s desc=%s variants=%s",
        row["source_url"],
        row["price_amount"],
        row["price_currency"],
        row["description_status"],
        row.get("variant_count"),
    )


def record_excluded(
    state: RunState,
    url: str,
    reason: str,
    detail: str,
    *,
    http_status: int | None = None,
) -> None:
    if url in state.processed:
        return
    record = {
        "source_url": url,
        "reason": reason,
        "detail": detail,
        "http_status": http_status,
        "market": MARKET,
        "locale": LOCALE,
        "recorded_at": utc_now(),
    }
    state.processed[url] = "excluded"
    state.excluded.append(record)
    append_jsonl(state.diag_dir / "excluded.jsonl", record)
    state.checkpoint(url, "excluded", record)
    LOGGER.info("EXCLUDED %s reason=%s", url, reason)


def record_failed(
    state: RunState,
    url: str,
    reason: str,
    detail: str,
    *,
    http_status: int | None = None,
) -> None:
    if url in state.processed:
        return
    record = {
        "source_url": url,
        "reason": reason,
        "detail": detail,
        "http_status": http_status,
        "market": MARKET,
        "locale": LOCALE,
        "recorded_at": utc_now(),
    }
    state.processed[url] = "failed"
    state.failed.append(record)
    append_jsonl(state.diag_dir / "failed.jsonl", record)
    state.checkpoint(url, "failed", record)
    LOGGER.info("FAILED %s reason=%s detail=%s", url, reason, detail)


def finalize(state: RunState, *, program_exit: int) -> None:
    finished_at = utc_now()
    counts = state.counts()
    if counts["processed_products"] != (
        counts["valid_products"] + counts["excluded_products"] + counts["failed_products"]
    ):
        raise RuntimeError(f"Count invariant violated: {counts}")
    if counts["partial_description_products"] > counts["valid_products"]:
        raise RuntimeError(f"Partial count invariant violated: {counts}")
    if counts["product_candidates"] != (
        counts["pending_products"] + counts["processed_products"]
    ):
        raise RuntimeError(f"Candidate count invariant violated: {counts}")

    if state.cancelled:
        state_name = "CANCELLED"
        outcome = OUTCOME_CANCELLED
    else:
        state_name = "FINISHED"
        if counts["valid_products"] == 0 and (
            counts["failed_products"] > 0 or counts["processed_products"] == 0
        ):
            outcome = OUTCOME_FAILED
        elif counts["failed_products"] > 0 or counts["pending_products"] > 0:
            outcome = OUTCOME_PARTIAL
        else:
            outcome = OUTCOME_COMPLETED

    if state.stop_reason is None:
        if counts["pending_products"] > 0:
            state.stop_reason = "BUDGET_EXHAUSTED"
        elif len(state.candidates) >= state.max_products:
            state.stop_reason = "BUDGET_EXHAUSTED"
        else:
            state.stop_reason = "NATURAL_END"
    if state.cancelled:
        state.stop_reason = "USER_CANCELLED"

    requests_total = state.stats.get("requests_total")
    runtime = {
        "llm_calls": 0,
        "raw_pages_retained": False,
        "browser_launches": state.browser_launches,
        "browser_cleanup": "PlaywrightCrawler.run() returned; the crawler closed its browser pool.",
        "requests_total_crawlee": requests_total,
        "robots_txt_fetch": 1,
        "request_interval_seconds": MIN_REQUEST_INTERVAL_SECONDS,
        "implementation_revisions": state.implementation_revisions,
        "program_exit": program_exit,
    }
    notes = [
        "Bounded trial: 30 product pages or 10 minutes, whichever comes first.",
        "robots.txt publishes Crawl-delay: 10; top-level requests are spaced by 10 s with concurrency 1.",
        "robots.txt disallows */catalog and */wishlist; no such URL is enqueued.",
        f"Product denominator from sitemap.xml: {state.denominator if state.denominator is not None else 'unknown'}.",
        "Prices are the lowest positive variant offer in the page's own JSON-LD, including out-of-stock variants; strikethrough prices are not read.",
        "Coverage covered counts processed candidates in this bounded task, not the whole catalogue.",
        "No model or other LLM is called at runtime.",
        "This candidate does not implement pause/resume; every run purges its Crawlee queue and is a new task.",
    ]
    if state.errors:
        notes.append("Global errors are listed in run-meta.json and the run log.")
    if state.blocked:
        notes.append("A persistent 429 blocked the run; see ACCESS_DENIED.")
    if state.budget_stop:
        notes.append("The 10-minute watchdog stopped the crawler.")
    notes.extend(state.warnings)

    exceptions = quality_exceptions(state.valid_rows)
    task_result = build_task_result(
        task_id=state.task_id,
        plan_id=PLAN_ID,
        plan_version=PLAN_VERSION,
        site="www.skatepro.es",
        market=MARKET,
        locale=LOCALE,
        state=state_name,
        outcome=outcome,
        stop_reason=state.stop_reason,
        started_at=state.started_at,
        finished_at=finished_at,
        discovered_urls=len(state.candidates) + len(state.navigation_urls),
        pending_navigation_entries=0,
        candidate_count=len(state.candidates),
        processed_count=counts["processed_products"],
        valid_count=counts["valid_products"],
        excluded_count=counts["excluded_products"],
        failed_count=counts["failed_products"],
        partial_count=counts["partial_description_products"],
        coverage=state.coverage(),
        runtime=runtime,
        notes=notes,
        exceptions=exceptions,
    )
    pending = [
        {
            "source_url": url,
            "reason": "NOT_PROCESSED_BUDGET" if state.budget_stop else "NOT_PROCESSED",
            "recorded_at": finished_at,
        }
        for url in state.candidates
        if url not in state.processed
    ]
    write_jsonl(state.diag_dir / "pending.jsonl", pending)
    write_json(state.output_dir / "task-result.json", task_result)
    write_valid_csv(state.output_dir / "valid.csv", state.valid_rows)

    run_meta = {
        "run_id": state.run_id,
        "task_id": state.task_id,
        "plan_id": PLAN_ID,
        "plan_version": PLAN_VERSION,
        "model_variant": "high",
        "runtime_llm_calls": 0,
        "build_started_at": state.build_started_at,
        "plan_ready_at": state.plan_ready_at,
        "started_at": state.started_at,
        "finished_at": finished_at,
        "wall_seconds": seconds_between(state.started_at, finished_at),
        "first_plan_s": seconds_between(state.build_started_at, state.plan_ready_at),
        "first_valid_product_at": state.first_valid_at,
        "first_valid_product_s": seconds_between(
            state.build_started_at, state.first_valid_at
        ),
        "implementation_revisions": state.implementation_revisions,
        "max_products": state.max_products,
        "time_budget_seconds": state.time_budget_seconds,
        "request_interval_seconds": MIN_REQUEST_INTERVAL_SECONDS,
        "sitemap_kind": state.sitemap_kind,
        "sitemap_denominator": state.denominator,
        "denominator_source": state.denominator_source,
        "selection_rule": state.selection_rule,
        "counts": counts,
        "outcome": outcome,
        "stop_reason": state.stop_reason,
        "state": state_name,
        "coverage": task_result["coverage"],
        "quality_exception_count": len(exceptions),
        "requests_logged": len(state.request_events),
        "requests_total_crawlee": requests_total,
        "robots_txt_fetch": 1,
        "browser_launches": state.browser_launches,
        "crawler_statistics": state.stats,
        "errors": state.errors,
        "warnings": state.warnings,
        "failed_products": state.failed,
        "excluded_products": state.excluded,
        "outputs": {
            "valid_csv": "valid.csv",
            "task_result": "task-result.json",
            "diagnostics": f"diagnostics/{state.run_id}/",
        },
    }
    write_json(state.diag_dir / "run-meta.json", run_meta)
    LOGGER.info(
        "Run finished state=%s outcome=%s stop=%s valid=%d excluded=%d failed=%d pending=%d",
        state_name,
        outcome,
        state.stop_reason,
        counts["valid_products"],
        counts["excluded_products"],
        counts["failed_products"],
        counts["pending_products"],
    )


def build_parser() -> argparse.ArgumentParser:
    package_dir = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        description="Bounded Crawlee crawl of skatepro.es product pages."
    )
    parser.add_argument("--run-id", default="run-001")
    parser.add_argument("--task-id", default=None)
    parser.add_argument(
        "--output-dir",
        default=str(package_dir),
        help="Directory for valid.csv/task-result.json; diagnostics go under diagnostics/<run-id>/.",
    )
    parser.add_argument("--max-products", type=int, default=MAX_PRODUCTS)
    parser.add_argument("--time-budget-seconds", type=int, default=TIME_BUDGET_SECONDS)
    parser.add_argument("--build-started-at", default=None)
    parser.add_argument("--plan-ready-at", default=None)
    parser.add_argument("--implementation-revisions", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--headful", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        LOGGER.warning("Interrupted by user.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
