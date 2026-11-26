from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import yaml

from ecom_crawler.execution import run_and_export, run_task
from ecom_crawler.runtime.rule import RuleError, load_rule
from tests.support import serve_http_fixture

RULE_TEMPLATE = """\
schema_version: "1.1"
rule_id: "hybrid-fixture"
rule_version: "2026.11.22-1"
kind: "hybrid"
status: candidate

site:
  name: "Hybrid fixture"
  entry_urls: ["__BASE__/virtual.html"]
  allowed_origins: ["__BASE__"]
  allowed_path_prefixes: ["/"]
  market: "FR"
  locale: "fr-FR"
  currency: "EUR"

scope:
  include: ['^/product/']
  exclude: []

capabilities:
  discovery: true
  product: true

discovery:
  sources:
    - type: adapter
      url: "__BASE__/virtual.html"
      browser:
        headless: true
        timeout_ms: 10000
        wait_state: "attached"
      advance:
        item_selector: "a.product"
        container: "#feed"
        settle_ms: 1
        no_new_stop: 1
      max_batches: 2
      max_seconds: 20
  product_url_patterns: ['^/product/[^/]+\\.html$']
  url_identity: "canonical"

runtime:
  adapter_id: "fake-adapter"
  adapter_version: "2026.11.22-1"
  entrypoint: "adapter.py"
  protocol: "ndjson-stdio-v1"
  capabilities: ["discovery"]

fetch:
  default_engine: "static"
  concurrency: 1
  delay_ms: 1000
  retry: {max_attempts: 1, backoff_ms: 0}
  timeout_ms: 10000
  browser: false

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
    statuses: ["complete", "partial", "fallback", "not_provided", "failed"]
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
  product_csv:
    enabled: true
    columns: 9
  task_result: true

task_defaults:
  max_urls: 10
  max_products: 10
  max_seconds: 30
"""


ADAPTER_OK = """\
import json
import sys

from pathlib import Path

context_path = sys.argv[sys.argv.index("--context") + 1]
context = json.load(open(context_path, encoding="utf-8"))
profile = context.get("browser", {}).get("profile_dir")
if profile:
    Path(profile).mkdir(parents=True, exist_ok=True)
    (Path(profile) / "lock").write_text("x", encoding="utf-8")
base = context["entry_url"].rsplit("/", 1)[0]
urls = [f"{base}/product/p{index}.html" for index in (1, 2, 3)]
print(json.dumps({"event": "start", "adapter_id": "fake-adapter"}), flush=True)
print(json.dumps({"event": "batch", "batch": 0, "ids": ["p1", "p2", "p3"], "rendered": 3, "recycled": 0, "new": 3, "total": 3}), flush=True)
print(json.dumps({"event": "discovered", "count": len(urls), "urls": urls}), flush=True)
print(json.dumps({"event": "done", "stop": "MAX_ITEMS", "items": len(urls), "rendered": 3, "recycled": 0, "requests": 1}), flush=True)
"""


ADAPTER_FAIL = """\
import json
import sys

print(json.dumps({
    "event": "error",
    "reason": "fixture_failure",
    "failure_class": "permanent",
    "detail": "adapter refused to run",
}), flush=True)
raise SystemExit(3)
"""


ADAPTER_HANG = """\
import json
import sys
import time
from pathlib import Path

context_path = sys.argv[sys.argv.index("--context") + 1]
context = json.load(open(context_path, encoding="utf-8"))
profile = context.get("browser", {}).get("profile_dir")
if profile:
    Path(profile).mkdir(parents=True, exist_ok=True)
    (Path(profile) / "lock").write_text("x", encoding="utf-8")
print(json.dumps({"event": "start", "adapter_id": "hang-adapter"}), flush=True)
time.sleep(60)
"""


