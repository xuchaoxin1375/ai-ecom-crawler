from __future__ import annotations

import unittest

from ecom_crawler.rule_diff import (
    compare_product_samples,
    normalize_validation,
)


def sample(url: str, **overrides: object) -> dict:
    payload = {
        "source_url": url,
        "name": "Example product",
        "price_amount": "10.00",
        "price_currency": "EUR",
        "primary_image_url": "https://example.fr/a.jpg",
        "description_html": "<p>A sufficiently complete description.</p>",
    }
    payload.update(overrides)
    return payload


class CompareProductSamplesTests(unittest.TestCase):
    def test_detects_core_field_regressions(self) -> None:
        old = [sample("https://example.fr/p/1")]
        new = [
            sample(
                "https://example.fr/p/1",
                name="Changed product",
                price_amount="9.00",
                price_currency="USD",
                primary_image_url="https://example.fr/b.jpg",
                description_html="<p>short</p>",
            )
        ]
        result = compare_product_samples(old, new)
        self.assertTrue(result["executed"])
        self.assertEqual(result["checked"], 1)
        fields = {item["field"] for item in result["regressions"]}
        self.assertEqual(
            fields,
            {
                "name",
                "price_amount",
                "price_currency",
                "primary_image_url",
                "description_html",
            },
        )

    def test_equal_fields_and_longer_description_are_not_regressions(self) -> None:
        old = [sample("https://example.fr/p/1")]
        new = [
            sample(
                "https://example.fr/p/1",
                description_html="<p>A much longer description with specs.</p>",
            )
        ]
        result = compare_product_samples(old, new)
        self.assertTrue(result["executed"])
        self.assertEqual(result["regressions"], [])

    def test_pages_missing_on_one_side_are_skipped(self) -> None:
        result = compare_product_samples(
            [sample("https://example.fr/old")],
            [sample("https://example.fr/new")],
        )
        self.assertFalse(result["executed"])
        self.assertIn("reason", result)
        reasons = {item["reason"] for item in result["skipped"]}
        self.assertEqual(
            reasons, {"missing_from_old_rule", "missing_from_new_rule"}
        )


class NormalizeValidationTests(unittest.TestCase):
    def _raw(self, **overrides: object) -> dict:
        payload = {
            "valid_products": 2,
            "failed_products": 0,
            "candidate_smoke": {
                "executed": True,
                "valid_products": 2,
                "product_samples": [
                    sample("https://example.fr/p/1"),
                    sample("https://example.fr/p/2"),
                ],
            },
            "regression": {
                "executed": False,
                "required": True,
                "checked": 0,
                "regressions": [],
                "reason": "not run",
            },
        }
        payload.update(overrides)
        return payload

    def test_repair_without_regression_is_incomplete(self) -> None:
        validation = normalize_validation(
            self._raw(), {"parent_version": "2026.11.23-1"}
        )
        self.assertEqual(validation["status"], "INCOMPLETE")
        self.assertIn(
            "required cross-version regression did not run",
            validation["status_reasons"],
        )
        self.assertEqual(len(validation["evidence_sha256"]), 64)

    def test_initial_build_without_regression_is_passed(self) -> None:
        validation = normalize_validation(
            self._raw(
                regression={
                    "executed": False,
                    "required": False,
                    "checked": 0,
                    "regressions": [],
                }
            ),
            {"parent_version": None},
        )
        self.assertEqual(validation["status"], "PASSED")

    def test_regression_entries_fail_the_report(self) -> None:
        validation = normalize_validation(
            self._raw(
                regression={
                    "executed": True,
                    "required": True,
                    "checked": 2,
                    "regressions": [
                        {
                            "field": "price_amount",
                            "sample": "https://example.fr/p/1",
                            "before": "10.00",
                            "after": "9.00",
                        }
                    ],
                }
            ),
            {"parent_version": "2026.11.23-1"},
        )
        self.assertEqual(validation["status"], "FAILED")
        self.assertIn(
            "cross-version regression detected",
            validation["status_reasons"],
        )

    def test_missing_feedback_sample_check_fails(self) -> None:
        validation = normalize_validation(
            self._raw(feedback_samples=["https://example.fr/p/9"]),
            {"parent_version": "2026.11.23-1"},
        )
        self.assertEqual(validation["status"], "FAILED")
        check = next(
            item
            for item in validation["issue_checks"]
            if item["sample"] == "https://example.fr/p/9"
        )
        self.assertFalse(check["passed"])


if __name__ == "__main__":
    unittest.main()
