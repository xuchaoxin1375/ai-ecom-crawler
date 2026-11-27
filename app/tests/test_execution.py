from __future__ import annotations

import json
import tempfile
import time
import types
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from ecom_crawler.cli import main
from ecom_crawler.execution import build_task, run_and_export, run_task
from ecom_crawler.runtime.runner import UNLIMITED_ITEMS, TaskRunner
from ecom_crawler.runtime.store import TaskStore
from ecom_crawler.runtime.worker import Worker
from ecom_crawler.validate import validate_run
from tests.support import serve_http_fixture

RULE_TEMPLATE = """\
schema_version: "1.1"
rule_id: "fixture-local"
rule_version: "2026.11.21-1"
kind: declarative
status: candidate

site:
  name: "Fixture"
  entry_urls: ["__BASE__/"]
  allowed_origins: ["__BASE__"]
  allowed_path_prefixes: ["/"]
  market: "GB"
  locale: "en-GB"
  currency: "GBP"

scope:
  include: ['^/p[0-9]+\\.html$']
  exclude: []
  max_products: 10
  max_seconds: 30

capabilities:
  discovery: true
  product: true

discovery:
  strategies: ["entry_links"]
  entry_url: "__BASE__/"
  link_selector: "a.product"
  product_url_patterns: ['^/p[0-9]+\\.html$']
  url_identity: "canonical"

fetch:
  default_engine: "static"
  concurrency: 1
  delay_ms: 1000
  retry: {max_attempts: 1, backoff_ms: 1000}
  timeout_ms: 10000
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
        - type: price_pair
          label: "meta_pair"
          gross: {selector: 'meta[property="product:price:amount"]', attr: "content"}
          pretax: {selector: 'meta[property="product:pretax_price:amount"]', attr: "content"}
          choose: "smaller"
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
    category:
      required: false
      fallbacks:
        - {type: constant, value: "Fixtures", label: "category"}
    brand:
      required: false
      fallbacks:
        - {type: constant, value: "Fixture Brand", label: "brand"}
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
    - {field: "price.currency", op: "matches", value: "^[A-Z]{3}$"}
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
  max_urls: 10
  max_products: 10
  max_seconds: 30
  concurrency:
    navigation: 1
    product: 1

compatibility:
  os: ["windows", "linux", "wsl2"]
  runtime: "python>=3.11"
  dependencies: ["scrapling==0.5.1", "pyyaml==6.0.3", "lxml"]
  browser: "none for static"

evidence:
  sample_urls: ["__BASE__/"]
  expected: []
  verified_at: null
  limitations: ["Local fixture only."]

notes: "Local fixture rule for D04 execution tests."
"""


def product_html(base: str, index: int) -> str:
    return (
        "<html><head>"
        f"<title>Product {index}</title>"
        '<meta property="og:site_name" content="Fixture">'
        f'<meta property="og:image" content="{base}/img/{index}.jpg">'
        '<meta property="product:price:amount" content="12.00">'
        '<meta property="product:pretax_price:amount" content="10.00">'
        '<meta property="product:price:currency" content="GBP">'
        f'<link rel="canonical" href="{base}/p{index}.html">'
        "</head><body>"
        f'<h1 itemprop="name">Product {index}</h1>'
        f'<div class="desc"><p>Body {index}.</p></div>'
        "</body></html>"
    )


