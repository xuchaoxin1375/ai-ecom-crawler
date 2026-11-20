"""Contract tests for the R06 declarative executor; no network access."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from executor.errors import PlanError
from executor.extract import ExtractedProduct, HtmlPage
from executor.manifest import load_plan
from executor.runner import (
    ProductRecord,
    Runner,
    RunOptions,
    discover_urls,
    validate_product,
)

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "plans" / "familidoo.yaml"


def make_record(**overrides: object) -> ProductRecord:
    data: dict[str, object] = {
        "name": "P",
        "price_amount": 12.5,
        "price_currency": "EUR",
        "primary_image_url": "https://example.test/i.jpg",
        "description_html": "<p>Body</p>",
        "category": "Cat",
        "brand": "Brand",
        "attributes": "Size#S|M",
        "source_url": "https://example.test/p",
        "description_status": "complete",
        "partial_reason": None,
        "missing_reasons": {},
        "field_sources": {"name": "h1"},
        "price_displayed": None,
        "price_pretax": None,
        "tax_basis": "unspecified",
    }
    data.update(overrides)
    return ProductRecord(**data)  # type: ignore[arg-type]


class ManifestTests(unittest.TestCase):
    def test_familidoo_plan_loads(self) -> None:
        plan = load_plan(PLAN_PATH)
        self.assertEqual(plan["plan_id"], "familidoo-fr-r06")
        self.assertEqual(plan["kind"], "declarative")
        self.assertEqual(plan["discovery"]["strategies"], ["entry_links"])

    def test_rejects_unknown_schema_version(self) -> None:
        plan = copy.deepcopy(load_plan(PLAN_PATH))
        plan["schema_version"] = "9.9"
        with self.assertRaises(PlanError):
            from executor.manifest import validate_plan

            validate_plan(plan)

    def test_rejects_unknown_top_level_key(self) -> None:
        plan = copy.deepcopy(load_plan(PLAN_PATH))
        plan["unexpected"] = True
        with self.assertRaises(PlanError):
            from executor.manifest import validate_plan

            validate_plan(plan)

    def test_rejects_program_kind(self) -> None:
        plan = copy.deepcopy(load_plan(PLAN_PATH))
        plan["kind"] = "program"
        with self.assertRaises(PlanError):
            from executor.manifest import validate_plan

            validate_plan(plan)

    def test_rejects_concurrency_two(self) -> None:
        plan = copy.deepcopy(load_plan(PLAN_PATH))
        plan["fetch"]["concurrency"] = 2
        with self.assertRaises(PlanError):
            from executor.manifest import validate_plan

            validate_plan(plan)

    def test_rejects_missing_core_field(self) -> None:
        plan = copy.deepcopy(load_plan(PLAN_PATH))
        del plan["extract"]["fields"]["source_url"]
        with self.assertRaises(PlanError):
            from executor.manifest import validate_plan

            validate_plan(plan)

    def test_rejects_invalid_scope_regex(self) -> None:
        plan = copy.deepcopy(load_plan(PLAN_PATH))
        plan["scope"]["include"] = ["/fr/(unclosed"]
        with self.assertRaises(PlanError):
            from executor.manifest import validate_plan

            validate_plan(plan)

    def test_rejects_delay_below_one_second(self) -> None:
        plan = copy.deepcopy(load_plan(PLAN_PATH))
        plan["fetch"]["delay_ms"] = 500
        with self.assertRaises(PlanError):
            from executor.manifest import validate_plan

            validate_plan(plan)


class DiscoveryTests(unittest.TestCase):
    def test_filters_scope_and_dedupes(self) -> None:
        plan = load_plan(PLAN_PATH)
        page = HtmlPage(
            '<a class="product_img_link" href="/fr/cat/1-a.html">A</a>'
            '<a class="product_img_link" href="/fr/cat/1-a.html#frag">A dup</a>'
            '<a class="product_img_link" href="/fr/cart">cart</a>'
            '<a class="product_img_link" href="https://evil.test/fr/cat/2-b.html">ext</a>'
            '<article class="js-product-miniature"><h3>'
            '<a href="/fr/cat/3-c.html">C</a></h3></article>',
            "https://www.familidoo.fr/fr/",
        )
        urls = discover_urls(page, plan, limit=10)
        self.assertEqual(
            urls,
            [
                "https://www.familidoo.fr/fr/cat/1-a.html",
                "https://www.familidoo.fr/fr/cat/3-c.html",
            ],
        )

    def test_scope_include_uses_regex(self) -> None:
        plan = copy.deepcopy(load_plan(PLAN_PATH))
        plan["scope"]["include"] = [r"^/fr/cat/"]
        page = HtmlPage(
            '<a class="product_img_link" href="/fr/cat/1-a.html">A</a>'
            '<a class="product_img_link" href="/fr/other/2-b.html">B</a>',
            "https://www.familidoo.fr/fr/",
        )
        urls = discover_urls(page, plan, limit=10)
        self.assertEqual(urls, ["https://www.familidoo.fr/fr/cat/1-a.html"])


class ValidationTests(unittest.TestCase):
    def test_missing_required_and_zero_price(self) -> None:
        plan = load_plan(PLAN_PATH)
        product = ExtractedProduct(
            values={
                "name": "",
                "price.amount": None,
                "price.currency": "",
                "primary_image_url": "",
                "source_url": "",
            },
            sources={},
            extras={},
            description_status="not_provided",
            partial_reason=None,
            missing_reasons={},
        )
        reasons = validate_product(product, plan)
        self.assertIn("missing_name", reasons)
        self.assertIn("zero_or_missing_price", reasons)
        self.assertIn("missing_primary_image_url", reasons)
        self.assertIn("missing_source_url", reasons)
        self.assertEqual(reasons.count("zero_or_missing_price"), 1)

    def test_invalid_currency(self) -> None:
        plan = load_plan(PLAN_PATH)
        product = ExtractedProduct(
            values={
                "name": "P",
                "price.amount": 1.0,
                "price.currency": "EURO",
                "primary_image_url": "https://example.test/i.jpg",
                "source_url": "https://example.test/p",
            },
            sources={},
            extras={},
            description_status="complete",
            partial_reason=None,
            missing_reasons={},
        )
        self.assertIn("invalid_currency", validate_product(product, plan))


class CsvTests(unittest.TestCase):
    def test_nine_columns_and_formula_protection(self) -> None:
        record = make_record(name="=SUM(A1)")
        row = record.csv_row()
        self.assertEqual(len(row), 9)
        self.assertEqual(row[0], "'=SUM(A1)")
        self.assertEqual(row[1], "12.50")

    def test_formula_protection_leaves_normal_text(self) -> None:
        record = make_record(name="Normal name")
        self.assertEqual(record.csv_row()[0], "Normal name")


class TaskResultTests(unittest.TestCase):
    def test_counts_and_quality_exceptions(self) -> None:
        plan = load_plan(PLAN_PATH)
        options = RunOptions(
            out_dir=ROOT / "unused",
            label="unit-test",
            max_products=2,
            max_seconds=10,
        )
        runner = Runner(plan, options)
        runner.discovered = ["u1", "u2"]
        runner.pending = []
        runner.entry_fetched = True
        runner.records = [
            make_record(missing_reasons={"brand": "NOT_PROVIDED"}),
        ]
        runner.audits = [
            {"source_url": "u1", "status": "valid", "reason": ""},
            {"source_url": "u2", "status": "excluded", "reason": "missing_name"},
        ]
        result = runner._task_result()
        counts = result["counts"]
        self.assertEqual(counts["product_candidates"], 2)
        self.assertEqual(counts["processed_products"], 2)
        self.assertEqual(counts["valid_products"], 1)
        self.assertEqual(counts["excluded_products"], 1)
        self.assertEqual(counts["pending_products"], 0)
        self.assertEqual(result["outcome"], "COMPLETED")
        self.assertEqual(result["coverage"]["status"], "PARTIAL")
        self.assertEqual(len(result["quality_exceptions"]), 1)
        self.assertEqual(
            result["quality_exceptions"][0]["missing_reasons"]["brand"], "NOT_PROVIDED"
        )

    def test_broken_invariant_raises(self) -> None:
        plan = load_plan(PLAN_PATH)
        options = RunOptions(
            out_dir=ROOT / "unused",
            label="unit-test",
            max_products=2,
            max_seconds=10,
        )
        runner = Runner(plan, options)
        runner.discovered = ["u1", "u2"]
        runner.pending = []
        runner.records = [make_record()]
        runner.audits = []
        with self.assertRaises(PlanError):
            runner._task_result()


if __name__ == "__main__":
    unittest.main()
