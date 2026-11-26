from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ecom_crawler.execution import run_and_export
from ecom_crawler.runtime.rule import RuleError, load_rule
from ecom_crawler.runtime.store import TaskStore
from tests.support import serve_http_fixture

RULE_TEMPLATE = """\
schema_version: "1.2"
rule_id: "browser-listing"
rule_version: "2026.11.21-1"
kind: declarative
status: candidate

site:
  name: "Browser Listing Fixture"
  entry_urls: ["__BASE__/listing-more.html"]
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
  sources:
    - type: listing
      url: "__BASE__/listing-more.html"
      product_link_selector: "a.product"
      advance:
        type: load_more
        button_selector: "#more"
        max_clicks: 5
        settle_ms: 50
        no_new_stop: 1
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
    navigation: {engine: "browser", wait_selector: "a.product"}
    product: {engine: "browser", wait_selector: "h1"}
  challenge_handling: "none; stop and record"

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
  max_urls: 10
  max_products: 10
  max_seconds: 60

compatibility:
  os: ["windows", "linux", "wsl2"]
  runtime: "python>=3.11"
  dependencies: ["patchright==1.64.4"]
  browser: "patchright CDP"

evidence:
  sample_urls: ["__BASE__/listing-more.html"]
  expected: []
  verified_at: null
  limitations: ["Local browser listing fixture only."]

notes: "Browser load-more and scroll fixture."
"""

LISTING_MORE_HTML = """\
<html><body>
<div id="items">
  <a class="product" href="/p1.html">One</a>
  <a class="product" href="/p2.html">Two</a>
</div>
<button id="more" type="button">Load more</button>
<script>
let page = 1;
document.getElementById('more').addEventListener('click', function () {
  page += 1;
  if (page <= 3) {
    for (const index of [(page - 1) * 2 + 1, (page - 1) * 2 + 2]) {
      const link = document.createElement('a');
      link.className = 'product';
      link.href = '/p' + index + '.html';
      link.textContent = 'Item ' + index;
      document.getElementById('items').appendChild(link);
    }
  } else {
    this.remove();
  }
  history.pushState({}, '', '/listing-more.html?page=' + page);
});
</script>
</body></html>
"""

LISTING_SCROLL_HTML = """\
<html><body>
<div id="items">
  <a class="product" href="/p1.html">One</a>
  <a class="product" href="/p2.html">Two</a>
</div>
<div id="spacer" style="height: 3000px"></div>
<script>
let loaded = 1;
window.addEventListener('scroll', function () {
  if (loaded >= 3) { return; }
  if ((window.innerHeight + window.scrollY) < document.body.offsetHeight - 100) { return; }
  loaded += 1;
  for (const index of [(loaded - 1) * 2 + 1, (loaded - 1) * 2 + 2]) {
    const link = document.createElement('a');
    link.className = 'product';
    link.href = '/p' + index + '.html';
    link.textContent = 'Item ' + index;
    document.getElementById('items').appendChild(link);
  }
  document.getElementById('spacer').style.height = (3000 + loaded * 1000) + 'px';
  history.pushState({}, '', '/listing-scroll.html?page=' + loaded);
});
</script>
</body></html>
"""

LISTING_CONTAINER_HTML = """\
<html><body>
<div id="feed" style="height: 220px; overflow: auto; border: 1px solid #ccc">
  <div id="items">
    <a class="product" href="/p1.html">One</a>
    <a class="product" href="/p2.html">Two</a>
  </div>
  <div id="spacer" style="height: 1200px"></div>
</div>
<script>
let loaded = 1;
const feed = document.getElementById('feed');
feed.addEventListener('scroll', function () {
  if (loaded >= 3) { return; }
  if (feed.scrollTop + feed.clientHeight < feed.scrollHeight - 20) { return; }
  loaded += 1;
  for (const index of [(loaded - 1) * 2 + 1, (loaded - 1) * 2 + 2]) {
    const link = document.createElement('a');
    link.className = 'product';
    link.href = '/p' + index + '.html';
    link.textContent = 'Item ' + index;
    document.getElementById('items').appendChild(link);
  }
  document.getElementById('spacer').style.height = (1200 + loaded * 600) + 'px';
});
</script>
</body></html>
"""


