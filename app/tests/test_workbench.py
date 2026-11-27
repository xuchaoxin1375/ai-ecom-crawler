from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ecom_crawler.runtime.models import WorkbenchNode, WorkItem
from ecom_crawler.runtime.rule import load_rule
from ecom_crawler.runtime.store import TaskStore
from ecom_crawler.web.app import create_app
from tests.test_execution import RULE_TEMPLATE

CLIENT_HEADERS = {
    "Host": "127.0.0.1:8765",
    "Origin": "http://127.0.0.1:8765",
    "X-Requested-With": "XMLHttpRequest",
}


class WorkbenchStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = TaskStore(self.root / "tasks.db")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_create_nodes_and_dismiss_runs_are_incremental(self) -> None:
        group = self.store.create_workbench_group(
            WorkbenchNode(node_id="g-1", node_type="group", name="法国")
        )
        self.assertEqual(group.node_id, "g-1")
        self.assertEqual(self.store.list_workbench_nodes()[0].name, "法国")
        self.assertIsNone(self.store.get_workbench_node("missing"))
        self.assertEqual(self.store.list_workbench_dismissals(), set())
        self.store.dismiss_workbench_runs(["task-1"])
        self.assertEqual(self.store.list_workbench_dismissals(), {"task-1"})
        self.store.restore_workbench_runs(["task-1"])
        self.assertEqual(self.store.list_workbench_dismissals(), set())

    def test_workbench_tables_are_created_for_existing_ledgers(self) -> None:
        with self.store._connect() as connection:
            names = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertIn("workbench_nodes", names)
        self.assertIn("workbench_task_defs", names)
        self.assertIn("workbench_task_runs", names)
        self.assertIn("workbench_recent_dismissals", names)


class WorkbenchApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "tasks.db"
        self.out_root = self.root / "out"
        self.out_root.mkdir()
        self.rules_dir = self.root / "rules"
        self.rules_dir.mkdir()
        (self.rules_dir / "fixture.yaml").write_text(
            RULE_TEMPLATE.replace("__BASE__", "https://fixture.example"),
            encoding="utf-8",
        )
        self.client = TestClient(
            create_app(self.db_path, self.out_root, self.rules_dir),
            headers=CLIENT_HEADERS,
        )
        self.store = TaskStore(self.db_path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_task_node(self) -> tuple[str, str]:
        group = self.client.post(
            "/api/workbench/groups",
            json={"name": "独立任务"},
        )
        self.assertEqual(group.status_code, 201, group.text)
        group_id = group.json()["node"]["node_id"]
        created = self.client.post(
            "/api/workbench/tasks",
            json={
                "name": "fixture.example",
                "input_url": "https://fixture.example/",
                "parent_id": group_id,
                "rule_id": "fixture-local",
                "rule_version": "2026.11.21-1",
                "task_type": "product",
                "collection_mode": "formal",
                "country": "GB",
                "language": "en-GB",
                "market": "GB",
                "category": "toy",
                "limits": {
                    "max_urls": 10,
                    "max_products": 3,
                    "max_seconds": 60,
                    "max_attempts": 1,
                },
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        return group_id, created.json()["node"]["node_id"]

    def create_batch(self, name: str = "fixture batch") -> str:
        created = self.client.post(
            "/api/batches",
            json={
                "name": name,
                "sites": ["https://fixture.example/"],
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        batch_id = created.json()["batch"]["batch_id"]
        site = self.store.get_batch_site(batch_id, "fixture.example")
        self.assertIsNotNone(site)
        self.store.update_batch_site(
            batch_id,
            "fixture.example",
            readiness="ready",
            rule_id="fixture-local",
            rule_version="2026.11.21-1",
            rule_path="fixture.yaml",
        )
        return batch_id

    def create_generic_task(self, request_id: str) -> str:
        created = self.client.post(
            "/api/tasks",
            json={
                "request_id": request_id,
                "rule_id": "fixture-local",
                "rule_version": "2026.11.21-1",
                "task_type": "product",
                "limits": {
                    "max_urls": 3,
                    "max_products": 2,
                    "max_seconds": 30,
                    "max_attempts": 1,
                },
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        return created.json()["task"]["task_id"]

    def test_create_tree_start_and_recent_contract(self) -> None:
        group_id, node_id = self.create_task_node()

        tree = self.client.get("/api/workbench/tree")
        self.assertEqual(tree.status_code, 200, tree.text)
        nodes = tree.json()["nodes"]
        self.assertEqual({node["node_type"] for node in nodes}, {"group", "task"})
        group = next(node for node in nodes if node["node_id"] == group_id)
        self.assertEqual(group["task_count"], 1)
        task_node = next(node for node in nodes if node["node_id"] == node_id)
        self.assertEqual(task_node["definition"]["site_key"], "fixture.example")
        self.assertIsNone(task_node["current_run"])

        started = self.client.post(f"/api/workbench/tasks/{node_id}/start")
        self.assertEqual(started.status_code, 202, started.text)
        task = started.json()["task"]
        self.assertEqual(task["state"], "QUEUED")
        self.assertEqual(task["batch_id"], None)

        tree = self.client.get("/api/workbench/tree")
        task_node = next(
            node for node in tree.json()["nodes"] if node["node_id"] == node_id
        )
        self.assertEqual(task_node["current_run"]["task_id"], task["task_id"])

        recent = self.client.get("/api/workbench/recent")
        self.assertEqual(recent.status_code, 200, recent.text)
        self.assertEqual(
            recent.json()["counts"],
            {"recent": 1, "running": 0, "queued": 1, "removed": 0},
        )
        item = recent.json()["items"][0]
        self.assertEqual(item["task_id"], task["task_id"])
        self.assertEqual(item["definition_name"], "fixture.example")
        self.assertEqual(item["path"], "独立任务")
        self.assertFalse(item["can_dismiss"])

        blocked = self.client.post(
            f"/api/workbench/recent/{task['task_id']}/dismiss"
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["error"]["code"], "NON_TERMINAL_TASK")

        batch_blocked = self.client.post(
            "/api/workbench/recent/dismiss",
            json={"task_ids": [task["task_id"]]},
        )
        self.assertEqual(batch_blocked.status_code, 409)
        self.assertEqual(batch_blocked.json()["error"]["code"], "NON_TERMINAL_TASK")

        self.store.update_task(
            task["task_id"], state="FINISHED", outcome="COMPLETED"
        )
        finished = self.client.get("/api/workbench/recent")
        self.assertTrue(finished.json()["items"][0]["can_dismiss"])
        missing = self.client.post(
            "/api/workbench/recent/dismiss",
            json={"task_ids": [task["task_id"], "missing-task"]},
        )
        self.assertEqual(missing.status_code, 404)
        kept = self.client.get("/api/workbench/recent").json()["items"]
        self.assertEqual([item["task_id"] for item in kept], [task["task_id"]])
        dismissed = self.client.post(
            "/api/workbench/recent/dismiss",
            json={"task_ids": [task["task_id"], task["task_id"]]},
        )
        self.assertEqual(dismissed.status_code, 200, dismissed.text)
        self.assertEqual(dismissed.json()["task_ids"], [task["task_id"]])
        self.assertEqual(
            self.client.get("/api/workbench/recent").json()["items"], []
        )
        removed = self.client.get("/api/workbench/recent?scope=removed")
        self.assertEqual(
            [item["task_id"] for item in removed.json()["items"]],
            [task["task_id"]],
        )
        self.assertEqual(
            removed.json()["counts"],
            {"recent": 0, "running": 0, "queued": 0, "removed": 1},
        )
        restored = self.client.post(
            f"/api/workbench/recent/{task['task_id']}/restore"
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(
            self.client.get("/api/workbench/recent").json()["items"][0][
                "task_id"
            ],
            task["task_id"],
        )

        history = self.client.get(f"/api/tasks/{task['task_id']}/events/history")
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual(history.json()["items"], [])

    def test_clone_task_definition_can_copy_rule_version(self) -> None:
        _, node_id = self.create_task_node()
        source_rule = self.rules_dir / "fixture.yaml"
        source_text = source_rule.read_text(encoding="utf-8")

        preview = self.client.get(
            f"/api/workbench/tasks/{node_id}/clone-preview"
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        body = preview.json()
        self.assertTrue(body["can_copy_rule"])
        self.assertFalse(body["can_copy_data"])
        self.assertEqual(body["default_name"], "fixture.example 副本")
        self.assertEqual(body["source_rule"]["rule_version"], "2026.11.21-1")

        cloned = self.client.post(
            f"/api/workbench/tasks/{node_id}/clone",
            json={"copy_rule": True},
        )
        self.assertEqual(cloned.status_code, 201, cloned.text)
        payload = cloned.json()
        self.assertIsNone(payload["run"])
        self.assertIn("-exp-", payload["definition"]["rule_version"])
        self.assertEqual(
            payload["definition"]["rule_version"], payload["rule"]["rule_version"]
        )
        self.assertEqual(payload["rule"]["status"], "candidate")
        self.assertEqual(source_rule.read_text(encoding="utf-8"), source_text)

        cloned_rule = self.rules_dir / payload["rule"]["path"]
        self.assertTrue(cloned_rule.is_file())
        rule = load_rule(cloned_rule)
        self.assertEqual(rule.rule_id, "fixture-local")
        self.assertEqual(rule.rule_version, payload["rule"]["rule_version"])
        self.assertEqual(rule.raw.get("status"), "candidate")

        tree = self.client.get("/api/workbench/tree").json()["nodes"]
        source_node = next(item for item in tree if item["node_id"] == node_id)
        clone_node = next(
            item for item in tree if item["node_id"] == payload["node"]["node_id"]
        )
        self.assertEqual(clone_node["parent_id"], source_node["parent_id"])
        self.assertEqual(clone_node["definition"]["site_key"], "fixture.example")
        self.assertIn("克隆自", clone_node["definition"]["note"])
        self.assertIsNone(clone_node["current_run"])

        rules = self.client.get("/api/rules").json()["items"]
        versions = {
            item["rule_version"]
            for item in rules
            if item["rule_id"] == "fixture-local"
        }
        self.assertIn("2026.11.21-1", versions)
        self.assertIn(payload["rule"]["rule_version"], versions)

    def test_clone_task_with_data_isolates_batch_and_rewrites_clone_run(self) -> None:
        group = self.client.post(
            "/api/workbench/groups", json={"name": "克隆实验目录"}
        )
        self.assertEqual(group.status_code, 201, group.text)
        group_id = group.json()["node"]["node_id"]
        batch_id = self.create_batch("clone data batch")
        source_task_id = self.create_generic_task("clone-source-task")
        self.store.update_task(
            source_task_id,
            site_key="fixture.example",
            batch_id=batch_id,
            state="FINISHED",
            outcome="COMPLETED",
        )
        self.store.update_batch_site(
            batch_id, "fixture.example", task_id=source_task_id
        )
        self.store.add_item(
            WorkItem(
                task_id=source_task_id,
                item_id="item-1",
                item_type="product",
                url="https://fixture.example/p/1",
                normalized_url="https://fixture.example/p/1",
                stage="product",
                state="DONE",
                result={"name": "Fixture product"},
            )
        )
        source_dir = self.out_root / source_task_id
        source_dir.mkdir()
        (source_dir / "task-result.json").write_text(
            json.dumps(
                {
                    "task_id": source_task_id,
                    "state": "FINISHED",
                    "outcome": "COMPLETED",
                    "counts": {"valid_products": 1},
                }
            ),
            encoding="utf-8",
        )
        (source_dir / "products.csv").write_text(
            "source_url,name\nhttps://fixture.example/p/1,Fixture product\n",
            encoding="utf-8",
        )
        (source_dir / "events.ndjson").write_text(
            '{"event":"task_started"}\n', encoding="utf-8"
        )
        imported = self.client.post(
            "/api/workbench/import-batch",
            json={"batch_id": batch_id, "parent_id": group_id},
        )
        self.assertEqual(imported.status_code, 200, imported.text)
        node_id = imported.json()["added"][0]["node_id"]

        preview = self.client.get(
            f"/api/workbench/tasks/{node_id}/clone-preview"
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        preview_body = preview.json()
        self.assertTrue(preview_body["can_copy_data"])
        self.assertEqual(
            preview_body["source_run"]["task_id"], source_task_id
        )
        self.assertGreater(preview_body["source_run"]["files"], 0)

        cloned = self.client.post(
            f"/api/workbench/tasks/{node_id}/clone",
            json={"copy_rule": True, "copy_data": True},
        )
        self.assertEqual(cloned.status_code, 201, cloned.text)
        payload = cloned.json()
        clone_node_id = payload["node"]["node_id"]
        clone_task_id = payload["run"]["task_id"]
        self.assertNotEqual(clone_task_id, source_task_id)
        self.assertEqual(payload["run"]["source_task_id"], source_task_id)
        self.assertEqual(payload["definition"]["batch_id"], None)
        self.assertIn("克隆自", payload["definition"]["note"])
        self.assertIn("-exp-", payload["definition"]["rule_version"])

        source_task = self.store.get_task(source_task_id)
        self.assertIsNotNone(source_task)
        self.assertEqual(source_task.batch_id, batch_id)
        clone_task = self.store.get_task(clone_task_id)
        self.assertIsNotNone(clone_task)
        self.assertEqual(clone_task.state, "FINISHED")
        self.assertEqual(clone_task.outcome, "COMPLETED")
        self.assertEqual(clone_task.batch_id, None)
        self.assertEqual(clone_task.plan_version, "2026.11.21-1")
        self.assertEqual(clone_task.input.get("cloned_from"), source_task_id)
        self.assertEqual(
            clone_task.input.get("workbench_node_id"), clone_node_id
        )
        self.assertEqual(len(self.store.items(clone_task_id, "product")), 1)

        clone_dir = self.out_root / clone_task_id
        self.assertTrue((clone_dir / "products.csv").is_file())
        result = json.loads(
            (clone_dir / "task-result.json").read_text(encoding="utf-8")
        )
        self.assertEqual(result["task_id"], clone_task_id)
        self.assertEqual(result["cloned_from"], source_task_id)
        self.assertEqual(result["counts"]["valid_products"], 1)

        site = self.store.get_batch_site(batch_id, "fixture.example")
        self.assertIsNotNone(site)
        self.assertEqual(site.task_id, source_task_id)

        tree = self.client.get("/api/workbench/tree").json()["nodes"]
        clone_node = next(
            item for item in tree if item["node_id"] == clone_node_id
        )
        self.assertEqual(clone_node["definition"]["batch_id"], None)
        self.assertEqual(clone_node["definition"]["rule_version"],
                         payload["definition"]["rule_version"])
        self.assertEqual(
            clone_node["current_run"]["task_id"], clone_task_id
        )

        summary = self.client.get(f"/api/tasks/{clone_task_id}")
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertEqual(summary.json()["state"], "FINISHED")
        self.assertEqual(summary.json()["counts"]["valid_products"], 1)

        config = self.client.get(f"/api/workbench/runs/{clone_task_id}/config")
        self.assertEqual(config.status_code, 200, config.text)
        self.assertFalse(config.json()["can_continue"])
        self.assertIn("快照", config.json()["continue_hint"] or "")

    def test_clone_blocks_data_without_terminal_run(self) -> None:
        _, node_id = self.create_task_node()
        preview = self.client.get(
            f"/api/workbench/tasks/{node_id}/clone-preview"
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertFalse(preview.json()["can_copy_data"])
        self.assertTrue(preview.json()["data_blockers"])

        blocked = self.client.post(
            f"/api/workbench/tasks/{node_id}/clone",
            json={"copy_data": True},
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(
            blocked.json()["error"]["code"], "CLONE_DATA_UNAVAILABLE"
        )
        self.assertEqual(
            self.client.get("/api/workbench/tree").json()["nodes"][0][
                "node_type"
            ],
            "group",
        )

    def test_cleanup_preview_and_purge_run_removes_data(self) -> None:
        _, node_id = self.create_task_node()
        started = self.client.post(f"/api/workbench/tasks/{node_id}/start")
        self.assertEqual(started.status_code, 202, started.text)
        task_id = started.json()["task"]["task_id"]
        self.store.update_task(task_id, state="FINISHED", outcome="COMPLETED")
        run_dir = self.out_root / task_id
        run_dir.mkdir()
        (run_dir / "products.csv").write_text("a,b\n1,2\n", encoding="utf-8")

        preview = self.client.get(f"/api/tasks/{task_id}/cleanup-preview")
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertTrue(preview.json()["can_purge"])
        self.assertEqual(preview.json()["files"], 1)
        self.assertGreater(preview.json()["bytes"], 0)

        purged = self.client.post(f"/api/tasks/{task_id}/purge")
        self.assertEqual(purged.status_code, 200, purged.text)
        self.assertTrue(purged.json()["purged"])
        self.assertFalse(run_dir.exists())
        self.assertEqual(self.client.get(f"/api/tasks/{task_id}").status_code, 404)
        self.assertEqual(self.client.get("/api/workbench/recent").json()["items"], [])

        tree = self.client.get("/api/workbench/tree").json()["nodes"]
        node = next(item for item in tree if item["node_id"] == node_id)
        self.assertIsNone(node["current_run"])

    def test_cleanup_blocks_active_run_and_feedback_without_confirmation(self) -> None:
        _, node_id = self.create_task_node()
        started = self.client.post(f"/api/workbench/tasks/{node_id}/start")
        self.assertEqual(started.status_code, 202, started.text)
        task_id = started.json()["task"]["task_id"]

        preview = self.client.get(f"/api/tasks/{task_id}/cleanup-preview")
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertFalse(preview.json()["can_purge"])
        blocked = self.client.post(f"/api/tasks/{task_id}/purge")
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["error"]["code"], "CLEANUP_BLOCKED")
        self.assertIsNotNone(self.store.get_task(task_id))

        self.store.update_task(task_id, state="FINISHED", outcome="COMPLETED")
        created = self.client.post(
            f"/api/tasks/{task_id}/feedback",
            json={
                "request_id": "req-cleanup-feedback",
                "category": "DESCRIPTION",
                "samples": ["https://fixture.example/product/1"],
                "expectation": "描述应包含规格块",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        feedback_id = created.json()["feedback"]["feedback_id"]
        referenced = self.client.post(f"/api/tasks/{task_id}/purge")
        self.assertEqual(referenced.status_code, 409)
        self.assertEqual(referenced.json()["error"]["code"], "CLEANUP_REFERENCED")

        purged = self.client.post(
            f"/api/tasks/{task_id}/purge",
            json={"purge_feedback": True},
        )
        self.assertEqual(purged.status_code, 200, purged.text)
        self.assertEqual(
            self.client.get(f"/api/feedback/{feedback_id}").status_code, 404
        )

    def test_purge_run_clears_batch_task_and_delivery_pointers(self) -> None:
        batch_id = self.create_batch("cleanup pointers")
        task_id = self.create_generic_task("req-cleanup-pointers")
        self.store.update_task(task_id, state="FINISHED", outcome="COMPLETED")
        self.store.update_batch_site(
            batch_id, "fixture.example", task_id=task_id
        )
        with self.store._connect() as connection:
            connection.execute(
                "UPDATE batch_sites SET delivery_task_id = ? "
                "WHERE batch_id = ? AND site_key = ?",
                (task_id, batch_id, "fixture.example"),
            )
            connection.commit()

        preview = self.client.get(f"/api/tasks/{task_id}/cleanup-preview")
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(
            {link["field"] for link in preview.json()["batch_links"]},
            {"task_id", "delivery_task_id"},
        )

        purged = self.client.post(f"/api/tasks/{task_id}/purge")
        self.assertEqual(purged.status_code, 200, purged.text)
        site = self.store.get_batch_site(batch_id, "fixture.example")
        self.assertIsNotNone(site)
        self.assertIsNone(site.task_id)
        self.assertIsNone(site.delivery_task_id)

    def test_delete_task_definition_can_keep_or_purge_runs(self) -> None:
        _, node_id = self.create_task_node()
        started = self.client.post(f"/api/workbench/tasks/{node_id}/start")
        self.assertEqual(started.status_code, 202, started.text)
        task_id = started.json()["task"]["task_id"]
        self.store.update_task(task_id, state="FINISHED", outcome="COMPLETED")
        run_dir = self.out_root / task_id
        run_dir.mkdir()
        (run_dir / "products.csv").write_text("a,b\n1,2\n", encoding="utf-8")

        preview = self.client.get(
            f"/api/workbench/nodes/{node_id}/cleanup-preview"
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["run_count"], 1)
        self.assertTrue(preview.json()["can_delete"])

        deleted = self.client.post(
            f"/api/workbench/nodes/{node_id}/delete",
            json={"purge_runs": True},
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertTrue(deleted.json()["deleted"])
        self.assertFalse(run_dir.exists())
        self.assertIsNone(self.store.get_task(task_id))
        tree = self.client.get("/api/workbench/tree").json()["nodes"]
        self.assertNotIn(node_id, {item["node_id"] for item in tree})

    def test_delete_task_definition_without_purge_keeps_runs(self) -> None:
        _, node_id = self.create_task_node()
        started = self.client.post(f"/api/workbench/tasks/{node_id}/start")
        self.assertEqual(started.status_code, 202, started.text)
        task_id = started.json()["task"]["task_id"]
        self.store.update_task(task_id, state="FINISHED", outcome="COMPLETED")

        deleted = self.client.post(
            f"/api/workbench/nodes/{node_id}/delete",
            json={"purge_runs": False},
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertIsNotNone(self.store.get_task(task_id))
        recent = self.client.get("/api/workbench/recent").json()["items"]
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["task_id"], task_id)
        self.assertIsNone(recent[0]["definition_name"])

    def test_event_history_pages_and_totals(self) -> None:
        task_id = self.create_generic_task("req-log-pages")
        run_dir = self.out_root / task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "events.ndjson"
        events = [
            {
                "ts": f"2026-11-27T10:00:0{index}Z",
                "event": "item_finished",
                "state": "DONE",
                "index": index,
            }
            for index in range(1, 6)
        ]
        path.write_text(
            "\n".join(json.dumps(event) for event in events) + "\n",
            encoding="utf-8",
        )

        tail = self.client.get(
            f"/api/tasks/{task_id}/events/history?limit=2"
        ).json()
        self.assertEqual(tail["total"], 5)
        self.assertEqual([item["seq"] for item in tail["items"]], [4, 5])
        self.assertTrue(tail["has_more"])
        self.assertEqual(tail["oldest_seq"], 4)
        self.assertEqual(tail["newest_seq"], 5)

        legacy = self.client.get(
            f"/api/tasks/{task_id}/events/history?tail=2"
        ).json()
        self.assertEqual([item["seq"] for item in legacy["items"]], [4, 5])

        conflict = self.client.get(
            f"/api/tasks/{task_id}/events/history?before=4&after=2"
        )
        self.assertEqual(conflict.status_code, 400)
        self.assertEqual(conflict.json()["error"]["code"], "BAD_REQUEST")

        older = self.client.get(
            f"/api/tasks/{task_id}/events/history?before=4&limit=2"
        ).json()
        self.assertEqual([item["seq"] for item in older["items"]], [2, 3])
        self.assertTrue(older["has_more"])

        first = self.client.get(
            f"/api/tasks/{task_id}/events/history?before=2&limit=2"
        ).json()
        self.assertEqual([item["seq"] for item in first["items"]], [1])
        self.assertFalse(first["has_more"])

        after = self.client.get(
            f"/api/tasks/{task_id}/events/history?after=2&limit=2"
        ).json()
        self.assertEqual([item["seq"] for item in after["items"]], [3, 4])
        self.assertTrue(after["has_more"])

        after_last = self.client.get(
            f"/api/tasks/{task_id}/events/history?after=5"
        ).json()
        self.assertEqual(after_last["items"], [])
        self.assertEqual(after_last["total"], 5)
        self.assertFalse(after_last["has_more"])

        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {"ts": "2026-11-27T10:00:06Z", "event": "item_finished"}
                )
                + "\n"
            )
            handle.write(
                json.dumps(
                    {"ts": "2026-11-27T10:00:07Z", "event": "task_finished"}
                )
                + "\n"
            )
        refreshed = self.client.get(
            f"/api/tasks/{task_id}/events/history?limit=2"
        ).json()
        self.assertEqual(refreshed["total"], 7)
        self.assertEqual([item["seq"] for item in refreshed["items"]], [6, 7])

    def test_event_stream_after_cursor_replays_and_ends(self) -> None:
        task_id = self.create_generic_task("req-log-stream")
        run_dir = self.out_root / task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "events.ndjson"
        path.write_text(
            "\n".join(
                json.dumps(
                    {
                        "ts": f"2026-11-27T10:00:0{index}Z",
                        "event": "item_finished",
                        "index": index,
                    }
                )
                for index in range(1, 6)
            )
            + "\n",
            encoding="utf-8",
        )
        cancelled = self.client.post(f"/api/tasks/{task_id}/cancel")
        self.assertEqual(cancelled.status_code, 202, cancelled.text)

        lines: list[str] = []
        with self.client.stream(
            "GET", f"/api/tasks/{task_id}/events?after=2"
        ) as response:
            self.assertEqual(response.status_code, 200)
            for line in response.iter_lines():
                lines.append(line)
                if line == "event: end":
                    break
        text = "\n".join(lines)
        self.assertIn("id: 3", text)
        self.assertIn("id: 4", text)
        self.assertIn("id: 5", text)
        self.assertNotIn("id: 1", text)
        self.assertNotIn("id: 2", text)
        self.assertIn("event: end", text)

        replay_lines: list[str] = []
        with self.client.stream(
            "GET",
            f"/api/tasks/{task_id}/events",
            headers={**CLIENT_HEADERS, "Last-Event-ID": "2"},
        ) as response:
            for line in response.iter_lines():
                replay_lines.append(line)
                if line == "event: end":
                    break
        replay_text = "\n".join(replay_lines)
        self.assertIn("id: 3", replay_text)
        self.assertIn("id: 5", replay_text)
        self.assertNotIn("id: 1", replay_text)
        self.assertNotIn("id: 2", replay_text)

    def test_rename_move_and_dissolve_nodes(self) -> None:
        group_id, node_id = self.create_task_node()
        child = self.client.post(
            "/api/workbench/groups",
            json={"name": "子目录", "parent_id": group_id},
        )
        self.assertEqual(child.status_code, 201, child.text)
        child_id = child.json()["node"]["node_id"]

        renamed = self.client.patch(
            f"/api/workbench/nodes/{node_id}", json={"name": "重命名任务"}
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["node"]["name"], "重命名任务")

        blank = self.client.patch(
            f"/api/workbench/nodes/{node_id}", json={"name": "   "}
        )
        self.assertEqual(blank.status_code, 422)

        moved = self.client.post(
            f"/api/workbench/nodes/{node_id}/move",
            json={"parent_id": child_id},
        )
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual(moved.json()["node"]["parent_id"], child_id)

        cycle = self.client.post(
            f"/api/workbench/nodes/{group_id}/move",
            json={"parent_id": child_id},
        )
        self.assertEqual(cycle.status_code, 409)
        self.assertEqual(cycle.json()["error"]["code"], "INVALID_MOVE")

        invalid_parent = self.client.post(
            f"/api/workbench/nodes/{child_id}/move",
            json={"parent_id": node_id},
        )
        self.assertEqual(invalid_parent.status_code, 409)

        dissolved = self.client.delete(f"/api/workbench/groups/{child_id}")
        self.assertEqual(dissolved.status_code, 200, dissolved.text)
        self.assertEqual(dissolved.json()["moved"], 1)

        nodes = self.client.get("/api/workbench/tree").json()["nodes"]
        by_id = {node["node_id"]: node for node in nodes}
        self.assertNotIn(child_id, by_id)
        self.assertEqual(by_id[node_id]["parent_id"], group_id)

        not_a_group = self.client.delete(f"/api/workbench/groups/{node_id}")
        self.assertEqual(not_a_group.status_code, 409)

    def test_move_before_sibling_orders_nodes(self) -> None:
        group_ids = []
        for name in ("A", "B", "C"):
            created = self.client.post("/api/workbench/groups", json={"name": name})
            self.assertEqual(created.status_code, 201, created.text)
            group_ids.append(created.json()["node"]["node_id"])
        moved = self.client.post(
            f"/api/workbench/nodes/{group_ids[2]}/move",
            json={"parent_id": None, "before_node_id": group_ids[0]},
        )
        self.assertEqual(moved.status_code, 200, moved.text)
        roots = [
            node["node_id"]
            for node in self.client.get("/api/workbench/tree").json()["nodes"]
            if node["parent_id"] is None
        ]
        self.assertEqual(roots[:3], [group_ids[2], group_ids[0], group_ids[1]])
        both = self.client.post(
            f"/api/workbench/nodes/{group_ids[2]}/move",
            json={
                "parent_id": None,
                "after_node_id": group_ids[0],
                "before_node_id": group_ids[1],
            },
        )
        self.assertEqual(both.status_code, 409)

    def test_update_task_definition_rejects_bad_rule(self) -> None:
        _, node_id = self.create_task_node()
        updated = self.client.patch(
            f"/api/workbench/tasks/{node_id}",
            json={
                "collection_mode": "formal",
                "country": "FR",
                "language": "fr",
                "market": "FR",
                "category": "textile",
                "limits": {
                    "max_urls": 30,
                    "max_products": 10,
                    "max_seconds": 90,
                    "max_attempts": 3,
                },
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        definition = updated.json()["definition"]
        self.assertEqual(definition["market"], "FR")
        self.assertEqual(definition["category"], "textile")
        self.assertEqual(definition["limits"]["max_urls"], 30)

        missing_rule = self.client.patch(
            f"/api/workbench/tasks/{node_id}",
            json={"rule_version": "2099.01.01-1"},
        )
        self.assertEqual(missing_rule.status_code, 400)
        self.assertEqual(missing_rule.json()["error"]["code"], "INVALID_RULE")

        switched = self.client.patch(
            f"/api/workbench/tasks/{node_id}",
            json={"task_type": "discovery"},
        )
        self.assertEqual(switched.status_code, 200, switched.text)
        self.assertEqual(switched.json()["definition"]["task_type"], "discovery")

    def test_import_batch_adds_definitions_and_skips_duplicates(self) -> None:
        group = self.client.post(
            "/api/workbench/groups", json={"name": "批次目录"}
        )
        self.assertEqual(group.status_code, 201, group.text)
        group_id = group.json()["node"]["node_id"]
        batch_id = self.create_batch()
        task_id = self.create_generic_task("import-batch-attach")
        self.store.update_task(task_id, site_key="fixture.example", batch_id=batch_id)
        self.store.update_batch_site(batch_id, "fixture.example", task_id=task_id)

        imported = self.client.post(
            "/api/workbench/import-batch",
            json={"batch_id": batch_id, "parent_id": group_id},
        )
        self.assertEqual(imported.status_code, 200, imported.text)
        payload = imported.json()
        self.assertEqual(len(payload["added"]), 1)
        self.assertTrue(payload["added"][0]["attached"])
        self.assertEqual(payload["skipped"], [])

        tree = self.client.get("/api/workbench/tree").json()["nodes"]
        node = next(
            item for item in tree if item["node_id"] == payload["added"][0]["node_id"]
        )
        self.assertEqual(node["definition"]["batch_id"], batch_id)
        self.assertEqual(node["definition"]["site_key"], "fixture.example")
        self.assertEqual(node["current_run"]["task_id"], task_id)
        self.assertEqual(node["parent_id"], group_id)

        recent = self.client.get("/api/workbench/recent").json()["items"]
        item = next(entry for entry in recent if entry["task_id"] == task_id)
        self.assertEqual(item["node_id"], node["node_id"])

        again = self.client.post(
            "/api/workbench/import-batch",
            json={"batch_id": batch_id, "parent_id": group_id},
        )
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["added"], [])
        self.assertEqual(again.json()["skipped"][0]["reason"], "已在任务树")

        self.store.update_task(task_id, state="FINISHED", outcome="COMPLETED")
        archived = self.client.post(f"/api/batches/{batch_id}/archive")
        self.assertEqual(archived.status_code, 202, archived.text)
        blocked = self.client.post(
            "/api/workbench/import-batch",
            json={"batch_id": batch_id, "parent_id": group_id},
        )
        self.assertEqual(blocked.status_code, 409)

    def test_attach_existing_run_creates_or_reuses_definition(self) -> None:
        group = self.client.post(
            "/api/workbench/groups", json={"name": "历史运行"}
        )
        self.assertEqual(group.status_code, 201, group.text)
        group_id = group.json()["node"]["node_id"]
        task_id = self.create_generic_task("attach-run")
        self.store.update_task(
            task_id, site_key="Fixture", domain_key="www.fixture.example"
        )

        attached = self.client.post(
            f"/api/workbench/runs/{task_id}/attach",
            json={"parent_id": group_id, "name": "历史 fixture"},
        )
        self.assertEqual(attached.status_code, 200, attached.text)
        body = attached.json()
        self.assertTrue(body["created"])
        self.assertTrue(body["attached"])
        node_id = body["node_id"]

        tree = self.client.get("/api/workbench/tree").json()["nodes"]
        node = next(item for item in tree if item["node_id"] == node_id)
        self.assertEqual(node["name"], "历史 fixture")
        self.assertEqual(node["definition"]["site_key"], "fixture.example")
        self.assertEqual(node["definition"]["domain"], "fixture.example")
        self.assertIsNone(node["definition"]["batch_id"])
        self.assertEqual(node["current_run"]["task_id"], task_id)

        again = self.client.post(
            f"/api/workbench/runs/{task_id}/attach",
            json={"parent_id": group_id},
        )
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["node_id"], node_id)
        self.assertFalse(again.json()["created"])
        self.assertFalse(again.json()["attached"])

    def test_attach_unassigned_runs_creates_default_and_reuses_definitions(self) -> None:
        first_id = self.create_generic_task("default-attach-1")
        second_id = self.create_generic_task("default-attach-2")
        for task_id in (first_id, second_id):
            self.store.update_task(
                task_id, site_key="fixture.example", domain_key="www.fixture.example"
            )

        before = self.client.get(
            "/api/workbench/recent", params={"scope": "recent", "limit": 10}
        )
        self.assertEqual(before.status_code, 200, before.text)
        self.assertEqual(before.json()["unassigned_total"], 2)

        attached = self.client.post("/api/workbench/defaults/attach-unassigned")
        self.assertEqual(attached.status_code, 200, attached.text)
        body = attached.json()
        self.assertEqual(body["processed"], 2)
        self.assertEqual(len(body["attached"]), 2)
        self.assertEqual(body["skipped"], [])
        self.assertEqual(body["default_group"]["name"], "Default")
        self.assertTrue(body["default_group"]["created"])
        node_ids = {item["node_id"] for item in body["attached"]}
        self.assertEqual(len(node_ids), 1)
        self.assertEqual(
            sum(1 for item in body["attached"] if item["created"]),
            1,
        )

        tree = self.client.get("/api/workbench/tree").json()["nodes"]
        default = next(
            node
            for node in tree
            if node["node_id"] == body["default_group"]["node_id"]
        )
        self.assertEqual(default["node_type"], "group")
        self.assertEqual(default["task_count"], 1)
        children = [node for node in tree if node["parent_id"] == default["node_id"]]
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0]["node_id"], next(iter(node_ids)))

        after = self.client.get(
            "/api/workbench/recent", params={"scope": "recent", "limit": 10}
        )
        self.assertEqual(after.json()["unassigned_total"], 0)
        self.assertTrue(
            all(item["node_id"] for item in after.json()["items"])
        )
        again = self.client.post("/api/workbench/defaults/attach-unassigned")
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["processed"], 0)
        self.assertEqual(
            again.json()["default_group"]["node_id"],
            body["default_group"]["node_id"],
        )

    def test_attach_unassigned_skips_rule_mismatch(self) -> None:
        first_id = self.create_generic_task("default-attach-skip-1")
        second_id = self.create_generic_task("default-attach-skip-2")
        for index, task_id in enumerate((first_id, second_id)):
            self.store.update_task(
                task_id,
                site_key=f"other{index}.example",
                domain_key=f"other{index}.example",
            )

        response = self.client.post("/api/workbench/defaults/attach-unassigned")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["processed"], 2)
        self.assertEqual(body["attached"], [])
        self.assertEqual(len(body["skipped"]), 2)
        self.assertEqual(
            {item["code"] for item in body["skipped"]},
            {"RULE_SITE_MISMATCH"},
        )

        remaining = self.client.get(
            "/api/workbench/recent", params={"scope": "recent", "limit": 10}
        )
        self.assertEqual(remaining.json()["unassigned_total"], 2)

    def test_duplicate_site_and_bad_parent_are_rejected(self) -> None:
        self.create_task_node()
        duplicate = self.client.post(
            "/api/workbench/tasks",
            json={
                "input_url": "https://fixture.example/",
                "rule_id": "fixture-local",
                "rule_version": "2026.11.21-1",
            },
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(
            duplicate.json()["error"]["code"], "WORKBENCH_TASK_EXISTS"
        )

        bad_parent = self.client.post(
            "/api/workbench/groups",
            json={"name": "无效父级", "parent_id": "missing"},
        )
        self.assertEqual(bad_parent.status_code, 404)

        mismatch = self.client.post(
            "/api/workbench/tasks",
            json={
                "input_url": "https://other.example/",
                "rule_id": "fixture-local",
                "rule_version": "2026.11.21-1",
            },
        )
        self.assertEqual(mismatch.status_code, 422)
        self.assertEqual(mismatch.json()["error"]["code"], "RULE_SITE_MISMATCH")

    def test_start_rejects_active_run(self) -> None:
        _, node_id = self.create_task_node()
        first = self.client.post(f"/api/workbench/tasks/{node_id}/start")
        self.assertEqual(first.status_code, 202, first.text)
        second = self.client.post(f"/api/workbench/tasks/{node_id}/start")
        self.assertEqual(second.status_code, 409)
        self.assertEqual(
            second.json()["error"]["code"], "WORKBENCH_TASK_ACTIVE"
        )
