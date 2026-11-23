from __future__ import annotations

import contextlib
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Self

from ecom_crawler.cli import main
from ecom_crawler.execution import submit_task
from ecom_crawler.runtime.fetcher import DomainLimiter
from ecom_crawler.runtime.lock import worker_lock
from ecom_crawler.runtime.models import FetchResult, WorkItem
from ecom_crawler.runtime.store import TaskStore
from ecom_crawler.runtime.worker import Worker

RULE = """\
schema_version: "1.1"
rule_id: "control-fixture"
rule_version: "1.0.0"
kind: declarative
status: candidate

site:
  name: "Control Fixture"
  entry_urls: ["https://fixture.test/"]
  allowed_origins: ["https://fixture.test"]
  allowed_path_prefixes: ["/"]
  market: "GB"
  locale: "en-GB"
  currency: "GBP"

scope:
  include: ['^/p1\\.html$']
  exclude: []
  max_products: 5
  max_seconds: 30

capabilities:
  discovery: true
  product: true

discovery:
  strategies: ["entry_links"]
  entry_url: "https://fixture.test/"
  link_selector: "a.product"
  product_url_patterns: ['^/p1\\.html$']
  url_identity: "canonical"

fetch:
  default_engine: "static"
  concurrency: 1
  delay_ms: 1000
  retry: {max_attempts: 1, backoff_ms: 10}
  timeout_ms: 1000
  browser: false
  login: false
  challenge_handling: "none"

extract:
  fields:
    name:
      required: true
      fallbacks:
        - {type: css_text, selector: "h1", label: "h1"}
    price.amount:
      required: true
      fallbacks:
        - {type: css_attr, selector: 'meta[property="product:price:amount"]', attr: "content", label: "price"}
    price.currency:
      required: true
      fallbacks:
        - {type: css_attr, selector: 'meta[property="product:price:currency"]', attr: "content", label: "currency"}
    primary_image_url:
      required: true
      fallbacks:
        - {type: css_attr, selector: 'meta[property="og:image"]', attr: "content", label: "image", absolute: true}
    description_html:
      required: false
      fallbacks:
        - {type: css_html, selector: "div.desc", label: "description", description_status: "complete"}
    source_url:
      required: true
      fallbacks:
        - {type: canonical, label: "canonical"}

normalize:
  price:
    tax_basis: "unspecified"
    choose: "smaller_public_pair"
    positive_only: true
  description:
    mode: "clean_html"
    statuses: ["complete", "partial", "not_provided", "failed"]
  options:
    exclude_quantity: true
    strip_price_delta: true

validate:
  required_fields:
    - "name"
    - "price.amount"
    - "price.currency"
    - "primary_image_url"
    - "source_url"
  assertions:
    - {field: "price.amount", op: ">", value: 0}
  partial_description: "allowed_with_flag"

output:
  url_list:
    enabled: true
    columns: ["url", "source", "status", "title"]
    format: "csv"
  product_csv:
    enabled: true
    columns: 9
    format: "csv"
  task_result: true

task_defaults:
  max_urls: 5
  max_products: 5
  max_seconds: 30
  concurrency:
    navigation: 1
    product: 1

compatibility:
  os: ["windows", "linux"]
  runtime: "python>=3.11"
  dependencies: []
  browser: "none"

evidence:
  sample_urls: ["https://fixture.test/"]
  expected: []
  verified_at: null
  limitations: ["Local test fixture only."]

notes: "Control-flow test rule."
"""

ENTRY_HTML = (
    "<html><body>"
    '<a class="product" href="/p1.html">One</a>'
    "</body></html>"
)

PRODUCT_HTML = (
    "<html><head>"
    "<title>Product 1</title>"
    '<meta property="og:image" content="https://fixture.test/img/1.jpg">'
    '<meta property="product:price:amount" content="12.00">'
    '<meta property="product:price:currency" content="GBP">'
    '<link rel="canonical" href="https://fixture.test/p1.html">'
    "</head><body>"
    '<h1 itemprop="name">Product 1</h1>'
    '<div class="desc"><p>Body 1.</p></div>'
    "</body></html>"
)


