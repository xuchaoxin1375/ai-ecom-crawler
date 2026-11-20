from __future__ import annotations

import json
import unittest
from pathlib import Path

import jsonschema

from ecom_crawler.pipeline import export_candidates
from tests.support import base_task, candidate

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"
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


if __name__ == "__main__":
    unittest.main()
