from __future__ import annotations

import unittest
from typing import Any

from ecom_crawler.executor.preflight import check_rule_selectors, format_selector_errors


def rule(selector: str) -> dict[str, Any]:
    return {
        "discovery": {"link_selector": selector},
        "extract": {
            "fields": {
                "name": {
                    "fallbacks": [
                        {"type": "css_text", "selector": selector},
                    ]
                }
            }
        },
        "fetch": {
            "browser": {"wait_selector": "text=Add to cart"},
        },
    }


class PreflightTests(unittest.TestCase):
    def test_accepts_supported_selectors(self) -> None:
        errors = check_rule_selectors(rule("a.product"))
        self.assertEqual(errors, [])

    def test_rejects_lxml_unsupported_negation(self) -> None:
        errors = check_rule_selectors(rule("a:not(:first-of-type)"))
        self.assertEqual(len(errors), 2)
        self.assertIn("discovery.link_selector", errors[0]["path"])
        self.assertIn("first-of-type", errors[0]["error"])
        message = format_selector_errors(errors)
        self.assertIn("invalid CSS selector", message)
        self.assertIn(":not(:first-of-type)", message)

    def test_skips_playwright_wait_selector(self) -> None:
        payload = rule("a.product")
        payload["fetch"]["browser"]["wait_selector"] = "a:not(:first-of-type)"
        errors = check_rule_selectors(payload)
        self.assertEqual(errors, [])

    def test_reports_multiple_errors_with_limit(self) -> None:
        errors = [
            {"path": f"extract.fields.f{index}", "selector": "a:not(:first-of-type)", "error": "bad"}
            for index in range(7)
        ]
        message = format_selector_errors(errors, limit=2)
        self.assertIn("extract.fields.f0", message)
        self.assertIn("5 more", message)


if __name__ == "__main__":
    unittest.main()
