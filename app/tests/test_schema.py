from __future__ import annotations

import json
import unittest
from pathlib import Path

import jsonschema

from ecom_crawler.pipeline import export_candidates
from ecom_crawler.rule_diff import build_change_summary, normalize_validation
from tests.support import base_task, candidate

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"
DOCS_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schema"
EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "示例"


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


class SchemaTests(unittest.TestCase):
    def test_schemas_are_valid_draft_2020_12(self) -> None:
        for name in (
            "candidate-record.schema.json",
            "product-record.schema.json",
            "task-result.schema.json",
        ):
            schema = load_schema(name)
            jsonschema.Draft202012Validator.check_schema(schema)

    def test_candidate_schema_accepts_docs_records(self) -> None:
        schema = load_schema("candidate-record.schema.json")
        validator = jsonschema.Draft202012Validator(schema)
        records = json.loads(
            (EXAMPLES / "商品记录.json").read_text(encoding="utf-8")
        )
        for record in records:
            errors = list(validator.iter_errors(record))
            self.assertEqual(errors, [], [error.message for error in errors])
        errors = list(validator.iter_errors(candidate()))
        self.assertEqual(errors, [], [error.message for error in errors])

    def test_product_and_task_schemas_accept_pipeline_output(self) -> None:
        result = export_candidates(
            base_task(),
            [
                candidate(),
                candidate(
                    source_url="https://shop.example/products/partial",
                    description_status="PARTIAL",
                    partial_reason="Compatibility table missing.",
                    missing_reasons={"brand": "NOT_PROVIDED"},
                    brand=None,
                ),
            ],
        )
        product_schema = load_schema("product-record.schema.json")
        product_validator = jsonschema.Draft202012Validator(product_schema)
        for product in result.products:
            payload = json.loads(json.dumps(product.to_record(), ensure_ascii=False))
            errors = list(product_validator.iter_errors(payload))
            self.assertEqual(errors, [], [error.message for error in errors])

        task_schema = load_schema("task-result.schema.json")
        task_validator = jsonschema.Draft202012Validator(task_schema)
        payload = json.loads(json.dumps(result.task_result, ensure_ascii=False))
        errors = list(task_validator.iter_errors(payload))
        self.assertEqual(errors, [], [error.message for error in errors])

    def test_product_schema_rejects_non_positive_price(self) -> None:
        result = export_candidates(base_task(), [candidate()])
        payload = json.loads(json.dumps(result.products[0].to_record()))
        payload["price"]["amount"] = 0
        validator = jsonschema.Draft202012Validator(load_schema("product-record.schema.json"))
        self.assertTrue(list(validator.iter_errors(payload)))

    def test_v2_rule_diff_and_validation_payloads_match_schemas(self) -> None:
        old = {
            "rule_id": "example",
            "rule_version": "2026.11.23-1",
            "site": {"market": "FR", "currency": "EUR"},
            "discovery": {"link_selector": "a.product"},
            "scope": {"max_products": 2},
            "extract": {
                "fields": {"name": {"fallbacks": [{"selector": "h1"}]}}
            },
        }
        new = json.loads(json.dumps(old))
        new["rule_version"] = "2026.11.23-2"
        new["scope"]["max_products"] = 4
        new["extract"]["fields"]["description_html"] = {
            "fallbacks": [{"selector": "div.description"}]
        }
        summary = build_change_summary(
            old,
            new,
            rule_id="example",
            rule_version="2026.11.23-2",
            parent_version="2026.11.23-1",
        )
        validation = normalize_validation(
            {
                "valid_products": 2,
                "failed_products": 0,
                "content_audit": {
                    "products_checked": 2,
                    "description_gaps": 0,
                },
                "currencies": {"EUR": 2},
            },
            summary,
        )

        self.assertIn("scope.max_products", summary["changed_fields"])
        self.assertIn(
            "extract.fields.description_html", summary["changed_fields"]
        )
        self.assertIn(
            "extract.fields.description_html", summary["changed_selectors"]
        )

        for schema_name, payload in (
            ("v2-build-change-summary.schema.json", summary),
            ("v2-build-validation.schema.json", validation),
        ):
            schema = json.loads(
                (DOCS_SCHEMA_DIR / schema_name).read_text(encoding="utf-8")
            )
            errors = list(
                jsonschema.Draft202012Validator(schema).iter_errors(payload)
            )
            self.assertEqual(
                errors, [], [error.message for error in errors]
            )


if __name__ == "__main__":
    unittest.main()
