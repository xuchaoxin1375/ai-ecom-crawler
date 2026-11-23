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


def make_task(task_id: str, state: str = "FINISHED") -> Task:
    return Task(
        task_id=task_id,
        plan_id="example",
        plan_version="1.0.0",
        task_type="product",
        state=state,
        outcome="COMPLETED" if state == "FINISHED" else None,
        stop_reason="NATURAL_END" if state == "FINISHED" else None,
        site_key="example.fr",
        batch_id="b-1",
    )


class FeedbackApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "tasks.db"
        self.out_root = self.root / "tasks"
        self.rules_dir = self.root / "rules"
        self.rules_dir.mkdir()
        self.store = TaskStore(self.db_path)
        self.store.create_task(make_task("task-1"))
        self.store.create_task(make_task("task-running", state="RUNNING"))
        self.client = TestClient(
            create_app(self.db_path, self.out_root, self.rules_dir),
            headers=CLIENT_HEADERS,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _create(self, request_id: str = "fb-1", **overrides: object) -> dict:
        body = {
            "request_id": request_id,
            "category": "DESCRIPTION",
            "samples": ["https://example.fr/products/1"],
            "expectation": "描述应包含规格块",
            "note": "业务验收不通过",
        }
        body.update(overrides)
        response = self.client.post("/api/tasks/task-1/feedback", json=body)
        self.assertIn(response.status_code, {200, 201}, response.text)
        return response.json()

    def test_create_is_terminal_idempotent_and_conflict_checked(self) -> None:
        created = self._create()
        self.assertTrue(created["created"])
        feedback = created["feedback"]
        self.assertEqual(feedback["status"], "OPEN")
        self.assertEqual(feedback["task_id"], "task-1")
        self.assertEqual(feedback["site_key"], "example.fr")
        self.assertEqual(feedback["rule"]["rule_id"], "example")
        self.assertEqual(feedback["samples"], ["https://example.fr/products/1"])

        replay = self.client.post(
            "/api/tasks/task-1/feedback",
            json={
                "request_id": "fb-1",
                "category": "DESCRIPTION",
                "samples": ["https://example.fr/products/1"],
                "expectation": "描述应包含规格块",
                "note": "业务验收不通过",
            },
        )
        self.assertEqual(replay.status_code, 200)
        self.assertFalse(replay.json()["created"])
        self.assertEqual(
            replay.json()["feedback"]["feedback_id"],
            feedback["feedback_id"],
        )

        conflict = self.client.post(
            "/api/tasks/task-1/feedback",
            json={
                "request_id": "fb-1",
                "category": "DESCRIPTION",
                "samples": ["https://example.fr/products/1"],
                "expectation": "不同的期望",
            },
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["error"]["code"], "CONFLICT")

    def test_create_rejects_active_task_and_invalid_payload(self) -> None:
        active = self.client.post(
            "/api/tasks/task-running/feedback",
            json={
                "request_id": "fb-active",
                "category": "DESCRIPTION",
                "samples": ["https://example.fr/products/1"],
                "expectation": "描述应包含规格块",
            },
        )
        self.assertEqual(active.status_code, 409)
        self.assertEqual(active.json()["error"]["code"], "INVALID_TASK_STATE")

        bad_sample = self.client.post(
            "/api/tasks/task-1/feedback",
            json={
                "request_id": "fb-bad-sample",
                "category": "DESCRIPTION",
                "samples": ["not-a-url"],
                "expectation": "描述应包含规格块",
            },
        )
        self.assertEqual(bad_sample.status_code, 400)
        self.assertEqual(bad_sample.json()["error"]["code"], "VALIDATION_ERROR")

        missing_sample = self.client.post(
            "/api/tasks/task-1/feedback",
            json={
                "request_id": "fb-missing-sample",
                "category": "DESCRIPTION",
                "expectation": "描述应包含规格块",
            },
        )
        self.assertEqual(missing_sample.status_code, 400)
        self.assertEqual(missing_sample.json()["error"]["code"], "VALIDATION_ERROR")

    def test_list_detail_and_filters(self) -> None:
        first = self._create("fb-list-1")["feedback"]
        second = self._create(
            "fb-list-2",
            category="BUSINESS_EXPECTATION",
            samples=[],
            expectation="这个范围不适合本批次",
        )["feedback"]

        listing = self.client.get("/api/tasks/task-1/feedback")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["total"], 2)
        self.assertEqual(
            {item["feedback_id"] for item in listing.json()["items"]},
            {first["feedback_id"], second["feedback_id"]},
        )

        filtered = self.client.get("/api/tasks/task-1/feedback?status=OPEN")
        self.assertEqual(filtered.json()["total"], 2)

        by_site = self.client.get("/api/feedback?site_key=example.fr")
        self.assertEqual(by_site.json()["total"], 2)
        by_batch = self.client.get("/api/feedback?batch_id=b-1")
        self.assertEqual(by_batch.json()["total"], 2)
        missing = self.client.get("/api/feedback?site_key=missing.fr")
        self.assertEqual(missing.json()["total"], 0)

        detail = self.client.get(f"/api/feedback/{first['feedback_id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["feedback_id"], first["feedback_id"])
        unknown = self.client.get("/api/feedback/fb-missing")
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(unknown.json()["error"]["code"], "FEEDBACK_NOT_FOUND")

    def test_triage_rule_repair_and_duplicate(self) -> None:
        first = self._create("fb-triage-1")["feedback"]
        second = self._create("fb-triage-2")["feedback"]

        triaged = self.client.post(
            f"/api/feedback/{first['feedback_id']}/triage",
            json={"triage": "RULE_REPAIR", "note": "描述块缺失"},
        )
        self.assertEqual(triaged.status_code, 200)
        self.assertEqual(triaged.json()["feedback"]["status"], "TRIAGED")
        self.assertEqual(triaged.json()["feedback"]["triage"], "RULE_REPAIR")

        duplicate = self.client.post(
            f"/api/feedback/{second['feedback_id']}/triage",
            json={
                "triage": "DUPLICATE",
                "duplicate_of": first["feedback_id"],
                "note": "同一问题",
            },
        )
        self.assertEqual(duplicate.status_code, 200)
        body = duplicate.json()["feedback"]
        self.assertEqual(body["status"], "WONTFIX")
        self.assertEqual(body["resolution"], "DUPLICATE")
        self.assertEqual(body["resolved_by"], "local-user")
        self.assertIsNotNone(body["closed_at"])

        missing_target = self.client.post(
            f"/api/feedback/{second['feedback_id']}/triage",
            json={"triage": "DUPLICATE", "duplicate_of": "fb-missing"},
        )
        self.assertEqual(missing_target.status_code, 400)
        self.assertEqual(missing_target.json()["error"]["code"], "VALIDATION_ERROR")

        self_target = self.client.post(
            f"/api/feedback/{second['feedback_id']}/triage",
            json={"triage": "DUPLICATE", "duplicate_of": second["feedback_id"]},
        )
        self.assertEqual(self_target.status_code, 400)
        self.assertEqual(self_target.json()["error"]["code"], "VALIDATION_ERROR")

        invalid_duplicate = self.client.post(
            f"/api/feedback/{first['feedback_id']}/triage",
            json={"triage": "RULE_REPAIR", "duplicate_of": second["feedback_id"]},
        )
        self.assertEqual(invalid_duplicate.status_code, 400)
        self.assertEqual(
            invalid_duplicate.json()["error"]["code"], "VALIDATION_ERROR"
        )

    def test_openapi_exposes_feedback_contract(self) -> None:
        response = self.client.get("/api/openapi.json")
        self.assertEqual(response.status_code, 200)
        schema = response.json()
        paths = schema["paths"]
        for path in (
            "/api/tasks/{task_id}/feedback",
            "/api/feedback",
            "/api/feedback/{feedback_id}",
            "/api/feedback/{feedback_id}/triage",
        ):
            self.assertIn(path, paths)
        components = schema["components"]["schemas"]
        for name in (
            "FeedbackCreateRequest",
            "FeedbackRecord",
            "FeedbackCreateResponse",
            "FeedbackListResponse",
            "FeedbackTriageResponse",
        ):
            self.assertIn(name, components)

        snapshot = Path(__file__).parents[1] / "schemas" / "openapi.json"
        expected = json.loads(snapshot.read_text(encoding="utf-8"))
        self.assertEqual(schema, expected)

    def test_validation_error_uses_unified_envelope(self) -> None:
        response = self.client.post(
            "/api/tasks/task-1/feedback",
            json={"request_id": "fb-invalid"},
        )
        self.assertEqual(response.status_code, 422)
        body = response.json()
        self.assertEqual(body["error"]["code"], "VALIDATION_ERROR")
        self.assertIsInstance(body["error"]["details"]["errors"], list)
        self.assertTrue(body["error"]["details"]["errors"])


if __name__ == "__main__":
    unittest.main()
