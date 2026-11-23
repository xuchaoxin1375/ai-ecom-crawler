"""Offline contract checks for the S6 campsaver extraction plan."""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from lxml import html as LH

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
EVIDENCE_ROOT = Path(os.environ.get("ECOM_EVIDENCE_ROOT", REPO_ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run  # noqa: E402


class JsonLdTests(unittest.TestCase):
    def test_strict_false_accepts_literal_newline(self) -> None:
        raw = '{"@type":"Product","name":"A","description":"line one\nline two"}'
        doc = LH.fromstring(f'<script type="application/ld+json">{raw}</script>')
        blocks = run.parse_jsonld(doc)
        self.assertEqual(blocks[0]["description"], "line one\nline two")

    def test_find_product_in_graph(self) -> None:
        payload = {"@graph": [{"@type": "Product", "name": "A"}, {"@type": "WebPage"}]}
        self.assertEqual([item["name"] for item in run.find_products(payload)], ["A"])

    def test_offer_summary_min_and_conditions(self) -> None:
        offers = [
            {"price": "249.95", "priceCurrency": "USD", "availability": "https://schema.org/BackOrder", "itemCondition": "https://schema.org/NewCondition", "sku": "A"},
            {"price": "219.95", "priceCurrency": "USD", "availability": "https://schema.org/InStock", "itemCondition": "https://schema.org/NewCondition", "sku": "B"},
        ]
        summary = run.offer_summary(offers)
        self.assertEqual(summary["price"], 219.95)
        self.assertEqual(summary["currency"], "USD")
        self.assertIn("https://schema.org/InStock", summary["availability"])
        self.assertEqual(summary["skus"], ["A", "B"])

    def test_offer_summary_skips_zero(self) -> None:
        self.assertIsNone(run.offer_summary([{"price": "0", "priceCurrency": "USD"}])["price"])


class DescriptionTests(unittest.TestCase):
    def test_cleans_html_and_decodes_entities(self) -> None:
        cleaned, status = run.clean_html("<p>Tom &amp; Jerry&#039;s pad</p><script>x()</script>")
        self.assertEqual(status, "complete")
        text = LH.fromstring(cleaned).text_content()
        self.assertIn("Tom & Jerry's pad", text)
        self.assertNotIn("<script", cleaned)

    def test_jsonld_description_is_complete(self) -> None:
        product = {"description": "<p>" + "A" * 100 + "</p>"}
        doc = LH.fromstring("<html></html>")
        _, status, reason = run.parse_description(product, doc, "Pad")
        self.assertEqual(status, "complete")
        self.assertIsNone(reason)

    def test_empty_description(self) -> None:
        doc = LH.fromstring("<html></html>")
        self.assertEqual(run.parse_description({}, doc, "Pad"), ("", "not_provided", None))


class BreadcrumbTests(unittest.TestCase):
    def test_dedupes_and_uses_last_category(self) -> None:
        html = """
        <div class="breadcrumb"><a href="/">Home</a><a href="/brand">Brand</a>
        <a href="/camp">Camp & Hike</a><a href="/pads">Pads</a><a href="/sleeping">Sleeping Pads</a></div>
        """
        doc = LH.fromstring(html)
        self.assertEqual(run.parse_breadcrumbs(doc), ["Brand", "Camp & Hike", "Pads", "Sleeping Pads"])


class VariantTests(unittest.TestCase):
    def test_differential_options_with_uom(self) -> None:
        payload = {
            "variantSelector": {
                "variants": [
                    {
                        "specifications": [
                            {
                                "name": "Length",
                                "is_differential": True,
                                "values": [{"value": "72", "uom": "in"}, {"value": "78", "uom": "in"}],
                            },
                            {
                                "name": "Color",
                                "is_differential": False,
                                "values": [{"value": "Green", "uom": ""}],
                            },
                        ]
                    }
                ]
            }
        }
        doc = LH.fromstring(
            '<script type="application/json">' + json.dumps(payload) + "</script>"
        )
        attributes, count = run.parse_variant_attributes(doc)
        self.assertEqual(attributes, "Length#72 in|78 in")
        self.assertEqual(count, 1)


class CsvTests(unittest.TestCase):
    def test_nine_columns_and_formula_protection(self) -> None:
        row = {column: "" for column in run.CSV_COLUMNS}
        row.update(
            {
                "name": "=CMD()",
                "price_amount": "189.95",
                "price_currency": "USD",
                "primary_image_url": "https://www.campsaver.com/i/original/x",
                "description_html": "<p>Hello</p>",
                "source_url": "https://www.campsaver.com/x.html",
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
            self.assertEqual(parsed["price_amount"], "189.95")
            self.assertEqual(len(parsed), 9)


class PublishedResultTests(unittest.TestCase):
    def test_counts_if_published(self) -> None:
        result_path = EVIDENCE_ROOT / ROOT.relative_to(REPO_ROOT) / "task-result.json"
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
        self.assertEqual(counts["valid_products"], 30)


if __name__ == "__main__":
    unittest.main()
