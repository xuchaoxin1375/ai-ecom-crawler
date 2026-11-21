from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ecom_crawler.bridge import convert_task_to_run_dir, export_description_status, to_candidate

TASK = {"market": "FR", "locale": "fr-FR", "finished_at": "2026-11-21T00:00:00Z"}
PRODUCT = {
    "source_url": "https://example.test/p1.html",
    "name": "Example",
    "price_amount": 9.99,
    "price_currency": "EUR",
    "primary_image_url": "https://example.test/1.jpg",
    "description_html": "<p>Body.</p>",
    "description_status": "fallback",
    "category": "Textiles",
    "brand": "Example",
    "attributes": "",
    "field_sources": {"name": "json_ld"},
}


class BridgeStatusTests(unittest.TestCase):
    def test_runtime_fallback_maps_to_summary_fallback(self) -> None:
        candidate = to_candidate(PRODUCT, TASK)
        self.assertEqual(candidate["description_status"], "SUMMARY_FALLBACK")

    def test_partial_reason_override_uses_export_status(self) -> None:
        product = {**PRODUCT, "description_status": "partial"}
        candidate = to_candidate(product, TASK, partial_reason="specifications omitted")
        self.assertEqual(candidate["description_status"], "PARTIAL")
        self.assertEqual(candidate["partial_reason"], "specifications omitted")

    def test_known_status_aliases(self) -> None:
        self.assertEqual(export_description_status("complete"), "COMPLETE")
        self.assertEqual(export_description_status("not_provided"), "NOT_PROVIDED")
        self.assertEqual(export_description_status("failed"), "FAILED")
        self.assertEqual(export_description_status("SUMMARY_FALLBACK"), "SUMMARY_FALLBACK")

    def test_converted_run_dir_uses_lf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task_result = root / "task-result.json"
            products = root / "products.jsonl"
            out_dir = root / "app-run"
            task_result.write_text(
                json.dumps(
                    {
                        "task_id": "bridge-001",
                        "market": "FR",
                        "locale": "fr-FR",
                        "finished_at": "2026-11-21T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            products.write_text(json.dumps(PRODUCT) + "\n", encoding="utf-8")
            convert_task_to_run_dir(task_result, products, out_dir)
            self.assertNotIn(b"\r\n", (out_dir / "task.json").read_bytes())
            self.assertNotIn(b"\r\n", (out_dir / "candidates.jsonl").read_bytes())


if __name__ == "__main__":
    unittest.main()
