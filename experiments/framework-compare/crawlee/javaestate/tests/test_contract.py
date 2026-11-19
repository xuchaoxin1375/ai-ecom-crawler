"""Contract tests for the javaestate Crawlee extractor and CSV export.

These are synthetic fixtures: they exercise the data rules (positive price,
currency evidence, description states, options, CSV quoting) without claiming
that any real page was fetched.
"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACKAGE_DIR))

from crawlee_javaestate.clean import clean_html_fragment  # noqa: E402
from crawlee_javaestate.export import CSV_COLUMNS, write_valid_csv  # noqa: E402
from crawlee_javaestate.extract import (  # noqa: E402
    ProductExcluded,
    ProductFailed,
    extract_product,
    serialize_options,
)

URL = "https://javaestate.com/products/synthetic-test-product"


def make_page(
    *,
    title: str = "Synthetic Test Product",
    variants: list[dict] | None = None,
    options: list[str] | None = None,
    vendor: str = "Synthetic Brand",
    product_type: str = "Test Type",
    description: str = "<p>A synthetic description.</p>",
    jsonld_description: str = "",
    embedded_description: str | None = None,
    include_description_container: bool = True,
    featured_image: str = "//cdn.shopify.com/s/files/1/0000/0000/products/test.jpg?v=1",
    currency: str = "USD",
    analytics_currency: str = "USD",
    country: str = "US",
    shop_locale: str = "en",
    category: str = "Synthetic Category",
    canonical: str = URL,
) -> str:
    if variants is None:
        variants = [
            {
                "title": "Default Title",
                "price": 2549,
                "available": True,
                "options": ["Default Title"],
            }
        ]
    if options is None:
        options = ["Title"]
    product = {
        "title": title,
        "description": description if embedded_description is None else embedded_description,
        "vendor": vendor,
        "type": product_type,
        "available": any(bool(v.get("available")) for v in variants),
        "variants": variants,
        "options": options,
        "featured_image": featured_image,
        "images": [featured_image],
    }
    jsonld = {
        "@context": "http://schema.org",
        "@type": "Product",
        "name": title,
        "brand": {"@type": "Brand", "name": vendor},
        "category": category,
        "description": jsonld_description,
        "image": featured_image,
        "offers": {
            "@type": "Offer",
            "price": str(variants[0].get("price", 0) / 100),
            "priceCurrency": currency,
            "availability": "http://schema.org/InStock",
        },
    }
    return f"""<!doctype html>
