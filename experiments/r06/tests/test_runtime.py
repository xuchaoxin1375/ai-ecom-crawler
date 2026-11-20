"""Runtime tests for the R06 task ledger, runner and parallel worker; no network access."""

from __future__ import annotations

import csv
import gzip
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.models import FetchResult, Task, WorkItem
from runtime.rule import RuleError, load_rule
from runtime.runner import TaskRunner
from runtime.store import TaskStore
from runtime.worker import Worker

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "plans" / "familidoo-runtime.yaml"
ENTRY = "https://www.familidoo.fr/fr/"
PRODUCT = "https://www.familidoo.fr/fr/cat/1-a.html"
ROBOTS = "https://www.familidoo.fr/robots.txt"

ROBOTS_OK = "User-agent: *\nAllow: /\n"
SITEMAP = "https://www.familidoo.fr/sitemap-products.xml"
SITEMAP_INDEX = "https://www.familidoo.fr/sitemap.xml"
SITEMAP_IMAGES = "https://www.familidoo.fr/sitemap-images.xml"
SITEMAP_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    f"<url><loc>{PRODUCT}</loc></url>"
    f"<url><loc>{ENTRY}</loc></url>"
    "</urlset>"
)
SITEMAP_INDEX_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    f"<sitemap><loc>{SITEMAP}</loc></sitemap>"
    "</sitemapindex>"
)
SITEMAP_INDEX_WITH_IMAGES_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    f"<sitemap><loc>{SITEMAP}</loc></sitemap>"
    f"<sitemap><loc>{SITEMAP_IMAGES}</loc></sitemap>"
    "</sitemapindex>"
)
LISTING = "https://www.familidoo.fr/fr/list?page=1"
SITE_MAP = "https://www.familidoo.fr/fr/site-map"
CATEGORY = "https://www.familidoo.fr/fr/categories/"
PRODUCT2 = "https://www.familidoo.fr/fr/cat/2-b.html"
PRODUCT3 = "https://www.familidoo.fr/fr/cat/3-c.html"
PUBLIC_JSON = "https://www.familidoo.fr/products.json?page=1"
PUBLIC_JSON_2 = "https://www.familidoo.fr/products.json?page=2"
ENTRY_HTML = (
    "<html><body>"
    '<a class="product_img_link" href="/fr/cat/1-a.html">Product</a>'
    "</body></html>"
)
PRODUCT_HTML = (
    "<html><head>"
    "<title>Test Product - Familidoo</title>"
    '<meta property="og:site_name" content="Familidoo">'
    '<meta property="og:image" content="https://www.familidoo.fr/img/p.jpg">'
    '<meta property="product:price:amount" content="12.00">'
    '<meta property="product:pretax_price:amount" content="10.00">'
    '<meta property="product:price:currency" content="EUR">'
    '<link rel="canonical" href="https://www.familidoo.fr/fr/cat/1-a.html">'
    "</head><body>"
    '<nav class="breadcrumb_nav">'
    '<span itemprop="name">Accueil</span>'
    '<span itemprop="name">Cat</span>'
    '<span itemprop="name">Test Product</span>'
    "</nav>"
    '<h1 itemprop="name">Test Product</h1>'
    '<div class="product_description_container"><p>Body text.</p></div>'
    "</body></html>"
)


class FakeFetcher:
    def __init__(self, pages: dict[str, tuple[int, str | bytes]]) -> None:
        self.pages = pages
        self.calls: list[str] = []
        self.requests = 0
        self.retries = 0

    def get(self, url: str) -> FetchResult:
        self.calls.append(url)
        self.requests += 1
        status, body = self.pages.get(url, (404, ""))
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        return FetchResult(status=status, url=url, body=raw)


class BlockingFetcher(FakeFetcher):
    def __init__(self, pages: dict[str, tuple[int, str]], block_url: str) -> None:
        super().__init__(pages)
        self.block_url = block_url
        self.started = threading.Event()
        self.release = threading.Event()

    def get(self, url: str) -> FetchResult:
        if url == self.block_url:
            self.started.set()
            self.release.wait(timeout=5)
        return super().get(url)


class FlakyFetcher(FakeFetcher):
    def __init__(
        self,
        pages: dict[str, tuple[int, str]],
        *,
        flaky_url: str,
        failures: int = 1,
    ) -> None:
        super().__init__(pages)
        self.flaky_url = flaky_url
        self.failures = failures

    def get(self, url: str) -> FetchResult:
        if url == self.flaky_url and self.failures > 0:
            self.failures -= 1
            self.calls.append(url)
            self.requests += 1
            return FetchResult(status=0, url=url, error="timeout")
        return super().get(url)


