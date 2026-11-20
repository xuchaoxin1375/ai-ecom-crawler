"""Runtime tests for the R06 task ledger, runner and parallel worker; no network access."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path

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
    def __init__(self, pages: dict[str, tuple[int, str]]) -> None:
        self.pages = pages
        self.calls: list[str] = []
        self.requests = 0
        self.retries = 0

    def get(self, url: str) -> FetchResult:
        self.calls.append(url)
        self.requests += 1
        status, body = self.pages.get(url, (404, ""))
        return FetchResult(status=status, url=url, body=body.encode("utf-8"))


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


def make_task(task_type: str, task_id: str | None = None) -> Task:
    return Task(
        task_id=task_id or f"test-{task_type}",
        rule_id="familidoo-fr-runtime",
        rule_version="2026.11.20-1",
        task_type=task_type,
        state="QUEUED",
        input={"rule_path": str(PLAN)},
        limits={
            "max_urls": 10,
            "max_products": 10,
            "max_seconds": 10,
            "concurrency": {"navigation": 1, "product": 2},
        },
        output={"url_list": True, "product_csv": task_type == "product"},
    )


def read_csv(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


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


class DiscoveryExcludedTests(unittest.TestCase):
    def test_robots_excluded_url_is_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "tasks.db")
            rule = load_rule(PLAN)
            task = make_task("discovery", "robots-excluded")
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
            self.assertEqual(counts["excluded_urls"], 1)
            self.assertEqual(counts["valid_urls"], 0)
            self.assertEqual(task_result["outcome"], "COMPLETED")
            rows = read_csv(root / "tasks" / task.task_id / "urls.csv")
            self.assertEqual(len(rows), 1)


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


if __name__ == "__main__":
    unittest.main()
