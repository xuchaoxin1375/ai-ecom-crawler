"""Contract checks for the skatepro Scrapling plan (no network)."""

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

from skatepro_scraper.config import CSV_COLUMNS  # noqa: E402
from skatepro_scraper.export import write_csv  # noqa: E402
from skatepro_scraper.normalize import (  # noqa: E402
    build_options,
    clean_name,
    format_amount,
    sanitize_description,
    serialize_options,
    to_decimal,
)


class PriceTests(unittest.TestCase):
    def test_numeric_and_es_text(self) -> None:
        self.assertEqual(str(to_decimal(69.95)), "69.95")
        self.assertEqual(str(to_decimal("69,95 €")), "69.95")
        self.assertEqual(str(to_decimal("1.234,50 €")), "1234.50")

    def test_rejects_garbage_and_keeps_sign_for_the_caller(self) -> None:
        for value in ("", None, True, "n/a", "NaN", "Infinity"):
            self.assertIsNone(to_decimal(value), value)
        # Non-positive amounts are filtered by the extractor, not by the parser.
        self.assertEqual(str(to_decimal(0)), "0")
        self.assertEqual(str(to_decimal(-1)), "-1")

    def test_format_amount(self) -> None:
        self.assertEqual(format_amount("14.9"), "14.90")
        self.assertEqual(format_amount(""), "")


class NameTests(unittest.TestCase):
    def test_strips_only_site_domain(self) -> None:
        self.assertEqual(clean_name("SkatePro Camiseta | skatepro.es"), "SkatePro Camiseta")
        self.assertEqual(clean_name("SkatePro Camiseta"), "SkatePro Camiseta")


class DescriptionTests(unittest.TestCase):
    def test_removes_unsafe_markup_and_keeps_tables(self) -> None:
        raw = (
            '<div class="x"><script>alert(1)</script><p>Hola <a href="https://x.test">link</a></p>'
            "<table><tr><th>Talla</th><td>M</td></tr></table><img src='x.jpg'></div>"
        )
        cleaned = sanitize_description(raw)
        for tag in ("<script", "<a ", "<img", 'class="x"'):
            self.assertNotIn(tag, cleaned)
        self.assertIn("link", cleaned)
        self.assertIn("<table>", cleaned)
        self.assertIn("M", cleaned)

    def test_empty_after_cleaning(self) -> None:
        self.assertEqual(sanitize_description("<div><script>x</script></div>"), "")


class OptionTests(unittest.TestCase):
    def test_union_across_variants(self) -> None:
        variants = [
            {"attribute_text": {"4": "Color", "2": "Talla"}, "attribute_variant_text": {"4": "Negro", "2": "S"}},
            {"attribute_text": {"4": "Color", "2": "Talla"}, "attribute_variant_text": {"4": "Blanco", "2": "M"}},
        ]
        self.assertEqual(build_options(variants), [("Color", ["Negro", "Blanco"]), ("Talla", ["S", "M"])])

    def test_quantity_dimension_is_skipped(self) -> None:
        variants = [{"attribute_text": {"9": "Cantidad"}, "attribute_variant_text": {"9": "1"}}]
        self.assertEqual(build_options(variants), [])

    def test_serialization_escapes_reserved_characters(self) -> None:
        text = serialize_options([("Size", ["S|M", "A#B", "C~D", "E\\F"])])
        self.assertEqual(text, "Size#S\\|M|A\\#B|C\\~D|E\\\\F")


class CsvTests(unittest.TestCase):
    def test_nine_columns_and_round_trip(self) -> None:
        row = {column: "" for column in CSV_COLUMNS}
        row.update(
            {
                "name": '名称, "quoted"',
                "price_amount": "0.95",
                "price_currency": "EUR",
                "description_html": "<p>Primera línea</p>\n<p>second, line</p>",
                "source_url": "https://www.skatepro.es/1-2.htm",
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
        self.assertEqual(rows[0]["description_html"], "<p>Primera línea</p>\n<p>second, line</p>")

    def test_formula_protection_keeps_price_numeric(self) -> None:
        row = {column: "" for column in CSV_COLUMNS}
        row.update({"name": "=CMD()", "price_amount": "1.00", "source_url": "https://www.skatepro.es/1-2.htm"})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "valid.csv"
            write_csv(path, [row])
            with path.open(encoding="utf-8", newline="") as handle:
                parsed = next(csv.DictReader(handle))
        self.assertEqual(parsed["name"], "'=CMD()")
        self.assertEqual(parsed["price_amount"], "1.00")


class TaskResultTests(unittest.TestCase):
    def test_counts_invariants_hold_for_published_run(self) -> None:
        result_path = ROOT / "task-result.json"
        if not result_path.exists():
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
        self.assertEqual(counts["in_flight_products"], 0)


if __name__ == "__main__":
    unittest.main()
