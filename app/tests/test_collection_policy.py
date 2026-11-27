import unittest

from ecom_crawler.collection_policy import (
    CollectionPolicyError,
    default_rate_overrides,
    formal_collection_limits,
    validate_collection_policy,
)


class CollectionPolicyTests(unittest.TestCase):
    def test_default_formal_collection_has_no_service_limits(self) -> None:
        policy = validate_collection_policy({})
        self.assertTrue(policy["formal_unlimited"])
        self.assertEqual(
            formal_collection_limits(policy),
            {"max_urls": None, "max_products": None, "max_seconds": None},
        )

    def test_bounded_formal_collection_uses_configured_limits(self) -> None:
        policy = validate_collection_policy(
            {
                "formal_unlimited": False,
                "formal_max_products": 250,
                "formal_max_seconds": 900,
            }
        )
        self.assertEqual(
            formal_collection_limits(policy),
            {"max_urls": None, "max_products": 250, "max_seconds": 900},
        )

    def test_default_rate_overrides_are_optional(self) -> None:
        policy = validate_collection_policy(
            {"default_per_domain_rps": 4, "default_concurrency": 3}
        )
        self.assertEqual(
            default_rate_overrides(policy),
            {"per_domain_rps": 4.0, "concurrency": 3},
        )
        self.assertEqual(default_rate_overrides(validate_collection_policy({})), {})

    def test_rejects_unknown_and_out_of_range_values(self) -> None:
        with self.assertRaises(CollectionPolicyError):
            validate_collection_policy({"formal_max_products": 0})
        with self.assertRaises(CollectionPolicyError):
            validate_collection_policy({"default_concurrency": 9})
        with self.assertRaises(CollectionPolicyError):
            validate_collection_policy({"unknown": True})
