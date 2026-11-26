from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import jsonschema
import yaml

from ecom_crawler.execution import run_task
from ecom_crawler.runtime.rule import RuleError, load_rule
from tests.support import serve_http_fixture

RULE_TEMPLATE = """\
schema_version: "1.3"
rule_id: "shopify-fixture"
rule_version: "2026.11.26-1"
kind: declarative
status: candidate

site:
  name: "Shopify Fixture"
  entry_urls: ["__BASE__/"]
  allowed_origins: ["__BASE__"]
  allowed_path_prefixes: ["/"]
  market: "FR"
  locale: "fr-FR"
  currency: "EUR"

scope:
  include: ['^/products/']
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
  product_url_patterns: ['^/products/[^/]+$']
  url_identity: "canonical"

product_source:
  type: "shopify_json"
  currency: "__SOURCE_CURRENCY__"
  url: "__BASE__/products.json"
  product_url_template: "__BASE__/products/{handle}"
  page_size: __PAGE_SIZE__
  max_pages: __MAX_PAGES__
  description:
    min_chars: __MIN_CHARS__
    fallback_concurrency: 1
  variants:
    price: "min_positive"

fetch:
  default_engine: "static"
  concurrency: 1
  delay_ms: 1000
  retry: {max_attempts: 1, backoff_ms: 1000}
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
        - {type: css_attr, selector: 'meta[property="product:price:amount"]', attr: "content", label: "html_price"}
    price.currency:
      required: true
      fallbacks:
        - {type: css_attr, selector: 'meta[property="product:price:currency"]', attr: "content", label: "html_currency"}
    primary_image_url:
      required: true
      fallbacks:
        - {type: css_attr, selector: 'meta[property="og:image"]', attr: "content", label: "og_image", absolute: true}
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

notes: "Local Shopify JSON product-source fixture."
"""

LONG_DESCRIPTION = "<p>" + ("Long product description with material and care details. " * 12) + "</p>"


def product_entry(index: int, *, body_html: str | None = None, price: str = "10.00") -> dict:
    return {
        "id": 1000 + index,
        "handle": f"p{index}",
        "title": f"Product {index}",
        "body_html": LONG_DESCRIPTION if body_html is None else body_html,
        "vendor": "Fixture Vendor",
        "product_type": "Fixture Type",
        "images": [{"src": f"/img/{index}.jpg"}],
        "variants": [
            {
                "id": 2000 + index,
                "title": "Default",
                "price": price,
                "available": True,
            }
        ],
    }


def product_html(index: int, *, price: str = "99.00", description: str = LONG_DESCRIPTION) -> str:
    return (
        "<html><head>"
        f"<title>Product {index}</title>"
        f'<meta property="og:image" content="/img/{index}.jpg">'
        f'<meta property="product:price:amount" content="{price}">'
        '<meta property="product:price:currency" content="EUR">'
        f'<link rel="canonical" href="/products/p{index}">'
        "</head><body>"
        f"<h1>Product {index}</h1>"
        f'<div class="desc">{description}</div>'
        "</body></html>"
    )


