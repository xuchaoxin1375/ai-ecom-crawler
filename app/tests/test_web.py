from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from ecom_crawler.runtime.models import Task, WorkItem
from ecom_crawler.runtime.store import TaskStore
from ecom_crawler.web.app import create_app


def make_task(task_id: str, state: str = "FINISHED", task_type: str = "product") -> Task:
    return Task(
        task_id=task_id,
        plan_id="fixture-web",
        plan_version="1.0.0",
        task_type=task_type,
        state=state,
        outcome="COMPLETED" if state == "FINISHED" else None,
        stop_reason="NATURAL_END" if state == "FINISHED" else None,
    )


class WebApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "tasks.db"
        self.out_root = self.root / "tasks"
        self.store = TaskStore(self.db_path)
        self.store.create_task(make_task("task-1"))
        task_dir = self.out_root / "task-1"
        task_dir.mkdir(parents=True)
        (task_dir / "task-result.json").write_text(
            json.dumps(
                {
                    "counts": {
                        "discovered_urls": 2,
                        "valid_products": 1,
                        "excluded_products": 0,
                        "failed_products": 0,
                    },
                    "coverage": {"status": "KNOWN", "denominator": 2, "covered": 2},
                    "quality_exceptions": [{"field": "brand", "reason": "missing"}],
                }
            ),
            encoding="utf-8",
        )
        (task_dir / "products.csv").write_text("source_url,name\n", encoding="utf-8")
        (task_dir / "records.jsonl").write_text("{}\n", encoding="utf-8")
        (task_dir / "diagnostics").mkdir()
        (task_dir / "diagnostics" / "excluded.jsonl").write_text("", encoding="utf-8")
        (task_dir / "secret.txt").write_text("not exported\n", encoding="utf-8")

        for index, state in enumerate(("DONE", "DONE", "FAILED")):
            self.store.add_item(
                WorkItem(
                    task_id="task-1",
                    item_id=f"p-{index}",
                    item_type="product",
                    url=f"https://fixture.test/p{index}.html",
                    normalized_url=f"https://fixture.test/p{index}.html",
                    state=state,
                    stage="product",
                )
            )
        self.store.add_item(
            WorkItem(
                task_id="task-1",
                item_id="nav-1",
                item_type="navigation",
                url="https://fixture.test/",
                normalized_url="https://fixture.test/",
                state="DONE",
                stage="discover",
            )
        )
        self.client = TestClient(create_app(self.db_path, self.out_root))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_health_and_read_only_index(self) -> None:
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        index = self.client.get("/")
        self.assertEqual(index.status_code, 200)
        self.assertIn("只读", index.text)

    def test_list_detail_and_filters(self) -> None:
        payload = self.client.get("/api/tasks").json()
        self.assertEqual(payload["total"], 1)
        task = payload["items"][0]
        self.assertEqual(task["task_id"], "task-1")
        self.assertEqual(task["counts"]["valid_products"], 1)
        self.assertEqual(task["coverage"]["status"], "KNOWN")
        self.assertEqual(len(task["quality_exceptions"]), 1)

        self.assertEqual(self.client.get("/api/tasks?state=FINISHED").json()["total"], 1)
        self.assertEqual(self.client.get("/api/tasks?state=RUNNING").json()["total"], 0)
        self.assertEqual(self.client.get("/api/tasks?task_type=discovery").json()["total"], 0)

        detail = self.client.get("/api/tasks/task-1")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["plan_id"], "fixture-web")
        self.assertEqual(self.client.get("/api/tasks/missing").status_code, 404)

    def test_items_pagination(self) -> None:
        payload = self.client.get("/api/tasks/task-1/items?kind=product&limit=2").json()
        self.assertEqual(payload["total"], 3)
        self.assertEqual(len(payload["items"]), 2)
        second = self.client.get(
            "/api/tasks/task-1/items?kind=product&limit=2&offset=2"
        ).json()
        self.assertEqual(len(second["items"]), 1)
        urls = self.client.get("/api/tasks/task-1/items?kind=url").json()
        self.assertEqual(urls["total"], 1)
        self.assertEqual(urls["items"][0]["item_type"], "navigation")

    def test_export_zip_uses_allowlist(self) -> None:
        response = self.client.get("/api/tasks/task-1/export")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = set(archive.namelist())
        self.assertEqual(
            names,
            {"products.csv", "task-result.json", "records.jsonl", "diagnostics/excluded.jsonl"},
        )
        self.assertNotIn("secret.txt", names)

    def test_export_requires_finished_task(self) -> None:
        self.store.create_task(make_task("running-1", state="RUNNING"))
        response = self.client.get("/api/tasks/running-1/export")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "EXPORT_NOT_READY")
        partial = self.client.get("/api/tasks/running-1/export?partial=true")
        self.assertEqual(partial.status_code, 404)


if __name__ == "__main__":
    unittest.main()
