from __future__ import annotations

import tempfile
import threading
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ecom_crawler.cli import main
from ecom_crawler.execution import run_and_export
from ecom_crawler.runtime.store import TaskStore
from ecom_crawler.validate import validate_run

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
def fixture_server() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            base = f"http://127.0.0.1:{self.server.server_port}"  # type: ignore[attr-defined]
            if self.path == "/":
                body = (
                    b"<html><body>"
                    b'<a class="product" href="/p1.html">One</a>'
                    b'<a class="product" href="/p2.html">Two</a>'
                    b"</body></html>"
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path in {"/p1.html", "/p2.html"}:
                index = 1 if self.path == "/p1.html" else 2
                body = product_html(base, index).encode("utf-8")
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
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class ExecutionTests(unittest.TestCase):
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
            stored = TaskStore(root / "tasks.db").get_task("fixture-product")
            assert stored is not None
            self.assertEqual(stored.state, "FINISHED")

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


if __name__ == "__main__":
    unittest.main()
