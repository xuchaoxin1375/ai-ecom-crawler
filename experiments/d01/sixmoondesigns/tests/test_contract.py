"""Offline contract checks for the S4 sixmoondesigns plan."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run  # noqa: E402


class CurrencyTests(unittest.TestCase):
    def test_shopify_currency(self) -> None:
        text = '<script>Shopify.currency = {"active":"USD","rate":"1.0"};</script>'
        self.assertEqual(run.parse_active_currency(text), "USD")
        text = '<script>Shopify.currency = {"active":"CNY","rate":"6.75"};</script>'
        self.assertEqual(run.parse_active_currency(text), "CNY")

    def test_meta_fallback_and_missing(self) -> None:
        text = '<meta property="product:price:currency" content="EUR">'
        self.assertEqual(run.parse_active_currency(text), "EUR")
        self.assertIsNone(run.parse_active_currency("<html></html>"))


class PriceTests(unittest.TestCase):
    def test_min_positive_variant(self) -> None:
        product = {"variants": [{"price": "0"}, {"price": "18.00"}, {"price": "12.50"}]}
        self.assertEqual(run.min_positive_price(product), 12.5)

    def test_no_positive_price(self) -> None:
        self.assertIsNone(run.min_positive_price({"variants": [{"price": "0"}, {"price": "abc"}]}))


class DescriptionTests(unittest.TestCase):
    def test_cleans_unsafe_markup_and_keeps_table(self) -> None:
        raw = (
            '<div class="x"><script>alert(1)</script><p>Hello <a href="https://x.test">link</a></p>'
            "<table><tr><th>Size</th><td>3.2 lb</td></tr></table><img src='x.jpg'></div>"
        )
        cleaned, status = run.clean_html(raw)
        self.assertEqual(status, "complete")
        self.assertNotIn("<script", cleaned)
        self.assertNotIn("<a ", cleaned)
        self.assertNotIn("<img", cleaned)
        self.assertIn("link", cleaned)
        self.assertIn("<table>", cleaned)
        self.assertIn("3.2 lb", cleaned)

    def test_empty_and_cleaned_empty(self) -> None:
        self.assertEqual(run.clean_html(""), ("", "not_provided"))
        self.assertEqual(run.clean_html("<script>x</script>"), ("", "failed"))


class AttributeTests(unittest.TestCase):
    def test_union_and_escape(self) -> None:
        product = {
            "options": [{"name": "Size"}, {"name": "Color"}, {"name": "Quantity"}],
            "variants": [
                {"option1": "S", "option2": "Red", "option3": "1"},
                {"option1": "M", "option2": "Blue|Dark", "option3": "2"},
            ],
        }
        self.assertEqual(run.serialize_attributes(product), "Size#S|M~Color#Red|Blue\\|Dark")

    def test_default_title_is_not_option(self) -> None:
        product = {"options": [{"name": "Title"}], "variants": [{"option1": "Default Title"}]}
        self.assertEqual(run.serialize_attributes(product), "")


class CsvTests(unittest.TestCase):
    def test_nine_columns_and_formula_protection(self) -> None:
        row = {column: "" for column in run.CSV_COLUMNS}
        row.update(
            {
                "name": "=CMD()",
                "price_amount": "18.00",
                "price_currency": "USD",
                "primary_image_url": "https://cdn.shopify.com/x.jpg",
                "description_html": "<p>Hello</p>",
                "source_url": "https://www.sixmoondesigns.com/products/x",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "valid.csv"
            run.write_csv(path, [row])
            with path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, run.CSV_COLUMNS)
                parsed = next(reader)
            self.assertEqual(parsed["name"], "'=CMD()")
            self.assertEqual(parsed["price_amount"], "18.00")
            self.assertEqual(len(parsed), 9)


class PublishedResultTests(unittest.TestCase):
    def test_counts_if_published(self) -> None:
        result_path = ROOT / "task-result.json"
        if not result_path.is_file():
            self.skipTest("no published task-result.json")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        counts = result["counts"]
        self.assertEqual(
            counts["product_candidates"],
            counts["pending_products"] + counts["in_flight_products"] + counts["processed_products"],
        )
        self.assertEqual(
            counts["processed_products"],
            counts["valid_products"] + counts["excluded_products"] + counts["failed_products"],
        )


if __name__ == "__main__":
    unittest.main()