<html><head>
<link rel="canonical" href="{canonical}">
<script type="application/ld+json">{json.dumps(jsonld)}</script>
</head><body>
<h1>{title}</h1>
{('<div class="product__description">' + description + '</div>') if include_description_container else ''}
<script>window.wpdExtensionIsProductPage = {json.dumps(product)};</script>
<script>Shopify.currency = {json.dumps({"active": currency, "rate": "1.0"})};
Shopify.country = "{country}"; Shopify.locale = "{shop_locale}";</script>
<script>ShopifyAnalytics.meta.currency = '{analytics_currency}';</script>
</body></html>"""


def extract(html: str):
    return extract_product(
        html,
        URL,
        market="US",
        locale="en-US",
        extracted_at="2026-11-19T00:00:00Z",
    )


class PriceAndCurrencyTests(unittest.TestCase):
    def test_min_positive_variant_and_options(self) -> None:
        html = make_page(
            variants=[
                {
                    "title": "S / Red",
                    "price": 2900,
                    "available": False,
                    "options": ["S", "Red"],
                },
                {
                    "title": "M / Blue",
                    "price": 3500,
                    "available": True,
                    "options": ["M", "Blue"],
                },
            ],
            options=["Size", "Color"],
        )
        result = extract(html)
        self.assertEqual(result.row["price_amount"], "29.00")
        self.assertEqual(result.row["price_currency"], "USD")
        self.assertEqual(result.row["attributes"], "Size#S|M~Color#Red|Blue")
        self.assertEqual(result.row["availability"], "in_stock")
        self.assertIn("Size#S", result.row["attributes"])

    def test_all_out_of_stock_variants_are_still_valid(self) -> None:
        html = make_page(
            variants=[
                {
                    "title": "Default Title",
                    "price": 2900,
                    "available": False,
                    "options": ["Default Title"],
                }
            ]
        )
        result = extract(html)
        self.assertEqual(result.row["price_amount"], "29.00")
        self.assertEqual(result.row["availability"], "out_of_stock")

    def test_zero_price_is_excluded_not_failed(self) -> None:
        html = make_page(
            variants=[
                {"title": "Default Title", "price": 0, "available": True, "options": ["Default Title"]}
            ]
        )
        with self.assertRaises(ProductExcluded) as ctx:
            extract(html)
        self.assertEqual(ctx.exception.reason, "ZERO_PRICE")

    def test_all_zero_variants_do_not_fall_back_to_jsonld(self) -> None:
        html = make_page(
            variants=[
                {"title": "Default Title", "price": 0, "available": True, "options": ["Default Title"]}
            ]
        )
        # The synthetic JSON-LD offer is also zero, but the embedded variants
        # are authoritative.  This test guards the precedence rule.
        with self.assertRaises(ProductExcluded) as ctx:
            extract(html)
        self.assertEqual(ctx.exception.reason, "ZERO_PRICE")

    def test_currency_conflict_is_failed(self) -> None:
        html = make_page(currency="USD", analytics_currency="EUR")
        with self.assertRaises(ProductFailed) as ctx:
            extract(html)
        self.assertEqual(ctx.exception.reason, "CURRENCY_CONFLICT")

    def test_non_usd_is_excluded(self) -> None:
        html = make_page(currency="EUR", analytics_currency="EUR")
        with self.assertRaises(ProductExcluded) as ctx:
            extract(html)
        self.assertEqual(ctx.exception.reason, "CURRENCY_NOT_TARGET")


class FieldTests(unittest.TestCase):
    def test_store_name_is_not_a_brand(self) -> None:
        html = make_page(vendor="Java Estate Roastery")
        result = extract(html)
        self.assertEqual(result.row["brand"], "")
        reasons = json.loads(result.row["missing_reasons"])
        self.assertEqual(reasons["brand"], "STORE_NAME_NOT_BRAND")

    def test_single_default_variant_has_no_meaningful_options(self) -> None:
        html = make_page()
        result = extract(html)
        self.assertEqual(result.row["attributes"], "")
        reasons = json.loads(result.row["missing_reasons"])
        self.assertEqual(reasons["options"], "NO_MEANINGFUL_OPTIONS")

    def test_jsonld_description_is_marked_fallback(self) -> None:
        html = make_page(
            description="",
            jsonld_description="Plain-text summary from structured data.",
        )
        result = extract(html)
        self.assertEqual(result.row["description_status"], "fallback")
        self.assertEqual(result.row["description_format"], "text")
        self.assertIn("Plain-text summary", result.row["description_html"])

    def test_no_description_is_marked_not_provided(self) -> None:
        html = make_page(description="", jsonld_description="")
        result = extract(html)
        self.assertEqual(result.row["description_status"], "not_provided")
        self.assertEqual(result.row["description_html"], "")
        self.assertEqual(result.evidence["description_source"], "empty_description_container")
        self.assertTrue(result.evidence["description_empty_container_hit"])
        reasons = json.loads(result.row["missing_reasons"])
        self.assertEqual(reasons["description_html"], "SOURCE_HAS_NO_DESCRIPTION")

    def test_dom_description_is_used_when_embedded_is_empty(self) -> None:
        html = make_page(
            description="<p>DOM-only description, kept after cleaning.</p>",
            embedded_description="",
        )
        result = extract(html)
        self.assertEqual(result.row["description_status"], "complete")
        self.assertEqual(result.evidence["description_source"], "product_page_dom")
        self.assertIn("DOM-only description", result.row["description_html"])

    def test_missing_description_container_is_failed(self) -> None:
        html = make_page(
            description="",
            embedded_description="",
            jsonld_description="",
            include_description_container=False,
        )
        with self.assertRaises(ProductFailed) as ctx:
            extract(html)
        self.assertEqual(ctx.exception.reason, "DESCRIPTION_BLOCK_NOT_FOUND")

    def test_generic_type_falls_back_to_jsonld_category(self) -> None:
        html = make_page(product_type="Shop", category="Real Category")
        result = extract(html)
        self.assertEqual(result.row["category"], "Real Category")


class CleaningAndExportTests(unittest.TestCase):
    def test_cleaner_removes_scripts_links_and_attributes(self) -> None:
        cleaned = clean_html_fragment(
            '<p class="x">Hello <a href="/x" onclick="bad()">link</a>'
            "<script>alert(1)</script><img src='x'><strong>world</strong></p>"
        )
        self.assertIn("Hello link", cleaned)
        self.assertIn("<strong>world</strong>", cleaned)
        self.assertNotIn("script", cleaned)
        self.assertNotIn("href", cleaned)
        self.assertNotIn("img", cleaned)

    def test_option_serialization_escapes_reserved_characters(self) -> None:
        value = serialize_options({"Size#1": ["A|B", "C~D", "E\\F"]})
        self.assertEqual(value, "Size\\#1#A\\|B|C\\~D|E\\\\F")

    def test_csv_round_trip_preserves_22_columns_and_text(self) -> None:
        html = make_page(
            title="=SUM(A1:A2) 中文, \"quoted\"",
            description="<p>Line one, with comma</p>\n<p>第二行 中文</p>",
        )
        result = extract(html)
        row = dict(result.row)
        row.update(
            {
                "task_id": "task-test",
                "plan_id": "javaestate-us-en-usd",
                "plan_version": "test-1",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "valid.csv"
            write_valid_csv(path, [row])
            raw = path.read_text(encoding="utf-8")
            self.assertTrue(raw.startswith("name,"))
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]), set(CSV_COLUMNS))
        self.assertEqual(len(rows[0]), 22)
        self.assertTrue(rows[0]["name"].startswith("'=SUM"))
        self.assertIn("中文", rows[0]["name"])
        self.assertIn("第二行 中文", rows[0]["description_html"])
        self.assertEqual(json.loads(rows[0]["missing_reasons"])["tax_basis"], "NOT_SPECIFIED_BY_SOURCE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