@contextmanager
def fixture_server(
    *, products: int = 2, proxy_origin: str | None = None,
    requests: list[str] | None = None,
) -> Iterator[str]:
    # For batch tests, serve an exact synthetic origin in HTTP proxy form.
    # Requests are never forwarded, and other origins are never served.
    fixture_indices = range(1, max(products, 3) + 1)
    image_paths = {f"/img/{i}.jpg" for i in fixture_indices}
    product_paths = {f"/p{i}.html": i for i in fixture_indices}
    links = "".join(
        f'<a class="product" href="/p{i}.html">Product {i}</a>' for i in range(1, products + 1)
    )
    listing = f"<html><body>{links}</body></html>".encode()
    listing_pages = {
        "/list": 1,
        "/list?p=2": 2,
        "/list?p=3": 3,
        "/list?brand=one&brand=two&p=2": 2,
        "/list?brand=one&brand=two&p=3": 3,
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            base = f"http://127.0.0.1:{self.server.server_port}"  # type: ignore[attr-defined]
            path = self.path
            if proxy_origin is not None:
                target = urlsplit(path)
                if f"{target.scheme}://{target.netloc}" != proxy_origin:
                    self.send_error(404)
                    return
                base = proxy_origin
                path = target.path
                if target.query:
                    path += f"?{target.query}"
            if requests is not None:
                requests.append(path)
            if path in image_paths:
                # One-pixel GIF; the fixture uses .jpg URLs for extraction tests.
                body = bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b")
                self.send_response(200)
                self.send_header("Content-Type", "image/gif")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(listing)))
                self.end_headers()
                self.wfile.write(listing)
                return
            product_path = urlsplit(path).path
            if product_path in product_paths:
                body = product_html(base, product_paths[product_path]).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path in listing_pages:
                page = listing_pages[path]
                body = (
                    f"<html><body><a class='product' href='/p{page}.html'>P{page}</a>"
                    "</body></html>"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    with serve_http_fixture(server):
        yield f"http://127.0.0.1:{server.server_address[1]}"


class ExecutionTests(unittest.TestCase):
    def test_worker_uses_recorded_task_proxy_before_process_default(self) -> None:
        origin = "http://task-proxy.test"
        default_requests: list[str] = []
        task_requests: list[str] = []
        with (
            tempfile.TemporaryDirectory() as temporary,
            fixture_server(proxy_origin=origin, requests=default_requests) as default_proxy,
            fixture_server(proxy_origin=origin, requests=task_requests) as task_proxy,
        ):
            root = Path(temporary)
            rule = root / "rule.yaml"
            rule.write_text(RULE_TEMPLATE.replace("__BASE__", origin), encoding="utf-8")
            store = TaskStore(root / "tasks.db")
            worker = Worker(store, out_root=root / "out", proxy=default_proxy, per_domain_rps=50)
            for task_id, proxy in (("specific", task_proxy), ("fallback", None)):
                task = build_task(
                    rule_path=rule, task_id=task_id, task_type="product",
                    max_urls=5, max_products=1, max_seconds=20, max_attempts=1,
                    proxy=proxy, seed_urls=[f"{origin}/p1.html"], discover=False,
                )
                store.create_task(task)
                store.request_start(task_id)
                worker.run_once()
                result = store.get_task(task_id)
                assert result is not None
                self.assertEqual(result.counters["valid_products"], 1)
                if proxy:
                    self.assertEqual(default_requests, [])
            self.assertEqual(task_requests, ["/p1.html"])
            self.assertEqual(default_requests, ["/p1.html"])

    def test_fixture_rule_runs_and_exports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, fixture_server() as base:
            root = Path(temporary)
            rule = root / "rule.yaml"
            rule.write_text(RULE_TEMPLATE.replace("__BASE__", base), encoding="utf-8")
            result = run_and_export(
                rule_path=rule,
                db_path=root / "tasks.db",
                out_root=root / "tasks",
                task_id="fixture-product",
                task_type="product",
                max_products=10,
                max_seconds=30,
                max_attempts=1,
                per_domain_rps=50,
            )
            self.assertEqual(result.task_result["state"], "FINISHED")
            self.assertEqual(result.task_result["counts"]["valid_products"], 2)
            self.assertIsNotNone(result.app_export)
            assert result.export_dir is not None
            self.assertEqual(validate_run(result.export_dir), [])
            rows = (result.export_dir / "products.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 3)
            self.assertIn("Product 1", rows[1])
            items = TaskStore(root / "tasks.db").items(
                "fixture-product", "product"
            )
            preview = next(
                item.result["product_preview"]
                for item in items
                if item.result.get("product_preview")
            )
            self.assertTrue(preview["name"])
            self.assertTrue(preview["price_amount"])
            self.assertTrue(preview["field_sources"])
            self.assertNotIn("description_html", preview)
            stored = TaskStore(root / "tasks.db").get_task("fixture-product")
            assert stored is not None
            self.assertEqual(stored.state, "FINISHED")

    def test_seed_urls_without_discovery_fetch_only_those_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, fixture_server() as base:
            root = Path(temporary)
            rule = root / "rule.yaml"
            rule.write_text(
                RULE_TEMPLATE.replace("__BASE__", base), encoding="utf-8"
            )
            result, _ = run_task(
                rule_path=rule,
                db_path=root / "tasks.db",
                out_root=root / "tasks",
                task_id="seed-only",
                task_type="product",
                max_products=10,
                max_seconds=30,
                max_attempts=1,
                per_domain_rps=50,
                seed_urls=[f"{base}/p1.html"],
                discover=False,
            )
            self.assertEqual(result["counts"]["valid_products"], 1)
            items = TaskStore(root / "tasks.db").items("seed-only", "product")
            self.assertEqual([item.url for item in items], [f"{base}/p1.html"])

    def test_full_archive_replays_offline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_root = root / "archive"
            with fixture_server() as base:
                rule = root / "rule.yaml"
                rule.write_text(
                    RULE_TEMPLATE.replace("__BASE__", base), encoding="utf-8"
                )
                first, _ = run_task(
                    rule_path=rule,
                    db_path=root / "first.db",
                    out_root=root / "first",
                    task_id="archive-full",
                    task_type="product",
                    max_products=10,
                    max_seconds=30,
                    max_attempts=1,
                    per_domain_rps=50,
                    archive_mode="full",
                    archive_root=archive_root,
                )
            self.assertEqual(first["counts"]["valid_products"], 2)
            archive_stats = (first.get("runtime") or {}).get("archive") or {}
            self.assertEqual(archive_stats.get("mode"), "full")
            self.assertGreaterEqual(archive_stats.get("pages", 0), 3)
            self.assertTrue((archive_root / "index.jsonl").is_file())

            second, _ = run_task(
                rule_path=rule,
                db_path=root / "second.db",
                out_root=root / "second",
                task_id="archive-offline",
                task_type="product",
                max_products=10,
                max_seconds=30,
                max_attempts=1,
                per_domain_rps=50,
                archive_mode="full",
                archive_root=archive_root,
                offline=True,
            )
            self.assertEqual(second["counts"]["valid_products"], 2)
            offline_archive = (second.get("runtime") or {}).get("archive") or {}
            self.assertGreater(offline_archive.get("hits", 0), 0)
            self.assertEqual(offline_archive.get("writes"), 0)

    def test_listing_source_max_pages_is_respected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, fixture_server() as base:
            root = Path(temporary)
            rule_text = RULE_TEMPLATE.replace("__BASE__", base)
            start = rule_text.index("\ndiscovery:") + 1
            end = rule_text.index("\nfetch:") + 1
            discovery = f'''discovery:
  strategies: ["entry_links"]
  product_url_patterns: ['^/p[0-9]+\\.html$']
  url_identity: "canonical"
  sources:
    - type: "listing"
      url: "{base}/list"
      product_link_selector: "a.product"
      max_pages: 2
      advance: {{type: "page_param", param: "p"}}

'''
            rule = root / "rule.yaml"
            rule.write_text(
                rule_text[:start] + discovery + rule_text[end:], encoding="utf-8"
            )
            result, _ = run_task(
                rule_path=rule,
                db_path=root / "tasks.db",
                out_root=root / "tasks",
                task_id="listing-limit",
                task_type="product",
                max_products=10,
                max_seconds=30,
                max_attempts=1,
                per_domain_rps=50,
            )
            self.assertEqual(result["counts"]["valid_products"], 2)
            product_urls = {
                json.loads(line).get("source_url")
                for line in (root / "tasks" / "listing-limit" / "products.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            }
            self.assertNotIn(f"{base}/p3.html", product_urls)

    def test_optional_brand_missing_is_not_quality_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, fixture_server() as base:
            root = Path(temporary)
            rule = root / "rule.yaml"
            text = RULE_TEMPLATE.replace("__BASE__", base)
            text = text.replace(
                '    brand:\n'
                '      required: false\n'
                '      fallbacks:\n'
                '        - {type: constant, value: "Fixture Brand", label: "brand"}\n',
                "",
            )
            rule.write_text(text, encoding="utf-8")
            result = run_and_export(
                rule_path=rule,
                db_path=root / "tasks.db",
                out_root=root / "tasks",
                task_id="fixture-no-brand",
                task_type="product",
                max_products=2,
                max_seconds=30,
                max_attempts=1,
                per_domain_rps=50,
            )
            self.assertEqual(result.task_result["quality_exceptions"], [])
            items = TaskStore(root / "tasks.db").items(
                "fixture-no-brand", "product"
            )
            preview = next(
                item.result["product_preview"]
                for item in items
                if item.result.get("product_preview")
            )
            self.assertEqual(preview["missing_reasons"], {})
            assert result.export_dir is not None
            record = json.loads(
                (result.export_dir / "records.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            self.assertEqual(record["missing_reasons"]["brand"], "NOT_PROVIDED")

    def test_cli_run_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, fixture_server() as base:
            root = Path(temporary)
            rule = root / "rule.yaml"
            rule.write_text(RULE_TEMPLATE.replace("__BASE__", base), encoding="utf-8")
            code = main(
                [
                    "run",
                    "--rule",
                    str(rule),
                    "--db",
                    str(root / "tasks.db"),
                    "--out-root",
                    str(root / "tasks"),
                    "--task-id",
                    "cli-fixture",
                    "--max-products",
                    "10",
                    "--max-seconds",
                    "30",
                    "--max-attempts",
                    "1",
                    "--per-domain-rps",
                    "50",
                ]
            )
            self.assertEqual(code, 0)
            export = root / "tasks" / "cli-fixture" / "export"
            self.assertTrue((export / "products.csv").is_file())
            self.assertEqual(validate_run(export), [])


class UnlimitedLimitTests(unittest.TestCase):
    def test_build_task_persists_unbounded_limits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, fixture_server() as base:
            rule = Path(temporary) / "rule.yaml"
            rule.write_text(
                RULE_TEMPLATE.replace("__BASE__", base),
                encoding="utf-8",
            )
            task = build_task(
                rule_path=rule,
                task_id="unbounded",
                task_type="product",
                max_urls=None,
                max_products=None,
                max_seconds=None,
                max_attempts=1,
            )
            self.assertIsNone(task.limits["max_urls"])
            self.assertIsNone(task.limits["max_products"])
            self.assertIsNone(task.limits["max_seconds"])
            self.assertEqual(task.limits["max_attempts"], 1)

    def test_unbounded_item_limits_use_runtime_sentinel(self) -> None:
        for task_type, key in (
            ("product", "max_products"),
            ("discovery", "max_urls"),
        ):
            fake = types.SimpleNamespace(
                task=types.SimpleNamespace(task_type=task_type, limits={key: None}),
                rule=types.SimpleNamespace(task_defaults={}),
                store=None,
            )
            self.assertEqual(
                TaskRunner._remaining_product_limit(fake),
                UNLIMITED_ITEMS,
            )

    def test_unbounded_seconds_does_not_expire(self) -> None:
        fake = types.SimpleNamespace(
            task=types.SimpleNamespace(
                limits={"max_seconds": None, "max_requests": None}
            ),
            _started_monotonic=time.monotonic() - 10_000,
        )
        self.assertFalse(TaskRunner._budget_exceeded(fake))


if __name__ == "__main__":
    unittest.main()
