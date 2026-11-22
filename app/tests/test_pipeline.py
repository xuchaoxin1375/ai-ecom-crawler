from __future__ import annotations

import unittest
from decimal import Decimal

from ecom_crawler.model import ContractError
from ecom_crawler.pipeline import export_candidates
from tests.support import base_task, candidate


class CandidateClassificationTests(unittest.TestCase):
    def test_valid_candidate_becomes_product(self) -> None:
        result = export_candidates(base_task(), [candidate()])
        self.assertEqual(len(result.products), 1)
        self.assertEqual(result.excluded, ())
        self.assertEqual(result.failed, ())
        self.assertEqual(result.task_result["counts"]["valid_products"], 1)
        product = result.products[0]
        self.assertEqual(product.price_amount, Decimal("29.00"))
        self.assertEqual(product.attributes, "Size#S|M")

    def test_non_positive_and_missing_prices_are_excluded(self) -> None:
        items = [
            candidate(source_url="https://shop.example/p/zero", price={"amount": "0", "currency": "GBP"}),
            candidate(source_url="https://shop.example/p/neg", price={"amount": "-1", "currency": "GBP"}),
            candidate(source_url="https://shop.example/p/missing", price={"currency": "GBP"}),
            candidate(source_url="https://shop.example/p/bad", price={"amount": "abc", "currency": "GBP"}),
        ]
        result = export_candidates(base_task(), items)
        self.assertEqual(result.products, ())
        self.assertEqual(result.failed, ())
        self.assertEqual(
            [item["reason"] for item in result.excluded],
            [
                "NON_POSITIVE_PRICE",
                "NON_POSITIVE_PRICE",
                "MISSING_PRICE",
                "INVALID_PRICE",
            ],
        )

    def test_missing_currency_is_a_failure(self) -> None:
        result = export_candidates(
            base_task(),
            [candidate(price={"amount": "29.00"})],
        )
        self.assertEqual(len(result.failed), 1)
        self.assertEqual(result.failed[0]["reason"], "MISSING_CURRENCY")

    def test_placeholder_image_is_a_failure(self) -> None:
        result = export_candidates(
            base_task(),
            [candidate(primary_image_url="https://shop.example/images/none.jpg")],
        )
        self.assertEqual(len(result.failed), 1)
        self.assertEqual(result.failed[0]["reason"], "PLACEHOLDER_IMAGE")

    def test_missing_name_is_a_failure(self) -> None:
        result = export_candidates(base_task(), [candidate(name="   ")])
        self.assertEqual(len(result.failed), 1)
        self.assertEqual(result.failed[0]["reason"], "MISSING_NAME")

    def test_duplicate_source_url_is_excluded(self) -> None:
        first = candidate()
        second = candidate(name="Duplicate")
        result = export_candidates(base_task(), [first, second])
        self.assertEqual(len(result.products), 1)
        self.assertEqual(len(result.excluded), 1)
        self.assertEqual(result.excluded[0]["reason"], "DUPLICATE_SOURCE_URL")

    def test_variants_choose_lowest_positive_and_keep_options(self) -> None:
        item = candidate(
            price={
                "currency": "GBP",
                "variants": [
                    {
                        "amount": "29.00",
                        "available": False,
                        "sku": "SHIRT-S",
                        "options": {"Size": "S"},
                    },
                    {
                        "amount": "35.00",
                        "available": True,
                        "sku": "SHIRT-M",
                        "options": {"Size": "M", "Color": "Red"},
                    },
                ],
            },
            options=[{"name": "Size", "values": ["S"]}],
        )
        result = export_candidates(base_task(), [item])
        product = result.products[0]
        self.assertEqual(product.price_amount, Decimal("29.00"))
        self.assertEqual(
            [(group.name, group.values) for group in product.options],
            [("Size", ("S", "M")), ("Color", ("Red",))],
        )
        variants = product.to_record()["variants"]
        self.assertEqual([variant["amount"] for variant in variants], [29.0, 35.0])
        self.assertEqual([variant["available"] for variant in variants], [False, True])
        self.assertEqual([variant["sku"] for variant in variants], ["SHIRT-S", "SHIRT-M"])

    def test_tax_candidates_choose_smaller_public_price(self) -> None:
        item = candidate(
            price={
                "currency": "GBP",
                "candidates": [
                    {
                        "amount": "24.17",
                        "label": "pretax",
                        "tax_basis": "EXCLUSIVE",
                    },
                    {
                        "amount": "29.00",
                        "label": "displayed",
                        "tax_basis": "INCLUSIVE",
                    },
                ],
            }
        )
        product = export_candidates(base_task(), [item]).products[0]
        self.assertEqual(product.price_amount, Decimal("24.17"))
        self.assertEqual(product.tax_basis, "EXCLUSIVE")
        self.assertEqual(product.price_displayed, Decimal("29.00"))
        self.assertEqual(product.price_pretax, Decimal("24.17"))

    def test_online_only_is_not_a_stock_status(self) -> None:
        product = export_candidates(
            base_task(), [candidate(availability="OnlineOnly")]
        ).products[0]
        self.assertIsNone(product.availability)
        self.assertEqual(product.availability_observed, "OnlineOnly")

    def test_market_mismatch_is_excluded(self) -> None:
        result = export_candidates(base_task(), [candidate(market="US")])
        self.assertEqual(len(result.excluded), 1)
        self.assertEqual(result.excluded[0]["reason"], "MARKET_MISMATCH")

    def test_sales_unit_is_added_once_to_description(self) -> None:
        product = export_candidates(
            base_task(), [candidate(sales_unit="per lb")]
        ).products[0]
        self.assertEqual(product.description_html, "<p>per lb</p><p>A shirt.</p>")
        self.assertEqual(product.sales_unit, "per lb")
        self.assertEqual(product.to_record()["sales_unit"], "per lb")

    def test_missing_brand_reason_conflicts_with_present_brand(self) -> None:
        result = export_candidates(
            base_task(),
            [candidate(missing_reasons={"brand": "NOT_PROVIDED"})],
        )
        self.assertEqual(len(result.failed), 1)
        self.assertEqual(result.failed[0]["reason"], "MISSING_REASON_CONFLICT")


