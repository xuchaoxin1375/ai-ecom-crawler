from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from ecom_crawler.runtime.models import Task, WorkItem
from ecom_crawler.runtime.store import TaskStore
from ecom_crawler.web.app import create_app

CLIENT_HEADERS = {
    "Host": "127.0.0.1:8765",
    "Origin": "http://127.0.0.1:8765",
    "X-Requested-With": "XMLHttpRequest",
}


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
        self.rules_dir = self.root / "rules"
        self.rules_dir.mkdir()
        self.rule_source = (
            Path(__file__).parents[2]
            / "experiments"
            / "d03"
            / "familidoo"
            / "familidoo-d03.yaml"
        )
        shutil.copy(self.rule_source, self.rules_dir / "familidoo.yaml")
        self.client = TestClient(
            create_app(self.db_path, self.out_root, self.rules_dir),
            headers=CLIENT_HEADERS,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _client_with(self, headers: dict[str, str]) -> TestClient:
        return TestClient(
            create_app(self.db_path, self.out_root, self.rules_dir),
            headers=headers,
        )

    def test_health_and_read_only_index(self) -> None:
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        index = self.client.get("/")
        self.assertEqual(index.status_code, 200)
        self.assertIn("采集", index.text)

    def test_managed_worker_lifespan(self) -> None:
        app = create_app(
            self.db_path,
            self.out_root,
            self.rules_dir,
            manage_worker=True,
        )
        with TestClient(app, headers=CLIENT_HEADERS) as client:
            health = client.get("/api/health").json()
            self.assertEqual(health["worker"], "managed")
            self.assertEqual(health["max_tasks"], 1)

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

    def _first_rule(self) -> dict:
        payload = self.client.get("/api/rules").json()
        self.assertTrue(payload["configured"])
        self.assertTrue(payload["items"])
        return payload["items"][0]

    def test_rules_catalog_and_create_idempotency(self) -> None:
        rules = self.client.get("/api/rules")
        self.assertEqual(rules.status_code, 200)
        payload = rules.json()
        self.assertTrue(payload["configured"])
        rule = payload["items"][0]
        self.assertTrue(rule["valid"])
        self.assertIn("product", rule["task_types"])
        self.assertNotIn(":\\\\", rule["path"])

        body = {
            "request_id": "req-1",
            "rule_id": rule["rule_id"],
            "rule_version": rule["rule_version"],
            "task_type": "product",
            "limits": {"max_products": 6, "max_seconds": 30, "max_attempts": 1},
        }
        created = self.client.post("/api/tasks", json=body)
        self.assertEqual(created.status_code, 201)
        first = created.json()
        self.assertTrue(first["created"])
        task_id = first["task"]["task_id"]
        self.assertEqual(first["task"]["state"], "DRAFT")
        self.assertIsNotNone(first["task"]["market"])

        replay = self.client.post("/api/tasks", json=body)
        self.assertEqual(replay.status_code, 200)
        self.assertFalse(replay.json()["created"])
        self.assertEqual(replay.json()["task"]["task_id"], task_id)

        conflict_body = dict(body)
        conflict_body["limits"] = {"max_products": 3}
        conflict = self.client.post("/api/tasks", json=conflict_body)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["error"]["code"], "CONFLICT")

        start = self.client.post(f"/api/tasks/{task_id}/start")
        self.assertEqual(start.status_code, 202)
        self.assertEqual(start.json()["state"], "QUEUED")
        pause = self.client.post(f"/api/tasks/{task_id}/pause")
        self.assertEqual(pause.status_code, 409)
        self.assertEqual(pause.json()["error"]["code"], "INVALID_STATE")
        cancel = self.client.post(f"/api/tasks/{task_id}/cancel")
        self.assertEqual(cancel.status_code, 202)
        self.assertEqual(cancel.json()["state"], "CANCELLED")

        archive = self.client.post(f"/api/tasks/{task_id}/archive")
        self.assertEqual(archive.status_code, 202)
        self.assertIsNotNone(archive.json()["archived_at"])
        default_list = self.client.get("/api/tasks").json()
        self.assertNotIn(task_id, [item["task_id"] for item in default_list["items"]])
        archived_list = self.client.get("/api/tasks?include_archived=true").json()
        self.assertIn(task_id, [item["task_id"] for item in archived_list["items"]])

        restore = self.client.post(f"/api/tasks/{task_id}/restore")
        self.assertEqual(restore.status_code, 202)
        self.assertIsNone(restore.json()["archived_at"])
        default_list = self.client.get("/api/tasks").json()
        self.assertIn(task_id, [item["task_id"] for item in default_list["items"]])

    def test_archive_running_task_is_rejected(self) -> None:
        rule = self._first_rule()
        body = {
            "request_id": "req-archive-running",
            "rule_id": rule["rule_id"],
            "rule_version": rule["rule_version"],
            "task_type": "product",
        }
        task_id = self.client.post("/api/tasks", json=body).json()["task"]["task_id"]
        self.client.post(f"/api/tasks/{task_id}/start")
        response = self.client.post(f"/api/tasks/{task_id}/archive")
        self.assertEqual(response.status_code, 409)

    def test_events_stream_snapshot_and_end(self) -> None:
        rule = self._first_rule()
        body = {
            "request_id": "req-events",
            "rule_id": rule["rule_id"],
            "rule_version": rule["rule_version"],
            "task_type": "product",
        }
        task_id = self.client.post("/api/tasks", json=body).json()["task"]["task_id"]
        self.client.post(f"/api/tasks/{task_id}/cancel")
        lines: list[str] = []
        with self.client.stream("GET", f"/api/tasks/{task_id}/events") as response:
            self.assertEqual(response.status_code, 200)
            for line in response.iter_lines():
                lines.append(line)
                if line == "event: end":
                    break
        text = "\n".join(lines)
        self.assertIn("event: snapshot", text)
        self.assertIn("event: end", text)

    def test_write_requires_same_origin_and_requested_with(self) -> None:
        rule = self._first_rule()
        body = {
            "request_id": "req-guard",
            "rule_id": rule["rule_id"],
            "rule_version": rule["rule_version"],
            "task_type": "product",
        }
        cross = self._client_with(
            {
                "Host": "127.0.0.1:8765",
                "Origin": "http://evil.test",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        response = cross.post("/api/tasks", json=body)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "FORBIDDEN")

        null_origin = self._client_with(
            {
                "Host": "127.0.0.1:8765",
                "Origin": "null",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        self.assertEqual(null_origin.post("/api/tasks", json=body).status_code, 403)

        missing_header = self._client_with(
            {
                "Host": "127.0.0.1:8765",
                "Origin": "http://127.0.0.1:8765",
            }
        )
        self.assertEqual(missing_header.post("/api/tasks", json=body).status_code, 403)

        bad_host = self._client_with(
            {
                "Host": "evil.test",
                "Origin": "http://127.0.0.1:8765",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        self.assertEqual(bad_host.get("/api/health").status_code, 403)

        read_only = self._client_with({"Host": "127.0.0.1:8765"})
        self.assertEqual(read_only.get("/api/health").status_code, 200)

        valid = self.client.post(
            "/api/tasks",
            json={**body, "request_id": "req-guard-ok"},
        )
        self.assertEqual(valid.status_code, 201)

    def test_items_limit_is_bounded(self) -> None:
        self.assertEqual(
            self.client.get("/api/tasks/task-1/items?limit=200").status_code,
            200,
        )
        self.assertEqual(
            self.client.get("/api/tasks/task-1/items?limit=201").status_code,
            422,
        )
        self.assertEqual(
            self.client.get("/api/tasks/task-1/items?limit=0").status_code,
            422,
        )

    def test_rule_lookup_rejects_path_traversal(self) -> None:
        rule = self._first_rule()
        body = {
            "request_id": "req-traversal",
            "rule_id": "../outside",
            "rule_version": rule["rule_version"],
            "task_type": "product",
        }
        response = self.client.post("/api/tasks", json=body)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "NOT_FOUND")

    def test_rule_catalog_skips_symlink_escape(self) -> None:
        outside = self.root / "outside.yaml"
        shutil.copy(self.rule_source, outside)
        link = self.rules_dir / "escape.yaml"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is unavailable")
        payload = self.client.get("/api/rules").json()
        self.assertNotIn("escape.yaml", [item["path"] for item in payload["items"]])

    def test_not_found_does_not_leak_absolute_paths(self) -> None:
        response = self.client.get("/api/tasks/missing")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(str(self.root), response.text)


if __name__ == "__main__":
    unittest.main()
