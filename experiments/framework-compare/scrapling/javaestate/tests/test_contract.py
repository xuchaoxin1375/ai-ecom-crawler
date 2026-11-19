"""Contract checks for the javaestate Scrapling plan (no network)."""

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

from javaestate_scraper.config import CSV_COLUMNS  # noqa: E402
from javaestate_scraper.export import write_csv  # noqa: E402
from javaestate_scraper.extract import _description  # noqa: E402
from javaestate_scraper.normalize import (  # noqa: E402
    build_options,
    clean_name,
    format_amount,
    parse_positive_money,
    sanitize_description,
    serialize_options,
    tax_basis_from_variants,
)


class PriceTests(unittest.TestCase):
    def test_positive_plain_and_thousands(self) -> None:
        self.assertEqual(str(parse_positive_money("25.49")), "25.49")
        self.assertEqual(str(parse_positive_money("1,234.50")), "1234.50")
        self.assertEqual(str(parse_positive_money("1.234,50")), "1234.50")

    def test_rejects_zero_negative_and_ambiguous(self) -> None:
        for value in ("0", "0.00", "-3.00", "", None, True, "NaN", "Infinity", "1,234"):
            self.assertIsNone(parse_positive_money(value), value)

    def test_cents_format(self) -> None:
        self.assertEqual(format_amount("25.4"), "25.40")
        self.assertEqual(format_amount(""), "")


class TaxBasisTests(unittest.TestCase):
    def test_only_false_taxable_becomes_no_tax(self) -> None:
        self.assertEqual(tax_basis_from_variants([{"taxable": False}])[0], "no_tax_applied")
        self.assertEqual(tax_basis_from_variants([{"taxable": True}])[0], "unknown_not_stated")
        self.assertEqual(
            tax_basis_from_variants([{"taxable": True}, {"taxable": False}])[0], "mixed_taxability"
        )
        self.assertEqual(tax_basis_from_variants([])[0], "unknown_not_stated")


class NameTests(unittest.TestCase):
    def test_strips_only_explicit_site_suffix(self) -> None:
        self.assertEqual(clean_name("Ghirardelli Sauce Pump | Java Estate Roastery"), "Ghirardelli Sauce Pump")
        self.assertEqual(clean_name("Java Estate Blend"), "Java Estate Blend")


class DescriptionTests(unittest.TestCase):
    def test_removes_unsafe_markup_and_keeps_tables(self) -> None:
        raw = (
            '<div class="x"><script>alert(1)</script><p>Hello <a href="https://x.test">link</a></p>'
            "<table><tr><th>Size</th><td>3.2 lb</td></tr></table><img src='x.jpg'></div>"
        )
        cleaned = sanitize_description(raw)
        self.assertNotIn("<script", cleaned)
        self.assertNotIn("<a ", cleaned)
        self.assertNotIn("<img", cleaned)
        self.assertIn("link", cleaned)
        self.assertIn("<table>", cleaned)
        self.assertIn("3.2 lb", cleaned)

    def test_plain_text_format(self) -> None:
        self.assertEqual(sanitize_description("Hello &amp; welcome\nworld", fmt="text"), "Hello & welcome world")


class _Node:
    def __init__(self, html: str) -> None:
        self.html_content = html
        self.attrib: dict[str, str] = {}

    def get_all_text(self, strip: bool = True) -> str:
        return self.html_content


class _MetaNode:
    def __init__(self, content: str) -> None:
        self.attrib = {"content": content}


class _FakePage:
    def __init__(self, dom: str = "", meta: str = "") -> None:
        self.dom = dom
        self.meta = meta

    def css(self, selector: str):
        if selector == ".product__description":
            return [_Node(self.dom)] if self.dom else []
        if selector.startswith("meta["):
            return [_MetaNode(self.meta)] if self.meta else []
        return []