def make_task(task_type: str, task_id: str | None = None) -> Task:
    return Task(
        task_id=task_id or f"test-{task_type}",
        plan_id="familidoo-fr-runtime",
        plan_version="2026.11.20-1",
        task_type=task_type,
        state="QUEUED",
        input={"rule_path": str(PLAN)},
        limits={
            "max_urls": 10,
            "max_products": 10,
            "max_seconds": 10,
            "max_attempts": 2,
            "retry_backoff_ms": 0,
            "concurrency": {"navigation": 1, "product": 2},
        },
        output={"url_list": True, "product_csv": task_type == "product"},
    )


def read_csv(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def sources_rule(root: Path, sources: list[dict[str, object]]):
    data = yaml.safe_load(PLAN.read_text(encoding="utf-8"))
    data["schema_version"] = "1.1"
    data["site"]["allowed_path_prefixes"] = ["/"]
    data["discovery"] = {
        "sources": sources,
        "product_url_patterns": ["^/fr/cat/"],
        "url_identity": "canonical",
        "limits": {"max_navigation": 10, "max_products": 10},
    }
    path = root / "sources-rule.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return load_rule(path)


def listing_html(product: str, next_href: str | None = None) -> str:
    link = f'<a class="product_img_link" href="{product}">Product</a>'
    nxt = f'<a rel="next" href="{next_href}">Next</a>' if next_href else ""
    return f"<html><body>{link}{nxt}</body></html>"


def html_index_html(product: str | None, category: str | None) -> str:
    links = []
    if product:
        links.append(f'<a href="{product}">Product</a>')
    if category:
        links.append(f'<a href="{category}">Category</a>')
    return f"<html><body>{''.join(links)}</body></html>"


class RuleTests(unittest.TestCase):
    def test_runtime_rule_loads(self) -> None:
        rule = load_rule(PLAN)
        self.assertEqual(rule.rule_id, "familidoo-fr-runtime")
        self.assertTrue(rule.supports("discovery"))
        self.assertTrue(rule.supports("product"))
        self.assertEqual(rule.entry_url, ENTRY)

    def test_rejects_unknown_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rule.yaml"
            path.write_text(
                PLAN.read_text(encoding="utf-8").replace(
                    'strategies: ["entry_links"]', 'strategies: ["sitemap"]'
                ),
                encoding="utf-8",
            )
            with self.assertRaises(RuleError):
                load_rule(path)

    def test_rejects_invalid_scope_regex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rule.yaml"
            path.write_text(
                PLAN.read_text(encoding="utf-8").replace(
                    "'/fr/.*\\.html$'", "'/fr/(unclosed'"
                ),
                encoding="utf-8",
            )
            with self.assertRaises(RuleError):
                load_rule(path)


class StoreTests(unittest.TestCase):
    def test_item_claim_and_reset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(Path(tmp) / "tasks.db")
            task = make_task("discovery", "store-task")
            store.create_task(task)
            item = WorkItem(
                task_id=task.task_id,
                item_id="i1",
                item_type="product",
                url=PRODUCT,
                normalized_url=PRODUCT,
            )
            self.assertTrue(store.add_item(item))
            self.assertFalse(store.add_item(item))
            claimed = store.claim_items(task.task_id, 2)
            self.assertEqual(len(claimed), 1)
            self.assertEqual(claimed[0].state, "IN_FLIGHT")
            self.assertEqual(store.reset_in_flight(task.task_id), 1)
            self.assertEqual(store.item_counts(task.task_id)["PENDING"], 1)
            store.mark_item(task.task_id, "i1", "DONE", {"status": "valid"})
            self.assertEqual(store.item_counts(task.task_id)["DONE"], 1)

    def test_reconcile_resets_then_fails_after_max_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(Path(tmp) / "tasks.db")
            task = make_task("product", "reconcile-task")
            store.create_task(task)
            item = WorkItem(
                task_id=task.task_id,
                item_id="i1",
                item_type="product",
                url=PRODUCT,
                normalized_url=PRODUCT,
            )
            store.add_item(item)
            store.claim_items(task.task_id, 1)
            first = store.reconcile_task(task.task_id, 2)
            self.assertEqual(first, {"in_flight": 1, "reset": 1, "failed": 0})
            self.assertEqual(store.item_counts(task.task_id)["PENDING"], 1)

            store.claim_items(task.task_id, 1)
            second = store.reconcile_task(task.task_id, 2)
            self.assertEqual(second, {"in_flight": 1, "reset": 0, "failed": 1})
            stored = store.items(task.task_id, "product")[0]
            self.assertEqual(stored.state, "FAILED")
            self.assertEqual(stored.failure_class, "transient")
            self.assertEqual(stored.result["reason"], "attempts_exhausted")

    def test_migrates_legacy_rule_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "legacy.db"
            connection = sqlite3.connect(db)
            connection.executescript(
                """
                CREATE TABLE tasks (
                    task_id TEXT PRIMARY KEY,
                    rule_id TEXT NOT NULL,
                    rule_version TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    state TEXT NOT NULL,
                    outcome TEXT,
                    stop_reason TEXT,
                    input_json TEXT NOT NULL,
                    limits_json TEXT NOT NULL,
                    output_json TEXT NOT NULL,
                    counters_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );
                CREATE TABLE task_items (
                    task_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    url TEXT NOT NULL,
                    normalized_url TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    parent_url TEXT,
                    discovered_from TEXT,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, item_id),
                    UNIQUE (task_id, item_type, normalized_url)
                );
                """
            )
            connection.execute(
                """
                INSERT INTO tasks VALUES (
                    'legacy', 'familidoo-fr-runtime', '2026.11.20-1',
                    'product', 'FINISHED', 'COMPLETED', 'NATURAL_END',
                    '{}', '{}', '{}', '{}', '2026-11-20T00:00:00Z',
                    '2026-11-20T00:00:00Z', NULL, NULL
                )
                """
            )
            connection.commit()
            connection.close()

            store = TaskStore(db)
            task = store.get_task("legacy")
            assert task is not None
            self.assertEqual(task.plan_id, "familidoo-fr-runtime")
            self.assertEqual(task.plan_version, "2026.11.20-1")
            item = WorkItem(
                task_id="legacy",
                item_id="i1",
                item_type="product",
                url=PRODUCT,
                normalized_url=PRODUCT,
            )
            self.assertTrue(store.add_item(item))
            self.assertIsNone(store.items("legacy", "product")[0].failure_class)


class DiscoveryTests(unittest.TestCase):
    def test_discovery_outputs_urls_without_product_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = load_rule(PLAN)
            task = make_task("discovery")
            store.create_task(task)
            fetcher = FakeFetcher(
                {
                    ROBOTS: (200, ROBOTS_OK),
                    ENTRY: (200, ENTRY_HTML),
                }
            )
            result = TaskRunner(
                store, rule, task, fetcher=fetcher, out_root=root / "tasks"
            ).run()
            self.assertEqual(result, "FINISHED")
            self.assertNotIn(PRODUCT, fetcher.calls)
            stored = store.get_task(task.task_id)
            assert stored is not None
            self.assertEqual(stored.state, "FINISHED")
            self.assertEqual(stored.outcome, "COMPLETED")
            rows = read_csv(root / "tasks" / task.task_id / "urls.csv")
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1][0], PRODUCT)
            task_result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(task_result["task_type"], "discovery")
            self.assertEqual(task_result["counts"]["url_candidates"], 1)
            self.assertEqual(task_result["counts"]["valid_urls"], 1)


