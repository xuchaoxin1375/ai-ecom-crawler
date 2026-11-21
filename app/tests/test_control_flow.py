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
from ecom_crawler.runtime.models import FetchResult
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

    def get(self, url: str) -> FetchResult:
        self.requests += 1
        if url.rstrip("/") == "https://fixture.test":
            return FetchResult(status=200, url=url, body=ENTRY_HTML.encode("utf-8"))
        if self.started is not None:
            self.started.set()
        if self.release is not None and not self.release.wait(5):
            raise AssertionError("test did not release the in-flight request")
        return FetchResult(status=200, url=url, body=PRODUCT_HTML.encode("utf-8"))


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
            fetcher_factory=lambda rule, limiter: StaticFetcher(started, release),
        )
        thread = threading.Thread(target=worker.run_once, daemon=True)
        thread.start()
        return worker, thread

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

    def test_worker_run_forever_processes_and_stops(self) -> None:
        task = self._submit("forever-flow")
        store = TaskStore(self.db_path)
        worker = Worker(
            store,
            out_root=self.out_root,
            max_tasks=1,
            per_domain_rps=50,
            fetcher_factory=lambda rule, limiter: StaticFetcher(),
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