@contextmanager
def fixture_server(
    products: list[dict],
    *,
    products_status: int = 200,
    entry_links: bool = False,
    page_size: int = 250,
):
    requests: list[str] = []
    entries = {f"/products/{entry['handle']}": entry for entry in products}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            raw_path = self.path
            requests.append(raw_path)
            parsed = urlsplit(raw_path)
            path = parsed.path
            if path == "/robots.txt":
                self.send_error(404)
                return
            if path == "/products.json":
                if products_status != 200:
                    self.send_error(products_status)
                    return
                query = parse_qs(parsed.query)
                page = int(query.get("page", ["1"])[0])
                limit = int(query.get("limit", [str(page_size)])[0])
                start = max(0, (page - 1) * limit)
                body = json.dumps(
                    {"products": products[start : start + limit]},
                    ensure_ascii=False,
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/":
                links = (
                    "".join(
                        f'<a class="product" href="/products/{entry["handle"]}">'
                        f'{entry["title"]}</a>'
                        for entry in products
                    )
                    if entry_links
                    else ""
                )
                body = f"<html><body>{links}</body></html>".encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path.startswith("/img/"):
                body = bytes.fromhex(
                    "47494638396101000100800000000000ffffff21f90401000000002c"
                    "00000000010001000002024401003b"
                )
                self.send_response(200)
                self.send_header("Content-Type", "image/gif")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            entry = entries.get(path)
            if entry is not None:
                match = path.rsplit("/", 1)[-1].removeprefix("p")
                body = product_html(int(match)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_error(404)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    with serve_http_fixture(server):
        yield f"http://127.0.0.1:{server.server_address[1]}", requests


def write_rule(root: Path, base: str, **values: object) -> Path:
    text = RULE_TEMPLATE.replace("__BASE__", base)
    text = text.replace("__PAGE_SIZE__", str(values.get("page_size", 250)))
    text = text.replace("__MAX_PAGES__", str(values.get("max_pages", 1)))
    text = text.replace("__MIN_CHARS__", str(values.get("min_chars", 200)))
    text = text.replace(
        "__SOURCE_CURRENCY__", str(values.get("source_currency", "EUR"))
    )
    path = root / "rule.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def read_products(root: Path, task_id: str) -> list[dict]:
    path = root / "tasks" / task_id / "products.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class ShopifyProductSourceTests(unittest.TestCase):
    def test_complete_json_products_skip_html_product_pages(self) -> None:
        products = [
            product_entry(1, price="10.00"),
            product_entry(2, price="20.00"),
            product_entry(3, price="30.00"),
        ]
        with tempfile.TemporaryDirectory() as temporary, fixture_server(
            products
        ) as (base, requests):
            root = Path(temporary)
            rule = write_rule(root, base)
            result, _ = run_task(
                rule_path=rule,
                db_path=root / "tasks.db",
                out_root=root / "tasks",
                task_id="shopify-direct",
                task_type="product",
                max_products=3,
                max_seconds=30,
                max_attempts=1,
                per_domain_rps=50,
            )

            self.assertEqual(result["state"], "FINISHED")
            self.assertEqual(result["outcome"], "COMPLETED")
            self.assertEqual(result["counts"]["valid_products"], 3)
            self.assertEqual(result["quality_exceptions"], [])
            self.assertEqual(result["runtime"]["shopify_json"]["direct"], 3)
            self.assertEqual(result["runtime"]["shopify_json"]["fallback"], 0)
            self.assertFalse(
                [path for path in requests if path.startswith("/products/p")],
                requests,
            )
            self.assertTrue(
                any(path.startswith("/products.json?") and "limit=250" in path for path in requests),
                requests,
            )

            rows = read_products(root, "shopify-direct")
            self.assertEqual([row["price_amount"] for row in rows], [10.0, 20.0, 30.0])
            self.assertEqual({row["price_currency"] for row in rows}, {"EUR"})
            self.assertEqual(
                {row["field_sources"]["price.amount"] for row in rows},
                {"shopify_json"},
            )
            self.assertEqual(
                {row["description_status"] for row in rows}, {"complete"}
            )

    def test_empty_json_description_falls_back_to_html(self) -> None:
        products = [product_entry(1, body_html="<p>Short.</p>", price="12.34")]
        with tempfile.TemporaryDirectory() as temporary, fixture_server(
            products
        ) as (base, requests):
            root = Path(temporary)
            rule = write_rule(root, base, min_chars=120)
            result, _ = run_task(
                rule_path=rule,
                db_path=root / "tasks.db",
                out_root=root / "tasks",
                task_id="shopify-fallback",
                task_type="product",
                max_products=1,
                max_seconds=30,
                max_attempts=1,
                per_domain_rps=50,
            )

            self.assertEqual(result["counts"]["valid_products"], 1)
            self.assertEqual(result["runtime"]["shopify_json"]["fallback"], 1)
            self.assertIn("/products/p1", requests)
            rows = read_products(root, "shopify-fallback")
            row = rows[0]
            self.assertEqual(row["price_amount"], 12.34)
            self.assertEqual(row["price_currency"], "EUR")
            self.assertEqual(row["description_status"], "complete")
            self.assertEqual(row["field_sources"]["price.amount"], "shopify_json")
            self.assertEqual(row["field_sources"]["description_html"], "description")

    def test_blocked_json_falls_back_to_declarative_discovery(self) -> None:
        products = [product_entry(1)]
        with tempfile.TemporaryDirectory() as temporary, fixture_server(
            products, products_status=403, entry_links=True
        ) as (base, requests):
            root = Path(temporary)
            rule = write_rule(root, base)
            result, _ = run_task(
                rule_path=rule,
                db_path=root / "tasks.db",
                out_root=root / "tasks",
                task_id="shopify-blocked",
                task_type="product",
                max_products=1,
                max_seconds=30,
                max_attempts=1,
                per_domain_rps=50,
            )

            self.assertEqual(result["state"], "FINISHED")
            self.assertEqual(result["outcome"], "COMPLETED")
            self.assertEqual(result["counts"]["valid_products"], 1)
            self.assertEqual(result["runtime"]["shopify_json"]["blocked"], 1)
            self.assertGreaterEqual(result["failure_classes"]["blocked"], 1)
            events = (
                root / "tasks" / "shopify-blocked" / "events.ndjson"
            ).read_text(encoding="utf-8")
            self.assertIn("shopify_json_unavailable", events)
            self.assertTrue(
                any(path.startswith("/products.json") for path in requests), requests
            )
            self.assertIn("/products/p1", requests)

    def test_products_json_pagination(self) -> None:
        products = [product_entry(1), product_entry(2), product_entry(3)]
        with tempfile.TemporaryDirectory() as temporary, fixture_server(
            products, page_size=2
        ) as (base, requests):
            root = Path(temporary)
            rule = write_rule(root, base, page_size=2, max_pages=2)
            result, _ = run_task(
                rule_path=rule,
                db_path=root / "tasks.db",
                out_root=root / "tasks",
                task_id="shopify-pages",
                task_type="product",
                max_products=3,
                max_seconds=30,
                max_attempts=1,
                per_domain_rps=50,
            )

            self.assertEqual(result["counts"]["valid_products"], 3)
            self.assertEqual(result["runtime"]["shopify_json"]["pages"], 2)
            self.assertTrue(
                any(path.startswith("/products.json") for path in requests), requests
            )
            self.assertTrue(
                any(path.startswith("/products.json?") and "page=2" in path for path in requests),
                requests,
            )

    def test_rule_rejects_old_schema_and_currency_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = "https://shop.example"
            rule = write_rule(root, base)
            text = rule.read_text(encoding="utf-8").replace(
                'schema_version: "1.3"', 'schema_version: "1.2"'
            )
            rule.write_text(text, encoding="utf-8")
            with self.assertRaises(RuleError):
                load_rule(rule)

            rule = write_rule(root, base, source_currency="USD")
            with self.assertRaises(RuleError):
                load_rule(rule)

    def test_manifest_schema_accepts_product_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rule = write_rule(root, "https://shop.example")
            payload = yaml.safe_load(rule.read_text(encoding="utf-8"))
            schema_path = (
                Path(__file__).resolve().parents[2]
                / "docs"
                / "schema"
                / "manifest.schema.json"
            )
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            errors = list(
                jsonschema.Draft202012Validator(schema).iter_errors(payload)
            )
            self.assertEqual(errors, [], [error.message for error in errors])

    def test_variant_price_modes(self) -> None:
        from types import SimpleNamespace

        from ecom_crawler.runtime.shopify import ShopifyProductSource

        entry = {
            "id": 1,
            "handle": "p1",
            "title": "Product 1",
            "price": "15.00",
            "body_html": "<p>" + ("Description. " * 30) + "</p>",
            "images": [{"src": "/img/1.jpg"}],
            "variants": [
                {"title": "Default", "price": "20.00"},
                {"title": "Small", "price": "10.00"},
            ],
        }
        base_rule = {
            "type": "shopify_json",
            "url": "https://shop.example/products.json",
            "product_url_template": "https://shop.example/products/{handle}",
            "currency": "EUR",
        }
        for mode, expected in (
            ("min_positive", 10.0),
            ("first", 20.0),
            ("product_price", 15.0),
        ):
            rule = SimpleNamespace(
                raw={
                    "product_source": {
                        **base_rule,
                        "variants": {"price": mode},
                    }
                },
                entry_url="https://shop.example/",
                site={"currency": "EUR"},
            )
            source = ShopifyProductSource.from_rule(rule)
            product = source.to_extracted(entry, base_url=base_rule["url"])
            self.assertEqual(product.values["price.amount"], expected)


if __name__ == "__main__":
    unittest.main()
