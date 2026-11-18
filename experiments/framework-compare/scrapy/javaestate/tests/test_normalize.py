"""Deterministic checks for the field rules that do not need the network."""

from __future__ import annotations

import csv
import io
import json
import unittest
from decimal import Decimal

from javaestate.normalize import (
    CSV_FIELDS,
    build_valid_row,
    clean_description,
    clean_name,
    csv_safe,
    format_price,
    lowest_positive_variant_price,
    serialize_options,
)


def product(**overrides):
    base = {
        "handle": "example-product",
        "title": "Example Product 12 oz",
        "vendor": "Example Brand",
        "product_type": "Cocoa",
        "body_html": "<p>Rich <strong>chocolate</strong> mix.</p><ul><li>12 oz</li></ul>",
        "images": [{"src": "//cdn.example.test/img.jpg"}],
        "options": [{"name": "Title", "values": ["Default Title"]}],
        "variants": [{"price": "12.50", "available": True}],
    }
    base.update(overrides)
    return base


class PriceTests(unittest.TestCase):
    def test_zero_and_negative_are_excluded_not_skipped(self):
        amount, reason, details = lowest_positive_variant_price(
            [{"price": "0.00"}, {"price": "29.00"}]
        )
        self.assertIsNone(amount)
        self.assertEqual(reason, "non_positive_price")
        self.assertEqual(details["lowest_variant_price"], "0.00")

    def test_invalid_and_missing_are_distinct(self):
        amount, reason, _ = lowest_positive_variant_price([{"price": "n/a"}])
        self.assertIsNone(amount)
        self.assertEqual(reason, "invalid_price")
        amount, reason, _ = lowest_positive_variant_price([])
        self.assertIsNone(amount)
        self.assertEqual(reason, "no_public_price")

    def test_lowest_includes_unavailable_variant(self):
        amount, reason, _ = lowest_positive_variant_price(
            [
                {"price": "29.00", "available": True},
                {"price": "24.17", "available": False},
            ]
        )
        self.assertIsNone(reason)
        self.assertEqual(amount, Decimal("24.17"))
        self.assertEqual(format_price(amount), "24.17")

    def test_comma_decimal_is_accepted_only_without_dot(self):
        amount, _, _ = lowest_positive_variant_price([{"price": "1.234,50"}])
        self.assertIsNone(amount)  # ambiguous thousands separator
        amount, _, _ = lowest_positive_variant_price([{"price": "24,17"}])
        self.assertEqual(amount, Decimal("24.17"))


class NameAndOptionTests(unittest.TestCase):
    def test_name_cleanup_is_conservative(self):
        self.assertEqual(
            clean_name("  Example  Product | Java Estate Roastery  "),
            "Example Product",
        )
        self.assertEqual(clean_name("Café 100% Arabica"), "Café 100% Arabica")

    def test_options_escape_and_merge(self):
        value = serialize_options(
            [
                {"name": "Size", "values": ["S", "M", "s"]},
                {"name": "Color", "values": ["Red|Blue", "Green#Teal"]},
                {"name": "Quantity", "values": ["1", "2"]},
            ]
        )
        self.assertEqual(value, "Size#S|M~Color#Red\\|Blue|Green\\#Teal")
        self.assertNotIn("Quantity", value)

    def test_price_delta_is_removed(self):
        value = serialize_options([{"name": "Size", "values": ["S +$2.00", "M"]}])
        self.assertEqual(value, "Size#S|M")

    def test_default_title_is_not_an_option(self):
        self.assertEqual(
            serialize_options([{"name": "Title", "values": ["Default Title"]}]), ""
        )


