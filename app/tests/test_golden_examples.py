from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from ecom_crawler.pipeline import export_run
from ecom_crawler.validate import validate_run, validate_task_result

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "docs" / "示例"


class DocsExampleTests(unittest.TestCase):
    """Run the published synthetic examples through the production pipeline."""

    def test_examples_reproduce_csv_and_task_result(self) -> None:
        product_records = json.loads(
            (EXAMPLES / "商品记录.json").read_text(encoding="utf-8")
        )
        excluded_records = json.loads(
            (EXAMPLES / "排除记录.json").read_text(encoding="utf-8")
        )
        task_result = json.loads(
            (EXAMPLES / "任务结果.json").read_text(encoding="utf-8")
        )
        zero = excluded_records[0]
        zero_candidate = {
            "source_url": zero["source_url"],
            "name": "Free Sample",
            "price": zero["observed_price"],
            "primary_image_url": "https://shop.example/images/sample.jpg",
            "description_html": "<p>Sample product.</p>",
            "description_format": "html",
            "description_status": "COMPLETE",
            "categories": ["Samples"],
            "brand": None,
            "options": [],
            "market": "GB",
            "locale": "en-GB",
            "availability": None,
            "tax_basis": "NOT_SPECIFIED",
            "extracted_at": "2026-10-27T14:02:00Z",
        }
        candidates = list(product_records) + [zero_candidate]

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            out_dir = root / "out"
            run_dir.mkdir()
            (run_dir / "task.json").write_text(
                json.dumps(task_result, ensure_ascii=False), encoding="utf-8"
            )
            (run_dir / "candidates.jsonl").write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in candidates) + "\n",
                encoding="utf-8",
            )
            export_run(run_dir, out_dir)

            actual_rows = list(
                csv.DictReader(
                    io.StringIO(
                        (out_dir / "products.csv").read_text(encoding="utf-8")
                    )
                )
            )
            expected_rows = list(
                csv.DictReader(
                    io.StringIO(
                        (EXAMPLES / "商品导出.csv").read_text(encoding="utf-8")
                    )
                )
            )
            self.assertEqual(actual_rows, expected_rows)

            actual = json.loads(
                (out_dir / "task-result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(actual["counts"], task_result["counts"])
            self.assertEqual(actual["outcome"], task_result["outcome"])
            self.assertEqual(actual["state"], task_result["state"])
            self.assertEqual(actual["stop_reason"], task_result["stop_reason"])
            self.assertEqual(actual["coverage"], task_result["coverage"])
            self.assertEqual(
                actual["business_acceptance"], task_result["business_acceptance"]
            )
            self.assertEqual(
                actual["quality_exceptions"], task_result["quality_exceptions"]
            )
            self.assertEqual(actual["runtime"], task_result["runtime"])
            self.assertEqual(actual["synthetic_example"], True)

            self.assertEqual(validate_run(out_dir), [])
            self.assertEqual(validate_task_result(actual), [])


if __name__ == "__main__":
    unittest.main()
