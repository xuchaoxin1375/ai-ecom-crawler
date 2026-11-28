from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from ecom_crawler.runtime.models import Task, WorkItem
from ecom_crawler.runtime.runner import TaskRunner
from ecom_crawler.runtime.store import TaskStore
from ecom_crawler.web.app import _workbench_stop_detail, create_app
from tests.test_execution import RULE_TEMPLATE

CLIENT_HEADERS = {
    "Host": "127.0.0.1:8765",
    "Origin": "http://127.0.0.1:8765",
    "X-Requested-With": "XMLHttpRequest",
}


class RunConfigApiTests(unittest.TestCase):
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

    def create_task_node(
        self, limits: dict[str, object] | None = None
    ) -> tuple[str, str]:
        group = self.client.post(
            "/api/workbench/groups", json={"name": "独立任务"}
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
                "limits": limits
                or {
                    "max_urls": 10,
                    "max_products": 3,
                    "max_seconds": 60,
                    "max_attempts": 1,
                },
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        return group_id, created.json()["node"]["node_id"]

    def start_task(self, node_id: str) -> str:
        started = self.client.post(f"/api/workbench/tasks/{node_id}/start")
        self.assertEqual(started.status_code, 202, started.text)
        return started.json()["task"]["task_id"]

    def mark_budget_exhausted(
        self,
        task_id: str,
        *,
        stop_detail: str,
        pending_products: int,
        done_products: int = 2,
        navigation_state: str = "DONE",
    ) -> None:
        task = self.store.get_task(task_id)
        self.assertIsNotNone(task)
        self.store.update_task(
            task_id,
            state="FINISHED",
            outcome="PARTIAL",
            stop_reason="BUDGET_EXHAUSTED",
            finished_at="2026-11-27T10:00:00Z",
            counters={
                "valid_products": done_products,
                "pending_products": pending_products,
                "processed_products": done_products,
            },
        )
        self.store.add_item(
            WorkItem(
                task_id=task_id,
                item_id="nav-1",
                item_type="navigation",
                url="https://fixture.example/",
                normalized_url="https://fixture.example/",
                state=navigation_state,
            )
        )
        for index in range(done_products):
            self.store.add_item(
                WorkItem(
                    task_id=task_id,
                    item_id=f"done-{index}",
                    item_type="product",
                    url=f"https://fixture.example/done{index}.html",
                    normalized_url=f"https://fixture.example/done{index}.html",
                    state="DONE",
                )
            )
        for index in range(pending_products):
            self.store.add_item(
                WorkItem(
                    task_id=task_id,
                    item_id=f"product-{index}",
                    item_type="product",
                    url=f"https://fixture.example/p{index}.html",
                    normalized_url=f"https://fixture.example/p{index}.html",
                    state="PENDING",
                )
            )
        run_dir = self.out_root / task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "task-result.json").write_text(
            json.dumps(
                {
                    "state": "FINISHED",
                    "outcome": "PARTIAL",
                    "stop_reason": "BUDGET_EXHAUSTED",
                    "stop_detail": stop_detail,
                    "counts": {
                        "valid_products": done_products,
                        "pending_products": pending_products,
                        "processed_products": done_products,
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_config_and_continue_resets_discovery_and_keeps_results(self) -> None:
        _, node_id = self.create_task_node()
        task_id = self.start_task(node_id)
        self.mark_budget_exhausted(
            task_id,
            stop_detail="sitemap index reached max_sitemaps",
            pending_products=2,
        )
        self.store.dismiss_workbench_runs([task_id])

        config = self.client.get(f"/api/workbench/runs/{task_id}/config")
        self.assertEqual(config.status_code, 200, config.text)
        body = config.json()
        self.assertEqual(body["stop_detail"], "sitemap index reached max_sitemaps")
        self.assertEqual(body["collection_mode"], "formal")
        self.assertTrue(body["can_continue"])
        self.assertTrue(body["reset_discovery"])
        self.assertEqual(body["pending_products"], 2)
        self.assertIn("续采会保留已采 2 条结果", body["continue_hint"])

        updated = self.client.patch(
            f"/api/workbench/runs/{task_id}/config",
            json={
                "limits": {
                    "max_seconds": 14400,
                    "max_products": 9000,
                    "max_sitemaps": 100,
                },
                "sync_definition": True,
                "action": "continue",
                "reset_discovery": True,
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        applied = updated.json()["applied"]
        self.assertTrue(applied["continued"])
        self.assertTrue(applied["run"])
        self.assertTrue(applied["definition"])
        task = self.store.get_task(task_id)
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task.state, "QUEUED")
        self.assertIsNone(task.outcome)
        self.assertIsNone(task.stop_reason)
        self.assertIsNone(task.finished_at)
        self.assertEqual(task.limits["max_seconds"], 14400)
        self.assertEqual(task.limits["max_products"], 9000)
        self.assertEqual(task.limits["max_sitemaps"], 100)
        self.assertEqual(task.counters["run_seconds"], 0)
        self.assertNotIn("discovery_limit", task.counters)
        navigation = self.store.items(task_id, "navigation")
        self.assertEqual([item.state for item in navigation], ["PENDING"])
        products = self.store.items(task_id, "product")
        self.assertEqual(
            sorted(item.state for item in products),
            ["DONE", "DONE", "PENDING", "PENDING"],
        )
        definition = self.store.get_workbench_task_def(node_id)
        self.assertIsNotNone(definition)
        assert definition is not None
        self.assertEqual(definition.limits["max_seconds"], 14400)
        self.assertEqual(definition.limits["max_sitemaps"], 100)
        self.assertNotIn(task_id, self.store.list_workbench_dismissals())
        recent = self.client.get("/api/workbench/recent").json()["items"]
        self.assertEqual([item["task_id"] for item in recent], [task_id])

    def test_save_updates_queued_limits_and_definition_rate(self) -> None:
        _, node_id = self.create_task_node()
        task_id = self.start_task(node_id)

        updated = self.client.patch(
            f"/api/workbench/runs/{task_id}/config",
            json={
                "limits": {"max_seconds": 7200, "max_products": 5000},
                "rate": {
                    "concurrency": 4,
                    "per_domain_rps": 3.5,
                    "delay_ms": 250,
                },
                "sync_definition": True,
                "action": "save",
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        task = self.store.get_task(task_id)
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task.state, "QUEUED")
        self.assertEqual(task.limits["max_seconds"], 7200)
        self.assertEqual(task.limits["max_products"], 5000)
        self.assertEqual(
            task.limits["concurrency"], {"navigation": 4, "product": 4}
        )
        self.assertEqual(task.limits["fetch_delay_ms"], 250)
        self.assertEqual(task.input["rate_policy"]["per_domain_rps"], 3.5)
        self.assertEqual(task.input["rate_policy"]["delay_ms"], 250)
        definition = self.store.get_workbench_task_def(node_id)
        self.assertIsNotNone(definition)
        assert definition is not None
        self.assertEqual(definition.limits["concurrency"], 4)
        self.assertEqual(definition.limits["per_domain_rps"], 3.5)
        self.assertEqual(definition.limits["delay_ms"], 250)
        config = self.client.get(f"/api/workbench/runs/{task_id}/config").json()
        self.assertEqual(config["limits"]["max_seconds"], 7200)
        self.assertEqual(config["limits"]["concurrency"], 4)
        self.assertEqual(config["limits"]["per_domain_rps"], 3.5)
        self.assertEqual(config["limits"]["delay_ms"], 250)

    def test_save_unlimited_adds_cancellation_warning(self) -> None:
        _, node_id = self.create_task_node()
        task_id = self.start_task(node_id)
        response = self.client.patch(
            f"/api/workbench/runs/{task_id}/config",
            json={
                "limits": {"max_products": None, "max_seconds": None},
                "sync_definition": True,
                "action": "save",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(
            "本次保存已取消对应预算上限。",
            response.json()["warnings"],
        )
        task = self.store.get_task(task_id)
        self.assertIsNotNone(task)
        assert task is not None
        self.assertIsNone(task.limits["max_products"])
        self.assertIsNone(task.limits["max_seconds"])

    def test_start_uses_formal_policy_and_site_rate(self) -> None:
        self.store.set_setting(
            "collection_policy",
            json.dumps(
                {
                    "formal_unlimited": True,
                    "formal_max_products": 10000,
                    "formal_max_seconds": 3600,
                }
            ),
        )
        self.store.set_setting(
            "site_rate_policies",
            json.dumps(
                {
                    "fixture.example": {
                        "concurrency": 4,
                        "per_domain_rps": 4.0,
                        "delay_ms": 50,
                        "max_attempts": 2,
                        "backoff_ms": 1000,
                    }
                }
            ),
        )
        _, node_id = self.create_task_node(
            limits={
                "max_urls": None,
                "max_products": None,
                "max_seconds": None,
                "max_attempts": 2,
            }
        )
        task_id = self.start_task(node_id)
        task = self.store.get_task(task_id)
        self.assertIsNotNone(task)
        assert task is not None
        self.assertIsNone(task.limits["max_products"])
        self.assertIsNone(task.limits["max_seconds"])
        self.assertEqual(
            task.limits["concurrency"], {"navigation": 4, "product": 4}
        )
        self.assertEqual(task.limits["fetch_delay_ms"], 50)
        self.assertEqual(task.input["rate_policy"]["per_domain_rps"], 4.0)
        self.assertEqual(task.input["rate_policy"]["concurrency"], 4)

    def test_continue_rejects_cancelled_and_exhausted_empty_runs(self) -> None:
        _, node_id = self.create_task_node()
        task_id = self.start_task(node_id)
        self.store.update_task(
            task_id,
            state="CANCELLED",
            outcome="CANCELLED",
            stop_reason="USER_CANCELLED",
        )
        rejected = self.client.patch(
            f"/api/workbench/runs/{task_id}/config",
            json={"action": "continue"},
        )
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertEqual(
            rejected.json()["error"]["code"], "TASK_NOT_CONTINUABLE"
        )

        self.store.update_task(
            task_id,
            state="FINISHED",
            outcome="COMPLETED",
            stop_reason="NATURAL_END",
            finished_at="2026-11-27T10:00:00Z",
            counters={"valid_products": 2, "pending_products": 0},
        )
        empty = self.client.patch(
            f"/api/workbench/runs/{task_id}/config",
            json={"action": "continue"},
        )
        self.assertEqual(empty.status_code, 409, empty.text)
        self.assertEqual(empty.json()["error"]["code"], "TASK_NOT_CONTINUABLE")

    def test_continue_rejects_non_budget_error_with_pending_items(self) -> None:
        _, node_id = self.create_task_node()
        task_id = self.start_task(node_id)
        self.mark_budget_exhausted(task_id, stop_detail="max_sitemaps", pending_products=2)
        self.store.update_task(task_id, stop_reason="PLAN_ERROR", outcome="FAILED")
        endpoint = f"/api/workbench/runs/{task_id}/config"
        self.assertFalse(self.client.get(endpoint).json()["can_continue"])
        self.assertFalse(self.client.get(f"/api/tasks/{task_id}").json()["can_continue"])
        self.assertEqual(self.client.patch(endpoint, json={"action": "continue"}).status_code, 409)


class FakeBudgetStore:
    def __init__(self, counts: dict[str, int]) -> None:
        self.counts = counts

    def item_counts(self, task_id: str, item_type: str | None = None) -> dict[str, int]:
        return dict(self.counts)


class RunnerBudgetTests(unittest.TestCase):
    def make_runner(self) -> TaskRunner:
        runner = TaskRunner.__new__(TaskRunner)
        runner.task = Task(
            task_id="budget-task",
            plan_id="fixture-local",
            plan_version="2026.11.21-1",
            task_type="product",
            limits={"max_products": 10, "max_seconds": 3600},
        )
        runner.store = FakeBudgetStore(
            {"PENDING": 1, "DONE": 10, "EXCLUDED": 0, "FAILED": 0}
        )
        runner.fetcher = SimpleNamespace(requests=0)
        runner._started_monotonic = time.monotonic() - 10
        runner._run_seconds_base = 0
        return runner

    def test_refresh_task_limits_recomputes_discovery_caps(self) -> None:
        runner = TaskRunner.__new__(TaskRunner)
        runner.task = Task(
            task_id="budget-task",
            plan_id="fixture-local",
            plan_version="2026.11.21-1",
            task_type="product",
            limits={"max_navigation": 10, "max_sitemaps": 4},
        )
        runner.rule = SimpleNamespace(
            discovery={"limits": {"max_navigation": 100, "max_sitemaps": 50}},
            sources=[{"type": "sitemap", "max_sitemaps": 50}],
        )
        runner._event = lambda *args, **kwargs: None
        runner._refresh_discovery_caps()
        self.assertEqual(runner._max_navigation, 10)
        self.assertEqual(runner._max_sitemaps, 4)
        runner._refresh_task_limits(
            SimpleNamespace(
                limits={"max_navigation": 20, "max_sitemaps": 100}
            )
        )
        self.assertEqual(runner._max_navigation, 20)
        self.assertEqual(runner._max_sitemaps, 100)

    def test_time_budget_counts_across_restarts(self) -> None:
        runner = self.make_runner()
        runner.store.counts["DONE"] = 0
        runner._run_seconds_base = 3595
        self.assertTrue(runner._budget_exceeded())
        self.assertIn("任务时长达到上限", runner._budget_stop_detail())
        runner._run_seconds_base = 3000
        self.assertFalse(runner._budget_exceeded())

    def test_product_budget_is_a_hard_processing_cap(self) -> None:
        runner = self.make_runner()
        self.assertTrue(runner._budget_exceeded())
        self.assertIn(
            "商品数达到上限（10/10）", runner._budget_stop_detail()
        )
        runner.store.counts["DONE"] = 5
        self.assertFalse(runner._budget_exceeded())
        runner.store.counts["DONE"] = 10
        runner.store.counts["PENDING"] = 0
        self.assertFalse(runner._budget_exceeded())


class StopDetailTests(unittest.TestCase):
    def make_task(self, task_type: str = "product", **limits: object) -> Task:
        return Task(
            task_id="detail-task",
            plan_id="fixture-local",
            plan_version="2026.11.21-1",
            task_type=task_type,
            state="FINISHED",
            outcome="PARTIAL",
            stop_reason="BUDGET_EXHAUSTED",
            finished_at="2026-11-27T10:00:00Z",
            limits=limits,
        )

    def test_generic_budget_detail_names_the_reached_limit(self) -> None:
        task = self.make_task(max_products=10000, max_seconds=3600)
        self.assertEqual(
            _workbench_stop_detail(
                task,
                {"processed_products": 639},
                {"stop_detail": "task budget exhausted"},
            ),
            "任务时长达到入队时的上限 3600 秒（1 小时）",
        )
        self.assertEqual(
            _workbench_stop_detail(
                self.make_task(max_products=10, max_seconds=3600),
                {"processed_products": 10},
                {"stop_detail": "task budget exhausted"},
            ),
            "商品数达到入队时的上限 10",
        )
        self.assertEqual(
            _workbench_stop_detail(
                self.make_task("discovery", max_urls=5, max_seconds=3600),
                {"valid_urls": 5},
                {"stop_detail": "task budget exhausted"},
            ),
            "URL 数达到入队时的上限 5",
        )
        self.assertEqual(
            _workbench_stop_detail(
                task,
                {"processed_products": 2333},
                {"stop_detail": "sitemap index reached max_sitemaps"},
            ),
            "sitemap index reached max_sitemaps",
        )
        running = self.make_task(max_products=10000, max_seconds=3600)
        running.state = "RUNNING"
        running.outcome = None
        running.stop_reason = None
        running.finished_at = None
        self.assertIsNone(
            _workbench_stop_detail(
                running, {"processed_products": 639}, {}
            )
        )


if __name__ == "__main__":
    unittest.main()