class TaskResultTests(unittest.TestCase):
    def test_pending_navigation_makes_outcome_partial(self) -> None:
        task = base_task(counts={"discovered_urls": 10, "pending_navigation_entries": 2})
        result = export_candidates(task, [candidate()])
        counts = result.task_result["counts"]
        self.assertEqual(counts["pending_navigation_entries"], 2)
        self.assertEqual(result.task_result["outcome"], "PARTIAL")

    def test_zero_valid_with_failure_is_failed(self) -> None:
        result = export_candidates(
            base_task(),
            [candidate(primary_image_url="https://shop.example/images/none.jpg")],
        )
        self.assertEqual(result.task_result["counts"]["valid_products"], 0)
        self.assertEqual(result.task_result["counts"]["failed_products"], 1)
        self.assertEqual(result.task_result["outcome"], "FAILED")

    def test_zero_valid_with_business_exclusion_is_completed(self) -> None:
        result = export_candidates(
            base_task(),
            [candidate(price={"amount": "0", "currency": "GBP"})],
        )
        self.assertEqual(result.task_result["counts"]["valid_products"], 0)
        self.assertEqual(result.task_result["counts"]["excluded_products"], 1)
        self.assertEqual(result.task_result["outcome"], "COMPLETED")

    def test_cancelled_state_is_preserved(self) -> None:
        task = base_task(state="CANCELLED", stop_reason="USER_CANCELLED")
        result = export_candidates(task, [candidate()])
        self.assertEqual(result.task_result["outcome"], "CANCELLED")

    def test_quality_exception_lists_partial_and_missing_fields(self) -> None:
        item = candidate(
            description_status="PARTIAL",
            partial_reason="Compatibility table could not be loaded.",
            missing_reasons={"brand": "NOT_PROVIDED"},
            brand=None,
        )
        result = export_candidates(base_task(), [item])
        exceptions = result.task_result["quality_exceptions"]
        self.assertEqual(len(exceptions), 1)
        self.assertEqual(exceptions[0]["description_status"], "PARTIAL")
        self.assertEqual(
            exceptions[0]["partial_reason"], "Compatibility table could not be loaded."
        )
        self.assertEqual(exceptions[0]["missing_reasons"], {})
        self.assertEqual(result.task_result["counts"]["partial_description_products"], 1)

    def test_optional_missing_fields_do_not_create_quality_exception(self) -> None:
        item = candidate(
            description_status="complete",
            missing_reasons={"brand": "NOT_PROVIDED", "category": "NOT_PROVIDED"},
            brand=None,
        )
        result = export_candidates(base_task(), [item])
        self.assertEqual(result.task_result["quality_exceptions"], [])
        self.assertEqual(result.task_result["counts"]["valid_products"], 1)

    def test_discovered_urls_smaller_than_candidates_is_rejected(self) -> None:
        task = base_task(counts={"discovered_urls": 1, "pending_navigation_entries": 0})
        with self.assertRaises(ContractError):
            export_candidates(
                task,
                [
                    candidate(),
                    candidate(source_url="https://shop.example/products/second"),
                ],
            )


if __name__ == "__main__":
    unittest.main()
