"""Contract tests for the skatepro.es Crawlee extractor and CSV export.

These are synthetic fixtures: they exercise the data rules (positive price,
variant minimum, currency evidence, description states, options, CSV shape)
without claiming that any real page was fetched.
"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PACKAGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACKAGE_DIR))

from crawlee_skatepro.clean import clean_html_fragment  # noqa: E402
from crawlee_skatepro.export import (  # noqa: E402
    CSV_COLUMNS,
    quality_exceptions,
    write_valid_csv,
)
from crawlee_skatepro.extract import (  # noqa: E402
    ProductExcluded,
    ProductFailed,
    _schema_availability,
    extract_product,
    normalize_url,
    parse_price_text,
    serialize_options,
)
from crawlee_skatepro.runner import load_shared_urls  # noqa: E402

URL = "https://www.skatepro.es/1-2.htm"


def variant(size: str, price, availability: str = "InStock", color: str = "") -> dict:
    return {
        "@type": "Product",
        "name": f"Synthetic Skate {size}",
        "sku": f"SKU-{size}",
        "size": size,
        "color": color,
        "image": ["https://cdn.skatepro.com/product/520/synthetic.webp"],
        "offers": {
            "@type": "Offer",
            "price": price,
            "priceCurrency": "EUR",
            "availability": f"https://schema.org/{availability}",
        },
    }


def make_page(
    *,
    name: str = "Synthetic Skate",
    variants: list[dict] | None = None,
    displayed_price: str = "37,95 €",
    description: str | None = "<p>Una descripción sintética del producto.</p>",
    specs: str | None = (
        '<div class="row"><div class="small-12 columns">'
        "<button class=\"spec_desc_button\">Material:</button></div>"
        '<div class="small-12 columns">Aluminio</div></div>'
    ),
    brand: str = "Synthetic Brand",
    category: str = "Patines > Patines en línea > Niños",
    image: str = "https://cdn.skatepro.com/product/520/synthetic.webp",
    locale: str = "es_ES",
    jsonld_description: str = "",
    group: bool = True,
) -> str:
    if variants is None:
        variants = [variant("38-41", 37.95)]
    product = {
        "@context": "https://schema.org",
        "@type": "ProductGroup" if group else "Product",
        "name": name,
        "brand": {"@type": "Brand", "name": brand},
        "category": category,
        "description": jsonld_description,
        "url": URL,
        "image": [image],
    }
    if group:
        product["hasVariant"] = variants
        product["productGroupID"] = "2"
    else:
        product.update(variants[0])

    blocks = [json.dumps(product, ensure_ascii=False)]
    if not group:
        blocks = [json.dumps(variants[0], ensure_ascii=False)]
    ld = "".join(
        f'<script type="application/ld+json">{block}</script>' for block in blocks
    )
    body = (
        '<section><h2>Descripción<button type="button"></button></h2>'
        f'<div class="wrapper"><div id="product_description"><div>{description}</div></div></div>'
        "</section>"
        if description
        else ""
    )
    specs_block = (
        f'<section><h2>Especificaciones</h2><div id="product_specifications">'
        f"{specs}</div></section>"
        if specs
        else ""
    )
    return f"""<!doctype html>
<html lang="es"><head>
<meta property="og:locale" content="{locale}">
<meta property="og:image" content="{image}">
<link rel="canonical" href="{URL}">
{ld}
</head><body>
<nav class="breadcrumb"><ol><li><a>Inicio</a></li>
<li><a>Patines</a></li><li><a>Patines en línea</a></li><li><a>Niños</a></li></ol></nav>
<a id="brand_name">{brand}</a>
<h1 class="product_page"><span>{name}</span></h1>
<div class="product_prices"><div class="pi_price"><div class="price">{displayed_price}</div></div></div>
<div class="pi_size_selector">
  {"".join(f'<div class="variant_selector_row" aria-label="{v.get("size", "")}"></div>' for v in variants)}
