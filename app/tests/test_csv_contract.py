from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from ecom_crawler.model import CSV_COLUMNS
from ecom_crawler.pipeline import export_candidates, export_run, render_products_csv
from tests.support import base_task, candidate


class CsvFidelityTests(unittest.TestCase):
    def test_nine_columns_and_text_escaping(self) -> None:
        item = candidate(
            source_url="https://shop.example/products/tricky",
            name='=SUM(A1) 商品, "引号"',
            brand="+Brand",
            description_html='<p>第一行<br>第二行</p><p>中文 &amp; 符号</p>',
            options=[{"name": "Size#1", "values": ["S|M", "Red~Blue", "back\\slash"]}],
        )
        result = export_candidates(base_task(), [item])
        text = render_products_csv(result.products)
        reader = csv.DictReader(io.StringIO(text))
        self.assertEqual(list(reader.fieldnames or []), list(CSV_COLUMNS))
        rows = list(reader)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["name"], "'=SUM(A1) 商品, \"引号\"")
        self.assertEqual(row["price_amount"], "29.00")
        self.assertEqual(row["price_currency"], "GBP")
        self.assertEqual(row["description_html"], result.products[0].description_html)
        self.assertEqual(row["attributes"], "Size\\#1#S\\|M|Red\\~Blue|back\\\\slash")
        self.assertEqual(row["brand"], "'+Brand")
        self.assertEqual(row["source_url"], "https://shop.example/products/tricky")

    def test_export_run_writes_task_result_with_escaped_json(self) -> None:
        item = candidate(
            source_url="https://shop.example/products/partial",
            description_status="PARTIAL",
            partial_reason='He said "complex".',
            missing_reasons={"brand": 'Not "provided"'},
            brand=None,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            out_dir = root / "out"
            run_dir.mkdir()
            (run_dir / "task.json").write_text(
                json.dumps(base_task()), encoding="utf-8"
            )
            (run_dir / "candidates.jsonl").write_text(
                json.dumps(item, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            result = export_run(run_dir, out_dir)
            self.assertTrue((out_dir / "products.csv").is_file())
            self.assertTrue((out_dir / "task-result.json").is_file())
            self.assertTrue((out_dir / "records.jsonl").is_file())
            self.assertTrue((out_dir / "diagnostics" / "excluded.jsonl").is_file())
            payload = json.loads(
                (out_dir / "task-result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                payload["quality_exceptions"][0]["partial_reason"],
                'He said "complex".',
            )
            self.assertEqual(
                payload["quality_exceptions"][0]["missing_reasons"],
                {"brand": 'Not "provided"'},
            )
            self.assertEqual(result.task_result["counts"]["partial_description_products"], 1)


if __name__ == "__main__":
    unittest.main()