class RobotsTests(unittest.TestCase):
    def test_robots_disallow_does_not_block_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = load_rule(PLAN)
            task = make_task("discovery", "robots-disallow")
            store.create_task(task)
            fetcher = FakeFetcher(
                {
                    ROBOTS: (200, "User-agent: *\nDisallow: /fr/cat/\n"),
                    ENTRY: (200, ENTRY_HTML),
                }
            )
            TaskRunner(store, rule, task, fetcher=fetcher, out_root=root / "tasks").run()
            task_result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            counts = task_result["counts"]
            self.assertEqual(counts["url_candidates"], 1)
            self.assertEqual(counts["excluded_urls"], 0)
            self.assertEqual(counts["valid_urls"], 1)
            self.assertEqual(task_result["outcome"], "COMPLETED")
            rows = read_csv(root / "tasks" / task.task_id / "urls.csv")
            self.assertEqual(len(rows), 2)
            self.assertFalse(
                (root / "tasks" / task.task_id / "robots.txt").exists(),
                "full robots.txt must not be retained",
            )

    def test_robots_probe_keeps_only_sitemap_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = load_rule(PLAN)
            rule.raw["discovery"]["robots_sitemap"] = True
            task = make_task("discovery", "robots-sitemap")
            store.create_task(task)
            sitemap = "https://www.familidoo.fr/sitemap.xml"
            fetcher = FakeFetcher(
                {
                    ROBOTS: (
                        200,
                        (
                            "User-agent: *\n"
                            "Disallow: /fr/cat/\n"
                            f"Sitemap: {sitemap}\n"
                            "Sitemap: https://www.familidoo.fr/sitemap-products.xml\n"
                        ),
                    ),
                    ENTRY: (200, ENTRY_HTML),
                }
            )
            TaskRunner(store, rule, task, fetcher=fetcher, out_root=root / "tasks").run()
            task_result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                task_result["access"]["robots_sitemaps"],
                [sitemap, "https://www.familidoo.fr/sitemap-products.xml"],
            )
            self.assertEqual(task_result["counts"]["valid_urls"], 1)
            self.assertEqual(task_result["counts"]["excluded_urls"], 0)
            self.assertFalse((root / "tasks" / task.task_id / "robots.txt").exists())


