"""Minimal manifest-driven runner: discovery, static fetch, extraction and output."""

from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

from protego import Protego
from scrapling.fetchers import FetcherSession

from .errors import (
    AccessDenied,
    BudgetExhausted,
    EnvironmentFailure,
    HttpStatusError,
    PlanError,
    StopRun,
    TransportError,
)
from .extract import ExtractedProduct, HtmlPage, extract_product
from .manifest import plan_entry_url
from .normalize import csv_safe, format_price

EXECUTOR_VERSION = "r06-declarative-executor/0.1"
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


@dataclass
class RunOptions:
    out_dir: Path
    label: str
    max_products: int
    max_seconds: float
    build_started_at: str | None = None


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
    description_status: str
    partial_reason: str | None
    missing_reasons: dict[str, str]
    field_sources: dict[str, str]
    price_displayed: float | None
    price_pretax: float | None
    tax_basis: str

    def csv_row(self) -> list[str]:
        return [
            csv_safe(self.name),
            format_price(self.price_amount),
            csv_safe(self.price_currency),
            csv_safe(self.primary_image_url),
            csv_safe(self.description_html),
            csv_safe(self.category),
            csv_safe(self.brand),
            csv_safe(self.attributes),
            csv_safe(self.source_url),
        ]


class Pacer:
    """Sequential HTTP client with a wall-clock budget, retries and event records."""

    def __init__(
        self,
        session: Any,
        *,
        delay_ms: int,
        max_seconds: float,
        timeout_ms: int,
        max_attempts: int,
        backoff_ms: int,
    ) -> None:
        self.session = session
        self.delay = max(delay_ms, 1000) / 1000
        self.deadline = time.monotonic() + max_seconds
        self.timeout = max(timeout_ms, 1) / 1000
        self.max_attempts = max(max_attempts, 1)
        self.backoff = max(backoff_ms, 0) / 1000
        self.requests = 0
        self.retries = 0
        self.per_purpose: dict[str, int] = {}
        self.events: list[dict[str, Any]] = []

    def get(self, url: str, *, purpose: str, allow_status: tuple[int, ...] = ()) -> Any:
        last_error = ""
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
                self._event(url, purpose, attempt, None, started, error=last_error)
                if attempt < self.max_attempts:
                    self._sleep_backoff(attempt)
                    continue
                raise TransportError(last_error) from exc

            status = int(getattr(response, "status", 0) or 0)
            body = _response_body(response)
            self._event(url, purpose, attempt, status, started, bytes_=len(body))
            if 200 <= status < 300 or status in allow_status:
                time.sleep(self.delay)
                return response
            if status in {401, 403}:
                raise AccessDenied(f"HTTP {status} for {url}")
            if status == 429:
                if attempt < self.max_attempts:
                    self._sleep_backoff(attempt)
                    continue
                raise AccessDenied(f"HTTP 429 after {self.max_attempts} attempts")
            if 500 <= status < 600:
                if attempt < self.max_attempts:
                    self._sleep_backoff(attempt)
                    continue
                raise TransportError(f"HTTP {status} for {url}")
            raise HttpStatusError(status, url)
        raise TransportError(last_error or "fetch failed")

    def _check_budget(self) -> None:
        if time.monotonic() >= self.deadline:
            raise BudgetExhausted("wall-clock budget exhausted before request")

    def _sleep_backoff(self, attempt: int) -> None:
        if self.backoff <= 0:
            return
        delay = min(self.backoff * (2 ** (attempt - 1)), 5.0)
        if time.monotonic() + delay >= self.deadline:
            raise BudgetExhausted("wall-clock budget would be exhausted by retry backoff")
        time.sleep(delay)

    def _event(
        self,
        url: str,
        purpose: str,
        attempt: int,
        status: int | None,
        started: float,
        *,
        bytes_: int = 0,
        error: str = "",
    ) -> None:
        event: dict[str, Any] = {
            "ts": utc_now(),
            "event": "http_attempt",
            "url": url,
            "purpose": purpose,
            "attempt": attempt,
            "status": status,
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
        }
        if bytes_:
            event["bytes"] = bytes_
        if error:
            event["error"] = error
        self.events.append(event)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _response_body(response: Any) -> bytes:
    body = getattr(response, "body", b"") or b""
    if isinstance(body, str):
        return body.encode("utf-8")
    return bytes(body)


def normalize_origin(value: str) -> str:
    parsed = urlparse(value)
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}".rstrip("/")


def normalize_url(value: str) -> str:
    parsed = urlparse(value)
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            parsed.params,
            parsed.query,
            "",
        )
    )


