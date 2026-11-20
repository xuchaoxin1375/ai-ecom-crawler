"""Task runner: work-item loop, discovery/product handlers, checkpoint and output."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from executor.extract import HtmlPage, extract_product
from executor.normalize import csv_safe, format_price
from executor.runner import CSV_COLUMNS, build_record, discover_urls, validate_product

from .atomic import append_jsonl, write_json, write_text
from .models import Task, WorkItem, utc_now
from .rule import RulePackage
from .store import TaskStore

RUNTIME_VERSION = "r06-runtime/0.2"


class StopTask(Exception):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class TaskRunner:
    def __init__(
        self,
        store: TaskStore,
        rule: RulePackage,
        task: Task,
        *,
        fetcher: Any,
        out_root: str | Path,
        poll_interval: float = 0.1,
    ) -> None:
        self.store = store
        self.rule = rule
        self.task = task
        self.fetcher = fetcher
        self.out_dir = Path(out_root) / task.task_id
        self.poll_interval = max(poll_interval, 0.02)
        self.products_path = self.out_dir / "products.jsonl"
        self.events_path = self.out_dir / "events.ndjson"
        self.items_path = self.out_dir / "items.jsonl"
        self.urls_path = self.out_dir / "urls.csv"
        self.products_csv_path = self.out_dir / "products.csv"
        self.task_result_path = self.out_dir / "task-result.json"
        self.progress_path = self.out_dir / "task-progress.json"
        self._products: list[dict[str, Any]] = []
        self._seen_canonical: set[str] = set()
        self._robots_url = ""
        self._robots_status = 0
        self._robots_sitemaps: list[str] = []
        self._started_monotonic = time.monotonic()
        self._stop_reason = "NATURAL_END"
        self._stop_detail = "entry-page sample exhausted"
        self._final_outcome: str | None = None
        self._write_lock = threading.Lock()
        self._recovery: dict[str, Any] = {}
        self._corrupt_products = 0
        self._includes = [re.compile(pattern) for pattern in rule.scope.get("include", [])]
        self._excludes = [re.compile(pattern) for pattern in rule.scope.get("exclude", [])]
        self._product_patterns = [
            re.compile(pattern)
            for pattern in rule.discovery.get("product_url_patterns", [])
        ]
        discovery_limits = rule.discovery.get("limits", {})
        self._max_navigation = max(
            1,
            int(
                task.limits.get(
                    "max_navigation", discovery_limits.get("max_navigation", 100)
                )
            ),
        )
        sitemap_limits = [
            int(source.get("max_sitemaps", discovery_limits.get("max_sitemaps", 50)))
            for source in rule.sources
            if source.get("type") == "sitemap"
        ]
        self._max_sitemaps = max(
            1,
            min(sitemap_limits)
            if sitemap_limits
            else int(discovery_limits.get("max_sitemaps", 50)),
        )

    def run(self) -> str:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._recovery = self.store.reconcile_task(
            self.task.task_id, self._max_attempts()
        )
        self._recovery["orphan_files_removed"] = self._cleanup_orphans()
        self._recovery["stale_result"] = self._quarantine_stale_result()
        self._recovery["corrupt_product_lines"] = self._load_products()
        started_at = self.task.started_at or utc_now()
        self.task.started_at = started_at
        self.store.update_task(
            self.task.task_id,
            state="RUNNING",
            started_at=started_at,
        )
        self._event("task_reconciled", **self._recovery)
        self._event(
            "task_started", task_type=self.task.task_type, plan_id=self.task.plan_id
        )
        control = "FINISHED"
        try:
            self._probe_robots_sitemaps()
            self._seed_sources()
            control = self._loop()
        except StopTask as exc:
            self._stop_reason = exc.reason
            self._stop_detail = exc.detail
            self._event("task_stopping", reason=exc.reason, detail=exc.detail)
        except Exception as exc:  # noqa: BLE001 - task boundary
            self._stop_reason = "ENVIRONMENT_ERROR"
            self._stop_detail = f"{type(exc).__name__}: {exc}"
            self._event("task_error", reason=self._stop_reason, detail=self._stop_detail)
        self._settle(control)
        return control

    def _loop(self) -> str:
        concurrency = self._concurrency()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures: dict[Future[tuple[str, dict[str, Any]]], WorkItem] = {}
            while True:
                if futures:
                    done, _ = wait(
                        futures, timeout=self.poll_interval, return_when=FIRST_COMPLETED
                    )
                    for future in done:
                        item = futures.pop(future)
                        try:
                            state, result = future.result()
                        except StopTask as exc:
                            self._finish_item(
                                item,
                                "FAILED",
                                {
                                    "reason": exc.reason.lower(),
                                    "failure_class": "blocked",
                                    "detail": exc.detail,
                                },
                            )
                            self._stop_reason = exc.reason
                            self._stop_detail = exc.detail
                            self._drain(futures)
                            return "FINISHED"
                        except Exception as exc:  # noqa: BLE001 - item boundary
                            state = "FAILED"
                            result = {
                                "reason": f"item_error:{type(exc).__name__}",
                                "failure_class": "permanent",
                            }
                        self._finish_item(item, state, result)
                else:
                    time.sleep(self.poll_interval)

                current = self.store.get_task(self.task.task_id)
                if current is None:
                    raise RuntimeError(f"task disappeared: {self.task.task_id}")
                if current.state == "PAUSING":
                    self._drain(futures)
                    self._event("task_pausing", pending=len(futures))
                    return "PAUSED"
                if current.state == "CANCELLING":
                    self._drain(futures, reject=True)
                    self._event("task_cancelling", pending=len(futures))
                    return "CANCELLED"
                if current.state == "CANCELLED":
                    return "CANCELLED"
                if current.state == "PAUSED":
                    return "PAUSED"
                if self._budget_exceeded():
                    self._stop_reason = "BUDGET_EXHAUSTED"
                    self._stop_detail = "task budget exhausted"
                    self._drain(futures)
                    return "FINISHED"

                free = concurrency - len(futures)
                if free > 0:
                    for item in self.store.claim_items(self.task.task_id, free):
                        futures[pool.submit(self._process_item, item)] = item

                if not futures:
                    counts = self.store.item_counts(self.task.task_id)
                    if counts.get("PENDING", 0) == 0 and counts.get("IN_FLIGHT", 0) == 0:
                        return "FINISHED"

    def _drain(
        self,
        futures: dict[Future[tuple[str, dict[str, Any]]], WorkItem],
        *,
        reject: bool = False,
    ) -> None:
        for future, item in list(futures.items()):
            try:
                state, result = future.result()
            except StopTask as exc:
                self._stop_reason = exc.reason
                self._stop_detail = exc.detail
                self._finish_item(
                    item,
                    "FAILED",
                    {
                        "reason": exc.reason.lower(),
                        "failure_class": "blocked",
                        "detail": exc.detail,
                    },
                    accept=not reject,
                )
            except Exception as exc:  # noqa: BLE001 - item boundary
                self._finish_item(
                    item,
                    "FAILED",
                    {
                        "reason": f"item_error:{type(exc).__name__}",
                        "failure_class": "permanent",
                    },
                    accept=not reject,
                )
            else:
                self._finish_item(item, state, result, accept=not reject)
            futures.pop(future, None)

    def _process_item(self, item: WorkItem) -> tuple[str, dict[str, Any]]:
        result = self.fetcher.get(item.url)
        if result.status == 0:
            return self._failure(
                item, "transient", "transport_error", error=result.error
            )
        if result.status in {401, 403}:
            raise StopTask("ACCESS_DENIED", f"HTTP {result.status} for {item.url}")
        if result.status == 429 or 500 <= result.status < 600:
            return self._failure(item, "transient", f"http_{result.status}")
        if not result.ok:
            return self._failure(item, "permanent", f"http_{result.status}")

        if item.item_type == "navigation" and item.discovered_from == "listing":
            return self._process_listing(item, result)
        if item.item_type == "navigation" and item.discovered_from == "html_index":
            return self._process_html_index(item, result)
        if item.item_type == "navigation" and item.discovered_from == "sitemap":
            return self._process_sitemap(item, result)

        page = HtmlPage(result.body, result.url)
        if item.item_type == "navigation":
            remaining = self._remaining_product_limit()
            if remaining <= 0:
                return "DONE", {"links": 0, "added": 0, "limit_reached": True}
            urls = discover_urls(page, self.rule.raw, limit=remaining)
            added = 0
            for url in urls:
                if self._add_product_item(url, parent=item.url):
                    added += 1
            return "DONE", {"links": len(urls), "added": added}

        plan = self.rule.product_plan()
        product = extract_product(page, plan)
        reasons = validate_product(product, plan)
        if reasons:
            return "EXCLUDED", {"reasons": reasons}
        canonical = str(product.values.get("source_url") or result.url)
        if not self._is_allowed_url(canonical):
            canonical = result.url
        if canonical in self._seen_canonical:
            return "EXCLUDED", {"reasons": ["duplicate_canonical"]}
        self._seen_canonical.add(canonical)
        product.values["source_url"] = canonical
        record = build_record(product)
        payload = _record_payload(record)
        return "DONE", {
            "status": "valid",
            "name": record.name,
            "price_amount": record.price_amount,
            "price_currency": record.price_currency,
            "product": payload,
        }

    def _process_html_index(
        self, item: WorkItem, result: Any
    ) -> tuple[str, dict[str, Any]]:
        page = HtmlPage(result.body, result.url)
        selector = str(
            item.result.get("link_selector")
            or self.rule.discovery.get("link_selector", "")
        )
        depth = int(item.result.get("depth", 0))
        max_depth = int(item.result.get("max_depth", 2))
        patterns = [
            re.compile(pattern)
            for pattern in item.result.get("category_patterns", [])
        ]
        products = 0
        categories = 0
        links = 0
        for element in page.css(selector):
            href = element.get("href")
            if not href:
                continue
            absolute = urljoin(item.url, href.strip())
            if not self._is_allowed_url(absolute):
                continue
            links += 1
            if self._is_product_candidate(absolute):
                if self._add_product_item(
                    absolute, parent=item.url, source="html_index"
                ):
                    products += 1
                continue
            if depth >= max_depth or not patterns:
                continue
            parsed = urlparse(absolute)
            if any(
                pattern.search(parsed.path) for pattern in patterns
            ) and self._add_navigation(
                absolute,
                source="html_index",
                parent=item.url,
                result={**item.result, "depth": depth + 1},
            ):
                categories += 1
        return "DONE", {
            "links": links,
            "added_products": products,
            "added_categories": categories,
            "depth": depth,
        }

    def _process_listing(
        self, item: WorkItem, result: Any
    ) -> tuple[str, dict[str, Any]]:
        page = HtmlPage(result.body, result.url)
        remaining = self._remaining_product_limit()
        if remaining <= 0:
            return "DONE", {"links": 0, "added": 0, "limit_reached": True}
        selector = str(item.result.get("link_selector") or "")
        urls = discover_urls(
            page,
            self.rule.raw,
            limit=remaining,
            selector=selector or None,
        )
        added = 0
        for url in urls:
            if self._add_product_item(url, parent=item.url, source="listing"):
                added += 1
        advance = item.result.get("advance", {"type": "none"})
        next_url = self._next_listing_url(item, page, advance) if added else None
        if next_url:
            next_page = int(item.result.get("page", 1)) + 1
            self._add_navigation(
                next_url,
                source="listing",
                parent=item.url,
                result={**item.result, "page": next_page},
            )
        return "DONE", {
            "links": len(urls),
            "added": added,
            "next": next_url,
            "stop": "no_new_items" if added == 0 else None,
        }

    def _next_listing_url(
        self, item: WorkItem, page: HtmlPage, advance: dict[str, Any]
    ) -> str | None:
        advance_type = str(advance.get("type", "none"))
        if advance_type not in {"page_param", "next_link"}:
            return None
        current = int(item.result.get("page", 1))
        default_max = int(self.rule.discovery.get("limits", {}).get("max_pages", 20))
        max_pages = max(1, int(advance.get("max_pages", default_max)))
        if current >= max_pages:
            return None
        if advance_type == "page_param":
            param = str(advance.get("param", "page"))
            parsed = urlparse(item.url)
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            query[param] = str(current + 1)
            return urlunparse(
                (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    parsed.params,
                    urlencode(query, doseq=True),
                    "",
                )
            )
        selector = str(advance.get("selector") or "a[rel=next]")
        elements = page.css(selector)
        if not elements:
            return None
        href = elements[0].get("href")
        if not href:
            return None
        return urljoin(item.url, href.strip())

    def _process_sitemap(
        self, item: WorkItem, result: Any
    ) -> tuple[str, dict[str, Any]]:
        body = result.body
        if body[:2] == b"\x1f\x8b":
            try:
                body = gzip.decompress(body)
            except OSError as exc:
                return "FAILED", {
                    "reason": "sitemap_gzip_error",
                    "failure_class": "permanent",
                    "error": str(exc),
                }
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            return "FAILED", {
                "reason": "sitemap_parse_error",
                "failure_class": "permanent",
                "error": str(exc),
            }

        root_name = _local_name(root.tag).lower()
        locations = [
            element.text.strip()
            for element in root.iter()
            if _local_name(element.tag).lower() == "loc" and element.text
        ]
        if root_name == "sitemapindex":
            added = 0
            skipped = 0
            for location in locations[: self._max_sitemaps]:
                if not self._is_allowed_url(location):
                    skipped += 1
                    continue
                if self._add_navigation(location, source="sitemap", parent=item.url):
                    added += 1
                else:
                    skipped += 1
            return "DONE", {
                "sitemap_type": "index",
                "children": len(locations),
                "added": added,
                "skipped": skipped,
            }

        if root_name == "urlset":
            candidates = 0
            added = 0
            excluded = 0
            for location in locations:
                if not self._is_product_candidate(location):
                    excluded += 1
                    continue
                candidates += 1
                if self._add_product_item(
                    location, parent=item.url, source="sitemap"
                ):
                    added += 1
            return "DONE", {
                "sitemap_type": "urlset",
                "locations": len(locations),
                "product_candidates": candidates,
                "added": added,
                "excluded": excluded,
            }

        return "FAILED", {
            "reason": "unsupported_sitemap_root",
            "failure_class": "permanent",
            "root": root_name,
        }

    def _is_product_candidate(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        if not self._is_allowed_url(url):
            return False
        if self._includes and not any(
            pattern.search(parsed.path) for pattern in self._includes
        ):
            return False
        if any(pattern.search(url) for pattern in self._excludes):
            return False
        return not (
            self._product_patterns
            and not any(
                pattern.search(parsed.path) for pattern in self._product_patterns
            )
        )

    def _failure(
        self,
        item: WorkItem,
        failure_class: str,
        reason: str,
        **extra: Any,
    ) -> tuple[str, dict[str, Any]]:
        result = {
            "reason": reason,
            "failure_class": failure_class,
            "attempts": item.attempts,
            **extra,
        }
        if failure_class == "transient" and item.attempts < self._max_attempts():
            delay = self._retry_delay(item.attempts)
            if delay > 0:
                time.sleep(delay)
            result["retryable"] = True
            return "PENDING", result
        return "FAILED", result

    def _max_attempts(self) -> int:
        return max(1, int(self.task.limits.get("max_attempts", 2)))

    def _retry_delay(self, attempt: int) -> float:
        raw = self.task.limits.get("retry_backoff_ms")
        if raw is None:
            raw = self.rule.fetch.get("retry", {}).get("backoff_ms", 1000)
        base = max(float(raw), 0.0) / 1000
        return min(base * (2 ** max(attempt - 1, 0)), 5.0)

    def _seed_sources(self) -> None:
        for source in self.rule.sources:
            source_type = str(source.get("type", "entry_links"))
            if source_type == "entry_links":
                self._add_navigation(
                    str(source.get("url") or self.rule.entry_url),
                    source="entry_links",
                )
            elif source_type == "sitemap":
                urls = list(source.get("urls") or [])
                if source.get("robots") is True:
                    urls.extend(self._robots_sitemaps)
                for url in dict.fromkeys(urls):
                    self._add_navigation(url, source="sitemap")
            elif source_type == "listing":
                url = str(source.get("url") or source.get("seed") or "")
                if not url:
                    continue
                advance = source.get("advance", {"type": "none"})
                self._add_navigation(
                    url,
                    source="listing",
                    result={
                        "advance": advance,
                        "page": int(advance.get("start", 1)),
                        "link_selector": source.get("product_link_selector")
                        or self.rule.discovery.get("link_selector", ""),
                    },
                )
            elif source_type == "html_index":
                url = str(source.get("url") or source.get("seed") or "")
                if not url:
                    continue
                self._add_navigation(
                    url,
                    source="html_index",
                    result={
                        "depth": 0,
                        "max_depth": int(source.get("max_depth", 2)),
                        "link_selector": source.get("link_selector")
                        or self.rule.discovery.get("link_selector", ""),
                        "category_patterns": source.get("category_patterns", []),
                    },
                )

    def _add_navigation(
        self,
        url: str,
        *,
        source: str,
        parent: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> bool:
        if not self._is_allowed_url(url):
            return False
        if (
            self.store.count_items(self.task.task_id, "navigation")
            >= self._max_navigation
        ):
            return False
        normalized = _normalize_url(url)
        item_id = hashlib.sha1(f"nav:{normalized}".encode()).hexdigest()[:16]
        return self.store.add_item(
            WorkItem(
                task_id=self.task.task_id,
                item_id=item_id,
                item_type="navigation",
                url=url,
                normalized_url=normalized,
                stage="discover",
                state="PENDING",
                parent_url=parent,
                discovered_from=source,
                result=result or {},
            )
        )

    def _add_product_item(
        self, url: str, *, parent: str, source: str = "entry_links"
    ) -> bool:
        if self._remaining_product_limit() <= 0:
            return False
        normalized = _normalize_url(url)
        item_id = hashlib.sha1(normalized.encode()).hexdigest()[:16]
        discovery = self.task.task_type == "discovery"
        state = "DONE" if discovery else "PENDING"
        result = {"status": "discovered", "source": parent} if discovery else {}
        item = WorkItem(
            task_id=self.task.task_id,
            item_id=item_id,
            item_type="product",
            url=url,
            normalized_url=normalized,
            stage="discover" if discovery else "fetch",
            state=state,
            parent_url=parent,
            discovered_from=source,
            result=result,
        )
        added = self.store.add_item(item)
        if added and discovery:
            self._append_jsonl(
                self.items_path,
                {
                    "ts": utc_now(),
                    "item_id": item.item_id,
                    "item_type": "product",
                    "url": url,
                    "state": state,
                    "result": result,
                },
            )
            self._event("url_discovered", url=url, source=parent)
        return added

    def _finish_item(
        self,
        item: WorkItem,
        state: str,
        result: dict[str, Any],
        *,
        accept: bool = True,
    ) -> None:
        current = self.store.get_task(self.task.task_id)
        if accept and current is not None and current.state in {"CANCELLING", "CANCELLED"}:
            accept = False
        if not accept and state == "DONE":
            state = "FAILED"
            result = {"reason": "task_cancelled", "failure_class": "blocked"}
        product = result.pop("product", None) if state == "DONE" and accept else None
        if product is not None:
            self._append_product(product)
        failure_class = result.get("failure_class")
        self.store.mark_item(
            item.task_id,
            item.item_id,
            state,
            result,
            failure_class=failure_class,
        )
        self._append_jsonl(
            self.items_path,
            {
                "ts": utc_now(),
                "item_id": item.item_id,
                "item_type": item.item_type,
                "url": item.url,
                "state": state,
                "failure_class": failure_class,
                "result": result,
            },
        )
        self._event(
            "item_finished",
            item_type=item.item_type,
            url=item.url,
            state=state,
            failure_class=failure_class,
        )

    def _cleanup_orphans(self) -> int:
        removed = 0
        if not self.out_dir.is_dir():
            return removed
        for path in self.out_dir.iterdir():
            if path.is_file() and (
                path.name.endswith(".tmp") or path.name.endswith(".partial")
            ):
                try:
                    path.unlink()
                except OSError:
                    continue
                removed += 1
        return removed

    def _quarantine_stale_result(self) -> bool:
        if not self.task_result_path.is_file():
            return False
        backup = self.task_result_path.with_name("task-result.previous.json")
        try:
            backup.unlink(missing_ok=True)
            self.task_result_path.replace(backup)
        except OSError:
            return False
        return True

    def _should_probe_robots(self) -> bool:
        discovery = self.rule.discovery
        if discovery.get("robots_sitemap") is True:
            return True
        sitemap = discovery.get("sitemap")
        if isinstance(sitemap, dict) and sitemap.get("robots") is True:
            return True
        for source in self.rule.sources:
            if source.get("type") == "sitemap" and source.get("robots") is True:
                return True
        strategies = discovery.get("strategies", [])
        return "sitemap" in strategies and not discovery.get("sitemap_urls")

    def _probe_robots_sitemaps(self) -> None:
        """Read robots only for `Sitemap:` lines; never store or enforce rules."""
        if not self._should_probe_robots():
            return
        parsed = urlparse(self.rule.entry_url)
        self._robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        result = self.fetcher.get(self._robots_url)
        self._robots_status = result.status
        if not result.ok:
            self._event(
                "robots_probe_failed",
                url=self._robots_url,
                status=result.status,
                error=result.error,
            )
            return
        text = result.body.decode("utf-8", "replace").removeprefix("\ufeff")
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.lower().startswith("sitemap:"):
                continue
            value = stripped.split(":", 1)[1].strip()
            if value and value not in self._robots_sitemaps:
                self._robots_sitemaps.append(value)
            if len(self._robots_sitemaps) >= 20:
                break
        self._event(
            "robots_sitemaps_probed",
            url=self._robots_url,
            status=result.status,
            sitemaps=len(self._robots_sitemaps),
        )

    def _is_allowed_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        origin = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
        allowed = {
            origin.rstrip("/") for origin in self.rule.site.get("allowed_origins", [])
        }
        if origin.rstrip("/") not in allowed:
            return False
        return any(
            parsed.path.startswith(prefix)
            for prefix in self.rule.site.get("allowed_path_prefixes", [])
        )

    def _remaining_product_limit(self) -> int:
        key = "max_urls" if self.task.task_type == "discovery" else "max_products"
        default = self.rule.task_defaults.get(key, 100)
        limit = int(self.task.limits.get(key, default))
        return max(limit - self.store.count_items(self.task.task_id, "product"), 0)

    def _concurrency(self) -> int:
        defaults = self.rule.task_defaults.get("concurrency", {})
        key = "navigation" if self.task.task_type == "discovery" else "product"
        fallback = defaults.get(key, self.rule.fetch.get("concurrency", 1))
        value = self.task.limits.get("concurrency", {}).get(key, fallback)
        return max(1, min(int(value), 8))

    def _budget_exceeded(self) -> bool:
        max_seconds = self.task.limits.get("max_seconds")
        if max_seconds is not None and time.monotonic() - self._started_monotonic >= float(
            max_seconds
        ):
            return True
        max_requests = self.task.limits.get("max_requests")
        if max_requests is not None:
            requests = int(getattr(self.fetcher, "requests", 0))
            if requests >= int(max_requests):
                return True
        return False

    def _settle(self, control: str) -> None:
        if control == "PAUSED":
            self.store.update_task(self.task.task_id, state="PAUSED")
            self._write_progress()
            self._event("task_paused")
            return
        if control == "CANCELLED":
            self._finalize("CANCELLED", "CANCELLED", "USER_CANCELLED", "user cancelled")
            return
        outcome = self._outcome()
        self._finalize("FINISHED", outcome, self._stop_reason, self._stop_detail)

    def _outcome(self) -> str:
        counts = self.store.item_counts(self.task.task_id, "product")
        valid = counts.get("DONE", 0)
        pending = counts.get("PENDING", 0) + counts.get("IN_FLIGHT", 0)
        failed = counts.get("FAILED", 0)
        if self._stop_reason in {
            "ACCESS_DENIED",
            "BUDGET_EXHAUSTED",
            "ENVIRONMENT_ERROR",
            "PLAN_ERROR",
        }:
            return "PARTIAL" if valid else "FAILED"
        if pending or failed:
            return "PARTIAL" if valid else "FAILED"
        if valid or counts.get("EXCLUDED", 0):
            return "COMPLETED"
        return "FAILED"

    def _finalize(
        self,
        state: str,
        outcome: str,
        stop_reason: str,
        stop_detail: str,
    ) -> None:
        finished_at = utc_now()
        task_result = self._task_result(state, outcome, stop_reason, stop_detail, finished_at)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        _write_json(self.task_result_path, task_result)
        self._write_urls_csv()
        self._write_products_csv()
        self.store.update_task(
            self.task.task_id,
            state=state,
            outcome=outcome,
            stop_reason=stop_reason,
            counters=task_result["counts"],
            finished_at=finished_at,
        )
        self._event("task_finished", state=state, outcome=outcome, stop_reason=stop_reason)

    def _write_progress(self) -> None:
        counts = self._counts()
        _write_json(
            self.progress_path,
            {
                "task_id": self.task.task_id,
                "task_type": self.task.task_type,
                "state": "PAUSED",
                "updated_at": utc_now(),
                "counts": counts,
            },
        )

    def _task_result(
        self,
        state: str,
        outcome: str,
        stop_reason: str,
        stop_detail: str,
        finished_at: str,
    ) -> dict[str, Any]:
        counts = self._counts()
        if self.task.task_type == "discovery":
            coverage = _coverage(
                counts["url_candidates"],
                counts["valid_urls"] + counts["excluded_urls"] + counts["failed_urls"],
                "declared-source URL candidates",
            )
        else:
            coverage = _coverage(
                counts["product_candidates"],
                counts["processed_products"],
                "declared-source product candidates",
            )
        quality_exceptions = []
        for product in self._products:
            if (
                product.get("description_status") == "complete"
                and not product.get("missing_reasons")
            ):
                continue
            quality_exceptions.append(
                {
                    "source_url": product["source_url"],
                    "description_status": product.get("description_status", "complete"),
                    "partial_reason": product.get("partial_reason"),
                    "missing_reasons": product.get("missing_reasons", {}),
                }
            )
        limitations = [
            "Bounded to the declared discovery sources and limits; not full-site coverage.",
            "Static HTML only; no browser rendering, login or access-control bypass.",
            "Runtime LLM calls: 0; no raw page HTML is retained.",
        ]
        limitations.extend(self.rule.raw.get("evidence", {}).get("limitations", []))
        limitations = list(dict.fromkeys(str(item) for item in limitations))
        return {
            "task_id": self.task.task_id,
            "task_type": self.task.task_type,
            "plan_id": self.task.plan_id,
            "plan_version": self.task.plan_version,
            "market": self.rule.site.get("market"),
            "locale": self.rule.site.get("locale"),
            "state": state,
            "outcome": outcome,
            "stop_reason": stop_reason,
            "stop_detail": stop_detail,
            "started_at": self.task.started_at,
            "finished_at": finished_at,
            "counts": counts,
            "failure_classes": self._failure_classes(),
            "recovery": self._recovery,
            "coverage": coverage,
            "business_acceptance": {
                "status": "NOT_REVIEWED",
                "accepted_by": None,
                "accepted_at": None,
                "reason": "R06 runtime prototype; no business sign-off yet.",
                "scope": "discovery sources declared by the rule",
            },
            "quality_exceptions": quality_exceptions,
            "pricing": {
                "policy": "Choose the smaller public pretax/gross pair per docs/02.",
                "products": [
                    {
                        "source_url": product["source_url"],
                        "displayed": product.get("price_displayed"),
                        "pretax": product.get("price_pretax"),
                        "chosen": round(product["price_amount"], 6),
                        "basis": product.get("tax_basis", "unspecified"),
                    }
                    for product in self._products
                ],
            },
            "runtime": {
                "executor": RUNTIME_VERSION,
                "llm_calls": 0,
                "raw_pages_retained": False,
                "http_engine": "scrapling.FetcherSession (curl_cffi, static HTML)",
            },
            "access": {
                "entry_url": self.rule.entry_url,
                "sources": [str(source.get("type")) for source in self.rule.sources],
                "robots_url": self._robots_url,
                "robots_status": self._robots_status,
                "robots_sitemaps": self._robots_sitemaps,
                "robots_policy": "sitemap_line_only",
                "delay_ms": self.rule.fetch.get("delay_ms", 1000),
                "max_products": self.task.limits.get("max_products"),
                "max_urls": self.task.limits.get("max_urls"),
                "max_seconds": self.task.limits.get("max_seconds"),
                "max_attempts": self._max_attempts(),
                "browser_launched": False,
                "login_used": False,
            },
            "resources": {
                "browser_launched": False,
                "processes": [],
                "orphan_files_removed": self._recovery.get(
                    "orphan_files_removed", 0
                ),
            },
            "limitations": limitations,
        }

    def _failure_classes(self) -> dict[str, int]:
        counts = {"transient": 0, "permanent": 0, "blocked": 0, "unknown": 0}
        for item in self.store.items(self.task.task_id):
            if item.state != "FAILED":
                continue
            failure_class = item.failure_class or item.result.get("failure_class")
            if failure_class not in counts:
                failure_class = "unknown"
            counts[failure_class] += 1
        return counts

    def _counts(self) -> dict[str, int]:
        items = self.store.items(self.task.task_id)
        navigation = [item for item in items if item.item_type == "navigation"]
        products = [item for item in items if item.item_type == "product"]
        by_state = {state: 0 for state in ("PENDING", "IN_FLIGHT", "DONE", "EXCLUDED", "FAILED")}
        for item in products:
            by_state[item.state] = by_state.get(item.state, 0) + 1
        pending = by_state["PENDING"] + by_state["IN_FLIGHT"]
        processed = by_state["DONE"] + by_state["EXCLUDED"] + by_state["FAILED"]
        if self.task.task_type == "discovery":
            return {
                "navigation_urls": len(navigation),
                "discovered_urls": len(items),
                "url_candidates": len(products),
                "pending_urls": pending,
                "valid_urls": by_state["DONE"],
                "excluded_urls": by_state["EXCLUDED"],
                "failed_urls": by_state["FAILED"],
            }
        return {
            "navigation_urls": len(navigation),
            "discovered_urls": len(items),
            "product_candidates": len(products),
            "pending_products": pending,
            "in_flight_products": by_state["IN_FLIGHT"],
            "processed_products": processed,
            "valid_products": by_state["DONE"],
            "excluded_products": by_state["EXCLUDED"],
            "failed_products": by_state["FAILED"],
            "partial_description_products": sum(
                1
                for product in self._products
                if product.get("description_status") == "partial"
            ),
        }

    def _load_products(self) -> int:
        if not self.products_path.is_file():
            return 0
        valid_lines: list[str] = []
        corrupt = 0
        for line in self.products_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                product = json.loads(line)
            except json.JSONDecodeError:
                corrupt += 1
                continue
            valid_lines.append(line)
            self._products.append(product)
            if product.get("source_url"):
                self._seen_canonical.add(product["source_url"])
        if corrupt:
            payload = "\n".join(valid_lines)
            write_text(
                self.products_path,
                payload + "\n" if payload else "",
                lock=self._write_lock,
            )
        self._corrupt_products = corrupt
        return corrupt

    def _append_product(self, product: dict[str, Any]) -> None:
        self._products.append(product)
        self._append_jsonl(self.products_path, product)

    def _write_urls_csv(self) -> None:
        items = [
            item
            for item in self.store.items(self.task.task_id, "product")
            if item.state == "DONE"
        ]
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(["url", "source", "status", "title"])
        for item in items:
            writer.writerow(
                [
                    csv_safe(item.url),
                    csv_safe(item.parent_url or ""),
                    csv_safe(str(item.result.get("status", ""))),
                    csv_safe(str(item.result.get("name", ""))),
                ]
            )
        write_text(self.urls_path, buffer.getvalue(), lock=self._write_lock)

    def _write_products_csv(self) -> None:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        for product in self._products:
            writer.writerow(
                [
                    csv_safe(str(product.get("name", ""))),
                    format_price(float(product.get("price_amount", 0))),
                    csv_safe(str(product.get("price_currency", ""))),
                    csv_safe(str(product.get("primary_image_url", ""))),
                    csv_safe(str(product.get("description_html", ""))),
                    csv_safe(str(product.get("category", ""))),
                    csv_safe(str(product.get("brand", ""))),
                    csv_safe(str(product.get("attributes", ""))),
                    csv_safe(str(product.get("source_url", ""))),
                ]
            )
        write_text(self.products_csv_path, buffer.getvalue(), lock=self._write_lock)

    def _event(self, event_type: str, **payload: Any) -> None:
        self._append_jsonl(
            self.events_path,
            {"ts": utc_now(), "event": event_type, **payload},
        )

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        append_jsonl(path, payload, lock=self._write_lock)


def _record_payload(record: Any) -> dict[str, Any]:
    return {
        "name": record.name,
        "price_amount": record.price_amount,
        "price_currency": record.price_currency,
        "primary_image_url": record.primary_image_url,
        "description_html": record.description_html,
        "category": record.category,
        "brand": record.brand,
        "attributes": record.attributes,
        "source_url": record.source_url,
        "description_status": record.description_status,
        "partial_reason": record.partial_reason,
        "missing_reasons": record.missing_reasons,
        "field_sources": record.field_sources,
        "price_displayed": record.price_displayed,
        "price_pretax": record.price_pretax,
        "tax_basis": record.tax_basis,
    }


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
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


def _coverage(denominator: int, covered: int, source: str) -> dict[str, Any]:
    if denominator <= 0:
        return {
            "status": "UNKNOWN",
            "denominator_source": None,
            "denominator": None,
            "covered": None,
            "notes": "No candidate URLs were discovered.",
        }
    return {
        "status": "PARTIAL",
        "denominator_source": source,
        "denominator": denominator,
        "covered": covered,
        "notes": "Bounded sample from one entry page; not full-site coverage.",
    }


def _write_json(path: Path, payload: Any) -> None:
    write_json(path, payload)