class SitemapTests(unittest.TestCase):
    def test_sitemap_discovery_outputs_product_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = sources_rule(root, [{"type": "sitemap", "urls": [SITEMAP]}])
            task = make_task("discovery", "sitemap-discovery")
            store.create_task(task)
            fetcher = FakeFetcher({SITEMAP: (200, SITEMAP_XML)})
            TaskRunner(
                store, rule, task, fetcher=fetcher, out_root=root / "tasks"
            ).run()
            self.assertNotIn(PRODUCT, fetcher.calls)
            result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["counts"]["navigation_urls"], 1)
            self.assertEqual(result["counts"]["url_candidates"], 1)
            self.assertEqual(result["counts"]["valid_urls"], 1)
            self.assertEqual(result["outcome"], "COMPLETED")
            rows = read_csv(root / "tasks" / task.task_id / "urls.csv")
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1][0], PRODUCT)

    def test_sitemap_index_follows_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = sources_rule(root, [{"type": "sitemap", "urls": [SITEMAP_INDEX]}])
            task = make_task("discovery", "sitemap-index")
            store.create_task(task)
            fetcher = FakeFetcher(
                {
                    SITEMAP_INDEX: (200, SITEMAP_INDEX_XML),
                    SITEMAP: (200, SITEMAP_XML),
                }
            )
            TaskRunner(
                store, rule, task, fetcher=fetcher, out_root=root / "tasks"
            ).run()
            result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["counts"]["navigation_urls"], 2)
            self.assertEqual(result["counts"]["valid_urls"], 1)

    def test_sitemap_index_filters_children(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = sources_rule(
                root,
                [
                    {
                        "type": "sitemap",
                        "urls": [SITEMAP_INDEX],
                        "sitemap_patterns": ["sitemap-products"],
                    }
                ],
            )
            task = make_task("discovery", "sitemap-filter")
            store.create_task(task)
            fetcher = FakeFetcher(
                {
                    SITEMAP_INDEX: (200, SITEMAP_INDEX_WITH_IMAGES_XML),
                    SITEMAP: (200, SITEMAP_XML),
                }
            )
            TaskRunner(
                store, rule, task, fetcher=fetcher, out_root=root / "tasks"
            ).run()
            self.assertNotIn(SITEMAP_IMAGES, fetcher.calls)
            result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["counts"]["navigation_urls"], 2)
            self.assertEqual(result["counts"]["valid_urls"], 1)

    def test_sitemap_gzip_is_decompressed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = sources_rule(root, [{"type": "sitemap", "urls": [SITEMAP]}])
            task = make_task("discovery", "sitemap-gzip")
            store.create_task(task)
            fetcher = FakeFetcher(
                {SITEMAP: (200, gzip.compress(SITEMAP_XML.encode("utf-8")))}
            )
            TaskRunner(
                store, rule, task, fetcher=fetcher, out_root=root / "tasks"
            ).run()
            result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["counts"]["valid_urls"], 1)
            self.assertEqual(result["outcome"], "COMPLETED")

    def test_sitemap_product_task_fetches_product(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = sources_rule(root, [{"type": "sitemap", "urls": [SITEMAP]}])
            task = make_task("product", "sitemap-product")
            store.create_task(task)
            fetcher = FakeFetcher(
                {
                    SITEMAP: (200, SITEMAP_XML),
                    PRODUCT: (200, PRODUCT_HTML),
                }
            )
            TaskRunner(
                store, rule, task, fetcher=fetcher, out_root=root / "tasks"
            ).run()
            self.assertIn(PRODUCT, fetcher.calls)
            result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["counts"]["valid_products"], 1)
            self.assertEqual(result["outcome"], "COMPLETED")
            rows = read_csv(root / "tasks" / task.task_id / "products.csv")
            self.assertEqual(len(rows), 2)

    def test_robots_sitemap_source_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = sources_rule(root, [{"type": "sitemap", "robots": True}])
            task = make_task("discovery", "sitemap-robots")
            store.create_task(task)
            fetcher = FakeFetcher(
                {
                    ROBOTS: (
                        200,
                        f"User-agent: *\nDisallow: /\nSitemap: {SITEMAP}\n",
                    ),
                    SITEMAP: (200, SITEMAP_XML),
                }
            )
            TaskRunner(
                store, rule, task, fetcher=fetcher, out_root=root / "tasks"
            ).run()
            result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["access"]["robots_sitemaps"], [SITEMAP])
            self.assertEqual(result["counts"]["valid_urls"], 1)
            self.assertFalse(
                (root / "tasks" / task.task_id / "robots.txt").exists()
            )


