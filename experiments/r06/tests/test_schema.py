"""Validate the declarative rule package against the published JSON Schema."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

import yaml

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional check dependency
    jsonschema = None

ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "docs" / "schema" / "manifest.schema.json"
RULE_PATH = ROOT / "experiments" / "r06" / "plans" / "familidoo-runtime.yaml"
PLAN_PATH = ROOT / "experiments" / "r06" / "plans" / "familidoo.yaml"


@unittest.skipIf(jsonschema is None, "jsonschema is not installed")
class SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.rule = yaml.safe_load(RULE_PATH.read_text(encoding="utf-8"))
        cls.plan = yaml.safe_load(PLAN_PATH.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(cls.schema)
        cls.validator = jsonschema.Draft202012Validator(cls.schema)

    def test_runtime_rule_matches_schema(self) -> None:
        self._assert_valid(self.rule)

    def test_single_run_plan_matches_schema(self) -> None:
        self._assert_valid(self.plan)

    def test_missing_capabilities_is_rejected(self) -> None:
        rule = copy.deepcopy(self.rule)
        del rule["capabilities"]
        self.assertTrue(list(self.validator.iter_errors(rule)))

    def _assert_valid(self, document: dict) -> None:
        errors = sorted(
            self.validator.iter_errors(document),
            key=lambda error: list(error.path),
        )
        self.assertEqual(
            errors,
            [],
            "\n".join(f"{list(error.path)}: {error.message}" for error in errors),
        )
