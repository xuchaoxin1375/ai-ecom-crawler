from __future__ import annotations

import tempfile
import threading
import unittest
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ecom_crawler.execution import run_and_export
from ecom_crawler.runtime.browser import BrowserConfig
from ecom_crawler.runtime.fetcher import HybridFetcher
from ecom_crawler.runtime.models import FetchResult
from ecom_crawler.runtime.resources import pid_alive
from ecom_crawler.runtime.rule import RuleError, load_rule
from ecom_crawler.runtime.store import TaskStore

RULE_TEMPLATE = """\
schema_version: "1.1"
rule_id: "browser-fixture"
rule_version: "2026.11.21-1"
kind: declarative
status: candidate

site:
  name: "Browser Fixture"
  entry_urls: ["__BASE__/"]
  allowed_origins: ["__BASE__"]
  allowed_path_prefixes: ["/"]
  market: "GB"
  locale: "en-GB"
  currency: "GBP"

scope:
  include: ['^/p[0-9]+\\.html$']
  exclude: []

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
  default_engine: "browser"
  concurrency: 1
  delay_ms: 1000
  retry: {max_attempts: 1, backoff_ms: 0}
  timeout_ms: 20000
  browser:
    headless: true
    disable_resources: true
  per_url_type:
    product:
      engine: "browser"
      wait_until: "domcontentloaded"
      wait_selector: "#ready"
      wait_selector_state: "attached"
  challenge_handling: "none; stop and record"

extract:
  fields:
    name:
      required: true
      fallbacks:
        - {type: css_text, selector: "h1#name", label: "rendered_name"}
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
        - {type: css_html, selector: "div#desc", label: "description", description_status: "complete"}
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
  max_seconds: 60

compatibility:
  os: ["windows", "linux", "wsl2"]
  runtime: "python>=3.11"
  dependencies: ["patchright==1.64.4"]
  browser: "patchright CDP"

evidence:
  sample_urls: ["__BASE__/"]
  expected: []
  verified_at: null
  limitations: ["Local browser fixture only."]

notes: "Browser adapter fixture: product fields are filled by JavaScript."
"""

ENTRY_HTML = (
    "<html><body>"
    '<a class="product" href="/p1.html">One</a>'
    "</body></html>"
)


def product_html(base: str) -> str:
    return (
        "<html><head>"
        "<title>JavaScript Product</title>"
        f'<meta property="og:image" content="{base}/img/1.jpg">'
        f'<link rel="canonical" href="{base}/p1.html">'
        "</head><body>"
        '<h1 id="name"></h1>'
        '<div id="desc"></div>'
        "<script>"
        "window.setTimeout(function () {"
        "  document.getElementById('name').textContent = 'Rendered Shirt';"
        "  document.getElementById('desc').innerHTML = '<p>Rendered body.</p>';"
        "  var price = document.createElement('meta');"
        "  price.setAttribute('property', 'product:price:amount');"
        "  price.setAttribute('content', '19.99');"
        "  document.head.appendChild(price);"
        "  var currency = document.createElement('meta');"
        "  currency.setAttribute('property', 'product:price:currency');"
        "  currency.setAttribute('content', 'GBP');"
        "  document.head.appendChild(currency);"
        "  var ready = document.createElement('div');"
        "  ready.id = 'ready';"
        "  document.body.appendChild(ready);"
        "}, 50);"
        "</script>"
        "</body></html>"
    )


@contextmanager
def fixture_server() -> Iterator[str]:
    class QuietServer(ThreadingHTTPServer):
        def handle_error(self, request: Any, client_address: Any) -> None:
            import sys

            if isinstance(sys.exc_info()[1], ConnectionResetError):
                return
            super().handle_error(request, client_address)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            base = f"http://127.0.0.1:{self.server.server_port}"  # type: ignore[attr-defined]
            if self.path == "/":
                body = ENTRY_HTML.encode("utf-8")
            elif self.path == "/p1.html":
                body = product_html(base).encode("utf-8")
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = QuietServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _browser_available() -> bool:
    try:
        from patchright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        try:
            return Path(playwright.chromium.executable_path).is_file()
        finally:
            playwright.stop()
    except Exception:  # noqa: BLE001 - optional browser probe
        return False