class DescriptionTests(unittest.TestCase):
    def test_html_is_cleaned_and_partial_flagged(self):
        description, fmt, status, reason = clean_description(
            '<p onclick="x()">Hello <a href="https://example.test">world</a>'
            "<script>alert(1)</script></p>"
            '<p class="byob-bundle-description-warning">admin only</p>'
            "<table><tr><td colspan=\"2\">Spec</td></tr></table>",
            catalog_only=True,
            page_status=429,
        )
        self.assertEqual(fmt, "html")
        self.assertEqual(status, "partial")
        self.assertIn("products.json body_html", reason)
        self.assertIn("page-only", reason)
        self.assertIn("Hello", description)
        self.assertIn("world", description)
        self.assertNotIn("onclick", description)
        self.assertNotIn("alert", description)
        self.assertNotIn("admin only", description)
        self.assertIn('colspan="2"', description)
        self.assertIn("<table>", description)

    def test_plain_text_stays_text(self):
        description, fmt, status, _ = clean_description(
            "Line one\nLine two", catalog_only=True, page_status=429
        )
        self.assertEqual(fmt, "text")
        self.assertEqual(status, "partial")
        self.assertIn("Line one\nLine two", description)

    def test_empty_description_is_not_provided(self):
        description, fmt, status, reason = clean_description(
            "<script>only script</script>", catalog_only=True, page_status=429
        )
        self.assertEqual((description, fmt, status, reason), ("", "", "not_provided", ""))


class RowTests(unittest.TestCase):
    def test_valid_row_has_22_contract_columns(self):
        row = build_valid_row(
            product=product(),
            source_url="https://javaestate.com/products/example-product",
            task_id="task-1",
            extracted_at="2026-11-19T00:00:00Z",
        )
        row["price_amount"] = "12.50"
        self.assertEqual(len(row), 22)
        self.assertEqual(list(row.keys()), CSV_FIELDS)
        self.assertEqual(row["price_currency"], "USD")
        self.assertEqual(row["market"], "US")
        self.assertEqual(row["locale"], "en-US")
        self.assertEqual(row["description_status"], "partial")
        self.assertEqual(row["availability"], "in_stock")
        self.assertEqual(row["tax_basis"], "NOT_STATED")
        self.assertEqual(row["attributes"], "")
        self.assertIn("attributes", json.loads(row["missing_reasons"]))

    def test_multi_variant_options_and_out_of_stock(self):
        row = build_valid_row(
            product=product(
                options=[{"name": "Size", "values": ["S", "M"]}],
                variants=[
                    {"price": "29.00", "available": False},
                    {"price": "35.00", "available": True},
                ],
            ),
            source_url="https://javaestate.com/products/example-product",
            task_id="task-1",
            extracted_at="2026-11-19T00:00:00Z",
        )
        self.assertEqual(row["availability"], "in_stock")
        self.assertEqual(row["attributes"], "Size#S|M")

    def test_missing_category_brand_image_are_recorded(self):
        row = build_valid_row(
            product=product(product_type="", vendor="BYOB"),
            source_url="https://javaestate.com/products/example-product",
            task_id="task-1",
            extracted_at="2026-11-19T00:00:00Z",
        )
        missing = json.loads(row["missing_reasons"])
        self.assertEqual(missing["category"], "not_provided")
        self.assertEqual(missing["brand"], "not_provided")


class CsvTests(unittest.TestCase):
    def test_csv_roundtrip_preserves_commas_quotes_newlines_chinese(self):
        row = {field: "" for field in CSV_FIELDS}
        row.update(
            {
                "name": '中文, "引号" 商品',
                "price_amount": "12.50",
                "description_html": "<p>第一行, 含逗号</p>\n<p>第二行</p>",
                "missing_reasons": '{"brand":"not_provided"}',
            }
        )
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, lineterminator="\r\n")
        writer.writeheader()
        writer.writerow({k: csv_safe(v) for k, v in row.items()})
        parsed = list(csv.DictReader(io.StringIO(buffer.getvalue())))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["name"], '中文, "引号" 商品')
        self.assertEqual(parsed[0]["description_html"], "<p>第一行, 含逗号</p>\n<p>第二行</p>")
        self.assertEqual(parsed[0]["missing_reasons"], '{"brand":"not_provided"}')

    def test_formula_prefix_is_guarded(self):
        self.assertEqual(csv_safe("=SUM(A1)"), "'=SUM(A1)")
        self.assertEqual(csv_safe("-1"), "'-1")
        self.assertEqual(csv_safe("12.50"), "12.50")


if __name__ == "__main__":
    unittest.main()
