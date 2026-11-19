"""Bounded skatepro.es crawl runner (Scrapling FetcherSession)."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import (
    DEFAULT_DELAY_SECONDS,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_CATEGORY_PAGES,
    DEFAULT_MAX_CATEGORY_SEEDS,
    DEFAULT_MAX_PRODUCTS,
    DEFAULT_MAX_RETRY_AFTER,
    DEFAULT_MAX_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    ENTRY_URL,
    LOCALE,
    MARKET,
    PLAN_ID,
    PLAN_VERSION,
    SITEMAP_URL,
)
from .discovery import Discovery, discover, robots_allows
from .export import write_csv, write_json, write_jsonl
from .extract import ProductRecord, extract_product, format_audit, looks_like_challenge
from .http import (
    AccessDenied,
    BudgetExhausted,
    EnvironmentError,
    PacedFetcher,
    PlanError,
    StopRun,
)
from .normalize import format_amount, serialize_options

LIMITATIONS = [
    "Static HTML only: Scrapling FetcherSession (curl_cffi) was sufficient; no browser was launched.",
    "The task cap is 30 product pages; the category grid and the site sitemap contain far more.",
    "robots.txt publishes Crawl-delay: 10 for meta-externalagent; this run applies 10 s end-to-start pacing "
    "to every request as the D01 S2 boundary requires.",
    "Prices come from the page's embedded variant feed (price_number) and take the lowest finite positive "
    "variant price; compare-at prices, shipping and bundles are ignored.",
    "No tax-inclusive/exclusive statement exists in the static HTML, so tax_basis stays unknown_not_stated.",
    "Options are the public variant dimensions; all SKU combinations were not enumerated as separate products.",
    "The 'Piezas compatibles' cross-sell block and customer reviews are excluded from description_html.",
    "The site shows a 'Delivery to United States' suggestion because of the egress IP; quotes stay EUR and "
    "JSON-LD shipping/return policies target ES. No delivery-country cookie was set and no currency conversion "
    "was performed.",
    "429 handling waits for Retry-After up to 60 s, retries at most 3 attempts, then stops the run.",
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _build_row(record: ProductRecord) -> dict[str, Any]:
    return {
        "name": record.name,
        "price_amount": format_amount(record.price_amount),
        "price_currency": record.price_currency,
        "primary_image_url": record.primary_image_url,
        "description_html": record.description_html,
        "category": record.category,
        "brand": record.brand,
        "attributes": serialize_options(record.options),
        "source_url": record.source_url,
    }


def _record_audit(record: ProductRecord, *, outcome: str, detail: str = "") -> dict[str, Any]:
    audit = format_audit(record)
    audit.update({"outcome": outcome, "detail": detail or record.exclusion_reason or record.extraction_error})
    return audit


def _quality_exceptions(valid: list[tuple[ProductRecord, dict[str, Any]]]) -> list[dict[str, Any]]:
    exceptions: list[dict[str, Any]] = []
    for record, _row in valid:
        if record.description_status == "complete" and not record.missing_reasons:
            continue
        exceptions.append(
            {
                "source_url": record.source_url,
                "description_status": record.description_status.upper(),
                "partial_reason": record.partial_reason or None,
                "missing_reasons": record.missing_reasons,
            }
        )
    return exceptions


def run(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    run_started = _utc_now()
    build_started = _parse_iso(args.build_started_at)
    task_id = f"scrapling-skatepro-{args.label}-{run_started.strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = out_dir / "diagnostics" / args.label
    run_dir.mkdir(parents=True, exist_ok=True)

    events_handle = (run_dir / "events.ndjson").open("w", encoding="utf-8", newline="\n")

    def event_sink(payload: dict[str, Any]) -> None:
        events_handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        events_handle.flush()

    def emit(event: str, **payload: Any) -> None:
        event_sink({"ts": _iso(_utc_now()), "event": event, **payload})

    emit(
        "run_start",
        task_id=task_id,
        plan_id=PLAN_ID,
        plan_version=args.plan_version,
        max_products=args.max_products,
        max_seconds=args.max_seconds,
        delay_seconds=args.delay,
        max_attempts=args.max_attempts,
    )

    start_mono = time.monotonic()
    deadline = start_mono + float(args.max_seconds)

    discovery: Discovery | None = None
    valid: list[tuple[ProductRecord, dict[str, Any]]] = []
    excluded: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    stop_reason: str | None = None
    stop_detail = ""
    first_valid_at: datetime | None = None
    client: PacedFetcher | None = None
    scrapling_version = "unknown"

    try:
        import scrapling

        from scrapling.fetchers import FetcherSession

        scrapling_version = getattr(scrapling, "__version__", "unknown")

        with FetcherSession(retries=1, timeout=float(args.timeout), impersonate="chrome") as session:
            client = PacedFetcher(
                session,
                delay=float(args.delay),
                max_attempts=int(args.max_attempts),
                timeout=float(args.timeout),
                deadline_monotonic=deadline,
                max_retry_after=float(args.max_retry_after),
                event_sink=event_sink,
            )
            emit("discovery_start", entry_url=ENTRY_URL)
            discovery = discover(
                client,
                entry_url=ENTRY_URL,
                sitemap_url=SITEMAP_URL,
                max_products=int(args.max_products),
                max_category_pages=int(args.max_category_pages),
                max_category_seeds=int(args.max_category_seeds),
                fetch_sitemap=not args.no_sitemap,
            )
            emit(
                "discovery_done",
                entry_final_url=discovery.entry_final_url,
                html_lang=discovery.html_lang,
                categories=discovery.visited_categories,
                kept_products=len(discovery.product_urls),
                pending_navigation=len(discovery.pending_navigation),
                sitemap_product_count=discovery.sitemap_product_count,
                robots_status=discovery.robots_status,
            )

            urls = list(discovery.product_urls)
            for index, url in enumerate(urls):
                if time.monotonic() >= deadline:
                    stop_reason = "BUDGET_EXHAUSTED"
                    stop_detail = f"wall-clock budget exhausted before product {index + 1}/{len(urls)}"
                    pending = [
                        {"source_url": item, "reason": "budget_exhausted_before_fetch"} for item in urls[index:]
                    ]
                    emit("run_stop", reason=stop_reason, detail=stop_detail, pending=len(pending))
                    break

                if not robots_allows(discovery, url):
                    excluded.append(
                        {
                            "source_url": url,
                            "reason": "robots_disallowed",
                            "detail": "robots.txt disallows this product URL for user-agent *",
                            "name": "",
                            "price_amount": "",
                            "price_currency": "",
                        }
                    )
                    audits.append({"source_url": url, "outcome": "excluded", "detail": "robots_disallowed"})
                    emit("product_excluded", url=url, reason="robots_disallowed")
                    continue

                try:
                    outcome = client.get(url, purpose="product")
                except AccessDenied as exc:
                    message = str(exc)
                    error_class = "http_429_after_retries" if "429" in message else "access_denied"
                    failed.append(
                        {
                            "source_url": url,
                            "error_class": error_class,
                            "error": message,
                            "attempts": client.requests,
                            "status": None,
                        }
                    )
                    audits.append({"source_url": url, "outcome": "failed", "detail": message})
                    stop_reason = "ACCESS_DENIED"
                    stop_detail = message
                    pending = [
                        {"source_url": item, "reason": "stopped_after_access_denial"}
                        for item in urls[index + 1 :]
                    ]
                    errors.append({"source_url": url, "class": error_class, "message": message})
                    emit("run_stop", reason=stop_reason, detail=stop_detail, pending=len(pending))
                    break
                except BudgetExhausted as exc:
                    pending = [
                        {"source_url": item, "reason": "budget_exhausted_before_fetch"} for item in urls[index:]
                    ]
                    stop_reason = "BUDGET_EXHAUSTED"
                    stop_detail = str(exc)
                    emit("run_stop", reason=stop_reason, detail=stop_detail, pending=len(pending))
                    break
                except (PlanError, EnvironmentError) as exc:
                    pending = [
                        {"source_url": item, "reason": "stopped_by_plan_or_environment_error"}
                        for item in urls[index:]
                    ]
                    stop_reason = exc.stop_reason
                    stop_detail = str(exc)
                    errors.append({"source_url": url, "class": exc.stop_reason, "message": str(exc)})
                    emit("run_stop", reason=stop_reason, detail=stop_detail, pending=len(pending))
                    break

                if not outcome.ok:
                    error_class = outcome.error_class or (
                        f"http_{outcome.status}" if outcome.status is not None else "http_error"
                    )
                    failed.append(
                        {
                            "source_url": url,
                            "error_class": error_class,
                            "error": outcome.error or f"HTTP {outcome.status}",
                            "attempts": outcome.attempts,
                            "status": outcome.status,
                        }
                    )
                    audits.append(
                        {
                            "source_url": url,
                            "outcome": "failed",
                            "detail": outcome.error or f"HTTP {outcome.status}",
                            "attempts": outcome.attempts,
                            "status": outcome.status,
                        }
                    )
                    emit("product_failed", url=url, error=outcome.error, status=outcome.status, attempts=outcome.attempts)
                    continue

                if looks_like_challenge(outcome.response):
                    failed.append(
                        {
                            "source_url": url,
                            "error_class": "challenge_page",
                            "error": "200 response looks like an access challenge shell",
                            "attempts": outcome.attempts,
                            "status": outcome.status,
                        }
                    )
                    audits.append({"source_url": url, "outcome": "failed", "detail": "challenge_page"})
                    stop_reason = "ACCESS_DENIED"
                    stop_detail = "challenge shell encountered"
                    pending = [
                        {"source_url": item, "reason": "stopped_after_challenge"} for item in urls[index + 1 :]
                    ]
                    errors.append({"source_url": url, "class": "challenge_page", "message": stop_detail})
                    emit("run_stop", reason=stop_reason, detail=stop_detail, pending=len(pending))
                    break

                try:
                    record = extract_product(outcome.response)
                except Exception as exc:  # extraction must never crash the whole run
                    message = f"{type(exc).__name__}: {exc}"
                    failed.append(
                        {
                            "source_url": url,
                            "error_class": "extraction_error",
                            "error": message,
                            "attempts": outcome.attempts,
                            "status": outcome.status,
                        }
                    )
                    audits.append({"source_url": url, "outcome": "failed", "detail": message})
                    errors.append({"source_url": url, "class": "extraction_error", "message": message})
                    emit("product_failed", url=url, error=message, status=outcome.status, attempts=outcome.attempts)
                    continue

                if record.exclusion_reason:
                    excluded.append(
                        {
                            "source_url": url,
                            "reason": record.exclusion_reason,
                            "detail": record.exclusion_detail,
                            "name": record.name,
                            "price_amount": format_amount(record.price_amount) if record.price_amount else "",
                            "price_currency": record.price_currency,
                        }
                    )
                    audits.append(_record_audit(record, outcome="excluded"))
                    emit("product_excluded", url=url, reason=record.exclusion_reason, detail=record.exclusion_detail)
                elif record.missing_reasons.get("name") or not record.name:
                    excluded.append(
                        {
                            "source_url": url,
                            "reason": "missing_name",
                            "detail": "no product name found in embedded data, JSON-LD or h1",
                            "name": "",
                            "price_amount": format_amount(record.price_amount) if record.price_amount else "",
                            "price_currency": record.price_currency,
                        }
                    )
                    audits.append(_record_audit(record, outcome="excluded"))
                    emit("product_excluded", url=url, reason="missing_name")
                else:
                    row = _build_row(record)
                    valid.append((record, row))
                    audits.append(_record_audit(record, outcome="valid"))
                    if first_valid_at is None:
                        first_valid_at = _utc_now()
                        emit("first_valid_product", url=url, at=_iso(first_valid_at), name=record.name)
                    emit(
                        "product_valid",
                        url=url,
                        name=record.name,
                        price_amount=row["price_amount"],
                        currency=record.price_currency,
                        description_status=record.description_status,
                        variant_count=record.variant_count,
                    )

            if stop_reason is None:
                if discovery.pending_navigation:
                    stop_reason = "BUDGET_EXHAUSTED"
                    stop_detail = (
                        f"task cap reached: processed {len(urls)} product pages; "
                        f"{len(discovery.pending_navigation)} navigation entries remain"
                    )
                else:
                    stop_reason = "NATURAL_END"
                    stop_detail = "all discovered product URLs were processed"

            emit(
                "run_finish",
                reason=stop_reason,
                valid=len(valid),
                excluded=len(excluded),
                failed=len(failed),
                pending=len(pending),
            )
            emit("session_closing", browser_launched=False, engine="scrapling.FetcherSession")
    except StopRun as exc:
        stop_reason = exc.stop_reason
        stop_detail = str(exc)
        errors.append({"source_url": None, "class": exc.stop_reason, "message": str(exc)})
        emit("run_stop", reason=stop_reason, detail=stop_detail)
    except Exception as exc:
        stop_reason = "ENVIRONMENT_ERROR"
        stop_detail = f"{type(exc).__name__}: {exc}"
        errors.append({"source_url": None, "class": "environment_error", "message": stop_detail})
        emit("run_stop", reason=stop_reason, detail=stop_detail)
    finally:
        emit("run_end", reason=stop_reason)
        events_handle.close()

    run_finished = _utc_now()
    valid_rows = [row for _record, row in valid]
    processed = len(valid_rows) + len(excluded) + len(failed)
    product_candidates = len(discovery.product_urls) if discovery else 0
    pending_count = len(pending)
    if product_candidates and processed + pending_count < product_candidates:
        pending_count = product_candidates - processed
    pending_navigation = len(discovery.pending_navigation) if discovery else 0

    partial_description = sum(1 for record, _row in valid if record.description_status == "partial")
    availability_summary: dict[str, int] = {}
    for record, _row in valid:
        key = record.availability or "unknown"
        availability_summary[key] = availability_summary.get(key, 0) + 1

    if stop_reason in {"ENVIRONMENT_ERROR", "PLAN_ERROR"} and not valid_rows:
        outcome = "FAILED"
    elif not valid_rows and failed:
        outcome = "FAILED"
    elif pending_count > 0 or failed or stop_reason in {"BUDGET_EXHAUSTED", "ACCESS_DENIED", "OTHER"}:
        outcome = "PARTIAL"
    else:
        outcome = "COMPLETED"

    denominator = discovery.sitemap_product_count if discovery else 0
    if denominator:
        coverage = {
            "status": "PARTIAL",
            "denominator_source": "https://www.skatepro.es/sitemap.xml product URL count at run time",
            "denominator": denominator,
            "covered": len(valid_rows),
            "notes": (
                f"Discovery scope is the entry page's category grid, capped at {args.max_products} product "
                f"pages; {len(valid_rows)} valid products of {denominator} sitemap product URLs. "
                "This is a bounded sample, not a full-site completion claim."
            ),
        }
    else:
        coverage = {
            "status": "UNKNOWN",
            "denominator_source": None,
            "denominator": None,
            "covered": None,
            "notes": "No reliable site-level denominator was obtained (sitemap unavailable).",
        }

    discovered: set[str] = set()
    if discovery:
        discovered.add(ENTRY_URL)
        discovered.update(discovery.visited_categories)
        discovered.update(discovery.product_urls)
        discovered.update(discovery.pending_navigation)

    counts = {
        "discovered_urls": len(discovered),
        "pending_navigation_entries": pending_navigation,
        "product_candidates": product_candidates,
        "pending_products": pending_count,
        "in_flight_products": 0,
        "processed_products": processed,
        "valid_products": len(valid_rows),
        "excluded_products": len(excluded),
        "failed_products": len(failed),
        "partial_description_products": partial_description,
    }

    runtime = {
        "llm_calls": 0,
        "raw_pages_retained": False,
        "browser_launched": False,
        "http_engine": "scrapling.FetcherSession (curl_cffi, static HTML)",
        "scrapling_version": scrapling_version,
        "concurrency": 1,
        "request_interval_seconds": float(args.delay),
        "max_attempts": int(args.max_attempts),
    }

    task_result = {
        "task_id": task_id,
        "plan_id": PLAN_ID,
        "plan_version": args.plan_version,
        "market": MARKET,
        "locale": LOCALE,
        "state": "FINISHED",
        "outcome": outcome,
        "stop_reason": stop_reason,
        "stop_detail": stop_detail,
        "started_at": _iso(run_started),
        "finished_at": _iso(run_finished),
        "counts": counts,
        "coverage": coverage,
        "business_acceptance": {
            "status": "NOT_REVIEWED",
            "accepted_by": None,
            "accepted_at": None,
            "reason": None,
            "scope": f"bounded {args.max_products}-product skatepro.es category run",
        },
        "quality_exceptions": _quality_exceptions(valid),
        "availability_summary": availability_summary,
        "runtime": runtime,
        "errors": errors,
        "limitations": LIMITATIONS + (discovery.notes if discovery else []),
        "artifacts": {
            "valid_csv": "valid.csv",
            "run_summary": "run-summary.json",
            "diagnostics_dir": f"diagnostics/{args.label}/",
        },
    }

    first_valid_seconds = None
    if first_valid_at and build_started:
        first_valid_seconds = round((first_valid_at - build_started).total_seconds(), 1)

    summary = {
        "task_id": task_id,
        "label": args.label,
        "plan_id": PLAN_ID,
        "plan_version": args.plan_version,
        "run_started_at": _iso(run_started),
        "run_finished_at": _iso(run_finished),
        "build_started_at": _iso(build_started) if build_started else None,
        "first_valid_at": _iso(first_valid_at) if first_valid_at else None,
        "first_valid_product_s": first_valid_seconds,
        "elapsed_s": round(time.monotonic() - start_mono, 2),
        "state": "FINISHED",
        "outcome": outcome,
        "stop_reason": stop_reason,
        "stop_detail": stop_detail,
        "counts": counts,
        "coverage": coverage,
        "requests": client.requests if client else 0,
        "retries": client.retries if client else 0,
        "per_purpose": client.per_purpose if client else {},
        "per_status": client.per_status if client else {},
        "errors": errors,
        "discovery": {
            "entry_url": discovery.entry_url if discovery else ENTRY_URL,
            "entry_final_url": discovery.entry_final_url if discovery else "",
            "html_lang": discovery.html_lang if discovery else "",
            "html_title": discovery.html_title if discovery else "",
            "site_name": discovery.site_name if discovery else "",
            "category_urls_available": len(discovery.category_urls) if discovery else 0,
            "visited_categories": discovery.visited_categories if discovery else [],
            "kept_products": len(discovery.product_urls) if discovery else 0,
            "duplicate_urls": discovery.duplicate_urls if discovery else 0,
            "filtered_urls": discovery.filtered_urls if discovery else 0,
            "pending_navigation": discovery.pending_navigation if discovery else [],
            "sitemap_url": SITEMAP_URL,
            "sitemap_product_count": discovery.sitemap_product_count if discovery else 0,
            "robots_status": discovery.robots_status if discovery else None,
            "notes": discovery.notes if discovery else [],
        },
        "product_audits": audits,
        "availability_summary": availability_summary,
        "runtime": runtime,
        "errors_count": len(errors),
    }

    meta = {
        "task_id": task_id,
        "framework": "Scrapling",
        "scrapling_version": scrapling_version,
        "engine": "scrapling.FetcherSession",
        "browser_launched": False,
        "python": sys.version,
        "platform": platform.platform(),
        "proxy_env_names": sorted(name for name in os.environ if "PROXY" in name.upper()),
        "command": " ".join(sys.argv),
        "network_note": "Proxy values withheld; egress was not independently measured.",
    }

    write_csv(out_dir / "valid.csv", valid_rows)
    write_json(out_dir / "task-result.json", task_result)
    write_json(out_dir / "run-summary.json", summary)
    write_json(run_dir / "run-summary.json", summary)
    write_json(run_dir / "run-meta.json", meta)

    write_csv(
        run_dir / "excluded_products.csv",
        excluded,
        columns=["source_url", "reason", "detail", "name", "price_amount", "price_currency"],
    )
    write_csv(
        run_dir / "failed_products.csv",
        failed,
        columns=["source_url", "error_class", "error", "attempts", "status"],
    )
    write_csv(run_dir / "pending_products.csv", pending, columns=["source_url", "reason"])
    write_jsonl(run_dir / "product-audit.jsonl", audits)
    (run_dir / "robots.txt").write_text(discovery.robots_text if discovery else "", encoding="utf-8")
    (run_dir / "discovered_urls.txt").write_text(
        "\n".join(sorted(discovered)) + ("\n" if discovered else ""), encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "task_id": task_id,
                "outcome": outcome,
                "stop_reason": stop_reason,
                "counts": counts,
                "requests": summary["requests"],
                "elapsed_s": summary["elapsed_s"],
                "first_valid_product_s": first_valid_seconds,
                "valid_csv": str(out_dir / "valid.csv"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if valid_rows else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bounded Scrapling crawl of skatepro.es")
    parser.add_argument("--out-dir", default=".", help="output directory for valid.csv/task-result.json")
    parser.add_argument("--label", default="run-001", help="diagnostics subdirectory label")
    parser.add_argument("--max-products", type=int, default=DEFAULT_MAX_PRODUCTS)
    parser.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS)
    parser.add_argument("--max-category-pages", type=int, default=DEFAULT_MAX_CATEGORY_PAGES)
    parser.add_argument("--max-category-seeds", type=int, default=DEFAULT_MAX_CATEGORY_SEEDS)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-retry-after", type=float, default=DEFAULT_MAX_RETRY_AFTER)
    parser.add_argument("--plan-version", default=PLAN_VERSION)
    parser.add_argument("--build-started-at", default=None, help="ISO 8601 build session start for first_* metrics")
    parser.add_argument("--no-sitemap", action="store_true", help="skip the sitemap denominator request")
    return parser


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
