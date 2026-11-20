"""Offline contract checks for the S5 shopthebulkstore plan."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

from lxml import html as LH

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run  # noqa: E402


class JsonLdTests(unittest.TestCase):
    def test_find_products_in_graph_and_list(self) -> None:
        payload = [
            {"@graph": [{"@type": "Product", "name": "A"}, {"@type": "WebPage"}]},
            [{"@type": ["Product", "Thing"], "name": "B"}],
        ]
        products = run.find_products(payload)
        self.assertEqual([item["name"] for item in products], ["A", "B"])

    def test_select_product_prefers_canonical(self) -> None:
        products = [
            {"name": "Other", "url": "https://shopthebulkstore.com/other"},
            {"name": "Main", "url": "https://shopthebulkstore.com/main", "@id": "...#product"},
        ]
        chosen = run.select_product(products, "https://shopthebulkstore.com/main")
        self.assertEqual(chosen["name"], "Main")

    def test_offer_details_offer_and_aggregate(self) -> None:
        product = {"offers": {"price": "5.99", "priceCurrency": "usd", "availability": "https://schema.org/InStock"}}
        price, currency, availability = run.offer_details(product)
        self.assertEqual((price, currency), (5.99, "USD"))
        self.assertIn("InStock", availability)

        aggregate = {
            "offers": {
                "@type": "AggregateOffer",
                "lowPrice": "4.49",
                "priceCurrency": "USD",
                "availability": "https://schema.org/OutOfStock",
            }
        }
        self.assertEqual(run.offer_details(aggregate)[:2], (4.49, "USD"))

    def test_offer_details_skips_zero_and_missing_currency(self) -> None:
        product = {"offers": [{"price": "0", "priceCurrency": "USD"}, {"price": "3.50"}]}
        self.assertEqual(run.offer_details(product), (None, None, None))


class CleanHtmlTests(unittest.TestCase):
    def test_removes_unsafe_markup_and_keeps_table(self) -> None:
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

    def test_empty(self) -> None:
        self.assertEqual(run.clean_html(""), ("", "not_provided"))
        self.assertEqual(run.clean_html("<script>x</script>"), ("", "failed"))


class DescriptionTests(unittest.TestCase):
    def test_combines_blocks_and_drops_subset(self) -> None:
        html = """
        <div class="product attribute description"><div class="value">
          <p>Product Name</p><p>Price is per lb.</p>
        </div></div>
        <div class="product attribute overview"><div class="value">
          <p>Product Name</p><p>A longer marketing description that stays.</p>
        </div></div>
        """
        doc = LH.fromstring(html)
        cleaned, text, status, reason = run.description_blocks(doc, {}, "Product Name")
        self.assertEqual(status, "complete")
        self.assertIsNone(reason)
        self.assertIn("Price is per lb.", cleaned)
        self.assertIn("A longer marketing description", cleaned)

    def test_name_and_unit_only_is_partial(self) -> None:
        html = """
        <div class="product attribute description"><div class="value">
          <p>Product Name</p><p>Price is per item.</p>
        </div></div>
        """
        doc = LH.fromstring(html)
        _, _, status, reason = run.description_blocks(doc, {}, "Product Name")
        self.assertEqual(status, "partial")
        self.assertTrue(reason)

    def test_jsonld_fallback(self) -> None:
        doc = LH.fromstring("<html><body><h1>Product Name</h1></body></html>")
        product = {"description": "A JSON-LD marketing description long enough to be useful."}
        _, _, status, reason = run.description_blocks(doc, product, "Product Name")
        self.assertEqual(status, "fallback")
        self.assertIn("JSON-LD", reason)


class PriceUnitTests(unittest.TestCase):
    def test_per_lb_and_per_item(self) -> None:
        self.assertEqual(run.detect_price_unit(["Price is per lb."])[0], "per_lb")
        self.assertEqual(run.detect_price_unit(["Sold by the pound."])[0], "per_lb")
        self.assertEqual(run.detect_price_unit(["Price is per item."])[0], "per_item")
        self.assertEqual(run.detect_price_unit(["Price is per 12oz. bag."])[0], "per_bag")
        self.assertEqual(run.detect_price_unit(["Price is per oz."])[0], "per_oz")
        self.assertEqual(run.detect_price_unit(["No unit here."])[0], None)

    def test_ensure_unit_prepends_once(self) -> None:
        html, text, status, reason = run.ensure_unit("<p>Body</p>", "Body", "complete", None, "Price is per lb")
        self.assertTrue(html.startswith("<p>Price is per lb.</p>"))
        self.assertEqual(status, "complete")
        html2, _, _, _ = run.ensure_unit(html, text, status, reason, "Price is per lb")
        self.assertEqual(html, html2)


class BreadcrumbAndOptionTests(unittest.TestCase):
    def test_breadcrumbs_and_category_total(self) -> None:
        html = """
        <div class="breadcrumbs"><a href="/">Home</a><a href="/candy">Candy</a>
        <strong>Candy Unwrapped</strong></div>
        <div class="toolbar-amount">Items 1-30 of 62</div>
        """
        doc = LH.fromstring(html)
        self.assertEqual(run.parse_breadcrumbs(doc), ["Candy", "Candy Unwrapped"])
        self.assertEqual(run.category_total(doc), 62)

    def test_select_options(self) -> None:
        html = """
        <label>Color</label>
        <select name="super_attribute[93]">
          <option value="">Choose an Option...</option>
          <option value="1">Red</option>
          <option value="2">Blue</option>
        </select>
        """
        doc = LH.fromstring(html)
        self.assertEqual(run.parse_options(doc), "Color#Red|Blue")

    def test_json_config_options(self) -> None:
        html = """
        <script type="text/x-magento-init">
        {"*":{"config":{"jsonConfig":{"attributes":{"93":{"label":"Size","options":[{"label":"S"},{"label":"M"}]}}}}}}
        </script>
        """
        doc = LH.fromstring(html)
        self.assertEqual(run.parse_options(doc), "Size#S|M")


class CanonicalTests(unittest.TestCase):
    def test_canonical_strips_query_and_trailing_slash(self) -> None:
        html = '<html><head><link rel="canonical" href="https://shopthebulkstore.com/item/?x=1"></head></html>'
        doc = LH.fromstring(html)
        self.assertEqual(run.canonical_url(doc, "https://shopthebulkstore.com/other"), "https://shopthebulkstore.com/item")

    def test_canonical_falls_back_to_fetched(self) -> None:
        doc = LH.fromstring("<html></html>")
        self.assertEqual(
            run.canonical_url(doc, "https://shopthebulkstore.com/item/"),
            "https://shopthebulkstore.com/item",
        )


class CsvTests(unittest.TestCase):
    def test_nine_columns_and_formula_protection(self) -> None:
        row = {column: "" for column in run.CSV_COLUMNS}
        row.update(
            {
                "name": "=CMD()",
                "price_amount": "5.99",
                "price_currency": "USD",
                "primary_image_url": "https://shopthebulkstore.com/media/x.jpg",
                "description_html": "<p>Hello</p>",
                "source_url": "https://shopthebulkstore.com/x",
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
            self.assertEqual(parsed["price_amount"], "5.99")
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
        self.assertEqual(counts["partial_description_products"] <= counts["valid_products"], True)


if __name__ == "__main__":
    unittest.main()