def discover_urls(page: HtmlPage, plan: dict[str, Any], *, limit: int) -> list[str]:
    discovery = plan["discovery"]
    site = plan["site"]
    entry_url = plan_entry_url(plan)
    includes = [re.compile(pattern) for pattern in plan["scope"].get("include", [])]
    excludes = [re.compile(pattern) for pattern in plan["scope"].get("exclude", [])]
    patterns = [re.compile(pattern) for pattern in discovery.get("product_url_patterns", [])]
    origins = {normalize_origin(origin) for origin in site["allowed_origins"]}
    prefixes = site.get("allowed_path_prefixes", [])

    results: list[str] = []
    seen: set[str] = set()
    for element in page.css(discovery["link_selector"]):
        href = element.get("href")
        if not href:
            continue
        absolute = urljoin(entry_url, href.strip())
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        if normalize_origin(f"{parsed.scheme}://{parsed.netloc}") not in origins:
            continue
        if prefixes and not any(parsed.path.startswith(prefix) for prefix in prefixes):
            continue
        if includes and not any(pattern.search(parsed.path) for pattern in includes):
            continue
        if any(pattern.search(absolute) for pattern in excludes):
            continue
        if patterns and not any(pattern.search(parsed.path) for pattern in patterns):
            continue
        normalized = normalize_url(absolute)
        if normalized in seen:
            continue
        seen.add(normalized)
        results.append(normalized)
        if len(results) >= limit:
            break
    return results


