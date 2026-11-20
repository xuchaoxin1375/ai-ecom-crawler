"""Extraction tests for the R06 declarative executor; no network access."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from executor.extract import ExtractedProduct, HtmlPage, extract_field, extract_product
from executor.normalize import clean_description, parse_number, serialize_option_groups


def make_plan(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "site": {"name": "Shop", "locale": "en-US", "currency": "USD"},
        "extract": {"fields": fields},
        "validate": {"required_fields": ["name"], "assertions": []},
    }


def name_field() -> dict[str, Any]:
    return {
        "fallbacks": [
            {"type": "json_ld", "path": "name", "label": "json_ld"},
            {"type": "css_text", "selector": 'h1[itemprop="name"]', "label": "h1_itemprop"},
            {"type": "css_text", "selector": "h1", "label": "h1"},
            {
                "type": "css_attr",
                "selector": 'meta[property="og:title"]',
                "attr": "content",
                "label": "og_title",
                "strip_site_suffix": True,
            },
            {"type": "title", "label": "title"},
        ]
    }


class NameTests(unittest.TestCase):
    def test_h1_wins_over_title(self) -> None:
        page = HtmlPage(
            "<html><head><title>Product - Shop</title></head><body><h1>Product H1</h1></body></html>",
            "https://example.test/p",
        )
        hit = extract_field(page, "name", name_field(), make_plan({}))
        assert hit is not None
        self.assertEqual(hit.value, "Product H1")
        self.assertEqual(hit.source, "h1")

    def test_title_fallback_strips_site_name(self) -> None:
        page = HtmlPage(
            "<html><head><title>Product - Shop</title>"
            '<meta property="og:site_name" content="Shop"></head><body></body></html>',
            "https://example.test/p",
        )
        hit = extract_field(page, "name", name_field(), make_plan({}))
        assert hit is not None
        self.assertEqual(hit.value, "Product")
        self.assertEqual(hit.source, "title")


class JsonLdTests(unittest.TestCase):
    def test_offers_list_min_positive(self) -> None:
        page = HtmlPage(
            "<html><head><script type='application/ld+json'>"
            '{"@context":"https://schema.org","@type":"Product","name":"P",'
            '"offers":[{"price":"29.00","priceCurrency":"USD"},'
            '{"price":"24.17","priceCurrency":"USD"}],'
            '"image":"https://example.test/i.jpg"}'
            "</script></head><body></body></html>",
            "https://example.test/p",
        )
        plan = make_plan(
            {
                "name": {"fallbacks": [{"type": "json_ld", "path": "name"}]},
                "price.amount": {
                    "fallbacks": [
                        {
                            "type": "json_ld",
                            "path": "offers.price",
                            "take": "min_positive",
                        }
                    ]
                },
                "price.currency": {
                    "fallbacks": [{"type": "json_ld", "path": "offers.priceCurrency"}]
                },
                "primary_image_url": {
                    "fallbacks": [{"type": "json_ld", "path": "image"}]
                },
                "source_url": {"fallbacks": [{"type": "canonical"}]},
            }
        )
        product = extract_product(page, plan)
        self.assertEqual(product.values["name"], "P")
        self.assertEqual(product.values["price.amount"], 24.17)
        self.assertEqual(product.values["price.currency"], "USD")
        self.assertEqual(product.values["primary_image_url"], "https://example.test/i.jpg")


class PriceTests(unittest.TestCase):
    def test_price_pair_chooses_pretax(self) -> None:
        page = HtmlPage(
            "<html><head>"
            '<meta property="product:price:amount" content="615">'
            '<meta property="product:pretax_price:amount" content="512.5">'
            '<meta property="product:price:currency" content="EUR">'
            "</head><body></body></html>",
            "https://example.test/p",
        )
        plan = make_plan(
            {
                "price.amount": {
                    "fallbacks": [
                        {
                            "type": "price_pair",
                            "gross": {
                                "selector": 'meta[property="product:price:amount"]',
                                "attr": "content",
                            },
                            "pretax": {
                                "selector": 'meta[property="product:pretax_price:amount"]',
                                "attr": "content",
                            },
                        }
                    ]
                },
                "price.currency": {
                    "fallbacks": [
                        {
                            "type": "css_attr",
                            "selector": 'meta[property="product:price:currency"]',
                            "attr": "content",
                        }
                    ]
                },
            }
        )
        product = extract_product(page, plan)
        self.assertEqual(product.values["price.amount"], 512.5)
        self.assertEqual(product.values["price.currency"], "EUR")
        self.assertEqual(product.extras["price.amount"]["basis"], "exclusive")
        self.assertEqual(product.extras["price.amount"]["displayed"], 615.0)
        self.assertEqual(product.extras["price.amount"]["pretax"], 512.5)

    def test_price_pair_gross_only(self) -> None:
        page = HtmlPage(
            "<html><head>"
            '<meta property="product:price:amount" content="39">'
            "</head><body></body></html>",
            "https://example.test/p",
        )
        plan = make_plan(
            {
                "price.amount": {
                    "fallbacks": [
                        {
                            "type": "price_pair",
                            "gross": {
                                "selector": 'meta[property="product:price:amount"]',
                                "attr": "content",
                            },
                            "pretax": {
                                "selector": 'meta[property="product:pretax_price:amount"]',
                                "attr": "content",
                            },
                        }
                    ]
                }
            }
        )
        product = extract_product(page, plan)
        self.assertEqual(product.values["price.amount"], 39.0)
        self.assertEqual(product.extras["price.amount"]["basis"], "inclusive")


class CategoryTests(unittest.TestCase):
    def test_breadcrumb_drops_last_and_home(self) -> None:
        page = HtmlPage(
            '<nav class="breadcrumb_nav">'
            '<span itemprop="name">Accueil</span>'
            '<span itemprop="name">Poussettes</span>'
            '<span itemprop="name">Product</span>'
            "</nav>",
            "https://example.test/p",
        )
        field = {
            "fallbacks": [
                {
                    "type": "breadcrumb",
                    "selector": 'nav.breadcrumb_nav span[itemprop="name"]',
                    "drop_last": True,
                    "exclude": ["accueil", "home"],
                }
            ]
        }
        hit = extract_field(page, "category", field, make_plan({}))
        assert hit is not None
        self.assertEqual(hit.value, "Poussettes")


class OptionTests(unittest.TestCase):
    def test_options_serialize_and_drop_quantity(self) -> None:
        page = HtmlPage(
            '<div class="product-variants">'
            '<div class="product-variants-item"><label>Size</label>'
            '<select><option>S</option><option>M</option><option></option></select></div>'
            '<div class="product-variants-item"><label>Quantity</label>'
            '<select><option>1</option><option>2</option></select></div>'
            '<div class="product-variants-item"><label>Color</label>'
            '<select><option>Red +$2.00</option><option>Blue</option></select></div>'
            "</div>",
            "https://example.test/p",
        )
        field = {
            "fallbacks": [
                {
                    "type": "option_groups",
                    "group_selector": "div.product-variants .product-variants-item",
                    "label_selector": "label",
                    "option_selector": "select option",
                }
            ]
        }
        hit = extract_field(page, "options", field, make_plan({}))
        assert hit is not None
        self.assertEqual(hit.value, "Size#S|M~Color#Red|Blue")

    def test_serialize_escapes_reserved_characters(self) -> None:
        self.assertEqual(
            serialize_option_groups([("Size", ["S|M", "A#B", "C~D"])]),
            r"Size#S\|M|A\#B|C\~D",
        )


class DescriptionTests(unittest.TestCase):
    def test_clean_removes_read_more_and_scripts(self) -> None:
        raw = (
            '<div class="product_description_container">'
            "<p>Hello <a class='st_read_more'>Lire la suite</a></p>"
            "<script>bad()</script>"
            "<ul><li>Spec</li><li></li></ul>"
            "</div>"
        )
        cleaned = clean_description(raw)
        self.assertIn("Hello", cleaned)
        self.assertIn("Spec", cleaned)
        self.assertNotIn("Lire la suite", cleaned)
        self.assertNotIn("bad()", cleaned)
        self.assertNotIn("<script", cleaned)

    def test_plain_text_description_is_wrapped(self) -> None:
        cleaned = clean_description("Line one.\n\nLine two.")
        self.assertEqual(cleaned, "<p>Line one.</p><p>Line two.</p>")

    def test_comments_are_removed(self) -> None:
        cleaned = clean_description("<p>Hello<!-- tracking --> world</p>")
        self.assertIn("Hello", cleaned)
        self.assertIn("world", cleaned)
        self.assertNotIn("tracking", cleaned)

    def test_short_description_marks_partial(self) -> None:
        page = HtmlPage(
            '<div class="product-description-short"><p>Short copy.</p></div>',
            "https://example.test/p",
        )
        plan = make_plan(
            {
                "description_html": {
                    "fallbacks": [
                        {
                            "type": "css_html",
                            "selector": "div.product-description-short",
                            "description_status": "partial",
                        }
                    ]
                }
            }
        )
        product = extract_product(page, plan)
        self.assertEqual(product.description_status, "partial")
        self.assertIn("Short copy", product.values["description_html"])
        self.assertIsNotNone(product.partial_reason)


class MissingValueTests(unittest.TestCase):
    def test_brand_is_not_inferred(self) -> None:
        page = HtmlPage("<h1>Brand Name Product</h1>", "https://example.test/p")
        plan = make_plan(
            {
                "name": {"fallbacks": [{"type": "css_text", "selector": "h1"}]},
                "brand": {
                    "fallbacks": [{"type": "css_text", "selector": "div.manufacturer a"}]
                },
            }
        )
        product = extract_product(page, plan)
        self.assertEqual(product.values["brand"], "")
        self.assertEqual(product.missing_reasons["brand"], "NOT_PROVIDED")

    def test_currency_is_not_guessed(self) -> None:
        page = HtmlPage("<h1>Product</h1>", "https://example.test/p")
        plan = make_plan(
            {
                "name": {"fallbacks": [{"type": "css_text", "selector": "h1"}]},
                "price.currency": {
                    "fallbacks": [
                        {
                            "type": "css_attr",
                            "selector": 'meta[property="product:price:currency"]',
                            "attr": "content",
                        }
                    ]
                },
            }
        )
        product = extract_product(page, plan)
        self.assertEqual(product.values["price.currency"], "")


class NumberTests(unittest.TestCase):
    def test_locale_and_machine_numbers(self) -> None:
        self.assertEqual(parse_number("1 234,56 €", locale="fr-FR", machine=False), 1234.56)
        self.assertEqual(parse_number("1,234.56", locale="en-US", machine=True), 1234.56)
        self.assertEqual(parse_number("615.000000", locale="fr-FR", machine=True), 615.0)
        self.assertEqual(parse_number("1.234,56", locale="de-DE", machine=True), 1234.56)
        self.assertIsNone(parse_number("0"))
        self.assertIsNone(parse_number("-1"))
        self.assertIsNone(parse_number("NaN"))


class ExtractedProductHelperTests(unittest.TestCase):
    def test_helper_dataclass(self) -> None:
        product = ExtractedProduct(
            values={"price.amount": 1.0},
            sources={},
            extras={},
            description_status="complete",
            partial_reason=None,
            missing_reasons={},
        )
        self.assertEqual(product.price_amount, 1.0)


if __name__ == "__main__":
    unittest.main()