class DescriptionStatusTests(unittest.TestCase):
    def test_complete_when_dom_matches_embedded(self) -> None:
        page = _FakePage(dom="<p>Full body text for this product.</p>")
        html, fmt, status, reason = _description(page, {"description": "<p>Full body text for this product.</p>"})
        self.assertEqual((fmt, status, reason), ("html", "complete", ""))
        self.assertIn("Full body", html)

    def test_partial_when_embedded_only(self) -> None:
        page = _FakePage()
        _html, _fmt, status, reason = _description(page, {"description": "<p>Full body text.</p>"})
        self.assertEqual(status, "partial")
        self.assertIn("embedded product JSON", reason)

    def test_partial_when_dom_is_materially_shorter(self) -> None:
        page = _FakePage(dom="<p>Short.</p>")
        _html, _fmt, status, reason = _description(
            page, {"description": "<p>" + "Long body text. " * 20 + "</p>"}
        )
        self.assertEqual(status, "partial")
        self.assertIn("shorter", reason)

    def test_fallback_to_meta_text(self) -> None:
        page = _FakePage(meta="Short summary only.")
        html, fmt, status, _reason = _description(page, None)
        self.assertEqual((fmt, status), ("text", "fallback"))
        self.assertEqual(html, "Short summary only.")

    def test_not_provided(self) -> None:
        _html, fmt, status, _reason = _description(_FakePage(), None)
        self.assertEqual((fmt, status), ("", "not_provided"))

    def test_failed_when_source_cleans_to_nothing(self) -> None:
        page = _FakePage(dom="<p></p>")
        _html, fmt, status, reason = _description(page, {"description": "<img src='x.jpg'>"})
        self.assertEqual((fmt, status), ("", "failed"))
        self.assertIn("cleaning produced no content", reason)


class OptionTests(unittest.TestCase):
    def test_embedded_variants_and_quantity_exclusion(self) -> None:
        options = build_options(
            ["Size", "Color", "Quantity"],
            [
                {"option1": "S", "option2": "Red", "option3": "1"},
                {"option1": "M", "option2": "Blue", "option3": "2"},
            ],
        )
        self.assertEqual(options, [("Size", ["S", "M"]), ("Color", ["Red", "Blue"])])

    def test_default_title_is_not_an_option(self) -> None:
        self.assertEqual(build_options(["Title"], [{"option1": "Default Title"}]), [])

    def test_serialization_escapes_reserved_characters(self) -> None:
        text = serialize_options([("Size", ["S|M", "A#B", "C~D", "E\\F"])])
        self.assertEqual(text, "Size#S\\|M|A\\#B|C\\~D|E\\\\F")


class CsvTests(unittest.TestCase):
    def test_22_columns_and_round_trip(self) -> None:
        row = {column: "" for column in CSV_COLUMNS}
        row.update(
            {
                "name": '名称, "quoted"',
                "price_amount": "25.49",
                "price_currency": "USD",
                "description_html": "<p>第一行</p>\n<p>second, line</p>",
                "source_url": "https://javaestate.com/products/example",
                "description_status": "complete",
                "missing_reasons": json.dumps({"brand": "not_provided"}, ensure_ascii=False),
                "extracted_at": "2026-11-19T00:00:00Z",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "valid.csv"
            write_csv(path, [row])
            with path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, CSV_COLUMNS)
                rows = list(reader)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["name"], '名称, "quoted"')
            self.assertEqual(rows[0]["description_html"], "<p>第一行</p>\n<p>second, line</p>")
            self.assertEqual(json.loads(rows[0]["missing_reasons"]), {"brand": "not_provided"})

    def test_formula_protection(self) -> None:
        row = {column: "" for column in CSV_COLUMNS}
        row.update({"name": "=CMD()", "price_amount": "1.00", "source_url": "https://javaestate.com/products/x"})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "valid.csv"
            write_csv(path, [row])
            with path.open(encoding="utf-8", newline="") as handle:
                parsed = next(csv.DictReader(handle))
        self.assertEqual(parsed["name"], "'=CMD()")
        self.assertEqual(parsed["price_amount"], "1.00")


if __name__ == "__main__":
    unittest.main()