class StaticFetcher:
    def __init__(self, started: threading.Event | None = None, release: threading.Event | None = None) -> None:
        self.started = started
        self.release = release
        self.requests = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def get(self, url: str, *, item_type: str | None = None) -> FetchResult:
        if url.rstrip("/").endswith("/robots.txt"):
            return FetchResult(status=404, url=url, body=b"")
        self.requests += 1
        if url.rstrip("/") == "https://fixture.test":
            return FetchResult(status=200, url=url, body=ENTRY_HTML.encode("utf-8"))
        if self.started is not None:
            self.started.set()
        if self.release is not None and not self.release.wait(5):
            raise AssertionError("test did not release the in-flight request")
        return FetchResult(status=200, url=url, body=PRODUCT_HTML.encode("utf-8"))


class Gate:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()


def prefixed_rule(prefix: str) -> str:
    text = RULE.replace(
        "https://fixture.test/", f"https://fixture.test/{prefix}/"
    )
    return text.replace("^/p1\\.html$", f"^/{prefix}/p1\\.html$")


def prefixed_entry(prefix: str) -> str:
    return (
        "<html><body>"
        f'<a class="product" href="/{prefix}/p1.html">One</a>'
        "</body></html>"
    )


def prefixed_product(prefix: str) -> str:
    text = PRODUCT_HTML.replace("Product 1", f"Product {prefix.upper()}")
    return text.replace(
        "https://fixture.test/p1.html", f"https://fixture.test/{prefix}/p1.html"
    )


class GateFetcher:
    def __init__(
        self,
        rule: Any,
        limiter: DomainLimiter,
        gates: dict[str, Gate],
    ) -> None:
        self.prefix = "a" if "/a/" in rule.entry_url else "b"
        self.limiter = limiter
        self.gates = gates

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def get(self, url: str, *, item_type: str | None = None) -> FetchResult:
        if url.rstrip("/").endswith("/robots.txt"):
            return FetchResult(status=404, url=url, body=b"")
        if url.rstrip("/") == f"https://fixture.test/{self.prefix}":
            return FetchResult(
                status=200,
                url=url,
                body=prefixed_entry(self.prefix).encode("utf-8"),
            )
        self.limiter.wait(url)
        gate = self.gates[self.prefix]
        gate.started.set()
        if not gate.release.wait(5):
            raise AssertionError("test did not release the in-flight request")
        return FetchResult(
            status=200,
            url=url,
            body=prefixed_product(self.prefix).encode("utf-8"),
        )


class ControlFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.rule_path = self.root / "rule.yaml"
        self.rule_path.write_text(RULE, encoding="utf-8")
        self.db_path = self.root / "tasks.db"
        self.out_root = self.root / "tasks"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _submit(self, task_id: str) -> Any:
        return submit_task(
            rule_path=self.rule_path,
            db_path=self.db_path,
            task_id=task_id,
            max_products=5,
            max_seconds=30,
            max_attempts=1,
        )

    def _worker(
        self,
        *,
        started: threading.Event | None = None,
        release: threading.Event | None = None,
    ) -> tuple[Worker, threading.Thread]:
        store = TaskStore(self.db_path)
        worker = Worker(
            store,
            out_root=self.out_root,
            max_tasks=1,
            per_domain_rps=50,
            fetcher_factory=lambda context: StaticFetcher(started, release),
        )
        thread = threading.Thread(target=worker.run_once, daemon=True)
        thread.start()
        return worker, thread

    def _prefixed_rule(self, prefix: str) -> Path:
        path = self.root / f"rule-{prefix}.yaml"
        path.write_text(prefixed_rule(prefix), encoding="utf-8")
        return path

    def _wait_for(self, predicate: Any, message: str, timeout: float = 5) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail(message)

    def _submit_prefixed(self, prefix: str, task_id: str) -> Any:
        return submit_task(
            rule_path=self._prefixed_rule(prefix),
            db_path=self.db_path,
            task_id=task_id,
            max_products=5,
            max_seconds=30,
            max_attempts=1,
        )

    def test_a20_pause_one_task_keeps_other_running(self) -> None:
        task_a = self._submit_prefixed("a", "a20-pause-a")
        task_b = self._submit_prefixed("b", "a20-pause-b")
        gates = {"a": Gate(), "b": Gate()}
        store = TaskStore(self.db_path)
        worker = Worker(
            store,
            out_root=self.out_root,
            max_tasks=2,
            per_domain_rps=50,
            fetcher_factory=lambda context: GateFetcher(context.rule, context.limiter, gates),
        )
        thread = threading.Thread(target=worker.run_once, daemon=True)
        thread.start()
        self.assertTrue(gates["a"].started.wait(5))
        self.assertTrue(gates["b"].started.wait(5))

        store.request_pause(task_a.task_id)
        gates["a"].release.set()
        self._wait_for(
            lambda: store.get_task(task_a.task_id).state == "PAUSED",
            "task A did not settle to PAUSED",
        )
        running_b = store.get_task(task_b.task_id)
        assert running_b is not None
        self.assertEqual(running_b.state, "RUNNING")

        gates["b"].release.set()
        thread.join(10)
        self.assertFalse(thread.is_alive(), "worker did not stop")
        self.assertEqual(store.get_task(task_a.task_id).state, "PAUSED")
        self.assertEqual(store.get_task(task_b.task_id).state, "FINISHED")
        self.assertEqual(store.item_counts(task_a.task_id, "product").get("DONE"), 1)
        self.assertEqual(store.item_counts(task_b.task_id, "product").get("DONE"), 1)

        lines_a = (self.out_root / task_a.task_id / "products.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        lines_b = (self.out_root / task_b.task_id / "products.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(len(lines_a), 1)
        self.assertEqual(len(lines_b), 1)
        self.assertIn("Product A", lines_a[0])
        self.assertIn("Product B", lines_b[0])

    def test_a20_cancel_one_task_keeps_other_running(self) -> None:
        task_a = self._submit_prefixed("a", "a20-cancel-a")
        task_b = self._submit_prefixed("b", "a20-cancel-b")
        gates = {"a": Gate(), "b": Gate()}
        store = TaskStore(self.db_path)
        worker = Worker(
            store,
            out_root=self.out_root,
            max_tasks=2,
            per_domain_rps=50,
            fetcher_factory=lambda context: GateFetcher(context.rule, context.limiter, gates),
        )
        thread = threading.Thread(target=worker.run_once, daemon=True)
        thread.start()
        self.assertTrue(gates["a"].started.wait(5))
        self.assertTrue(gates["b"].started.wait(5))

        store.request_cancel(task_a.task_id)
        gates["a"].release.set()
        self._wait_for(
            lambda: store.get_task(task_a.task_id).state == "CANCELLED",
            "task A did not settle to CANCELLED",
        )
        running_b = store.get_task(task_b.task_id)
        assert running_b is not None
        self.assertEqual(running_b.state, "RUNNING")

        gates["b"].release.set()
        thread.join(10)
        self.assertFalse(thread.is_alive(), "worker did not stop")
        self.assertEqual(store.get_task(task_a.task_id).state, "CANCELLED")
        self.assertEqual(store.get_task(task_b.task_id).state, "FINISHED")
        self.assertEqual(store.item_counts(task_a.task_id, "product").get("FAILED"), 1)
        self.assertEqual(store.item_counts(task_b.task_id, "product").get("DONE"), 1)
        products_a = self.out_root / task_a.task_id / "products.jsonl"
        self.assertFalse(products_a.exists() and products_a.read_text(encoding="utf-8").strip())

    def test_same_domain_limiter_serializes(self) -> None:
        limiter = DomainLimiter(per_domain_rps=5)
        barrier = threading.Barrier(2)
        times: list[float] = []

        def call() -> None:
            barrier.wait()
            limiter.wait("https://fixture.test/a/")
            times.append(time.monotonic())

        threads = [threading.Thread(target=call) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        self.assertEqual(len(times), 2)
        self.assertGreaterEqual(abs(times[1] - times[0]), 0.15)
        self.assertGreaterEqual(limiter.waits, 1)

    def test_cancel_rejects_late_result(self) -> None:
        task = self._submit("cancel-flow")
        started = threading.Event()
        release = threading.Event()
        _, thread = self._worker(started=started, release=release)
        self.assertTrue(started.wait(5), "product request did not start")
        store = TaskStore(self.db_path)
        self.assertEqual(store.request_cancel(task.task_id).state, "CANCELLING")
        release.set()
        thread.join(10)
        self.assertFalse(thread.is_alive(), "worker did not stop")

        stored = store.get_task(task.task_id)
        assert stored is not None
        self.assertEqual(stored.state, "CANCELLED")
        self.assertEqual(stored.outcome, "CANCELLED")
        self.assertEqual(stored.stop_reason, "USER_CANCELLED")
        items = {item.item_type: item for item in store.items(task.task_id)}
        self.assertNotIn("IN_FLIGHT", {item.state for item in store.items(task.task_id)})
        product_item = items["product"]
        self.assertEqual(product_item.state, "FAILED")
        self.assertEqual(product_item.result.get("reason"), "task_cancelled")
        products = self.out_root / task.task_id / "products.jsonl"
        self.assertFalse(products.exists() and products.read_text(encoding="utf-8").strip())

    def test_pause_settles_and_resume_requeues(self) -> None:
        task = self._submit("pause-flow")
        started = threading.Event()
        release = threading.Event()
        _, thread = self._worker(started=started, release=release)
        self.assertTrue(started.wait(5), "product request did not start")
        store = TaskStore(self.db_path)
        self.assertEqual(store.request_pause(task.task_id).state, "PAUSING")
        release.set()
        thread.join(10)
        self.assertFalse(thread.is_alive(), "worker did not stop")

        stored = store.get_task(task.task_id)
        assert stored is not None
        self.assertEqual(stored.state, "PAUSED")
        self.assertEqual(stored.outcome, None)
        done = [
            item
            for item in store.items(task.task_id, "product")
            if item.state == "DONE"
        ]
        self.assertEqual(len(done), 1)
        self.assertEqual(store.request_resume(task.task_id).state, "QUEUED")

        _, resume_thread = self._worker()
        resume_thread.join(10)
        self.assertFalse(resume_thread.is_alive(), "resumed worker did not stop")
        finished = store.get_task(task.task_id)
        assert finished is not None
        self.assertEqual(finished.state, "FINISHED")
        self.assertEqual(finished.outcome, "COMPLETED")
        result = json.loads(
            (self.out_root / task.task_id / "task-result.json").read_text(encoding="utf-8")
        )
        self.assertEqual(result["counts"]["valid_products"], 1)

    def test_worker_heartbeat_keeps_lease_alive(self) -> None:
        task = self._submit("heartbeat-flow")
        started = threading.Event()
        release = threading.Event()
        store = TaskStore(self.db_path)
        worker = Worker(
            store,
            out_root=self.out_root,
            max_tasks=1,
            per_domain_rps=50,
            fetcher_factory=lambda context: StaticFetcher(started, release),
            lease_ttl_seconds=1.0,
            heartbeat_interval=0.1,
        )
        thread = threading.Thread(target=worker.run_once, daemon=True)
        thread.start()
        self.assertTrue(started.wait(5), "product request did not start")
        time.sleep(1.5)
        running = store.get_task(task.task_id)
        assert running is not None
        self.assertEqual(running.state, "RUNNING")
        lease = store.lease_info(task.task_id)
        assert lease is not None
        self.assertIsNotNone(lease["owner"])
        self.assertGreater(lease["token"], 0)

        release.set()
        thread.join(10)
        self.assertFalse(thread.is_alive(), "worker did not stop")
        finished = store.get_task(task.task_id)
        assert finished is not None
        self.assertEqual(finished.state, "FINISHED")

    def test_two_workers_process_one_task_once(self) -> None:
        task = self._submit("two-workers")
        workers = [
            Worker(
                TaskStore(self.db_path),
                out_root=self.out_root,
                max_tasks=1,
                per_domain_rps=50,
                fetcher_factory=lambda context: StaticFetcher(),
            )
            for _ in range(2)
        ]
        started: list[int] = []
        lock = threading.Lock()

        def run(worker: Worker) -> None:
            count = worker.run_once()
            with lock:
                started.append(count)

        threads = [
            threading.Thread(target=run, args=(worker,), daemon=True)
            for worker in workers
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(15)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(sorted(started), [0, 1])
        stored = TaskStore(self.db_path).get_task(task.task_id)
        assert stored is not None
        self.assertEqual(stored.state, "FINISHED")
        lines = (self.out_root / task.task_id / "products.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(len(lines), 1)

    def test_worker_takes_over_expired_task(self) -> None:
        task = self._submit("takeover-flow")
        dead = TaskStore(self.db_path)
        claimed = dead.claim_tasks("dead-worker", 1, 0.05)
        self.assertEqual(len(claimed), 1)
        dead.add_item(
            WorkItem(
                task_id=task.task_id,
                item_id="crashed-product",
                item_type="product",
                url="https://fixture.test/p1.html",
                normalized_url="https://fixture.test/p1.html",
                stage="product",
                state="IN_FLIGHT",
                attempts=0,
            )
        )
        task_dir = self.out_root / task.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "products.jsonl").write_text(
            json.dumps(
                {
                    "name": "Stale product",
                    "source_url": "https://fixture.test/p1.html",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        time.sleep(0.2)

        worker = Worker(
            TaskStore(self.db_path),
            out_root=self.out_root,
            max_tasks=1,
            per_domain_rps=50,
            fetcher_factory=lambda context: StaticFetcher(),
        )
        self.assertEqual(worker.run_once(), 1)
        stored = TaskStore(self.db_path).get_task(task.task_id)
        assert stored is not None
        self.assertEqual(stored.state, "FINISHED")
        self.assertEqual(stored.outcome, "COMPLETED")
        self.assertEqual(
            TaskStore(self.db_path).item_counts(task.task_id, "product").get("DONE"),
            1,
        )
        lines = (self.out_root / task.task_id / "products.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(len(lines), 1)
        self.assertNotIn("Stale product", lines[0])

    def _run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_cli_submit_status_cancel(self) -> None:
        code, stdout, stderr = self._run_cli(
            [
                "submit",
                "--rule",
                str(self.rule_path),
                "--db",
                str(self.db_path),
                "--task-id",
                "cli-control",
                "--max-products",
                "5",
                "--max-seconds",
                "30",
                "--max-attempts",
                "1",
            ]
        )
        self.assertEqual(code, 0, stderr)
        self.assertIn("submitted: cli-control state=QUEUED", stdout)

        code, stdout, stderr = self._run_cli(
            ["status", "--db", str(self.db_path), "--task-id", "cli-control", "--json"]
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["state"], "QUEUED")

        code, _, stderr = self._run_cli(
            ["pause", "--db", str(self.db_path), "--task-id", "cli-control"]
        )
        self.assertEqual(code, 2)
        self.assertIn("cannot pause", stderr)

        code, stdout, stderr = self._run_cli(
            ["cancel", "--db", str(self.db_path), "--task-id", "cli-control"]
        )
        self.assertEqual(code, 0, stderr)
        self.assertIn("state=CANCELLED", stdout)

        code, stdout, stderr = self._run_cli(
            ["status", "--db", str(self.db_path), "--task-id", "cli-control", "--json"]
        )
        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["state"], "CANCELLED")
        self.assertEqual(payload["outcome"], "CANCELLED")

        code, stdout, stderr = self._run_cli(
            ["list", "--db", str(self.db_path), "--json"]
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual([item["task_id"] for item in json.loads(stdout)], ["cli-control"])

    def test_cli_worker_refuses_second_instance(self) -> None:
        with worker_lock(self.db_path):
            code, _, stderr = self._run_cli(
                [
                    "worker",
                    "--db",
                    str(self.db_path),
                    "--out-root",
                    str(self.out_root),
                ]
            )
        self.assertEqual(code, 2)
        self.assertIn("another worker", stderr)

    def test_worker_run_forever_processes_and_stops(self) -> None:
        task = self._submit("forever-flow")
        store = TaskStore(self.db_path)
        worker = Worker(
            store,
            out_root=self.out_root,
            max_tasks=1,
            per_domain_rps=50,
            fetcher_factory=lambda context: StaticFetcher(),
        )
        stop = threading.Event()
        thread = threading.Thread(
            target=worker.run_forever,
            kwargs={"stop_event": stop, "poll_interval": 0.01},
            daemon=True,
        )
        thread.start()
        deadline = time.monotonic() + 10
        stored = None
        while time.monotonic() < deadline:
            stored = store.get_task(task.task_id)
            if stored is not None and stored.state == "FINISHED":
                break
            time.sleep(0.02)
        stop.set()
        thread.join(10)
        self.assertFalse(thread.is_alive(), "run_forever did not stop")
        assert stored is not None
        self.assertEqual(stored.state, "FINISHED")
        self.assertEqual(stored.outcome, "COMPLETED")


if __name__ == "__main__":
    unittest.main()