BROWSER_AVAILABLE = _browser_available()


class BrowserConfigTests(unittest.TestCase):
    def test_boolean_browser_flag_uses_defaults(self) -> None:
        config = BrowserConfig.from_fetch({"timeout_ms": 12000, "browser": True})
        self.assertTrue(config.launch.headless)
        self.assertEqual(config.page.timeout_ms, 12000)

    def test_browser_mapping_and_per_type_overrides(self) -> None:
        config = BrowserConfig.from_fetch(
            {
                "default_engine": "browser",
                "browser": {
                    "headless": False,
                    "real_chrome": True,
                    "challenge_wait_ms": 5000,
                    "wait_selector": "main",
                },
                "per_url_type": {
                    "product": {
                        "engine": "browser",
                        "wait_selector": "#ready",
                        "wait_ms": 250,
                    }
                },
            }
        )
        self.assertFalse(config.launch.headless)
        self.assertTrue(config.launch.real_chrome)
        self.assertEqual(config.launch.challenge_wait_ms, 5000)
        self.assertEqual(config.page.wait_selector, "main")
        self.assertEqual(config.page_by_type["product"].wait_selector, "#ready")
        self.assertEqual(config.page_by_type["product"].wait_ms, 250)

    def test_rule_accepts_browser_engines(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            rule = Path(temporary) / "rule.yaml"
            rule.write_text(
                RULE_TEMPLATE.replace("__BASE__", "https://example.test"),
                encoding="utf-8",
            )
            loaded = load_rule(rule)
            self.assertEqual(loaded.fetch["default_engine"], "browser")
            self.assertEqual(
                loaded.fetch["per_url_type"]["product"]["engine"], "browser"
            )

    def test_rule_rejects_unknown_engine(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            rule = Path(temporary) / "rule.yaml"
            text = RULE_TEMPLATE.replace("__BASE__", "https://example.test")
            text = text.replace('default_engine: "browser"', 'default_engine: "magic"')
            rule.write_text(text, encoding="utf-8")
            with self.assertRaises(RuleError):
                load_rule(rule)

    def test_rule_rejects_browser_false_with_browser_engine(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            rule = Path(temporary) / "rule.yaml"
            text = RULE_TEMPLATE.replace("__BASE__", "https://example.test")
            text = text.replace(
                "  browser:\n    headless: true\n    disable_resources: true",
                "  browser: false",
            )
            rule.write_text(text, encoding="utf-8")
            with self.assertRaises(RuleError):
                load_rule(rule)


class HybridRoutingTests(unittest.TestCase):
    def _fetcher(self, engine: str, calls: list[tuple[str, str, str | None]]) -> Any:
        class FakeFetcher:
            thread_affine = engine == "browser"

            def __init__(self) -> None:
                self.requests = 0
                self.closed = False

            def get(self, url: str, *, item_type: str | None = None) -> FetchResult:
                self.requests += 1
                calls.append((engine, url, item_type))
                return FetchResult(status=200, url=url, body=b"<html></html>")

            def describe(self) -> dict[str, Any]:
                return {
                    "engine": engine,
                    "engines_used": [engine] if self.requests else [],
                    "thread_affine": self.thread_affine,
                    "browser_launched": engine == "browser" and bool(self.requests),
                }

            def close(self) -> None:
                self.closed = True

        return FakeFetcher()

    def test_items_route_to_declared_engine_and_close(self) -> None:
        calls: list[tuple[str, str, str | None]] = []
        fetchers: dict[str, Any] = {}

        def build(engine: str) -> Any:
            if engine not in fetchers:
                fetchers[engine] = self._fetcher(engine, calls)
            return fetchers[engine]

        router = HybridFetcher(
            default_engine="static",
            overrides={"product": "browser"},
            builders={"static": lambda: build("static"), "browser": lambda: build("browser")},
        )
        self.assertTrue(router.thread_affine)
        router.get("https://example.test/", item_type="navigation")
        router.get("https://example.test/p1.html", item_type="product")
        self.assertEqual(router.requests, 2)
        self.assertEqual(
            [(engine, item) for engine, _, item in calls],
            [("static", "navigation"), ("browser", "product")],
        )
        description = router.describe()
        self.assertEqual(description["engine"], "hybrid")
        self.assertEqual(description["engines_used"], ["browser", "static"])
        router.close()
        self.assertTrue(all(fetcher.closed for fetcher in fetchers.values()))


@unittest.skipUnless(BROWSER_AVAILABLE, "Patchright Chromium is not installed")
class BrowserIntegrationTests(unittest.TestCase):
    def test_javascript_product_runs_through_browser_and_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, fixture_server() as base:
            root = Path(temporary)
            rule = root / "rule.yaml"
            rule.write_text(RULE_TEMPLATE.replace("__BASE__", base), encoding="utf-8")

            with urllib.request.urlopen(f"{base}/p1.html") as response:
                static_html = response.read().decode("utf-8")
            self.assertIn('<h1 id="name"></h1>', static_html)
            self.assertNotIn(">Rendered Shirt<", static_html)

            result = run_and_export(
                rule_path=rule,
                db_path=root / "tasks.db",
                out_root=root / "tasks",
                task_id="browser-fixture",
                task_type="product",
                max_products=5,
                max_seconds=60,
                max_attempts=1,
                per_domain_rps=50,
            )
            task_result = result.task_result
            self.assertEqual(task_result["state"], "FINISHED")
            self.assertEqual(task_result["counts"]["valid_products"], 1)
            self.assertEqual(task_result["stop_reason"], "NATURAL_END")
            self.assertTrue(task_result["runtime"]["browser"]["launched"])
            self.assertEqual(task_result["runtime"]["fetch_engines"], ["browser"])
            self.assertIn("patchright CDP", task_result["runtime"]["http_engine"])
            self.assertTrue(task_result["access"]["browser_launched"])
            self.assertIn("Browser rendering", " ".join(task_result["limitations"]))
            pid = task_result["resources"]["browser_pid"]
            self.assertIsInstance(pid, int)
            self.assertEqual(task_result["resources"]["browser_profile"], "browser-profile")

            rows = (result.export_dir / "products.csv").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(len(rows), 2)
            self.assertIn("Rendered Shirt", rows[1])

            store = TaskStore(root / "tasks.db")
            self.assertEqual(store.list_resources("browser-fixture"), [])
            self.assertFalse((root / "tasks" / "browser-fixture" / "browser-profile").exists())
            self.assertFalse(pid_alive(int(pid)))

    def test_hybrid_static_navigation_and_browser_product(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, fixture_server() as base:
            root = Path(temporary)
            rule = root / "rule.yaml"
            text = RULE_TEMPLATE.replace("__BASE__", base)
            text = text.replace('default_engine: "browser"', 'default_engine: "static"')
            rule.write_text(text, encoding="utf-8")

            result = run_and_export(
                rule_path=rule,
                db_path=root / "tasks.db",
                out_root=root / "tasks",
                task_id="browser-hybrid",
                task_type="product",
                max_products=5,
                max_seconds=60,
                max_attempts=1,
                per_domain_rps=50,
            )
            task_result = result.task_result
            self.assertEqual(task_result["state"], "FINISHED")
            self.assertEqual(task_result["counts"]["valid_products"], 1)
            self.assertEqual(
                task_result["runtime"]["fetch_engines"], ["browser", "static"]
            )
            self.assertIn("static HTML", task_result["runtime"]["http_engine"])
            self.assertIn("patchright CDP", task_result["runtime"]["http_engine"])
            rows = (result.export_dir / "products.csv").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertIn("Rendered Shirt", rows[1])


if __name__ == "__main__":
    unittest.main()
