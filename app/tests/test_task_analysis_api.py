from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ecom_crawler.runtime.models import Task
from ecom_crawler.runtime.store import TaskStore
from ecom_crawler.web.app import create_app

CLIENT_HEADERS = {
    "Host": "127.0.0.1:8765",
    "Origin": "http://127.0.0.1:8765",
    "X-Requested-With": "XMLHttpRequest",
}


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


class TaskAnalysisApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "tasks.db"
        self.out_root = self.root / "tasks"
        self.store = TaskStore(self.db_path)
        self.store.create_task(
            Task(
                task_id="task-1",
                plan_id="fixture",
                plan_version="1",
                task_type="product",
                state="FINISHED",
                outcome="COMPLETED",
                started_at="2026-11-26T22:07:09Z",
                finished_at="2026-11-26T22:10:09Z",
                counters={"run_seconds": 180},
                limits={"max_products": 10, "max_requests": 20},
            )
        )
        task_dir = self.out_root / "task-1"
        task_dir.mkdir(parents=True)
        write_jsonl(
            task_dir / "events.ndjson",
            [
                {"ts": "2026-11-26T22:07:09Z", "event": "task_started"},
                {
                    "ts": "2026-11-26T22:07:10Z",
                    "event": "item_finished",
                    "item_type": "product",
                    "state": "DONE",
                },
                {
                    "ts": "2026-11-26T22:08:10Z",
                    "event": "item_finished",
                    "item_type": "product",
                    "state": "FAILED",
                },
                {
                    "ts": "2026-11-26T22:09:10Z",
                    "event": "item_finished",
                    "item_type": "product",
                    "state": "DONE",
                },
                {"ts": "2026-11-26T22:10:09Z", "event": "task_finished"},
            ],
        )
        write_jsonl(
            task_dir / "items.jsonl",
            [
                {
                    "ts": "2026-11-26T22:08:10Z",
                    "item_type": "product",
                    "url": "https://fixture.test/p/1",
                    "state": "FAILED",
                    "failure_class": "permanent",
                    "result": {"reason": "validation_error"},
                }
            ],
        )
        write_jsonl(
            task_dir / "requests.ndjson",
            [
                {
                    "ts": "2026-11-26T22:07:05Z",
                    "attempt": 1,
                    "engine": "static",
                    "status": 200,
                },
                {
                    "ts": "2026-11-26T22:08:05Z",
                    "attempt": 2,
                    "engine": "static",
                    "status": 429,
                },
                {
                    "ts": "2026-11-26T22:09:05Z",
                    "attempt": 1,
                    "engine": "static",
                    "status": 200,
                },
            ],
        )
        (task_dir / "task-result.json").write_text(
            json.dumps(
                {
                    "counts": {
                        "processed_products": 3,
                        "valid_products": 2,
                        "excluded_products": 0,
                        "failed_products": 1,
                        "discovered_urls": 4,
                        "product_candidates": 3,
                        "pending_products": 0,
                    },
                    "failure_classes": {
                        "transient": 0,
                        "permanent": 1,
                        "blocked": 0,
                    },
                    "coverage": {
                        "status": "PARTIAL",
                        "denominator": 4,
                        "covered": 3,
                    },
                }
            ),
            encoding="utf-8",
        )
        self.client = TestClient(
            create_app(self.db_path, self.out_root, None),
            headers=CLIENT_HEADERS,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_analysis_endpoint_returns_series_and_request_metrics(self) -> None:
        response = self.client.get("/api/tasks/task-1/analysis")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["processed"], 3)
        self.assertEqual(payload["summary"]["valid"], 2)
        self.assertEqual(payload["summary"]["failed"], 1)
        self.assertEqual(len(payload["series"]["points"]), 3)
        self.assertTrue(payload["requests"]["available"])
        self.assertEqual(payload["requests"]["total"], 3)
        self.assertEqual(payload["requests"]["retries"], 1)
        self.assertEqual(payload["requests"]["rate_limited"], 1)
        self.assertEqual(payload["budget"]["used_requests"], 3)
        self.assertTrue(response.headers["ETag"].startswith('"'))
        self.assertEqual(response.headers["Cache-Control"], "private, max-age=15")

    def test_analysis_window_and_conditional_request(self) -> None:
        first = self.client.get(
            "/api/tasks/task-1/analysis",
            params={"window_seconds": 60, "bucket_seconds": 60},
        )
        self.assertEqual(first.status_code, 200)
        payload = first.json()
        self.assertEqual(payload["scope"]["window_seconds"], 60)
        self.assertEqual(len(payload["series"]["points"]), 1)
        etag = first.headers["ETag"]
        cached = self.client.get(
            "/api/tasks/task-1/analysis",
            params={"window_seconds": 60, "bucket_seconds": 60},
            headers={"If-None-Match": etag},
        )
        self.assertEqual(cached.status_code, 304)
        self.assertEqual(cached.content, b"")

    def test_old_run_reports_missing_request_log(self) -> None:
        (self.out_root / "task-1" / "requests.ndjson").unlink()
        response = self.client.get("/api/tasks/task-1/analysis")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["requests"]["available"])
        self.assertEqual(payload["requests"]["reason"], "legacy")
        self.assertNotIn("total", payload["requests"])

    def test_unknown_task_is_404(self) -> None:
        response = self.client.get("/api/tasks/missing/analysis")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