class PublicJsonTests(unittest.TestCase):
    def test_public_json_page_param(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = sources_rule(
                root,
                [
                    {
                        "type": "public_json",
                        "url": PUBLIC_JSON,
                        "items_path": "products",
                        "url_field": "url",
                        "pagination": {
                            "type": "page_param",
                            "param": "page",
                            "max_pages": 2,
                        },
                    }
                ],
            )
            task = make_task("discovery", "public-json")
            store.create_task(task)
            fetcher = FakeFetcher(
                {
                    PUBLIC_JSON: (
                        200,
                        json.dumps(
                            {"products": [{"url": PRODUCT}, {"url": PRODUCT2}]}
                        ),
                    ),
                    PUBLIC_JSON_2: (
                        200,
                        json.dumps({"products": [{"url": PRODUCT3}]}),
                    ),
                }
            )
            TaskRunner(
                store, rule, task, fetcher=fetcher, out_root=root / "tasks"
            ).run()
            result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["counts"]["navigation_urls"], 2)
            self.assertEqual(result["counts"]["valid_urls"], 3)
            self.assertNotIn(PRODUCT, fetcher.calls)

    def test_public_json_offset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            start = "https://www.familidoo.fr/products.json?offset=0&limit=2"
            second = "https://www.familidoo.fr/products.json?offset=2&limit=2"
            rule = sources_rule(
                root,
                [
                    {
                        "type": "public_json",
                        "url": start,
                        "items_path": "products",
                        "url_field": "url",
                        "pagination": {
                            "type": "offset",
                            "offset_param": "offset",
                            "limit_param": "limit",
                            "page_size": 2,
                            "max_pages": 2,
                            "total_path": "total",
                        },
                    }
                ],
            )
            task = make_task("discovery", "public-json-offset")
            store.create_task(task)
            fetcher = FakeFetcher(
                {
                    start: (
                        200,
                        json.dumps(
                            {
                                "products": [{"url": PRODUCT}, {"url": PRODUCT2}],
                                "total": 3,
                            }
                        ),
                    ),
                    second: (
                        200,
                        json.dumps(
                            {"products": [{"url": PRODUCT3}], "total": 3}
                        ),
                    ),
                }
            )
            TaskRunner(
                store, rule, task, fetcher=fetcher, out_root=root / "tasks"
            ).run()
            result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["counts"]["navigation_urls"], 2)
            self.assertEqual(result["counts"]["valid_urls"], 3)


class HtmlIndexTests(unittest.TestCase):
    def test_html_index_follows_category_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = sources_rule(
                root,
                [
                    {
                        "type": "html_index",
                        "url": SITE_MAP,
                        "link_selector": "a",
                        "category_patterns": ["^/fr/categories/"],
                        "max_depth": 1,
                    }
                ],
            )
            task = make_task("discovery", "html-index")
            store.create_task(task)
            fetcher = FakeFetcher(
                {
                    SITE_MAP: (200, html_index_html(PRODUCT, "/fr/categories/")),
                    CATEGORY: (200, html_index_html(PRODUCT2, None)),
                }
            )
            TaskRunner(
                store, rule, task, fetcher=fetcher, out_root=root / "tasks"
            ).run()
            result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["counts"]["navigation_urls"], 2)
            self.assertEqual(result["counts"]["url_candidates"], 2)
            self.assertEqual(result["counts"]["valid_urls"], 2)
            self.assertNotIn(PRODUCT, fetcher.calls)
            self.assertNotIn(PRODUCT2, fetcher.calls)

    def test_html_index_respects_max_depth_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = sources_rule(
                root,
                [
                    {
                        "type": "html_index",
                        "url": SITE_MAP,
                        "link_selector": "a",
                        "category_patterns": ["^/fr/categories/"],
                        "max_depth": 0,
                    }
                ],
            )
            task = make_task("discovery", "html-index-depth")
            store.create_task(task)
            fetcher = FakeFetcher(
                {
                    SITE_MAP: (200, html_index_html(PRODUCT, "/fr/categories/")),
                }
            )
            TaskRunner(
                store, rule, task, fetcher=fetcher, out_root=root / "tasks"
            ).run()
            result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["counts"]["navigation_urls"], 1)
            self.assertEqual(result["counts"]["valid_urls"], 1)


