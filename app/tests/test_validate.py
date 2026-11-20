from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from ecom_crawler.pipeline import export_candidates, export_run
from ecom_crawler.validate import validate_run, validate_task_result
from tests.support import base_task, candidate


class TaskResultValidationTests(unittest.TestCase):
    def test_valid_result_passes(self) -> None:
        result = export_candidates(base_task(), [candidate()])
        self.assertEqual(validate_task_result(result.task_result), [])

    def test_count_invariant_is_checked(self) -> None:
        result = export_candidates(base_task(), [candidate()])
        payload = json.loads(json.dumps(result.task_result))
        payload["counts"]["valid_products"] = 2
        errors = validate_task_result(payload)
        self.assertTrue(any("processed" in error for error in errors), errors)

    def test_partial_exception_count_is_checked(self) -> None:
        item = candidate(
            description_status="PARTIAL",
            partial_reason="Compatibility table missing.",
        )
        result = export_candidates(base_task(), [item])
        payload = json.loads(json.dumps(result.task_result))
        payload["counts"]["partial_description_products"] = 0
        errors = validate_task_result(payload)
        self.assertTrue(
            any("partial_description_products" in error for error in errors), errors
        )

    def test_unknown_coverage_rejects_denominator(self) -> None:
        result = export_candidates(base_task(), [candidate()])
        payload = json.loads(json.dumps(result.task_result))
        payload["coverage"]["denominator"] = 10
        errors = validate_task_result(payload)
        self.assertTrue(any("UNKNOWN coverage" in error for error in errors), errors)


class RunValidationTests(unittest.TestCase):
    def test_exported_run_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            out_dir = root / "out"
            run_dir.mkdir()
            (run_dir / "task.json").write_text(json.dumps(base_task()), encoding="utf-8")
            (run_dir / "candidates.jsonl").write_text(
                json.dumps(candidate(), ensure_ascii=False) + "\n", encoding="utf-8"
            )
            export_run(run_dir, out_dir)
            self.assertEqual(validate_run(out_dir), [])

    def test_records_url_mismatch_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            out_dir = root / "out"
            run_dir.mkdir()
            (run_dir / "task.json").write_text(json.dumps(base_task()), encoding="utf-8")
            (run_dir / "candidates.jsonl").write_text(
                json.dumps(candidate(), ensure_ascii=False) + "\n", encoding="utf-8"
            )
            export_run(run_dir, out_dir)
            records = [
                json.loads(line)
                for line in (out_dir / "records.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            records[0]["source_url"] = "https://shop.example/products/other"
            (out_dir / "records.jsonl").write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            errors = validate_run(out_dir)
            self.assertTrue(
                any("source_url order" in error for error in errors), errors
            )

    def test_csv_row_count_mismatch_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            out_dir = root / "out"
            run_dir.mkdir()
            (run_dir / "task.json").write_text(json.dumps(base_task()), encoding="utf-8")
            (run_dir / "candidates.jsonl").write_text(
                json.dumps(candidate(), ensure_ascii=False) + "\n", encoding="utf-8"
            )
            export_run(run_dir, out_dir)
            with (out_dir / "products.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            with (out_dir / "products.csv").open(
                "w", encoding="utf-8", newline=""
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
                writer.writerow(rows[0])
            errors = validate_run(out_dir)
            self.assertTrue(any("row count" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