def product_html(index: int) -> str:
    return (
        "<html><head>"
        f"<title>Product {index}</title>"
        f'<meta property="og:image" content="https://fixture.test/img/{index}.jpg">'
        f'<meta property="product:price:amount" content="{10 + index}.00">'
        '<meta property="product:price:currency" content="GBP">'
        f'<link rel="canonical" href="https://fixture.test/p{index}.html">'
        "</head><body>"
        f'<h1 itemprop="name">Product {index}</h1>'
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
            if self.path == "/listing-more.html":
                body = LISTING_MORE_HTML.encode("utf-8")
            elif self.path == "/listing-scroll.html":
                body = LISTING_SCROLL_HTML.encode("utf-8")
            elif self.path == "/listing-container.html":
                body = LISTING_CONTAINER_HTML.encode("utf-8")
            elif self.path.startswith("/p") and self.path.endswith(".html"):
                try:
                    index = int(self.path[2:-5])
                except ValueError:
                    index = 1
                body = product_html(index).replace(
                    "https://fixture.test", base
                ).encode("utf-8")
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
    with serve_http_fixture(server):
        yield f"http://127.0.0.1:{server.server_address[1]}"


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


@unittest.skipUnless(BROWSER_AVAILABLE, "Patchright Chromium is not installed")
class BrowserListingActionTests(unittest.TestCase):
    def _run(self, root: Path, base: str, html_name: str, advance: str) -> Any:
        # The fixture attaches its scroll/click handlers at the end of the
        # document.  A 50-100 ms settle can observe a scroll before the
        # listener is ready and then stop after one stalled step; use a
        # longer settle and require two stalled steps to keep the test about
        # list advancement instead of browser startup timing.
        rule = root / "rule.yaml"
        text = RULE_TEMPLATE.replace("__BASE__", base)
        text = text.replace("/listing-more.html", f"/{html_name}").replace(
            """      advance:
        type: load_more
        button_selector: "#more"
        max_clicks: 5
        settle_ms: 50
        no_new_stop: 1""",
            "      advance:\n        " + advance,
        )
        rule.write_text(text, encoding="utf-8")
        return run_and_export(
            rule_path=rule,
            db_path=root / "tasks.db",
            out_root=root / "tasks",
            task_id="browser-listing",
            task_type="product",
            max_products=10,
            max_seconds=60,
            # Browser startup/navigation is occasionally transient on CI.
            # One retry keeps this test about list advancement instead of
            # runner timing; production defaults are unchanged.
            max_attempts=2,
            per_domain_rps=50,
        )

    def _assert_valid_products(
        self, result: Any, root: Path, expected: int = 6
    ) -> None:
        counts = result.task_result.get("counts") or {}
        if counts.get("valid_products") == expected:
            return
        navigation = [
            {
                "url": item.url,
                "state": item.state,
                "attempts": item.attempts,
                "failure_class": item.failure_class,
                "result": item.result,
            }
            for item in TaskStore(root / "tasks.db").items(
                "browser-listing", "navigation"
            )
        ]
        detail = {
            "counts": counts,
            "state": result.task_result.get("state"),
            "outcome": result.task_result.get("outcome"),
            "stop_reason": result.task_result.get("stop_reason"),
            "failure_classes": result.task_result.get("failure_classes"),
            "recovery": result.task_result.get("recovery"),
            "browser": (result.task_result.get("runtime") or {}).get("browser"),
            "navigation": navigation,
        }
        self.fail(
            f"valid_products={counts.get('valid_products')} != {expected}: "
            + json.dumps(detail, ensure_ascii=False, sort_keys=True)
        )

    def test_load_more_appends_products(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, fixture_server() as base:
            root = Path(temporary)
            result = self._run(
                root,
                base,
                "listing-more.html",
                "type: load_more\n        button_selector: \"#more\"\n        max_clicks: 5\n        settle_ms: 500\n        no_new_stop: 2",
            )
            self._assert_valid_products(result, root)
            listing = next(
                item
                for item in TaskStore(root / "tasks.db").items(
                    "browser-listing", "navigation"
                )
                if item.discovered_from == "listing"
            )
            advance = listing.result["advance"]
            self.assertEqual(advance["type"], "load_more")
            self.assertGreaterEqual(advance["items"], 6)
            self.assertIn(advance["stop"], {"NO_NEW_ITEMS", "BUTTON_GONE"})
            self.assertGreaterEqual(advance["url_changes"], 1)
            self.assertIn("?page=", advance["final_url"])
            self.assertTrue(advance["urls"])

    def test_infinite_scroll_appends_products(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, fixture_server() as base:
            root = Path(temporary)
            result = self._run(
                root,
                base,
                "listing-scroll.html",
                "type: infinite_scroll\n        mode: \"scroll\"\n        max_scrolls: 5\n        settle_ms: 500\n        no_new_stop: 2",
            )
            self._assert_valid_products(result, root)
            listing = next(
                item
                for item in TaskStore(root / "tasks.db").items(
                    "browser-listing", "navigation"
                )
                if item.discovered_from == "listing"
            )
            advance = listing.result["advance"]
            self.assertEqual(advance["type"], "infinite_scroll")
            self.assertGreaterEqual(advance["items"], 6)
            self.assertIn(advance["stop"], {"NO_NEW_ITEMS", "MAX_STEPS"})
            self.assertGreaterEqual(advance["url_changes"], 1)
            self.assertIn("?page=", advance["final_url"])
            self.assertTrue(advance["urls"])

    def test_infinite_scroll_container_appends_products(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, fixture_server() as base:
            root = Path(temporary)
            result = self._run(
                root,
                base,
                "listing-container.html",
                "type: infinite_scroll\n        mode: \"scroll\"\n        container: \"#feed\"\n        max_scrolls: 5\n        settle_ms: 500\n        no_new_stop: 2",
            )
            self._assert_valid_products(result, root)
            listing = next(
                item
                for item in TaskStore(root / "tasks.db").items(
                    "browser-listing", "navigation"
                )
                if item.discovered_from == "listing"
            )
            advance = listing.result["advance"]
            self.assertEqual(advance["type"], "infinite_scroll")
            self.assertGreaterEqual(advance["items"], 6)
            self.assertIn(advance["stop"], {"NO_NEW_ITEMS", "MAX_STEPS"})
            self.assertGreaterEqual(advance["steps"], 2)
            self.assertEqual(advance["url_changes"], 0)


class BrowserAdvanceValidationTests(unittest.TestCase):
    def test_load_more_requires_schema_1_2(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            rule = Path(temporary) / "rule.yaml"
            text = RULE_TEMPLATE.replace("__BASE__", "https://example.test")
            text = text.replace('schema_version: "1.2"', 'schema_version: "1.1"')
            rule.write_text(text, encoding="utf-8")
            with self.assertRaises(RuleError):
                load_rule(rule)

    def test_load_more_requires_browser_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            rule = Path(temporary) / "rule.yaml"
            text = RULE_TEMPLATE.replace("__BASE__", "https://example.test")
            text = text.replace('default_engine: "browser"', 'default_engine: "static"')
            text = text.replace(
                "  per_url_type:\n"
                '    navigation: {engine: "browser", wait_selector: "a.product"}\n'
                '    product: {engine: "browser", wait_selector: "h1"}\n',
                "",
            )
            rule.write_text(text, encoding="utf-8")
            with self.assertRaises(RuleError):
                load_rule(rule)


if __name__ == "__main__":
    unittest.main()