class ListingTests(unittest.TestCase):
    def test_page_param_follows_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = sources_rule(
                root,
                [
                    {
                        "type": "listing",
                        "url": LISTING,
                        "product_link_selector": "a.product_img_link",
                        "advance": {
                            "type": "page_param",
                            "param": "page",
                            "max_pages": 3,
                        },
                    }
                ],
            )
            task = make_task("discovery", "listing-pages")
            store.create_task(task)
            fetcher = FakeFetcher(
                {
                    LISTING: (200, listing_html(PRODUCT)),
                    "https://www.familidoo.fr/fr/list?page=2": (
                        200,
                        listing_html(PRODUCT2),
                    ),
                    "https://www.familidoo.fr/fr/list?page=3": (
                        200,
                        listing_html(PRODUCT3),
                    ),
                }
            )
            TaskRunner(
                store, rule, task, fetcher=fetcher, out_root=root / "tasks"
            ).run()
            result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["counts"]["navigation_urls"], 3)
            self.assertEqual(result["counts"]["url_candidates"], 3)
            self.assertEqual(result["counts"]["valid_urls"], 3)
            rows = read_csv(root / "tasks" / task.task_id / "urls.csv")
            self.assertEqual(len(rows), 4)
            self.assertNotIn(PRODUCT, fetcher.calls)

    def test_next_link_follows_href(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = sources_rule(
                root,
                [
                    {
                        "type": "listing",
                        "url": LISTING,
                        "product_link_selector": "a.product_img_link",
                        "advance": {
                            "type": "next_link",
                            "selector": "a[rel=next]",
                            "max_pages": 5,
                        },
                    }
                ],
            )
            task = make_task("discovery", "listing-next")
            store.create_task(task)
            fetcher = FakeFetcher(
                {
                    LISTING: (200, listing_html(PRODUCT, "/fr/list?page=2")),
                    "https://www.familidoo.fr/fr/list?page=2": (
                        200,
                        listing_html(PRODUCT2),
                    ),
                }
            )
            TaskRunner(
                store, rule, task, fetcher=fetcher, out_root=root / "tasks"
            ).run()
            result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["counts"]["navigation_urls"], 2)
            self.assertEqual(result["counts"]["valid_urls"], 2)

    def test_listing_product_task_fetches_products(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = sources_rule(
                root,
                [
                    {
                        "type": "listing",
                        "url": LISTING,
                        "product_link_selector": "a.product_img_link",
                        "advance": {
                            "type": "page_param",
                            "param": "page",
                            "max_pages": 2,
                        },
                    }
                ],
            )
            task = make_task("product", "listing-product")
            store.create_task(task)
            fetcher = FakeFetcher(
                {
                    LISTING: (200, listing_html(PRODUCT)),
                    "https://www.familidoo.fr/fr/list?page=2": (
                        200,
                        listing_html(PRODUCT2),
                    ),
                    PRODUCT: (200, PRODUCT_HTML),
                    PRODUCT2: (200, PRODUCT_HTML.replace(PRODUCT, PRODUCT2)),
                }
            )
            TaskRunner(
                store, rule, task, fetcher=fetcher, out_root=root / "tasks"
            ).run()
            result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["counts"]["valid_products"], 2)
            self.assertEqual(result["outcome"], "COMPLETED")


class ProductTests(unittest.TestCase):
    def test_product_outputs_nine_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = load_rule(PLAN)
            task = make_task("product")
            store.create_task(task)
            fetcher = FakeFetcher(
                {
                    ROBOTS: (200, ROBOTS_OK),
                    ENTRY: (200, ENTRY_HTML),
                    PRODUCT: (200, PRODUCT_HTML),
                }
            )
            TaskRunner(store, rule, task, fetcher=fetcher, out_root=root / "tasks").run()
            rows = read_csv(root / "tasks" / task.task_id / "products.csv")
            self.assertEqual(len(rows), 2)
            self.assertEqual(len(rows[0]), 9)
            self.assertEqual(rows[1][0], "Test Product")
            self.assertEqual(rows[1][1], "10.00")
            self.assertEqual(rows[1][2], "EUR")
            task_result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(task_result["counts"]["valid_products"], 1)
            self.assertEqual(task_result["outcome"], "COMPLETED")
            self.assertEqual(task_result["plan_id"], "familidoo-fr-runtime")
            self.assertEqual(task_result["plan_version"], "2026.11.20-1")
            self.assertNotIn("rule_id", task_result)
            self.assertEqual(
                task_result["failure_classes"],
                {"transient": 0, "permanent": 0, "blocked": 0, "unknown": 0},
            )


