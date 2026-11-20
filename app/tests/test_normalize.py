from __future__ import annotations

import unittest
from decimal import Decimal

from ecom_crawler.model import RecordIssue
from ecom_crawler.normalize import (
    apply_sales_unit,
    clean_description_html,
    clean_name,
    is_placeholder_image,
    normalize_availability,
    normalize_categories,
    normalize_description,
    normalize_options,
    normalize_source_url,
    parse_price,
    serialize_options,
    text_to_html,
)


class PriceTests(unittest.TestCase):
    def assert_price(self, value: object, expected: str, *, locale: str = "en-GB") -> None:
        amount, reason = parse_price(value, locale=locale)
        self.assertIsNone(reason)
        self.assertEqual(amount, Decimal(expected))

    def test_positive_integer_and_decimal(self) -> None:
        self.assert_price(29, "29")
        self.assert_price(29.0, "29")
        self.assert_price("29.00", "29.00")
        self.assert_price("18.5", "18.5")

    def test_rejects_zero_negative_and_invalid(self) -> None:
        for value, reason in (
            (0, "NON_POSITIVE_PRICE"),
            ("0.00", "NON_POSITIVE_PRICE"),
            (-5, "NON_POSITIVE_PRICE"),
            ("-1.20", "NON_POSITIVE_PRICE"),
            (None, "MISSING_PRICE"),
            ("", "MISSING_PRICE"),
            ("abc", "INVALID_PRICE"),
            (True, "INVALID_PRICE"),
            (float("nan"), "INVALID_PRICE"),
            (float("inf"), "INVALID_PRICE"),
        ):
            amount, actual = parse_price(value, locale="en-GB")
            self.assertIsNone(amount, msg=value)
            self.assertEqual(actual, reason, msg=value)

    def test_locale_decimal_and_grouping(self) -> None:
        self.assert_price("1,234.56", "1234.56", locale="en-US")
        self.assert_price("1.234,56", "1234.56", locale="de-DE")
        self.assert_price("24,17", "24.17", locale="fr-FR")
        self.assert_price("1.234", "1234", locale="de-DE")
        self.assert_price("1.234", "1.234", locale="en-US")
        self.assert_price("1,234", "1234", locale="en-US")
        self.assert_price("1,234", "1.234", locale="fr-FR")

    def test_currency_symbols_and_spaces(self) -> None:
        self.assert_price("£1,234.56", "1234.56", locale="en-GB")
        self.assert_price("1 234,56 €", "1234.56", locale="fr-FR")
        self.assert_price("1'234.56", "1234.56", locale="en-GB")
        self.assert_price("USD 1,234.56", "1234.56", locale="en-US")

    def test_ambiguous_single_separator_without_locale(self) -> None:
        for value in ("1,234", "1.234"):
            amount, reason = parse_price(value, locale="")
            self.assertIsNone(amount)
            self.assertEqual(reason, "AMBIGUOUS_PRICE")

    def test_malformed_grouping(self) -> None:
        for value in ("1,2,3", "1..2", "1,234."):
            amount, reason = parse_price(value, locale="en-GB")
            self.assertIsNone(amount)
            self.assertIn(reason, {"INVALID_PRICE", "AMBIGUOUS_PRICE"}, msg=value)


class TextTests(unittest.TestCase):
    def test_clean_html_keeps_structure_and_drops_unsafe_nodes(self) -> None:
        raw = (
            '<p class="lead" data-id="1">Hello <a href="/x">world</a></p>'
            "<script>alert(1)</script><img src=\"x\">"
            '<div class="read-more">more</div><p></p>'
        )
        self.assertEqual(clean_description_html(raw), "<p>Hello world</p>")

    def test_clean_html_preserves_tables_and_lists(self) -> None:
        raw = "<p>Copy</p><ul><li>One</li></ul><table><tr><td>A</td><td>B</td></tr></table>"
        self.assertEqual(clean_description_html(raw), raw)

    def test_plain_text_is_wrapped(self) -> None:
        self.assertEqual(
            text_to_html("Line 1\nLine 2\n\n第二段 <tag>"),
            "<p>Line 1<br>Line 2</p><p>第二段 &lt;tag&gt;</p>",
        )
        self.assertEqual(clean_description_html("Plain text"), "<p>Plain text</p>")

    def test_name_strips_host_suffix_only(self) -> None:
        self.assertEqual(
            clean_name("Example Shirt - shop.example", source_url="https://shop.example/p/1"),
            "Example Shirt",
        )
        self.assertEqual(
            clean_name("Example Brand Shirt", source_url="https://shop.example/p/1"),
            "Example Brand Shirt",
        )

    def test_placeholder_image_detection(self) -> None:
        self.assertTrue(is_placeholder_image("https://shop.example/images/none.jpg"))
        self.assertTrue(is_placeholder_image("https://shop.example/images/placeholder.png"))
        self.assertTrue(is_placeholder_image("https://shop.example/images/default-product.jpg"))
        self.assertFalse(is_placeholder_image("https://shop.example/images/thumbnail.jpg"))
        self.assertFalse(is_placeholder_image("https://shop.example/images/shirt.jpg"))