</div>
{body}
{specs_block}
</body></html>"""


def extract(html: str, url: str = URL):
    return extract_product(
        html, url, market="ES", locale="es-ES", extracted_at="2026-11-19T00:00:00Z"
    )


class PriceParsingTests(unittest.TestCase):
    def test_spanish_formats(self):
        self.assertEqual(str(parse_price_text("19,95 €")), "19.95")
        self.assertEqual(str(parse_price_text("1.234,95 €")), "1234.95")
        self.assertEqual(str(parse_price_text("49,9")), "49.9")
        # es-ES: a single dot followed by two digits is ambiguous, not a decimal.
        self.assertIsNone(parse_price_text("19.95"))
        self.assertIsNone(parse_price_text(""))
        self.assertIsNone(parse_price_text("consultar"))

    def test_url_normalisation_removes_variant_query(self):
        self.assertEqual(
            normalize_url("https://www.skatepro.es/77-53419.htm?stockcode=a%2Fb"),
            "https://www.skatepro.es/77-53419.htm",
        )
        self.assertEqual(
            normalize_url("http://WWW.skatepro.es/77-53419.htm/"),
            "https://www.skatepro.es/77-53419.htm",
        )


class OptionTests(unittest.TestCase):
    def test_escaping(self):
        self.assertEqual(
            serialize_options({"Talla#x": ["a|b", "c~d"]}),
            "Talla\\#x#a\\|b|c\\~d",
        )

    def test_size_dimension_kept_and_single_colour_dropped(self):
        result = extract(make_page())
        self.assertEqual(result.row["attributes"], "Talla#38-41")

    def test_multi_colour_dimension_serialised(self):
        variants = [variant("Única", 10, color="Negro"), variant("Única", 10, color="Azul")]
        result = extract(make_page(variants=variants, displayed_price="10,00 €"))
        self.assertEqual(result.row["attributes"], "Talla#Única~Color#Negro|Azul")


class PriceRuleTests(unittest.TestCase):
    def test_lowest_positive_variant_including_out_of_stock(self):
        variants = [
            variant("38-41", 35.0, "InStock"),
            variant("42-45", 29.0, "OutOfStock"),
        ]
        result = extract(make_page(variants=variants, displayed_price="35,00 €"))
        self.assertEqual(result.row["price_amount"], "29.00")
        self.assertEqual(result.row["price_currency"], "EUR")
        self.assertEqual(result.row["availability"], "in_stock")
        self.assertTrue(result.evidence["price_specification_ignored"])

    def test_zero_price_is_excluded_with_reason(self):
        variants = [variant("38-41", 0)]
        with self.assertRaises(ProductExcluded) as ctx:
            extract(make_page(variants=variants, displayed_price="0,00 €"))
        self.assertEqual(ctx.exception.reason, "ZERO_PRICE")

    def test_no_price_is_excluded(self):
        variants = [variant("38-41", None)]
        with self.assertRaises(ProductExcluded) as ctx:
            extract(make_page(variants=variants))
        self.assertEqual(ctx.exception.reason, "NO_PRICE")

    def test_currency_conflict_is_a_failure(self):
        variants = [variant("38-41", 37.95), variant("42-45", 37.95)]
        variants[1]["offers"]["priceCurrency"] = "DKK"
        with self.assertRaises(ProductFailed) as ctx:
            extract(make_page(variants=variants))
        self.assertEqual(ctx.exception.reason, "CURRENCY_CONFLICT")

    def test_foreign_currency_is_excluded(self):
        variants = [variant("38-41", 37.95)]
        variants[0]["offers"]["priceCurrency"] = "GBP"
        with self.assertRaises(ProductExcluded) as ctx:
            extract(make_page(variants=variants))
        self.assertEqual(ctx.exception.reason, "CURRENCY_NOT_TARGET")

    def test_displayed_price_must_match_a_variant(self):
        with self.assertRaises(ProductFailed) as ctx:
            extract(make_page(displayed_price="99,95 €"))
        self.assertEqual(ctx.exception.reason, "PRICE_EVIDENCE_CONFLICT")


class AvailabilityTests(unittest.TestCase):
    def test_schema_mapping(self):
        self.assertEqual(_schema_availability(["https://schema.org/InStock"]), "in_stock")
        self.assertEqual(_schema_availability(["https://schema.org/PreOrder"]), "preorder")
        self.assertEqual(_schema_availability(["https://schema.org/BackOrder"]), "backorder")
        self.assertEqual(
            _schema_availability(
                ["https://schema.org/OutOfStock", "https://schema.org/OutOfStock"]
            ),
            "out_of_stock",
        )
        self.assertEqual(_schema_availability([]), "")

    def test_preorder_is_recorded(self):
        variants = [variant("38-41", 37.95, "PreOrder")]
        result = extract(make_page(variants=variants))
        self.assertEqual(result.row["availability"], "preorder")
        self.assertEqual(result.row["availability_source"], "jsonld.offer.availability")


class DescriptionTests(unittest.TestCase):
    def test_body_and_specs_are_merged_with_headings(self):
        result = extract(make_page())
        html = result.row["description_html"]
        self.assertEqual(result.row["description_status"], "complete")
        self.assertIn("Descripción", html)
        self.assertIn("Especificaciones", html)
        self.assertIn("Material:", html)
        self.assertIn("Aluminio", html)
        self.assertTrue(html.startswith("<p><strong>"))

    def test_specs_only_is_partial_with_reason(self):
        result = extract(make_page(description=None))
        self.assertEqual(result.row["description_status"], "partial")
        self.assertTrue(result.row["partial_reason"])

    def test_jsonld_only_is_fallback(self):
        result = extract(
            make_page(description=None, specs=None, jsonld_description="Texto de respaldo.")
        )
        self.assertEqual(result.row["description_status"], "fallback")
        self.assertEqual(
            result.row["missing_reasons"]["description_html"], "JSONLD_FALLBACK"
        )

    def test_no_description_evidence_fails(self):
        with self.assertRaises(ProductFailed) as ctx:
            extract(make_page(description=None, specs=None))
        self.assertEqual(ctx.exception.reason, "DESCRIPTION_BLOCK_NOT_FOUND")

    def test_cleaner_drops_scripts_and_keeps_text(self):
        html = clean_html_fragment(
            '<div><p>Hola</p><script>alert(1)</script><a href="#">link</a></div>'
        )
        self.assertIn("Hola", html)
        self.assertIn("link", html)
        self.assertNotIn("script", html)
        self.assertNotIn("href", html)


class SharedSelectionTests(unittest.TestCase):
    def test_url_file_accepts_object_and_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "urls.json"
            path.write_text(
                json.dumps(
                    {
                        "urls": [
                            URL,
                            URL,
                            "https://www.skatepro.es/3-4.htm",
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                load_shared_urls(path),
                [URL, "https://www.skatepro.es/3-4.htm"],
            )

    def test_url_file_rejects_non_product_urls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "urls.json"
            path.write_text(
                json.dumps(["https://www.skatepro.es/c2.htm"]),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "product pattern"):
                load_shared_urls(path)


class ExportTests(unittest.TestCase):
    def test_csv_has_exactly_the_nine_business_columns(self):
        self.assertEqual(
            CSV_COLUMNS,
            [
                "name",
                "price_amount",
                "price_currency",
                "primary_image_url",
                "description_html",
                "category",
                "brand",
                "attributes",
                "source_url",
            ],
        )
        result = extract(make_page())
        row = dict(result.row)
        for key in ("task_id", "plan_id", "plan_version", "market", "locale"):
            row[key] = "test"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "valid.csv"
            write_valid_csv(path, [row])
            with path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, CSV_COLUMNS)
                written = next(reader)
            self.assertEqual(written["name"], "Synthetic Skate")
            self.assertEqual(written["price_amount"], "37.95")

    def test_quality_exceptions_list_only_incomplete_or_missing(self):
        complete = {
            "source_url": "https://www.skatepro.es/1-1.htm",
            "description_status": "complete",
            "partial_reason": "",
            "missing_reasons": {},
        }
        missing_option = dict(complete, source_url="https://www.skatepro.es/1-2.htm",
                              missing_reasons={"options": "NO_MEANINGFUL_OPTIONS"})
        partial = dict(complete, source_url="https://www.skatepro.es/1-3.htm",
                       description_status="partial", partial_reason="solo especificaciones")
        listed = quality_exceptions([complete, missing_option, partial])
        self.assertEqual(
            sorted(item["source_url"] for item in listed),
            ["https://www.skatepro.es/1-2.htm", "https://www.skatepro.es/1-3.htm"],
        )
        by_url = {item["source_url"]: item for item in listed}
        self.assertIsNone(by_url["https://www.skatepro.es/1-2.htm"]["partial_reason"])
        self.assertEqual(
            by_url["https://www.skatepro.es/1-3.htm"]["partial_reason"],
            "solo especificaciones",
        )


if __name__ == "__main__":
    unittest.main()
