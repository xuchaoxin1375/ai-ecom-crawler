from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ecom_crawler.runtime.analysis import build_analysis, clear_analysis_cache
from ecom_crawler.runtime.models import Task

NOW = datetime(2026, 11, 26, 22, 10, 30, tzinfo=UTC)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


class AnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_analysis_cache()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.task_dir = self.root / "task-1"
        self.task_dir.mkdir()
        self.task = Task(
            task_id="task-1",
            plan_id="fixture",
            plan_version="1",
            task_type="product",
            state="FINISHED",
            started_at="2026-11-26T22:07:09Z",
            finished_at="2026-11-26T22:10:09Z",
            counters={"run_seconds": 180},
            limits={"max_products": 10, "max_requests": 20},
        )
        self.counts = {
            "processed_products": 5,
            "valid_products": 2,
            "excluded_products": 1,
            "failed_products": 2,
            "discovered_urls": 7,
            "product_candidates": 5,
            "pending_products": 0,
        }
        self.result = {
            "counts": self.counts,
            "failure_classes": {"transient": 0, "permanent": 2, "blocked": 0},
            "coverage": {"status": "PARTIAL", "denominator": 7, "covered": 5},
        }
        write_jsonl(
            self.task_dir / "events.ndjson",
            [
                {"ts": "2026-11-26T22:07:09Z", "event": "task_started"},
                {
                    "ts": "2026-11-26T22:07:10Z",
                    "event": "item_finished",
                    "item_type": "product",
                    "state": "DONE",
                },
                {
                    "ts": "2026-11-26T22:07:20Z",
                    "event": "item_finished",
                    "item_type": "product",
                    "state": "FAILED",
                },
                {
                    "ts": "2026-11-26T22:08:10Z",
                    "event": "item_finished",
                    "item_type": "product",
                    "state": "EXCLUDED",
                },
                {
                    "ts": "2026-11-26T22:09:10Z",
                    "event": "item_finished",
                    "item_type": "product",
                    "state": "DONE",
                },
                {
                    "ts": "2026-11-26T22:10:10Z",
                    "event": "item_finished",
                    "item_type": "product",
                    "state": "FAILED",
                },
                {"ts": "2026-11-26T22:10:09Z", "event": "task_finished"},
            ],
        )
        write_jsonl(
            self.task_dir / "items.jsonl",
            [
                {
                    "ts": "2026-11-26T22:07:20Z",
                    "item_type": "product",
                    "url": "https://fixture.test/p/1",
                    "state": "FAILED",
                    "failure_class": "permanent",
                    "result": {"reason": "validation_error"},
                },
                {
                    "ts": "2026-11-26T22:10:10Z",
                    "item_type": "product",
                    "url": "https://fixture.test/p/4",
                    "state": "FAILED",
                    "failure_class": "permanent",
                    "result": {"reason": "http_404"},
                },
            ],
        )
        write_jsonl(
            self.task_dir / "requests.ndjson",
            [
                {
                    "ts": "2026-11-26T22:07:05Z",
                    "attempt": 1,
                    "engine": "static",
                    "status": 200,
                },
                {
                    "ts": "2026-11-26T22:07:15Z",
                    "attempt": 2,
                    "engine": "static",
                    "status": 429,
                },
                {
                    "ts": "2026-11-26T22:08:05Z",
                    "attempt": 1,
                    "engine": "static",
                    "status": 0,
                    "error": "TimeoutError: timeout",
                },
                {
                    "ts": "2026-11-26T22:09:05Z",
                    "attempt": 1,
                    "engine": "static",
                    "status": 404,
                },
                {
                    "ts": "2026-11-26T22:10:05Z",
                    "attempt": 1,
                    "engine": "static",
                    "status": 200,
                },
            ],
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def build(self, **overrides):
        return build_analysis(
            self.task,
            self.task_dir,
            counts=overrides.pop("counts", self.counts),
            result=overrides.pop("result", self.result),
            now=overrides.pop("now", NOW),
            **overrides,
        )

    def test_item_and_request_series_share_buckets_and_cumulative_values(self) -> None:
        payload = self.build()
        self.assertEqual(payload["summary"]["processed"], 5)
        self.assertEqual(payload["summary"]["valid"], 2)
        self.assertEqual(payload["summary"]["failed"], 2)
        self.assertEqual(payload["summary"]["yield_rate"], 0.4)
        self.assertEqual(payload["summary"]["failure_rate"], 0.4)
        points = payload["series"]["points"]
        self.assertEqual([point["start"] for point in points], [
            "2026-11-26T22:07:00Z",
            "2026-11-26T22:08:00Z",
            "2026-11-26T22:09:00Z",
            "2026-11-26T22:10:00Z",
        ])
        self.assertEqual(points[0]["processed"], 2)
        self.assertEqual(points[0]["failed"], 1)
        self.assertEqual(points[0]["cumulative_processed"], 2)
        self.assertEqual(points[1]["processed"], 1)
        self.assertEqual(points[1]["cumulative_processed"], 3)
        self.assertEqual(points[2]["cumulative_processed"], 4)
        self.assertEqual(points[3]["cumulative_processed"], 5)
        self.assertTrue(points[3]["partial"])
        self.assertEqual(points[0]["requests"], {
            "total": 2,
            "retries": 1,
            "errors": 1,
            "rate_limited": 1,
        })
        self.assertEqual(points[3]["cumulative_requests"]["total"], 5)

    def test_request_summary_separates_status_classes_and_errors(self) -> None:
        payload = self.build()
        requests = payload["requests"]
        self.assertTrue(requests["available"])
        self.assertEqual(requests["total"], 5)
        self.assertEqual(requests["retries"], 1)
        self.assertEqual(requests["errors"], 3)
        self.assertEqual(requests["rate_limited"], 1)
        self.assertEqual(requests["status_classes"], {
            "2xx": 2,
            "3xx": 0,
            "4xx": 2,
            "5xx": 0,
            "none": 1,
        })
        self.assertEqual(payload["budget"]["used_requests"], 5)

    def test_failure_reasons_and_recent_window_keep_global_cumulative(self) -> None:
        payload = self.build(window_seconds=120)
        points = payload["series"]["points"]
        self.assertEqual(
            [point["start"] for point in points],
            [
                "2026-11-26T22:08:00Z",
                "2026-11-26T22:09:00Z",
                "2026-11-26T22:10:00Z",
            ],
        )
        self.assertEqual(points[0]["cumulative_processed"], 3)
        self.assertEqual(points[-1]["cumulative_processed"], 5)
        self.assertEqual(payload["failures"]["total"], 2)
        self.assertEqual(payload["failures"]["by_reason"][0]["code"], "validation_error")
        self.assertEqual(payload["failures"]["by_reason"][1]["code"], "http_404")
        self.assertEqual(
            payload["failures"]["by_reason"][0]["sample_url"],
            "https://fixture.test/p/1",
        )

    def test_legacy_run_without_request_log_is_explicit(self) -> None:
        (self.task_dir / "requests.ndjson").unlink()
        payload = self.build()
        self.assertFalse(payload["requests"]["available"])
        self.assertEqual(payload["requests"]["reason"], "legacy")
        self.assertNotIn("total", payload["requests"])
        self.assertEqual(payload["data_quality"]["level"], "full")

    def test_legacy_failure_reasons_are_flagged(self) -> None:
        (self.task_dir / "items.jsonl").unlink()
        payload = self.build()
        self.assertTrue(payload["data_quality"]["legacy_reasons"])
        self.assertEqual(payload["data_quality"]["level"], "legacy")
        self.assertEqual(payload["failures"]["total"], 2)
        self.assertEqual(payload["failures"]["by_class"]["permanent"], 2)

    def test_truncated_request_log_is_visible(self) -> None:
        write_jsonl(
            self.task_dir / "requests.ndjson",
            [
                {
                    "ts": "2026-11-26T22:07:05Z",
                    "attempt": 1,
                    "engine": "static",
                    "status": 200,
                },
                {"ts": "2026-11-26T22:10:20Z", "event": "truncated", "reason": "records"},
            ],
        )
        payload = self.build()
        self.assertTrue(payload["requests"]["truncated"])
        self.assertEqual(payload["data_quality"]["level"], "partial")
        self.assertEqual(payload["diagnostics"][0]["code"], "request_log_truncated")

    def test_legacy_items_without_item_type_still_count_failures(self) -> None:
        rows = [
            json.loads(line)
            for line in (self.task_dir / "items.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        for row in rows:
            row.pop("item_type", None)
        write_jsonl(self.task_dir / "items.jsonl", rows)
        payload = self.build()
        self.assertEqual(payload["failures"]["total"], 2)
        self.assertEqual(len(payload["failures"]["by_reason"]), 2)

    def test_corrupt_line_is_skipped_and_flagged(self) -> None:
        with (self.task_dir / "events.ndjson").open("a", encoding="utf-8") as handle:
            handle.write("not-json\n")
        payload = self.build()
        self.assertEqual(payload["data_quality"]["skipped_lines"], 1)
        self.assertEqual(payload["data_quality"]["level"], "partial")
        self.assertEqual(payload["summary"]["processed"], 5)

    def test_discovery_task_uses_product_items_for_url_candidates(self) -> None:
        self.task.task_type = "discovery"
        counts = {
            "discovered_urls": 7,
            "url_candidates": 5,
            "valid_urls": 2,
            "excluded_urls": 1,
            "failed_urls": 2,
            "pending_urls": 0,
        }
        result = {
            "counts": counts,
            "failure_classes": {"transient": 0, "permanent": 2, "blocked": 0},
            "coverage": {"status": "PARTIAL", "denominator": 7, "covered": 5},
        }
        payload = self.build(counts=counts, result=result)
        self.assertEqual(payload["summary"]["processed"], 5)
        self.assertEqual(payload["summary"]["valid"], 2)
        self.assertEqual(payload["summary"]["excluded"], 1)
        self.assertEqual(payload["summary"]["failed"], 2)
        self.assertEqual(payload["summary"]["product_candidates"], 5)
        self.assertTrue(payload["series"]["points"])
        self.assertEqual(payload["budget"]["used_urls"], 5)
        self.assertEqual(payload["failures"]["total"], 2)

    def test_points_are_capped_to_the_most_recent_720(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            task_dir = Path(temporary)
            events = []
            for minute in range(721):
                stamp = datetime(2026, 11, 26, tzinfo=UTC) + timedelta(minutes=minute)
                events.append(
                    {
                        "ts": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "event": "item_finished",
                        "item_type": "product",
                        "state": "DONE",
                    }
                )
            write_jsonl(task_dir / "events.ndjson", events)
            task = Task(
                task_id="task-720",
                plan_id="fixture",
                plan_version="1",
                task_type="product",
                state="FINISHED",
                started_at="2026-11-26T00:00:00Z",
                finished_at="2026-11-26T12:00:00Z",
                counters={"run_seconds": 43200},
            )
            payload = build_analysis(
                task,
                task_dir,
                counts={
                    "processed_products": 721,
                    "valid_products": 721,
                    "failed_products": 0,
                },
                result={},
                bucket_seconds=60,
                now=datetime(2026, 11, 26, 12, 30, tzinfo=UTC),
            )
        self.assertEqual(len(payload["series"]["points"]), 720)
        self.assertTrue(payload["scope"]["truncated"])
        self.assertEqual(payload["scope"]["first_bucket_at"], "2026-11-26T00:01:00Z")

    def test_queued_task_returns_empty_state(self) -> None:
        self.task.state = "QUEUED"
        self.task.started_at = None
        payload = self.build()
        self.assertEqual(payload["scope"]["state"], "QUEUED")
        self.assertEqual(payload["series"]["points"], [])
        self.assertEqual(payload["requests"]["reason"], "not_started")
        self.assertEqual(payload["data_quality"]["level"], "empty")


if __name__ == "__main__":
    unittest.main()
