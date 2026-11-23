from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from ecom_crawler.migrate_rules import migrate
from ecom_crawler.runtime.models import Batch, BatchSite, BuildRecord, Task, utc_now
from ecom_crawler.runtime.store import TaskStore


def write_rule(
    root: Path,
    name: str,
    *,
    rule_id: str | None,
    rule_version: str,
    status: str = "candidate",
    extra: str = "",
) -> Path:
    payload: dict[str, Any] = {
        "rule_version": rule_version,
        "status": status,
        "updated_at": "2026-11-23T00:00:00Z",
    }
    if rule_id is not None:
        payload["rule_id"] = rule_id
    if extra:
        payload["notes"] = extra
    path = root / name
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


class MigrateRulesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temporary.name)
        self.db = self.root / "tasks.db"
        self.rules = self.root / "rules"
        self.rules.mkdir()
        self.store = TaskStore(self.db)
        for batch_id in ("b-1", "b-2"):
            self.store.create_batch(
                Batch(batch_id=batch_id, name=batch_id, market="FR", language="fr-FR")
            )
        self.store.add_batch_sites(
            [
                BatchSite(
                    batch_id="b-1",
                    site_key="example.fr",
                    domain="example.fr",
                    input_value="https://example.fr/",
                    readiness="ready",
                ),
                BatchSite(
                    batch_id="b-2",
                    site_key="example.fr",
                    domain="example.fr",
                    input_value="https://example.fr/",
                    readiness="ready",
                ),
                BatchSite(
                    batch_id="b-1",
                    site_key="kept.fr",
                    domain="kept.fr",
                    input_value="https://kept.fr/",
                    readiness="ready",
                ),
            ]
        )
        self.v1 = write_rule(
            self.rules,
            "example-v1.yaml",
            rule_id="example",
            rule_version="2026.11.23-1",
            status="active",
        )
        self.v2 = write_rule(
            self.rules,
            "example-v2.yaml",
            rule_id="example",
            rule_version="2026.11.23-2",
        )
        self.v3 = write_rule(
            self.rules,
            "example-v3.yaml",
            rule_id="example",
            rule_version="2026.11.23-3",
        )
        self.v0 = write_rule(
            self.rules,
            "example-v0.yaml",
            rule_id="example",
            rule_version="2026.11.22-0",
        )
        write_rule(
            self.rules,
            "other-old.yaml",
            rule_id="other",
            rule_version="2026.11.22-1",
            status="active",
        )
        write_rule(
            self.rules,
            "dup-a.yaml",
            rule_id="dup",
            rule_version="2026.11.22-1",
            extra="a",
        )
        write_rule(
            self.rules,
            "dup-b.yaml",
            rule_id="dup",
            rule_version="2026.11.22-1",
            extra="b",
        )
        write_rule(
            self.rules,
            "broken.yaml",
            rule_id=None,
            rule_version="2026.11.22-1",
        )
        self._set_site_pointer(
            "b-1",
            "example.fr",
            "example",
            "2026.11.23-1",
            self.v1.name,
            "2026-11-22T00:00:00Z",
        )
        self._set_site_pointer(
            "b-2",
            "example.fr",
            "example",
            "2026.11.23-2",
            self.v2.name,
            "2026-11-23T00:00:00Z",
        )
        self._set_site_pointer(
            "b-1",
            "kept.fr",
            "kept",
            "2026.11.22-1",
            self.v1.name,
            "2026-11-21T00:00:00Z",
        )
        self.store.upsert_site_rule(
            self._site_rule("kept.fr", "kept", "2026.11.22-1", self.v1)
        )
        self.store.create_task(
            Task(
                task_id="task-1",
                plan_id="example-build",
                plan_version="2026.11.23-1",
                task_type="product",
                state="FINISHED",
                site_key="example.fr",
                rule_path=self.v1.name,
            )
        )
        self.store.create_task(
            Task(
                task_id="task-2",
                plan_id="example-build",
                plan_version="2026.11.23-1",
                task_type="product",
                state="FINISHED",
                site_key="example.fr",
                rule_path="missing-rule.yaml",
            )
        )
        self.store.create_task(
            Task(
                task_id="task-3",
                plan_id="example-build",
                plan_version="2026.11.23-1",
                task_type="product",
                state="FINISHED",
                site_key="example.fr",
                rule_sha256="a" * 64,
            )
        )
        self.store.create_build(
            BuildRecord(
                build_id="build-1",
                batch_id="b-1",
                site_key="example.fr",
                rule_version="2026.11.23-1",
            )
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _set_site_pointer(
        self,
        batch_id: str,
        site_key: str,
        rule_id: str,
        rule_version: str,
        rule_path: str,
        updated_at: str | None = None,
    ) -> None:
        with sqlite3.connect(self.db) as connection:
            connection.execute(
                """
                UPDATE batch_sites
                SET rule_id = ?, rule_version = ?, rule_path = ?, updated_at = ?
                WHERE batch_id = ? AND site_key = ?
                """,
                (
                    rule_id,
                    rule_version,
                    rule_path,
                    updated_at or utc_now(),
                    batch_id,
                    site_key,
                ),
            )

    def _site_rule(self, site_key: str, rule_id: str, version: str, path: Path):
        from ecom_crawler.runtime.models import SiteRule

        return SiteRule(
            site_key=site_key,
            rule_id=rule_id,
            rule_version=version,
            sha256="b" * 64,
            path=path.name,
        )

    def test_migration_backfills_and_is_idempotent(self) -> None:
        dry = migrate(self.db, self.rules, dry_run=True)
        self.assertIsNone(self.store.get_site_rule("example.fr"))
        self.assertEqual(dry["report"]["counts"]["site_rules_written"], 1)

        result = migrate(self.db, self.rules)
        report = result["report"]
        counts = report["counts"]
        self.assertEqual(counts["site_rules_written"], 1)
        self.assertEqual(counts["site_rules_skipped"], 1)
        self.assertEqual(counts["site_rule_conflicts"], 1)
        self.assertEqual(counts["rule_version_conflicts"], 1)
        self.assertGreaterEqual(counts["missing_rule_files"], 1)
        self.assertEqual(counts["tasks_hash_written"], 1)
        self.assertEqual(counts["tasks_without_hash"], 1)
        self.assertEqual(counts["builds_backfilled"], 1)

        active = self.store.get_site_rule("example.fr")
        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual(active.rule_version, "2026.11.23-2")
        kept = self.store.get_site_rule("kept.fr")
        assert kept is not None
        self.assertEqual(kept.sha256, "b" * 64)

        statuses = {
            (item.rule_id, item.rule_version): item.status
            for item in self.store.list_rule_versions("example", limit=10)[0]
        }
        self.assertEqual(statuses[("example", "2026.11.23-2")], "active")
        self.assertEqual(statuses[("example", "2026.11.23-3")], "candidate")
        self.assertEqual(statuses[("example", "2026.11.22-0")], "superseded")
        other = self.store.list_rule_versions("other", limit=10)[0]
        self.assertEqual(other[0].status, "superseded")
        self.assertEqual(self.store.list_rule_versions("dup", limit=10)[0], [])

        self.assertIsNotNone(self.store.get_task("task-1").rule_sha256)
        self.assertIsNone(self.store.get_task("task-2").rule_sha256)
        self.assertEqual(self.store.get_build("build-1").target_rule_version, "2026.11.23-1")

        text = result["path"].read_text(encoding="utf-8")
        self.assertNotIn(str(self.root), text)
        self.assertIn("broken.yaml", text)
        self.assertIn("missing-rule.yaml", text)

        second = migrate(self.db, self.rules)["report"]["counts"]
        self.assertEqual(second["site_rules_written"], 0)
        self.assertEqual(second["rule_versions_written"], 0)
        self.assertEqual(second["tasks_hash_written"], 0)
        self.assertEqual(second["builds_backfilled"], 0)

    def test_migration_does_not_overwrite_existing_site_rule(self) -> None:
        result = migrate(self.db, self.rules)
        kept = self.store.get_site_rule("kept.fr")
        assert kept is not None
        self.assertEqual(kept.sha256, "b" * 64)
        self.assertEqual(result["report"]["counts"]["site_rules_skipped"], 1)


if __name__ == "__main__":
    unittest.main()