def validate_product(product: ExtractedProduct, plan: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    values = product.values
    for field_name in plan["validate"]["required_fields"]:
        value = values.get(field_name)
        if field_name == "price.amount":
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                reasons.append("zero_or_missing_price")
        elif not value:
            reasons.append(f"missing_{field_name.replace('.', '_')}")

    currency = str(values.get("price.currency", ""))
    if currency and not re.fullmatch(r"[A-Z]{3}", currency):
        reasons.append("invalid_currency")

    for assertion in plan["validate"].get("assertions", []):
        field_name = assertion["field"]
        op = assertion["op"]
        expected = assertion["value"]
        actual = values.get(field_name)
        if op == "matches":
            if not re.search(str(expected), str(actual or "")):
                reasons.append(f"assertion_failed_{field_name.replace('.', '_')}")
            continue
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            continue
        matches = {
            ">": actual > expected,
            ">=": actual >= expected,
            "<": actual < expected,
            "<=": actual <= expected,
            "==": actual == expected,
        }[op]
        if not matches:
            reasons.append(f"assertion_failed_{field_name.replace('.', '_')}")
    return list(dict.fromkeys(reasons))


class Runner:
    def __init__(self, plan: dict[str, Any], options: RunOptions) -> None:
        self.plan = plan
        self.options = options
        self.out_dir = options.out_dir
        self.diagnostics = options.out_dir / "diagnostics" / options.label
        self.entry_url = plan_entry_url(plan)
        self.started_at = utc_now()
        self.started_monotonic = time.monotonic()
        self.events: list[dict[str, Any]] = []
        self.discovered: list[str] = []
        self.pending: list[str] = []
        self.records: list[ProductRecord] = []
        self.audits: list[dict[str, Any]] = []
        self.first_valid_at: str | None = None
        self.stop_reason = "NATURAL_END"
        self.stop_detail = "entry-page sample exhausted"
        self.entry_fetched = False
        self.robots: Protego | None = None
        self.robots_text = ""
        self.robots_url = ""
        self.client: Pacer | None = None
        self.seen_canonical: set[str] = set()
        self._allowed_origins = {
            normalize_origin(origin) for origin in plan["site"]["allowed_origins"]
        }
        self._allowed_prefixes = plan["site"].get("allowed_path_prefixes", [])

    def run(self) -> int:
        self.diagnostics.mkdir(parents=True, exist_ok=True)
        fetch = self.plan["fetch"]
        try:
            with FetcherSession(
                impersonate="chrome",
                timeout=fetch["timeout_ms"] / 1000,
                retries=1,
            ) as session:
                self.client = Pacer(
                    session,
                    delay_ms=int(fetch["delay_ms"]),
                    max_seconds=self.options.max_seconds,
                    timeout_ms=int(fetch["timeout_ms"]),
                    max_attempts=int(fetch["retry"]["max_attempts"]),
                    backoff_ms=int(fetch["retry"]["backoff_ms"]),
                )
                self._fetch_robots()
                entry_page = self._fetch_entry()
                self._discover(entry_page)
                self._process_all()
        except StopRun as exc:
            self.stop_reason = exc.stop_reason
            self.stop_detail = str(exc)
        except Exception as exc:  # noqa: BLE001 - top-level run boundary
            self.stop_reason = "ENVIRONMENT_ERROR"
            self.stop_detail = f"{type(exc).__name__}: {exc}"
        finally:
            self._write_all()

        elapsed = round(time.monotonic() - self.started_monotonic, 2)
        print(
            f"valid={len(self.records)} failed={self.count('failed')} "
            f"excluded={self.count('excluded')} pending={len(self.pending)} "
            f"requests={self.client.requests if self.client else 0} elapsed={elapsed}s"
        )
        print(f"output: {self.out_dir}")
        return 0 if self.records else 2

    def _fetch_robots(self) -> None:
        parsed = urlparse(self.entry_url)
        self.robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        assert self.client is not None
        try:
            response = self.client.get(self.robots_url, purpose="robots", allow_status=(404,))
        except HttpStatusError as exc:
            raise EnvironmentFailure(f"robots.txt HTTP {exc.status}") from exc
        except TransportError as exc:
            raise EnvironmentFailure(f"robots.txt transport error: {exc}") from exc
        status = int(getattr(response, "status", 0) or 0)
        self.robots_text = _response_body(response).decode("utf-8", "replace")
        if status != 404:
            try:
                self.robots = Protego.parse(self.robots_text.removeprefix("\ufeff"))
            except Exception as exc:
                raise PlanError(f"cannot parse robots.txt: {exc}") from exc
            if not self.robots.can_fetch(self.entry_url, "*"):
                raise AccessDenied("robots.txt disallows the entry URL")

    def _fetch_entry(self) -> HtmlPage:
        assert self.client is not None
        try:
            response = self.client.get(self.entry_url, purpose="entry")
        except HttpStatusError as exc:
            raise PlanError(f"entry page HTTP {exc.status}") from exc
        except TransportError as exc:
            raise EnvironmentFailure(f"entry page transport error: {exc}") from exc
        self.entry_fetched = True
        final_url = str(getattr(response, "url", self.entry_url))
        return HtmlPage(_response_body(response), final_url)

    def _discover(self, page: HtmlPage) -> None:
        urls = discover_urls(page, self.plan, limit=self.options.max_products)
        if not urls:
            raise PlanError("no product links matched the plan on the entry page")
        self.discovered = urls
        self.pending = list(urls)

    def _process_all(self) -> None:
        while self.pending:
            url = self.pending.pop(0)
            self._process_one(url)

    def _process_one(self, url: str) -> None:
        if self.robots is not None and not self.robots.can_fetch(url, "*"):
            self._audit(url, "excluded", "robots_disallowed")
            return

        assert self.client is not None
        try:
            response = self.client.get(url, purpose="product")
        except AccessDenied:
            self._audit(url, "failed", "access_denied")
            raise
        except BudgetExhausted:
            self.pending.insert(0, url)
            raise
        except HttpStatusError as exc:
            self._audit(url, "failed", f"http_{exc.status}")
            return
        except TransportError:
            self._audit(url, "failed", "transport_error")
            return

        page = HtmlPage(_response_body(response), str(getattr(response, "url", url)))
        try:
            product = extract_product(page, self.plan)
            reasons = validate_product(product, self.plan)
        except PlanError:
            self._audit(url, "failed", "plan_error")
            raise
        except Exception as exc:  # noqa: BLE001 - per-product extraction boundary
            self._audit(url, "failed", f"extract_error:{type(exc).__name__}")
            return

        if reasons:
            self._audit(url, "excluded", ";".join(reasons))
            return

        source_url = str(product.values.get("source_url") or url)
        if not self._is_allowed_url(source_url):
            source_url = str(getattr(response, "url", url))
        if source_url in self.seen_canonical:
            self._audit(url, "excluded", "duplicate_canonical")
            return
        self.seen_canonical.add(source_url)
        product.values["source_url"] = source_url

        record = build_record(product)
        self.records.append(record)
        if self.first_valid_at is None:
            self.first_valid_at = utc_now()
        self._audit(url, "valid", "", record=record)

    def _is_allowed_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        origin = normalize_origin(f"{parsed.scheme}://{parsed.netloc}")
        if origin not in self._allowed_origins:
            return False
        return any(parsed.path.startswith(prefix) for prefix in self._allowed_prefixes)

    def _audit(
        self,
        url: str,
        status: str,
        reason: str,
        record: ProductRecord | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "source_url": url,
            "status": status,
            "reason": reason,
        }
        if record is not None:
            entry.update(
                {
                    "name": record.name,
                    "name_source": record.field_sources.get("name", ""),
                    "price_amount": record.price_amount,
                    "price_currency": record.price_currency,
                    "price_displayed": record.price_displayed,
                    "price_pretax": record.price_pretax,
                    "tax_basis": record.tax_basis,
                    "category": record.category,
                    "brand": record.brand,
                    "description_status": record.description_status,
                    "field_sources": record.field_sources,
                    "missing_reasons": record.missing_reasons,
                }
            )
        self.audits.append(entry)

    def count(self, status: str) -> int:
        return sum(1 for audit in self.audits if audit["status"] == status)

    def _write_all(self) -> None:
        self.diagnostics.mkdir(parents=True, exist_ok=True)
        (self.diagnostics / "robots.txt").write_text(self.robots_text, encoding="utf-8")
        (self.diagnostics / "discovered_urls.txt").write_text(
            "\n".join(self.discovered) + ("\n" if self.discovered else ""),
            encoding="utf-8",
        )
        write_ndjson(self.diagnostics / "events.ndjson", self.client.events if self.client else [])
        write_ndjson(self.diagnostics / "product-audit.jsonl", self.audits)
        write_csv(
            self.diagnostics / "excluded_products.csv",
            ["source_url", "reason"],
            [
                [audit["source_url"], audit["reason"]]
                for audit in self.audits
                if audit["status"] == "excluded"
            ],
        )
        write_csv(
            self.diagnostics / "failed_products.csv",
            ["source_url", "reason"],
            [
                [audit["source_url"], audit["reason"]]
                for audit in self.audits
                if audit["status"] == "failed"
            ],
        )
        write_csv(
            self.out_dir / "valid.csv",
            CSV_COLUMNS,
            [record.csv_row() for record in self.records],
        )
        task_result = self._task_result()
        run_summary = self._run_summary(task_result)
        write_json(self.out_dir / "task-result.json", task_result)
        write_json(self.out_dir / "run-summary.json", run_summary)
        write_json(self.diagnostics / "task-result.json", task_result)
        write_json(self.diagnostics / "run-summary.json", run_summary)

    def _task_result(self) -> dict[str, Any]:
        valid = len(self.records)
        excluded = self.count("excluded")
        failed = self.count("failed")
        pending = len(self.pending)
        candidates = len(self.discovered)
        processed = valid + excluded + failed
        if candidates != pending + processed:
            raise PlanError(
                "count invariant broken: "
                f"candidates={candidates} pending={pending} processed={processed}"
            )
        if pending == 0 and failed == 0 and (valid > 0 or excluded > 0):
            outcome = "COMPLETED"
        elif valid > 0:
            outcome = "PARTIAL"
        else:
            outcome = "FAILED"

        if candidates:
            coverage = {
                "status": "PARTIAL",
                "denominator_source": "entry-page links accepted by the plan",
                "denominator": candidates,
                "covered": processed,
                "notes": "Bounded sample from one entry page; not full-site coverage.",
            }
        else:
            coverage = {
                "status": "UNKNOWN",
                "denominator_source": None,
                "denominator": None,
                "covered": None,
                "notes": "Discovery did not complete; no reliable denominator.",
            }

        quality_exceptions = []
        for record in self.records:
            if record.description_status == "complete" and not record.missing_reasons:
                continue
            quality_exceptions.append(
                {
                    "source_url": record.source_url,
                    "description_status": record.description_status,
                    "partial_reason": record.partial_reason,
                    "missing_reasons": record.missing_reasons,
                }
            )

        limitations = [
            "Bounded to links accepted from the entry page; not full-site coverage.",
            "Static HTML only; no browser rendering, login or access-control bypass.",
            "Runtime LLM calls: 0; no raw page HTML is retained.",
        ]
        limitations.extend(self.plan.get("evidence", {}).get("limitations", []))
        limitations = list(dict.fromkeys(str(item) for item in limitations))

        return {
            "task_id": f"{self.plan['plan_id']}-{self.options.label}",
            "plan_id": self.plan["plan_id"],
            "plan_version": self.plan["plan_version"],
            "market": self.plan["site"].get("market"),
            "locale": self.plan["site"].get("locale"),
            "state": "FINISHED",
            "outcome": outcome,
            "stop_reason": self.stop_reason,
            "stop_detail": self.stop_detail,
            "started_at": self.started_at,
            "finished_at": utc_now(),
            "counts": {
                "discovered_urls": candidates + (1 if self.entry_fetched else 0),
                "pending_navigation_entries": 0,
                "product_candidates": candidates,
                "pending_products": pending,
                "in_flight_products": 0,
                "processed_products": processed,
                "valid_products": valid,
                "excluded_products": excluded,
                "failed_products": failed,
                "partial_description_products": sum(
                    1 for record in self.records if record.description_status == "partial"
                ),
            },
            "coverage": coverage,
            "business_acceptance": {
                "status": "NOT_REVIEWED",
                "accepted_by": None,
                "accepted_at": None,
                "reason": "R06 prototype run; no business sign-off yet.",
                "scope": "entry-page sample declared by the plan",
            },
            "quality_exceptions": quality_exceptions,
            "pricing": {
                "policy": (
                    "Choose the smaller public pretax/gross pair per docs/02; "
                    "basis is recorded per product."
                ),
                "products": [
                    {
                        "source_url": record.source_url,
                        "displayed": record.price_displayed,
                        "pretax": record.price_pretax,
                        "chosen": round(record.price_amount, 6),
                        "basis": record.tax_basis,
                    }
                    for record in self.records
                ],
            },
            "runtime": {
                "executor": EXECUTOR_VERSION,
                "llm_calls": 0,
                "raw_pages_retained": False,
                "http_engine": "scrapling.FetcherSession (curl_cffi, static HTML)",
            },
            "access": {
                "entry_url": self.entry_url,
                "robots_url": self.robots_url,
                "client": "scrapling.FetcherSession impersonate=chrome",
                "delay_s": max(int(self.plan["fetch"]["delay_ms"]), 1000) / 1000,
                "max_products": self.options.max_products,
                "max_seconds": self.options.max_seconds,
                "browser_launched": False,
                "login_used": False,
            },
            "limitations": limitations,
        }

    def _run_summary(self, task_result: dict[str, Any]) -> dict[str, Any]:
        elapsed = round(time.monotonic() - self.started_monotonic, 2)
        first_valid_seconds = _seconds_between(self.options.build_started_at, self.first_valid_at)
        return {
            "task_id": task_result["task_id"],
            "label": self.options.label,
            "plan_id": self.plan["plan_id"],
            "plan_version": self.plan["plan_version"],
            "run_started_at": self.started_at,
            "run_finished_at": utc_now(),
            "elapsed_s": elapsed,
            "build_started_at": self.options.build_started_at,
            "first_valid_at": self.first_valid_at,
            "first_valid_product_s": first_valid_seconds,
            "requests": self.client.requests if self.client else 0,
            "retries": self.client.retries if self.client else 0,
            "per_purpose": self.client.per_purpose if self.client else {},
            "valid_products": len(self.records),
            "failed_products": task_result["counts"]["failed_products"],
            "excluded_products": task_result["counts"]["excluded_products"],
            "pending_products": task_result["counts"]["pending_products"],
            "stop_reason": self.stop_reason,
            "stop_detail": self.stop_detail,
            "http_engine": "scrapling.FetcherSession (curl_cffi, static HTML)",
            "executor": EXECUTOR_VERSION,
        }


def build_record(product: ExtractedProduct) -> ProductRecord:
    values = product.values
    price = values.get("price.amount")
    if not isinstance(price, (int, float)) or isinstance(price, bool):
        raise PlanError("validated product has a non-numeric price")
    extras = product.extras.get("price.amount", {})
    return ProductRecord(
        name=str(values.get("name", "")),
        price_amount=float(price),
        price_currency=str(values.get("price.currency", "")),
        primary_image_url=str(values.get("primary_image_url", "")),
        description_html=str(values.get("description_html", "")),
        category=str(values.get("category", "")),
        brand=str(values.get("brand", "")),
        attributes=str(values.get("options", "")),
        source_url=str(values.get("source_url", "")),
        description_status=product.description_status,
        partial_reason=product.partial_reason,
        missing_reasons=dict(product.missing_reasons),
        field_sources=dict(product.sources),
        price_displayed=_as_float(extras.get("displayed")),
        price_pretax=_as_float(extras.get("pretax")),
        tax_basis=str(extras.get("basis", "unspecified")),
    )


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _seconds_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        started = datetime.fromisoformat(start)
        finished = datetime.fromisoformat(end)
    except ValueError:
        return None
    return round((finished - started).total_seconds(), 1)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_ndjson(path: Path, rows: list[dict[str, Any]]) -> None:
    text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
