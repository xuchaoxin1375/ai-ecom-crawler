"""Fixture tests for the deterministic rules (docs/02, A01/A02/A04/A14).

Fixtures are small synthetic fragments; no site page is stored.
"""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lxml import html as lxml_html  # noqa: E402

from skatepro.normalize import (  # noqa: E402
    build_description,
    clean_html_fragment,
    collect_options,
    csv_safe,
    currency_evidence,
    lowest_positive_variant_price,
    product_offers,
    serialize_options,
)


class PriceTests(unittest.TestCase):
    def test_lowest_positive_variant_including_unavailable(self):
        amount, reason, details = lowest_positive_variant_price(
            [
                {"price_number": 35.0, "stock_level": "green"},
                {"price_number": 29.0, "stock_level": "red"},
            ]
        )
        self.assertEqual(amount, Decimal("29.00"))
        self.assertIsNone(reason)
        self.assertEqual(details["variant_count"], 2)

    def test_zero_price_is_excluded_not_zeroed(self):
        amount, reason, _ = lowest_positive_variant_price([{"price_number": 0}])
        self.assertIsNone(amount)
        self.assertEqual(reason, "non_positive_price")

    def test_invalid_price_is_reported(self):
        amount, reason, details = lowest_positive_variant_price([{"price_number": "n/a"}])
        self.assertIsNone(amount)
        self.assertEqual(reason, "invalid_price")
        self.assertEqual(details["invalid_variant_prices"], ["n/a"])


class OptionTests(unittest.TestCase):
    def test_single_value_dimension_is_not_an_option(self):
        variants = [
            {
                "attribute_text": {"4": "Color", "2": "Talla"},
                "attribute_variant_text": {"4": "Negro", "2": "S"},
            },
            {
                "attribute_text": {"4": "Color", "2": "Talla"},
                "attribute_variant_text": {"4": "Negro", "2": "M"},
            },
        ]
        groups, skipped = collect_options(variants)
        self.assertEqual([g["name"] for g in groups], ["Talla"])
        self.assertIn("Color", skipped)
        self.assertEqual(serialize_options(groups), "Talla#S|M")

    def test_serialization_escapes_reserved_characters(self):
        groups = [{"name": "Color", "values": ["Red|Blue", "A#B"]}]
        self.assertEqual(serialize_options(groups), "Color#Red\\|Blue|A\\#B")


class DescriptionTests(unittest.TestCase):
    def test_clean_html_keeps_structure_and_drops_active_content(self):
        raw = (
            '<p onclick="x()">Texto <a href="/x">enlace</a></p>'
            '<script>alert(1)</script><img src="x.webp">'
            '<table><tr><td colspan="2">A</td></tr></table>'
        )
        cleaned = clean_html_fragment(raw)
        self.assertIn("<p>Texto enlace</p>", cleaned)
        self.assertIn('<td colspan="2">A</td>', cleaned)
        self.assertNotIn("<script", cleaned)
        self.assertNotIn("<img", cleaned)
        self.assertNotIn("onclick", cleaned)

    def test_bare_urls_are_removed(self):
        cleaned = clean_html_fragment("<p>Ver https://example.com/a para más</p>")
        self.assertNotIn("https://", cleaned)

    def test_status_complete_when_description_and_specs_exist(self):
        doc = lxml_html.fromstring(
            '<html><body><div id="product_description"><p>Texto</p></div>'
            '<div id="product_specifications">'
            '<div class="row"><div class="columns">Peso:</div><div class="columns">1kg</div></div>'
            "</div></body></html>"
        )
        description, status, reason, details = build_description(doc)
        self.assertEqual(status, "complete")
        self.assertEqual(reason, "")
        self.assertIn("<table>", description)
        self.assertEqual(details["spec_rows"], 1)

    def test_status_not_provided_when_sections_are_absent(self):
        doc = lxml_html.fromstring("<html><body><h1>Solo título</h1></body></html>")
        description, status, _, _ = build_description(doc)
        self.assertEqual(description, "")
        self.assertEqual(status, "not_provided")


class CsvTests(unittest.TestCase):
    def test_formula_guard_only_touches_text(self):
        self.assertEqual(csv_safe("=1+1"), "'=1+1")
        self.assertEqual(csv_safe("69.95"), "69.95")


class ProductGroupTests(unittest.TestCase):
    def test_product_group_offers_are_collected_from_variants(self):
        group = {
            "@type": "ProductGroup",
            "hasVariant": [
                {"offers": {"price": 8.95, "priceCurrency": "EUR"}},
                {"offers": {"price": 9.95, "priceCurrency": "EUR"}},
            ],
        }
        offers = product_offers(group)
        self.assertEqual(len(offers), 2)
        self.assertEqual({o["priceCurrency"] for o in offers}, {"EUR"})

    def test_mixed_currencies_are_not_accepted(self):
        doc = lxml_html.fromstring("<html><body></body></html>")
        group = {
            "@type": "ProductGroup",
            "hasVariant": [
                {"offers": {"price": 8.95, "priceCurrency": "EUR"}},
                {"offers": {"price": 9.95, "priceCurrency": "GBP"}},
            ],
        }
        code, _ = currency_evidence(doc, group)
        self.assertEqual(code, "")


if __name__ == "__main__":
    unittest.main()
