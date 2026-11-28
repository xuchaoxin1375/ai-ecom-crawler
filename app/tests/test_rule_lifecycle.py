from __future__ import annotations

import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from ecom_crawler.runtime.models import (
    BuildRecord,
    RuleVersion,
    SiteRule,
    Task,
    utc_now,
)
from ecom_crawler.runtime.rule import load_rule
from ecom_crawler.runtime.store import TaskStore
from ecom_crawler.web.app import create_app

CLIENT_HEADERS = {
    "Host": "127.0.0.1:8765",
    "Origin": "http://127.0.0.1:8765",
    "X-Requested-With": "XMLHttpRequest",
}
BASE_VERSION = "2026.11.21-1"


class RuleLifecycleApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "tasks.db"
        self.out_root = self.root / "tasks"
        self.rules_dir = self.root / "rules"
        self.rules_dir.mkdir()
        self.rule_source = (
            Path(__file__).parents[2]
            / "experiments"
            / "d03"
            / "familidoo"
            / "familidoo-d03.yaml"
        )
        self.rule_path = self.rules_dir / "familidoo.yaml"
        shutil.copy(self.rule_source, self.rule_path)
        rule = load_rule(self.rule_path)
        self.rule_id = rule.rule_id
        digest = hashlib.sha256(self.rule_path.read_bytes()).hexdigest()
        now = utc_now()
        self.store = TaskStore(self.db_path)
        self.store.create_rule_version(
            RuleVersion(
                rule_id=self.rule_id,
                rule_version=BASE_VERSION,
                sha256=digest,
                path=self.rule_path.name,
                status="active",
                activated_at=now,
                activated_by="test-fixture",
            )
        )
        self.store.upsert_site_rule(
            SiteRule(
                site_key="familidoo.fr",
                rule_id=self.rule_id,
                rule_version=BASE_VERSION,
                sha256=digest,
                path=self.rule_path.name,
                updated_at=now,
            )
        )
        self.client = TestClient(
            create_app(self.db_path, self.out_root, self.rules_dir),
            headers=CLIENT_HEADERS,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def add_version(
        self,
        version: str,
        *,
        status: str = "candidate",
        source_build_id: str | None = None,
    ) -> tuple[Path, str]:
        payload = yaml.safe_load(self.rule_path.read_text(encoding="utf-8"))
        payload["rule_version"] = version
        payload["status"] = "candidate"
        path = self.rules_dir / f"familidoo-{version}.yaml"
        path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.store.create_rule_version(
            RuleVersion(
                rule_id=self.rule_id,
                rule_version=version,
                sha256=digest,
                path=path.name,
                status=status,
                parent_version=BASE_VERSION,
                source_build_id=source_build_id,
            )
        )
        return path, digest

    def create_workbench_def(self, version: str) -> str:
        group = self.client.post(
            "/api/workbench/groups", json={"name": "生命周期测试"}
        )
        self.assertEqual(group.status_code, 201, group.text)
        created = self.client.post(
            "/api/workbench/tasks",
            json={
                "name": f"familidoo-{version}",
                "input_url": "https://www.familidoo.fr/fr/",
                "parent_id": group.json()["node"]["node_id"],
                "rule_id": self.rule_id,
                "rule_version": version,
                "task_type": "product",
                "collection_mode": "sample",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        return created.json()["node"]["node_id"]

    def create_build(self, version: str, state: str) -> str:
        build_id = f"build-{version}-{state.lower()}"
        self.store.create_build(
            BuildRecord(
                build_id=build_id,
                batch_id="batch-fixture",
                site_key="familidoo.fr",
                state=state,
                outcome="succeeded" if state == "FINISHED" else None,
                rule_id=self.rule_id,
                rule_version=version,
                target_rule_version=version,
                source_rule_version=BASE_VERSION,
                source_rule_sha256=hashlib.sha256(
                    self.rule_path.read_bytes()
                ).hexdigest(),
            )
        )
        return build_id

    def test_retire_site_rule_blocks_new_work_and_can_be_reactivated(self) -> None:
        node_id = self.create_workbench_def(BASE_VERSION)
        active_build = self.create_build(BASE_VERSION, "RUNNING")
        blocked = self.client.post(
            "/api/sites/familidoo.fr/rule/retire",
            json={"request_id": "retire-busy"},
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(blocked.json()["error"]["code"], "SITE_BUSY")
        self.store.update_build(active_build, state="FINISHED", outcome="succeeded")

        retired = self.client.post(
            "/api/sites/familidoo.fr/rule/retire",
            json={"request_id": "retire-1", "reason": "停止新任务"},
        )
        self.assertEqual(retired.status_code, 200, retired.text)
        body = retired.json()
        self.assertTrue(body["retired"])
        self.assertIsNotNone(body["site"]["retired_at"])
        self.assertEqual(
            body["site"]["active"]["rule_version"], BASE_VERSION
        )
        version = self.store.get_rule_version(self.rule_id, BASE_VERSION)
        self.assertIsNotNone(version)
        self.assertEqual(version.status, "retired")
        activation = self.store.get_activation_by_request("retire-1")
        self.assertIsNotNone(activation)
        self.assertEqual(activation.action, "retire")

        repeated = self.client.post(
            "/api/sites/familidoo.fr/rule/retire",
            json={"request_id": "retire-1"},
        )
        self.assertEqual(repeated.status_code, 200, repeated.text)
        duplicate = self.client.post(
            "/api/sites/familidoo.fr/rule/retire",
            json={"request_id": "retire-2"},
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["error"]["code"], "RULE_RETIRED")

        start = self.client.post(f"/api/workbench/tasks/{node_id}/start")
        self.assertEqual(start.status_code, 409, start.text)
        self.assertEqual(start.json()["error"]["code"], "SITE_RULE_RETIRED")

        direct = self.client.post(
            "/api/tasks",
            json={
                "request_id": "retired-direct-task",
                "rule_id": self.rule_id,
                "rule_version": BASE_VERSION,
                "task_type": "product",
                "limits": {
                    "max_urls": 3,
                    "max_products": 2,
                    "max_seconds": 30,
                    "max_attempts": 1,
                },
            },
        )
        self.assertEqual(direct.status_code, 409, direct.text)
        self.assertEqual(direct.json()["error"]["code"], "SITE_RULE_RETIRED")

        batch = self.client.post(
            "/api/batches",
            json={
                "name": "retired batch",
                "sites": ["https://www.familidoo.fr/fr/"],
            },
        )
        self.assertEqual(batch.status_code, 201, batch.text)
        site = batch.json()["batch"]["sites"][0]
        self.assertEqual(site["readiness"], "needs_onboarding")
        self.assertIn("已停用", site["note"])

        _, candidate_digest = self.add_version("2026.11.21-2")
        site_rule, _ = self.store.activate_rule(
            site_key="familidoo.fr",
            rule_id=self.rule_id,
            rule_version="2026.11.21-2",
            sha256=candidate_digest,
            expected_active_version=BASE_VERSION,
            request_id="reactivate-1",
            action="activate",
        )
        self.assertIsNone(site_rule.retired_at)
        restarted = self.client.post(f"/api/workbench/tasks/{node_id}/start")
        self.assertEqual(restarted.status_code, 202, restarted.text)

    def test_cleanup_preview_and_purge_unreferenced_version(self) -> None:
        path, digest = self.add_version("2026.11.21-3", status="rejected")
        preview = self.client.get(
            f"/api/rules/{self.rule_id}/versions/2026.11.21-3/cleanup-preview"
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        body = preview.json()
        self.assertTrue(body["can_purge"])
        self.assertTrue(body["file_exists"])
        self.assertEqual(body["references"]["tasks"], 0)
        self.assertEqual(body["references"]["builds"], 0)

        purged = self.client.post(
            f"/api/rules/{self.rule_id}/versions/2026.11.21-3/purge",
            json={"request_id": "cleanup-1", "reason": "测试清理"},
        )
        self.assertEqual(purged.status_code, 200, purged.text)
        result = purged.json()
        self.assertTrue(result["purged"])
        self.assertTrue(result["file_removed"])
        self.assertFalse(path.exists())
        self.assertIsNone(
            self.store.get_rule_version(self.rule_id, "2026.11.21-3")
        )
        audit = self.store.get_rule_cleanup_by_request("cleanup-1")
        self.assertIsNotNone(audit)
        self.assertEqual(audit["sha256"], digest)

        repeated = self.client.post(
            f"/api/rules/{self.rule_id}/versions/2026.11.21-3/purge",
            json={"request_id": "cleanup-1"},
        )
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["cleanup_id"], result["cleanup_id"])

    def test_cleanup_blocks_task_definition_and_active_build(self) -> None:
        self.add_version("2026.11.21-4", status="rejected")
        self.store.create_task(
            Task(
                task_id="task-cleanup-ref",
                plan_id=self.rule_id,
                plan_version="2026.11.21-4",
                task_type="product",
                state="FINISHED",
                outcome="COMPLETED",
            )
        )
        blocked = self.client.post(
            f"/api/rules/{self.rule_id}/versions/2026.11.21-4/purge",
            json={"request_id": "cleanup-task-blocked"},
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(
            blocked.json()["error"]["code"], "RULE_CLEANUP_BLOCKED"
        )

        self.add_version("2026.11.21-5", status="candidate")
        self.create_workbench_def("2026.11.21-5")
        preview = self.client.get(
            f"/api/rules/{self.rule_id}/versions/2026.11.21-5/cleanup-preview"
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertFalse(preview.json()["can_purge"])
        self.assertEqual(preview.json()["references"]["workbench_defs"], 1)

        self.add_version("2026.11.21-6", status="candidate")
        self.create_build("2026.11.21-6", "RUNNING")
        active = self.client.get(
            f"/api/rules/{self.rule_id}/versions/2026.11.21-6/cleanup-preview"
        )
        self.assertEqual(active.status_code, 200, active.text)
        self.assertFalse(active.json()["can_purge"])
        self.assertEqual(active.json()["references"]["builds_active"], 1)

    def test_cleanup_blocks_changed_rule_file(self) -> None:
        path, _ = self.add_version("2026.11.21-8", status="rejected")
        path.write_text(
            path.read_text(encoding="utf-8") + "\n# changed after ledger\n",
            encoding="utf-8",
        )
        preview = self.client.get(
            f"/api/rules/{self.rule_id}/versions/2026.11.21-8/cleanup-preview"
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        body = preview.json()
        self.assertFalse(body["can_purge"])
        self.assertIn("哈希", " ".join(body["blockers"]))
        purged = self.client.post(
            f"/api/rules/{self.rule_id}/versions/2026.11.21-8/purge",
            json={"request_id": "cleanup-changed-file"},
        )
        self.assertEqual(purged.status_code, 409, purged.text)
        self.assertTrue(path.exists())

    def test_terminal_build_is_a_warning_not_a_blocker(self) -> None:
        path, _ = self.add_version(
            "2026.11.21-7", status="rejected", source_build_id="build-terminal-7"
        )
        build_id = self.create_build("2026.11.21-7", "FINISHED")
        self.assertEqual(build_id, "build-2026.11.21-7-finished")
        preview = self.client.get(
            f"/api/rules/{self.rule_id}/versions/2026.11.21-7/cleanup-preview"
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        body = preview.json()
        self.assertTrue(body["can_purge"])
        self.assertEqual(body["references"]["builds"], 1)
        self.assertEqual(body["references"]["builds_active"], 0)
        self.assertTrue(body["warnings"])

        purged = self.client.post(
            f"/api/rules/{self.rule_id}/versions/2026.11.21-7/purge",
            json={"request_id": "cleanup-terminal-build"},
        )
        self.assertEqual(purged.status_code, 200, purged.text)
        self.assertFalse(path.exists())
        self.assertIsNotNone(self.store.get_build(build_id))