class DescriptionTests(unittest.TestCase):
    def test_blocks_split_product_copy_relations_and_policy(self) -> None:
        description = normalize_description(
            {
                "description": {
                    "status": "COMPLETE",
                    "blocks": [
                        {"kind": "marketing", "html": "<p>Copy</p>"},
                        {
                            "kind": "specs",
                            "html": "<table><tr><td>Weight</td><td>1 kg</td></tr></table>",
                        },
                        {"kind": "compatibility", "html": "<p>Fits A</p>"},
                        {"kind": "policy", "html": "<p>Shipping policy</p>"},
                    ],
                }
            }
        )
        self.assertEqual(
            description.html,
            "<p>Copy</p><table><tr><td>Weight</td><td>1 kg</td></tr></table>",
        )
        self.assertEqual(description.relations[0]["kind"], "compatibility")
        self.assertNotIn("Shipping", description.html)
        self.assertEqual(description.missing_reasons, {})

    def test_missing_description_status_is_rejected(self) -> None:
        with self.assertRaises(RecordIssue) as context:
            normalize_description({"description_html": "<p>Copy</p>"})
        self.assertEqual(context.exception.code, "MISSING_DESCRIPTION_STATUS")

    def test_partial_requires_reason(self) -> None:
        with self.assertRaises(RecordIssue) as context:
            normalize_description(
                {"description_html": "<p>Partial copy</p>", "description_status": "PARTIAL"}
            )
        self.assertEqual(context.exception.code, "PARTIAL_DESCRIPTION_WITHOUT_REASON")

    def test_not_provided_adds_missing_reason(self) -> None:
        description = normalize_description(
            {"description_html": "", "description_status": "NOT_PROVIDED"}
        )
        self.assertEqual(description.html, "")
        self.assertEqual(description.missing_reasons["description_html"], "NOT_PROVIDED")

    def test_summary_fallback_is_marked(self) -> None:
        description = normalize_description(
            {"description_html": "<p>Short summary</p>", "description_status": "SUMMARY_FALLBACK"}
        )
        self.assertEqual(description.status, "SUMMARY_FALLBACK")
        self.assertEqual(
            description.missing_reasons["description_html"], "SUMMARY_FALLBACK"
        )

    def test_complete_with_empty_html_is_a_conflict(self) -> None:
        with self.assertRaises(RecordIssue) as context:
            normalize_description({"description_html": "", "description_status": "COMPLETE"})
        self.assertEqual(context.exception.code, "DESCRIPTION_COMPLETE_BUT_EMPTY")

    def test_complete_with_missing_description_reason_is_a_conflict(self) -> None:
        with self.assertRaises(RecordIssue) as context:
            normalize_description(
                {
                    "description_html": "<p>Copy</p>",
                    "description_status": "COMPLETE",
                    "missing_reasons": {"description_html": "NOT_PROVIDED"},
                }
            )
        self.assertEqual(
            context.exception.code, "DESCRIPTION_COMPLETE_WITH_MISSING_REASON"
        )

    def test_sales_unit_is_prepended_once(self) -> None:
        html = "<p>Product copy.</p>"
        self.assertEqual(
            apply_sales_unit(html, "per lb"),
            "<p>per lb</p><p>Product copy.</p>",
        )
        self.assertEqual(
            apply_sales_unit("<p>Price per lb.</p>", "per lb"),
            "<p>Price per lb.</p>",
        )
        self.assertEqual(apply_sales_unit("", "per lb"), "")


class OptionAndCategoryTests(unittest.TestCase):
    def test_options_merge_and_drop_quantity_and_price_delta(self) -> None:
        groups = normalize_options(
            [
                {"name": "Size", "values": ["S", "s", "M"]},
                {"name": "size", "values": ["L"]},
                {"name": "Quantity", "values": ["1", "2"]},
                {"name": "Color", "values": ["Red +$2.00", "Blue"]},
            ]
        )
        self.assertEqual(
            [(group.name, group.values) for group in groups],
            [("Size", ("S", "M", "L")), ("Color", ("Red", "Blue"))],
        )
        self.assertEqual(serialize_options(groups), "Size#S|M|L~Color#Red|Blue")

    def test_option_serialization_escapes_reserved_characters(self) -> None:
        groups = normalize_options(
            [{"name": "Size#1", "values": ["S|M", "Red~Blue", "back\\slash"]}]
        )
        self.assertEqual(
            serialize_options(groups),
            "Size\\#1#S\\|M|Red\\~Blue|back\\\\slash",
        )

    def test_categories_drop_generic_levels_and_duplicates(self) -> None:
        self.assertEqual(
            normalize_categories(["Home", "Women", "Clothing", "Shirts", "shirts", " Tops "]),
            ("Shirts", "Tops"),
        )

    def test_availability_channel_values_are_not_stock(self) -> None:
        self.assertEqual(normalize_availability("OnlineOnly"), (None, "OnlineOnly"))
        self.assertEqual(normalize_availability("InStoreOnly"), (None, "InStoreOnly"))
        self.assertEqual(
            normalize_availability("OUT_OF_STOCK"), ("OUT_OF_STOCK", "OUT_OF_STOCK")
        )
        self.assertEqual(normalize_availability(None), (None, None))

    def test_source_url_normalization(self) -> None:
        self.assertEqual(
            normalize_source_url("HTTPS://Shop.Example/products/a?x=1#frag"),
            "https://shop.example/products/a?x=1",
        )
        with self.assertRaises(RecordIssue):
            normalize_source_url("javascript:alert(1)")


if __name__ == "__main__":
    unittest.main()