class RetryTests(unittest.TestCase):
    def test_transient_failure_retries_until_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = load_rule(PLAN)
            task = make_task("product", "retry-success")
            store.create_task(task)
            fetcher = FlakyFetcher(
                {
                    ROBOTS: (200, ROBOTS_OK),
                    ENTRY: (200, ENTRY_HTML),
                    PRODUCT: (200, PRODUCT_HTML),
                },
                flaky_url=PRODUCT,
                failures=1,
            )
            TaskRunner(
                store, rule, task, fetcher=fetcher, out_root=root / "tasks"
            ).run()
            result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["outcome"], "COMPLETED")
            self.assertEqual(result["counts"]["valid_products"], 1)
            self.assertEqual(result["failure_classes"]["transient"], 0)
            item = store.items(task.task_id, "product")[0]
            self.assertEqual(item.state, "DONE")
            self.assertEqual(item.attempts, 2)

    def test_transient_failure_exhausts_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = load_rule(PLAN)
            task = make_task("product", "retry-fail")
            task.limits["max_attempts"] = 2
            store.create_task(task)
            fetcher = FlakyFetcher(
                {
                    ROBOTS: (200, ROBOTS_OK),
                    ENTRY: (200, ENTRY_HTML),
                    PRODUCT: (200, PRODUCT_HTML),
                },
                flaky_url=PRODUCT,
                failures=10,
            )
            TaskRunner(
                store, rule, task, fetcher=fetcher, out_root=root / "tasks"
            ).run()
            result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["outcome"], "FAILED")
            self.assertEqual(result["failure_classes"]["transient"], 1)
            item = store.items(task.task_id, "product")[0]
            self.assertEqual(item.state, "FAILED")
            self.assertEqual(item.failure_class, "transient")
            self.assertEqual(item.attempts, 2)

    def test_blocked_failure_is_classified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = load_rule(PLAN)
            task = make_task("product", "blocked")
            store.create_task(task)
            fetcher = FakeFetcher(
                {
                    ROBOTS: (200, ROBOTS_OK),
                    ENTRY: (200, ENTRY_HTML),
                    PRODUCT: (403, ""),
                }
            )
            TaskRunner(
                store, rule, task, fetcher=fetcher, out_root=root / "tasks"
            ).run()
            result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["outcome"], "FAILED")
            self.assertEqual(result["stop_reason"], "ACCESS_DENIED")
            self.assertEqual(result["failure_classes"]["blocked"], 1)
            item = store.items(task.task_id, "product")[0]
            self.assertEqual(item.state, "FAILED")
            self.assertEqual(item.failure_class, "blocked")


class RecoveryTests(unittest.TestCase):
    def test_in_flight_item_is_reset_before_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = load_rule(PLAN)
            task = make_task("product", "recover")
            store.create_task(task)
            store.add_item(
                WorkItem(
                    task_id=task.task_id,
                    item_id="i1",
                    item_type="product",
                    url=PRODUCT,
                    normalized_url=PRODUCT,
                )
            )
            store.claim_items(task.task_id, 1)
            TaskRunner(
                store,
                rule,
                task,
                fetcher=FakeFetcher(
                    {
                        ROBOTS: (200, ROBOTS_OK),
                        ENTRY: (200, ENTRY_HTML),
                        PRODUCT: (200, PRODUCT_HTML),
                    }
                ),
                out_root=root / "tasks",
            ).run()
            result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["recovery"]["reset"], 1)
            self.assertEqual(result["counts"]["valid_products"], 1)

    def test_exhausted_item_fails_on_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = load_rule(PLAN)
            task = make_task("product", "recover-failed")
            task.limits["max_attempts"] = 2
            store.create_task(task)
            store.add_item(
                WorkItem(
                    task_id=task.task_id,
                    item_id="i1",
                    item_type="product",
                    url=PRODUCT,
                    normalized_url=PRODUCT,
                )
            )
            store.claim_items(task.task_id, 1)
            store.mark_item(task.task_id, "i1", "PENDING")
            store.claim_items(task.task_id, 1)
            TaskRunner(
                store,
                rule,
                task,
                fetcher=FakeFetcher(
                    {
                        ROBOTS: (200, ROBOTS_OK),
                        ENTRY: (200, ENTRY_HTML),
                        PRODUCT: (200, PRODUCT_HTML),
                    }
                ),
                out_root=root / "tasks",
            ).run()
            result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["recovery"]["failed"], 1)
            self.assertEqual(result["outcome"], "FAILED")

    def test_plan_version_mismatch_fails_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            task = make_task("product", "plan-mismatch")
            task.plan_version = "old-version"
            store.create_task(task)

            def factory(rule: object, limiter: object):
                raise AssertionError("fetcher must not start on plan mismatch")

            Worker(
                store,
                out_root=root / "tasks",
                fetcher_factory=factory,
            ).run_once()
            stored = store.get_task(task.task_id)
            assert stored is not None
            self.assertEqual(stored.state, "FINISHED")
            self.assertEqual(stored.outcome, "FAILED")
            self.assertEqual(stored.stop_reason, "PLAN_ERROR")
            result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["plan_id"], "familidoo-fr-runtime")
            self.assertEqual(result["plan_version"], "old-version")


