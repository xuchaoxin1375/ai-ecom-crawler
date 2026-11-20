"""Contract tests for the familidoo R04 pilot; no network access."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from scrapling.parser import Selector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run


class PriceTests(unittest.TestCase):
    def test_pick_price_prefers_pretax(self) -> None:
        page = Selector(
            content=(
                '<meta property="product:price:amount" content="615">'
                '<meta property="product:pretax_price:amount" content="512.5">'
                '<meta property="product:price:currency" content="EUR">'
            ),
            url="https://example.test/p",
        )
        chosen, currency, basis, displayed, pretax = run.pick_price(page)
        self.assertEqual(chosen, 512.5)
        self.assertEqual(currency, "EUR")
        self.assertEqual(basis, "exclusive")
        self.assertEqual(displayed, 615.0)
        self.assertEqual(pretax, 512.5)

    def test_pick_price_inclusive_when_only_gross(self) -> None:
        page = Selector(
            content=(
                '<meta property="product:price:amount" content="39">'
                '<meta property="product:price:currency" content="EUR">'
            ),
            url="https://example.test/p",
        )
        chosen, currency, basis, _displayed, pretax = run.pick_price(page)
        self.assertEqual(chosen, 39.0)
        self.assertEqual(currency, "EUR")
        self.assertEqual(basis, "inclusive")
        self.assertIsNone(pretax)


class NameTests(unittest.TestCase):
    def test_h1_wins_over_title(self) -> None:
        page = Selector(
            content=(
                "<html><head><title>Product - Shop</title>"
                '<meta property="og:site_name" content="Shop"></head>'
                "<body><h1>Product H1</h1></body></html>"
            ),
            url="https://example.test/p",
        )
        name, source = run.extract_name(page)
        self.assertEqual(name, "Product H1")
        self.assertEqual(source, "h1")

    def test_title_fallback_strips_site_name(self) -> None:
        page = Selector(
            content=(
                "<html><head><title>Product - Shop</title>"
                '<meta property="og:site_name" content="Shop"></head><body></body></html>'
            ),
            url="https://example.test/p",
        )
        name, source = run.extract_name(page)
        self.assertEqual(name, "Product")
        self.assertEqual(source, "title")


class DescriptionTests(unittest.TestCase):
    def test_clean_removes_read_more_and_scripts(self) -> None:
        raw = (
            '<div class="product_description_container">'
            "<p>Hello <a class='st_read_more'>Lire la suite</a></p>"
            "<script>bad()</script>"
            "<ul><li>Spec</li><li></li></ul>"
            "</div>"
        )
        cleaned = run.clean_description(raw)
        self.assertIn("Hello", cleaned)
        self.assertIn("Spec", cleaned)
        self.assertNotIn("Lire la suite", cleaned)
        self.assertNotIn("bad()", cleaned)
        self.assertNotIn("<script", cleaned)


class CsvTests(unittest.TestCase):
    def test_formula_protection(self) -> None:
        self.assertEqual(run.csv_safe("=SUM(A1)"), "'=SUM(A1)")
        self.assertEqual(run.csv_safe("normal"), "normal")


class OptionTests(unittest.TestCase):
    def test_serialize_select_options(self) -> None:
        page = Selector(
            content=(
                '<div class="product-variants">'
                '<div class="product-variants-item">'
                "<label>Size</label>"
                '<select name="size"><option>S</option><option>M</option></select>'
                "</div></div>"
            ),
            url="https://example.test/p",
        )
        self.assertEqual(run.serialize_options(page), "Size#S|M")


class ManifestTests(unittest.TestCase):
    def test_required_keys_present(self) -> None:
        manifest = (Path(__file__).resolve().parents[1] / "manifest.yaml").read_text(encoding="utf-8")
        for key in (
            "schema_version",
            "plan_id",
            "plan_version",
            "kind",
            "status",
            "site",
            "scope",
            "discovery",
            "fetch",
            "extract",
            "normalize",
            "validate",
            "compatibility",
            "evidence",
        ):
            self.assertIn(f"{key}:", manifest)


if __name__ == "__main__":
    unittest.main()