def product_html(index: int) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Product {index}</title>
<meta property="og:image" content="/img/p{index}.jpg">
<meta property="product:price:amount" content="{10 + index}.00">
<meta property="product:price:currency" content="EUR">
<link rel="canonical" href="/product/p{index}.html">
</head><body><h1>Product {index}</h1></body></html>
"""


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
            if self.path == "/virtual.html":
                body = b"<html><body><div id='feed'></div></body></html>"
            elif self.path.startswith("/product/p") and self.path.endswith(".html"):
                try:
                    index = int(self.path[len("/product/p") : -len(".html")])
                except ValueError:
                    index = 1
                body = product_html(index).encode()
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


def write_package(root: Path, base: str, adapter: str) -> Path:
    rule = root / "rule.yaml"
    rule.write_text(RULE_TEMPLATE.replace("__BASE__", base), encoding="utf-8")
    (root / "adapter.py").write_text(adapter, encoding="utf-8")
    return rule


def enable_task_profile(rule: Path) -> None:
    text = rule.read_text(encoding="utf-8")
    text = text.replace(
        '        wait_state: "attached"',
        '        wait_state: "attached"\n        profile_mode: "task"',
    )
    rule.write_text(text, encoding="utf-8")


class HybridRuntimeTests(unittest.TestCase):
    def test_hybrid_adapter_discovers_and_products_are_extracted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, fixture_server() as base:
            root = Path(temporary)
            rule = write_package(root, base, ADAPTER_OK)
            result = run_and_export(
                rule_path=rule,
                db_path=root / "tasks.db",
                out_root=root / "tasks",
                task_id="hybrid-001",
                task_type="product",
                max_products=10,
                max_seconds=30,
                max_attempts=1,
                per_domain_rps=50,
            )
            counts = result.task_result["counts"]
            self.assertEqual(counts["valid_products"], 3)
            self.assertEqual(counts["failed_products"], 0)
            adapter = result.task_result["runtime"]["adapter"]
            self.assertEqual(adapter["adapter_id"], "fake-adapter")
            self.assertEqual(adapter["discovered"], 3)
            self.assertEqual(adapter["added"], 3)
            self.assertEqual(adapter["rendered"], 3)
            self.assertEqual(adapter["recycled"], 0)
            self.assertEqual(adapter["stop"], "MAX_ITEMS")
            self.assertEqual(adapter["profile_mode"], "ephemeral")
            self.assertIsNone(adapter["profile_dir"])
            self.assertIsNone(adapter["profile_removed"])
            self.assertTrue((result.out_dir / "adapter-context.json").is_file())
            self.assertTrue((result.out_dir / "adapter.ndjson").is_file())
            self.assertFalse((result.out_dir / "adapter-browser-profile").exists())
            context = json.loads(
                (result.out_dir / "adapter-context.json").read_text(encoding="utf-8")
            )
            self.assertNotIn("profile_dir", context["browser"])
            self.assertIsNotNone(result.app_export)
            rows = (result.out_dir / "export" / "products.csv").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(len(rows), 4)

    def test_persistent_profile_is_registered_and_cleaned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, fixture_server() as base:
            root = Path(temporary)
            rule = write_package(root, base, ADAPTER_OK)
            enable_task_profile(rule)
            result = run_and_export(
                rule_path=rule,
                db_path=root / "tasks.db",
                out_root=root / "tasks",
                task_id="hybrid-profile-001",
                task_type="product",
                max_products=10,
                max_seconds=30,
                max_attempts=1,
                per_domain_rps=50,
            )
            adapter = result.task_result["runtime"]["adapter"]
            self.assertEqual(adapter["profile_mode"], "task")
            self.assertTrue(adapter["profile_removed"])
            self.assertFalse((result.out_dir / "adapter-browser-profile").exists())

    def test_hybrid_discovery_writes_url_list_without_product_fetches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, fixture_server() as base:
            root = Path(temporary)
            rule = write_package(root, base, ADAPTER_OK)
            result, task_dir = run_task(
                rule_path=rule,
                db_path=root / "tasks.db",
                out_root=root / "tasks",
                task_id="hybrid-discovery-001",
                task_type="discovery",
                max_urls=10,
                max_seconds=30,
                max_attempts=1,
                per_domain_rps=50,
            )
            self.assertEqual(result["counts"]["valid_urls"], 3)
            self.assertEqual(result["counts"]["url_candidates"], 3)
            self.assertEqual(result["counts"]["navigation_urls"], 0)
            rows = (task_dir / "urls.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 4)
            self.assertEqual(result["runtime"]["adapter"]["added"], 3)

    def test_adapter_failure_is_recorded_without_products(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, fixture_server() as base:
            root = Path(temporary)
            rule = write_package(root, base, ADAPTER_FAIL)
            result, task_dir = run_task(
                rule_path=rule,
                db_path=root / "tasks.db",
                out_root=root / "tasks",
                task_id="hybrid-fail-001",
                task_type="product",
                max_products=10,
                max_seconds=30,
                max_attempts=1,
                per_domain_rps=50,
            )
            self.assertEqual(result["outcome"], "FAILED")
            self.assertEqual(result["stop_reason"], "ADAPTER_FAILED")
            self.assertIn("fixture_failure", result["stop_detail"])
            self.assertEqual(result["counts"]["valid_products"], 0)
            self.assertTrue((task_dir / "adapter.ndjson").is_file())

    def test_adapter_timeout_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, fixture_server() as base:
            root = Path(temporary)
            rule = write_package(root, base, ADAPTER_HANG)
            enable_task_profile(rule)
            rule.write_text(
                rule.read_text(encoding="utf-8").replace(
                    "max_seconds: 20", "max_seconds: 1"
                ),
                encoding="utf-8",
            )
            result, task_dir = run_task(
                rule_path=rule,
                db_path=root / "tasks.db",
                out_root=root / "tasks",
                task_id="hybrid-timeout-001",
                task_type="product",
                max_products=10,
                max_seconds=30,
                max_attempts=1,
                per_domain_rps=50,
            )
            self.assertEqual(result["outcome"], "FAILED")
            self.assertEqual(result["stop_reason"], "ADAPTER_FAILED")
            self.assertIn("adapter_timeout", result["stop_detail"])
            self.assertTrue((task_dir / "adapter.ndjson").is_file())
            self.assertFalse((task_dir / "adapter-browser-profile").exists())

    def test_hybrid_requires_runtime_and_safe_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, fixture_server() as base:
            root = Path(temporary)
            rule = write_package(root, base, ADAPTER_OK)
            data = yaml.safe_load(rule.read_text(encoding="utf-8"))
            data.pop("runtime")
            rule.write_text(
                yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuleError, "runtime"):
                load_rule(rule)

            rule = write_package(root, base, ADAPTER_OK)
            data = yaml.safe_load(rule.read_text(encoding="utf-8"))
            data["runtime"]["entrypoint"] = "../adapter.py"
            rule.write_text(
                yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuleError, "entrypoint"):
                load_rule(rule)

            rule = write_package(root, base, ADAPTER_OK)
            (root / "adapter.py").unlink()
            with self.assertRaisesRegex(RuleError, "entrypoint"):
                load_rule(rule)

    def test_adapter_proxy_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, fixture_server() as base:
            root = Path(temporary)
            rule = write_package(root, base, ADAPTER_OK)
            data = yaml.safe_load(rule.read_text(encoding="utf-8"))
            source = data["discovery"]["sources"][0]
            source["browser"]["proxy"] = "http://127.0.0.1:7897"
            rule.write_text(
                yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            load_rule(rule)

            source["browser"]["proxy"] = "ftp://127.0.0.1:7897"
            rule.write_text(
                yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuleError, "proxy"):
                load_rule(rule)

            source["browser"]["proxy"] = "http://user:secret@127.0.0.1:7897"
            rule.write_text(
                yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuleError, "credentials"):
                load_rule(rule)

    def test_declarative_cannot_use_adapter_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, fixture_server() as base:
            root = Path(temporary)
            rule = write_package(root, base, ADAPTER_OK)
            text = rule.read_text(encoding="utf-8").replace(
                'kind: "hybrid"', 'kind: "declarative"'
            )
            rule.write_text(text, encoding="utf-8")
            with self.assertRaises(RuleError):
                load_rule(rule)


if __name__ == "__main__":
    unittest.main()