class ParallelTests(unittest.TestCase):
    def test_two_tasks_start_in_parallel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            pages = {
                ROBOTS: (200, ROBOTS_OK),
                ENTRY: (200, ENTRY_HTML),
                PRODUCT: (200, PRODUCT_HTML),
            }
            barrier = threading.Barrier(2, timeout=5)

            @contextmanager
            def factory(rule: object, limiter: object):
                barrier.wait()
                yield FakeFetcher(pages)

            discovery = make_task("discovery", "parallel-discovery")
            product = make_task("product", "parallel-product")
            store.create_task(discovery)
            store.create_task(product)
            worker = Worker(
                store,
                out_root=root / "tasks",
                max_tasks=2,
                per_domain_rps=1000,
                fetcher_factory=factory,
            )
            worker.run_once()
            for task in (discovery, product):
                stored = store.get_task(task.task_id)
                assert stored is not None
                self.assertEqual(stored.state, "FINISHED")
                self.assertTrue(
                    (root / "tasks" / task.task_id / "task-result.json").is_file()
                )


class ControlTests(unittest.TestCase):
    def test_pause_then_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = load_rule(PLAN)
            task = make_task("product", "pause-task")
            store.create_task(task)
            fetcher = BlockingFetcher(
                {
                    ROBOTS: (200, ROBOTS_OK),
                    ENTRY: (200, ENTRY_HTML),
                    PRODUCT: (200, PRODUCT_HTML),
                },
                block_url=ENTRY,
            )
            runner = TaskRunner(
                store, rule, task, fetcher=fetcher, out_root=root / "tasks"
            )
            thread = threading.Thread(target=runner.run)
            thread.start()
            self.assertTrue(fetcher.started.wait(timeout=5))
            store.update_task(task.task_id, state="PAUSING")
            fetcher.release.set()
            thread.join(timeout=10)
            stored = store.get_task(task.task_id)
            assert stored is not None
            self.assertEqual(stored.state, "PAUSED")
            self.assertTrue(
                (root / "tasks" / task.task_id / "task-progress.json").is_file()
            )

            resumed = TaskRunner(
                store,
                rule,
                stored,
                fetcher=FakeFetcher(
                    {
                        ROBOTS: (200, ROBOTS_OK),
                        ENTRY: (200, ENTRY_HTML),
                        PRODUCT: (200, PRODUCT_HTML),
                    }
                ),
                out_root=root / "tasks",
            )
            resumed.run()
            stored = store.get_task(task.task_id)
            assert stored is not None
            self.assertEqual(stored.state, "FINISHED")
            self.assertEqual(stored.outcome, "COMPLETED")

    def test_cancel_rejects_late_product(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = load_rule(PLAN)
            task = make_task("product", "cancel-task")
            store.create_task(task)
            fetcher = BlockingFetcher(
                {
                    ROBOTS: (200, ROBOTS_OK),
                    ENTRY: (200, ENTRY_HTML),
                    PRODUCT: (200, PRODUCT_HTML),
                },
                block_url=PRODUCT,
            )
            runner = TaskRunner(
                store, rule, task, fetcher=fetcher, out_root=root / "tasks"
            )
            thread = threading.Thread(target=runner.run)
            thread.start()
            self.assertTrue(fetcher.started.wait(timeout=5))
            store.update_task(task.task_id, state="CANCELLING")
            fetcher.release.set()
            thread.join(timeout=10)
            stored = store.get_task(task.task_id)
            assert stored is not None
            self.assertEqual(stored.state, "CANCELLED")
            self.assertEqual(stored.outcome, "CANCELLED")
            item = store.items(task.task_id, "product")[0]
            self.assertEqual(item.state, "FAILED")
            self.assertEqual(item.failure_class, "blocked")
            self.assertEqual(item.result["reason"], "task_cancelled")
            rows = read_csv(root / "tasks" / task.task_id / "products.csv")
            self.assertEqual(len(rows), 1)
            result = json.loads(
                (root / "tasks" / task.task_id / "task-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["outcome"], "CANCELLED")
            self.assertEqual(result["failure_classes"]["blocked"], 1)


if __name__ == "__main__":
    unittest.main()
