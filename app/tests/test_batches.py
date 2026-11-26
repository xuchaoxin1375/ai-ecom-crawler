from __future__ import annotations

import hashlib
import io
import json
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from ecom_crawler.runtime.batch import parse_site_text, parse_sites, target_key
from ecom_crawler.runtime.models import (
    Batch,
    BatchSite,
    BuildRecord,
    RuleVersion,
    SiteRule,
    Task,
    utc_now,
)
from ecom_crawler.runtime.rule import load_rule
from ecom_crawler.runtime.store import TaskStore
from ecom_crawler.runtime.worker import Worker
from ecom_crawler.web.app import create_app
from tests.test_execution import RULE_TEMPLATE, fixture_server

CLIENT_HEADERS = {
    "Host": "127.0.0.1:8765",
    "Origin": "http://127.0.0.1:8765",
    "X-Requested-With": "XMLHttpRequest",
}


class SiteParsingTests(unittest.TestCase):
    def test_normalizes_urls_and_marks_duplicates(self) -> None:
        parsed = parse_sites(
            [
                "https://www.Example.fr/path?q=1",
                "example.fr",
                "not a site",
                "ftp://example.fr",
                "https://shop.example.fr/",
            ]
        )
        self.assertEqual(parsed[0].domain, "www.example.fr")
        self.assertEqual(parsed[0].site_key, "example.fr")
        self.assertIsNone(parsed[0].error)
        self.assertEqual(parsed[1].duplicate_of, "https://www.Example.fr/path?q=1")
        self.assertIn("空白", parsed[2].error or "")
        self.assertIn("http", parsed[3].error or "")
        self.assertEqual(parsed[4].site_key, "shop.example.fr")

    def test_parse_text_accepts_csv_first_column(self) -> None:
        text = "url,name\nhttps://a.example.fr/,A\nb.example.fr,B\n\n"
        self.assertEqual(
            parse_site_text(text),
            ["https://a.example.fr/", "b.example.fr"],
        )

    def test_invalid_hosts_are_not_treated_as_domains(self) -> None:
        for raw in ("", "localhost", "127.0.0.1", "http://", "https://a..fr"):
            parsed = parse_sites([raw])
            self.assertFalse(parsed[0].valid, raw)


class BatchStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = TaskStore(self.root / "tasks.db")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_schema_contains_batch_objects_and_task_batch_id(self) -> None:
        connection = sqlite3.connect(self.root / "tasks.db")
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            task_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(tasks)")
            }
            site_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(batch_sites)")
            }
            build_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(builds)")
            }
        finally:
            connection.close()
        self.assertIn("batches", tables)
        self.assertIn("batch_sites", tables)
        self.assertIn("builds", tables)
        self.assertIn("batch_id", task_columns)
        self.assertIn("proxy", site_columns)
        self.assertIn("proxy", build_columns)

    def test_batch_crud_and_site_link(self) -> None:
        batch = Batch(batch_id="b-1", name="France", country="FR", market="FR")
        self.store.create_batch(batch)
        self.assertEqual(self.store.get_batch("b-1").name, "France")
        self.store.update_batch("b-1", note="note")
        self.assertEqual(self.store.get_batch("b-1").note, "note")

        site = BatchSite(
            batch_id="b-1",
            site_key="example.fr",
            domain="www.example.fr",
            input_value="https://www.example.fr/",
            readiness="ready",
            rule_id="rule-1",
            rule_version="1.0.0",
            rule_path="rule.yaml",
        )
        self.assertEqual(self.store.add_batch_sites([site]), 1)
        self.assertEqual(self.store.add_batch_sites([site]), 0)
        self.assertEqual(len(self.store.list_batch_sites("b-1")), 1)

        task = Task(
            task_id="task-batch",
            plan_id="rule-1",
            plan_version="1.0.0",
            task_type="product",
            state="DRAFT",
            batch_id="b-1",
        )
        self.assertTrue(
            self.store.create_task_for_site(task, site_key="example.fr")
        )
        self.assertFalse(
            self.store.create_task_for_site(task, site_key="example.fr")
        )
        self.assertEqual(self.store.get_task("task-batch").batch_id, "b-1")
        self.assertEqual(self.store.get_batch_site("b-1", "example.fr").task_id, "task-batch")
        self.assertEqual(len(self.store.list_batch_tasks("b-1")), 1)


class BatchApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "tasks.db"
        self.out_root = self.root / "tasks"
        self.store = TaskStore(self.db_path)
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
        shutil.copy(
            Path(__file__).parents[2]
            / "experiments"
            / "d03"
            / "decohappy"
            / "decohappy-a08.yaml",
            self.rules_dir / "decohappy.yaml",
        )
        for filename, site_key in (
            ("familidoo.yaml", "familidoo.fr"),
            ("decohappy.yaml", "decohappy.com"),
        ):
            self._activate_fixture_rule(filename, site_key)
        self.client = TestClient(
            create_app(self.db_path, self.out_root, self.rules_dir),
            headers=CLIENT_HEADERS,
        )

    def _activate_fixture_rule(self, filename: str, site_key: str) -> None:
        path = self.rules_dir / filename
        rule = load_rule(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        now = utc_now()
        self.store.create_rule_version(
            RuleVersion(
                rule_id=rule.rule_id,
                rule_version=rule.rule_version,
                sha256=digest,
                path=filename,
                status="active",
                activated_at=now,
                activated_by="test-fixture",
            )
        )
        self.store.upsert_site_rule(
            SiteRule(
                site_key=site_key,
                rule_id=rule.rule_id,
                rule_version=rule.rule_version,
                sha256=digest,
                path=filename,
                updated_at=now,
            )
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _create(self, **overrides: object) -> dict:
        body: dict = {
            "name": "法国手工纺织 2026-11",
            "country": "FR",
            "market": "FR",
            "language": "fr-FR",
            "category": "手工／纺织",
            "sites": [
                "https://www.familidoo.fr/fr/",
                "https://example-boutique.fr/",
                "not-a-domain",
                "ftp://example.fr",
                "familidoo.fr",
                "https://www.familidoo.fr/autre",
            ],
        }
        body.update(overrides)
        return self.client.post("/api/batches", json=body).json()

    def _add_familidoo_version(self, version: str) -> tuple[str, str]:
        payload = yaml.safe_load(
            (self.rules_dir / "familidoo.yaml").read_text(encoding="utf-8")
        )
        payload["rule_version"] = version
        payload["status"] = "candidate"
        target = self.rules_dir / f"familidoo-{version}.yaml"
        target.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        self.store.create_rule_version(
            RuleVersion(
                rule_id=str(payload["rule_id"]),
                rule_version=version,
                sha256=digest,
                path=target.name,
                status="candidate",
                parent_version="2026.11.21-1",
            )
        )
        return target.name, digest

    def _switch_site_rule(
        self,
        version: str,
        digest: str,
        *,
        action: str,
        request_id: str,
    ) -> None:
        active = self.store.get_site_rule("familidoo.fr")
        self.store.activate_rule(
            site_key="familidoo.fr",
            rule_id="familidoo-fr-d03",
            rule_version=version,
            sha256=digest,
            expected_active_version=active.rule_version if active else None,
            expected_active_sha256=active.sha256 if active else None,
            request_id=request_id,
            action=action,
            actor="test",
        )

    def _candidate_only_batch(self) -> dict:
        payload = yaml.safe_load(
            (self.rules_dir / "familidoo.yaml").read_text(encoding="utf-8")
        )
        payload["rule_id"] = "candidate-only-fr"
        payload["rule_version"] = "1.0.0"
        payload["status"] = "candidate"
        payload["site"]["name"] = "Candidate only"
        payload["site"]["entry_urls"] = ["https://candidate-only.fr/"]
        payload["site"]["allowed_origins"] = ["https://candidate-only.fr"]
        payload["site"]["allowed_path_prefixes"] = ["/"]
        payload["discovery"]["entry_url"] = "https://candidate-only.fr/"
        (self.rules_dir / "candidate-only.yaml").write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return self.client.post(
            "/api/batches",
            json={
                "name": "候选未激活",
                "market": "FR",
                "sites": ["https://candidate-only.fr/"],
            },
        ).json()

    def test_preview_does_not_create_batch(self) -> None:
        response = self.client.post(
            "/api/batches",
            json={
                "name": "预览批次",
                "sites": ["https://www.familidoo.fr/fr/", "bad"],
                "preview": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["created"])
        self.assertEqual(payload["preview"]["import"]["summary"]["ready"], 1)
        self.assertEqual(payload["preview"]["import"]["summary"]["invalid"], 1)
        self.assertEqual(self.client.get("/api/batches").json()["total"], 0)

    def test_create_imports_sites_and_explains_skips(self) -> None:
        payload = self._create()
        batch = payload["batch"]
        report = payload["import"]
        self.assertTrue(payload["created"])
        self.assertEqual(report["summary"]["total"], 6)
        self.assertEqual(report["summary"]["ready"], 1)
        self.assertEqual(report["summary"]["needs_onboarding"], 1)
        self.assertEqual(report["summary"]["duplicate"], 2)
        self.assertEqual(report["summary"]["invalid"], 2)
        self.assertEqual(batch["counts"]["sites"], 6)
        self.assertEqual(batch["status"], "PARTIAL_READY")

        reasons = {item["input_value"]: item["reason"] for item in report["items"]}
        self.assertIn("重复", reasons["familidoo.fr"])
        self.assertIn("域名", reasons["not-a-domain"])
        self.assertIn("http", reasons["ftp://example.fr"])
        ready = next(
            site for site in batch["sites"] if site["readiness"] == "ready"
        )
        self.assertEqual(ready["rule"]["rule_id"], "familidoo-fr-d03")
        self.assertEqual(batch["counts"]["startable"], 1)

        detail = self.client.get(f"/api/batches/{batch['batch_id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.json()["sites"]), 6)

    def test_import_appends_sites_to_existing_batch(self) -> None:
        batch = self._create()["batch"]
        before = batch["counts"]["sites"]
        response = self.client.post(
            f"/api/batches/{batch['batch_id']}/import",
            json={
                "sites_text": "https://another-boutique.example/\nbad",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        summary = payload["import"]["summary"]
        self.assertEqual(summary["needs_onboarding"], 1)
        self.assertEqual(summary["invalid"], 1)
        self.assertEqual(payload["batch"]["counts"]["sites"], before + 2)
        detail = self.client.get(f"/api/batches/{batch['batch_id']}").json()
        self.assertEqual(len(detail["sites"]), before + 2)

    def test_start_selected_sites(self) -> None:
        batch = self._create(
            sites=[
                "https://www.familidoo.fr/fr/",
                "https://decohappy.com/fr",
            ]
        )["batch"]
        batch_id = batch["batch_id"]
        response = self.client.post(
            f"/api/batches/{batch_id}/start",
            json={"site_keys": ["decohappy.com"]},
        )
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(len(payload["accepted"]), 1)
        self.assertEqual(payload["accepted"][0]["site_key"], "decohappy.com")
        detail = self.client.get(f"/api/batches/{batch_id}").json()
        by_key = {site["site_key"]: site for site in detail["sites"]}
        self.assertIsNotNone(by_key["decohappy.com"]["task_id"])
        self.assertIsNone(by_key["familidoo.fr"]["task_id"])

        missing = self.client.post(
            f"/api/batches/{batch_id}/start",
            json={"site_keys": ["missing.example"]},
        )
        self.assertEqual(missing.status_code, 404)

        second = self.client.post(
            f"/api/batches/{batch_id}/start",
            json={"site_keys": ["familidoo.fr"]},
        )
        self.assertEqual(second.status_code, 202)
        self.assertEqual(len(second.json()["accepted"]), 1)
        self.assertEqual(
            second.json()["accepted"][0]["site_key"], "familidoo.fr"
        )

    def test_planned_batch_matches_explicit_entry_and_keeps_other_scope(self) -> None:
        batch = self._create(
            collection_mode="formal",
            sites=[
                "https://www.familidoo.fr/fr/",
                "https://www.familidoo.fr/another-category/",
                "https://www.familidoo.fr/fr/#products",
            ],
        )["batch"]
        self.assertEqual(batch["counts"]["sites"], 2)
        self.assertEqual(batch["counts"]["startable"], 1)
        self.assertEqual(batch["counts"]["needs_onboarding"], 1)
        by_input = {site["input_value"]: site for site in batch["sites"]}
        matched = by_input["https://www.familidoo.fr/fr/"]
        other = by_input["https://www.familidoo.fr/another-category/"]
        self.assertNotEqual(matched["site_key"], other["site_key"])
        response = self.client.post(
            f"/api/batches/{batch['batch_id']}/start",
            json={"limits": {"max_products": 1, "max_seconds": 1}},
        )
        result = response.json()
        self.assertEqual(response.status_code, 202, result)
        self.assertEqual([item["site_key"] for item in result["accepted"]], [matched["site_key"]])
        self.assertEqual([item["site_key"] for item in result["skipped"]], [other["site_key"]])
        task = self.store.get_task(result["accepted"][0]["task_id"])
        self.assertEqual(task.input["target_entry"], matched["input_value"])
        self.assertEqual(task.domain_key, "familidoo.fr")
        self.assertEqual(task.limits["max_products"], 10000)
        self.assertEqual(task.limits["max_seconds"], 3600)

    def test_two_targets_on_same_domain_export_their_own_products(self) -> None:
        origin = "http://batch-catalog.test"
        entries = [f"{origin}/list?p={index}" for index in (2, 3)]
        for index, entry in zip((2, 3), entries, strict=True):
            rule = yaml.safe_load(RULE_TEMPLATE.replace("__BASE__", origin))
            rule["rule_id"] = f"batch-catalog-{index}"
            rule["site"]["entry_urls"] = [entry]
            rule["discovery"]["entry_url"] = entry
            filename = f"batch-catalog-{index}.yaml"
            (self.rules_dir / filename).write_text(yaml.safe_dump(rule), encoding="utf-8")
            self._activate_fixture_rule(filename, target_key("batch-catalog.test", entry, "GB"))

        batch = self._create(collection_mode="formal", market="GB", sites=entries)["batch"]
        path = f"/api/batches/{batch['batch_id']}"
        with fixture_server(proxy_origin=origin) as proxy:
            started = self.client.post(f"{path}/start", json={"proxy": proxy}).json()
            self.assertEqual(len(started["accepted"]), 2, started)
            Worker(self.store, out_root=self.out_root, per_domain_rps=50).run_once()
        response = self.client.get(f"{path}/export")
        self.assertEqual(response.status_code, 200, response.text)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            manifest = json.loads(archive.read("batch.json"))
            by_entry = {row["input_value"]: row for row in manifest["sites"]}
            for index, entry in zip((2, 3), entries, strict=True):
                row = by_entry[entry]
                self.assertEqual(row["counts"]["valid_products"], 1, row)
                csv_file = archive.read(f"sites/{row['site_key']}/products.csv").decode("utf-8")
                self.assertIn(f"Product {index}", csv_file)
                self.assertIn(f"{origin}/p{index}.html", csv_file)

    def test_import_prefers_active_rule_over_candidate(self) -> None:
        self._add_familidoo_version("2026.11.22-2")
        batch = self._create(sites=["https://www.familidoo.fr/fr/"])["batch"]
        ready = next(
            site for site in batch["sites"] if site["readiness"] == "ready"
        )
        self.assertEqual(ready["rule"]["rule_version"], "2026.11.21-1")

        started = self.client.post(
            f"/api/batches/{batch['batch_id']}/start", json={}
        ).json()
        self.assertEqual(len(started["accepted"]), 1, started)
        task = self.store.get_task(started["accepted"][0]["task_id"])
        assert task is not None
        self.assertEqual(task.plan_version, "2026.11.21-1")

    def test_start_uses_active_rule_after_activation_and_rollback(self) -> None:
        batch = self._create(sites=["https://www.familidoo.fr/fr/"])["batch"]
        path, digest = self._add_familidoo_version("2026.11.22-2")
        self._switch_site_rule(
            "2026.11.22-2",
            digest,
            action="activate",
            request_id="test-activate-2",
        )

        # The batch row still points at the rule imported before activation.
        started = self.client.post(
            f"/api/batches/{batch['batch_id']}/start", json={}
        ).json()
        self.assertEqual(len(started["accepted"]), 1, started)
        task = self.store.get_task(started["accepted"][0]["task_id"])
        assert task is not None
        self.assertEqual(task.plan_version, "2026.11.22-2")
        self.assertEqual(task.rule_path, str(self.rules_dir / path))

        second = self._create(sites=["https://www.familidoo.fr/fr/"])["batch"]
        second_site = next(
            site for site in second["sites"] if site["readiness"] == "ready"
        )
        self.assertEqual(
            second_site["rule"]["rule_version"], "2026.11.22-2"
        )

        active = self.store.get_site_rule("familidoo.fr")
        assert active is not None
        v1 = self.store.get_rule_version("familidoo-fr-d03", "2026.11.21-1")
        assert v1 is not None
        self.store.activate_rule(
            site_key="familidoo.fr",
            rule_id=v1.rule_id,
            rule_version=v1.rule_version,
            sha256=v1.sha256,
            expected_active_version="2026.11.22-2",
            expected_active_sha256=digest,
            request_id="test-rollback-1",
            action="rollback",
            actor="test",
        )
        third = self._create(sites=["https://www.familidoo.fr/fr/"])["batch"]
        third_site = next(
            site for site in third["sites"] if site["readiness"] == "ready"
        )
        self.assertEqual(
            third_site["rule"]["rule_version"], "2026.11.21-1"
        )

    def test_candidate_only_rule_is_not_ready(self) -> None:
        payload = self._candidate_only_batch()
        site = payload["batch"]["sites"][0]
        self.assertEqual(site["readiness"], "needs_onboarding")
        self.assertIn("未激活", site["note"])
        self.assertEqual(payload["import"]["summary"]["ready"], 0)

    def test_market_mismatch_is_skipped(self) -> None:
        payload = self._create(
            market="US",
            sites=["https://www.familidoo.fr/fr/"],
        )
        site = payload["batch"]["sites"][0]
        self.assertEqual(site["readiness"], "needs_onboarding")
        self.assertIn("市场不匹配", site["note"])
        started = self.client.post(
            f"/api/batches/{payload['batch']['batch_id']}/start", json={}
        ).json()
        self.assertEqual(started["accepted"], [])
        self.assertIn("市场不匹配", started["skipped"][0]["reason"])

    def test_build_events_stream_snapshot_and_end(self) -> None:
        batch = self._create()["batch"]
        build_id = "build-events"
        self.store.create_build(
            BuildRecord(
                build_id=build_id,
                batch_id=batch["batch_id"],
                site_key="familidoo.fr",
                state="FINISHED",
                outcome="succeeded",
            )
        )
        lines: list[str] = []
        with self.client.stream(
            "GET", f"/api/builds/{build_id}/events"
        ) as response:
            self.assertEqual(response.status_code, 200)
            for line in response.iter_lines():
                lines.append(line)
                if line == "event: end":
                    break
        text = "\n".join(lines)
        self.assertIn("event: snapshot", text)
        self.assertIn("event: end", text)
        self.assertIn('"build_id": "build-events"', text)

    def test_start_pause_cancel_and_archive(self) -> None:
        batch = self._create()["batch"]
        batch_id = batch["batch_id"]

        started = self.client.post(f"/api/batches/{batch_id}/start")
        self.assertEqual(started.status_code, 202)
        result = started.json()
        self.assertEqual(len(result["accepted"]), 1)
        self.assertEqual(len(result["skipped"]), 5)
        task_id = result["accepted"][0]["task_id"]
        self.assertEqual(result["batch"]["counts"]["queued"], 1)
        self.assertEqual(result["batch"]["status"], "RUNNING")

        again = self.client.post(f"/api/batches/{batch_id}/start").json()
        self.assertEqual(again["accepted"], [])
        self.assertIn("站点已开始", [item["reason"] for item in again["skipped"]])

        paused = self.client.post(f"/api/batches/{batch_id}/pause").json()
        self.assertEqual(paused["accepted"], [])
        self.assertIn("排队任务", paused["skipped"][0]["reason"])

        cancelled = self.client.post(f"/api/batches/{batch_id}/cancel")
        self.assertEqual(cancelled.status_code, 202)
        cancelled_payload = cancelled.json()
        self.assertEqual(cancelled_payload["accepted"][0]["task_id"], task_id)
        self.assertEqual(cancelled_payload["batch"]["counts"]["cancelled"], 1)
        self.assertEqual(cancelled_payload["batch"]["status"], "PARTIAL")

        rerun = self.client.post(
            f"/api/batches/{batch_id}/start",
            json={"rerun_finished": True},
        )
        self.assertEqual(rerun.status_code, 202, rerun.text)
        rerun_payload = rerun.json()
        self.assertEqual(len(rerun_payload["accepted"]), 1, rerun_payload)
        rerun_task_id = rerun_payload["accepted"][0]["task_id"]
        self.assertNotEqual(rerun_task_id, task_id)
        self.assertIsNotNone(self.store.get_task(task_id))
        self.assertIsNotNone(self.store.get_task(rerun_task_id))

        rerun_cancelled = self.client.post(f"/api/batches/{batch_id}/cancel")
        self.assertEqual(rerun_cancelled.status_code, 202, rerun_cancelled.text)
        self.assertEqual(
            rerun_cancelled.json()["accepted"][0]["task_id"], rerun_task_id
        )

        archive = self.client.post(f"/api/batches/{batch_id}/archive")
        self.assertEqual(archive.status_code, 202)
        self.assertEqual(archive.json()["batch"]["status"], "ARCHIVED")
        self.assertEqual(self.client.get("/api/batches").json()["total"], 0)
        self.assertEqual(
            self.client.get("/api/batches?include_archived=true").json()["total"], 1
        )
        self.assertEqual(
            self.client.post(f"/api/batches/{batch_id}/restore").status_code, 202
        )
        self.assertEqual(self.client.get("/api/batches").json()["total"], 1)

    def test_import_more_sites_and_filter_batches(self) -> None:
        batch = self._create()["batch"]
        batch_id = batch["batch_id"]
        added = self.client.post(
            f"/api/batches/{batch_id}/import",
            json={
                "sites": [
                    "https://www.familidoo.fr/fr/",
                    "nouveau-site.fr",
                    "nouveau-site.fr",
                ]
            },
        )
        self.assertEqual(added.status_code, 200)
        summary = added.json()["import"]["summary"]
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["duplicate"], 2)
        self.assertEqual(summary["needs_onboarding"], 1)

        by_country = self.client.get("/api/batches?country=fr").json()
        self.assertEqual(by_country["total"], 1)
        by_status = self.client.get("/api/batches?status=partial_ready").json()
        self.assertEqual(by_status["total"], 1)
        by_status = self.client.get("/api/batches?status=running").json()
        self.assertEqual(by_status["total"], 0)
        by_category = self.client.get(
            "/api/batches?category=%E6%89%8B%E5%B7%A5%EF%BC%8F%E7%BA%BA%E7%BB%87"
        ).json()
        self.assertEqual(by_category["total"], 1)

    def test_export_manifest_and_site_files(self) -> None:
        batch = self._create()["batch"]
        batch_id = batch["batch_id"]
        started = self.client.post(f"/api/batches/{batch_id}/start").json()
        task_id = started["accepted"][0]["task_id"]

        not_ready = self.client.get(f"/api/batches/{batch_id}/export")
        self.assertEqual(not_ready.status_code, 409)
        partial = self.client.get(f"/api/batches/{batch_id}/export?partial=true")
        self.assertEqual(partial.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(partial.content)) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("batch.json"))
        self.assertIn("batch.json", names)
        self.assertIn("sites.csv", names)
        statuses = {
            item["site_key"]: item["export_status"] for item in manifest["sites"]
        }
        self.assertEqual(statuses["example-boutique.fr"], "needs_onboarding")
        self.assertEqual(statuses["familidoo.fr"], "running")

        self.store.update_task(
            task_id,
            state="FINISHED",
            outcome="COMPLETED",
            stop_reason="NATURAL_END",
        )
        run_dir = self.out_root / task_id
        run_dir.mkdir(parents=True)
        (run_dir / "products.csv").write_text(
            "source_url,name,price\nhttps://example.fr/p/1,Example,9.99\n",
            encoding="utf-8",
        )
        task_result = json.dumps(
            {
                "counts": {
                    "valid_products": 1,
                    "failed_products": 0,
                },
                "coverage": {"status": "KNOWN"},
                "quality_exceptions": [],
            },
            ensure_ascii=False,
        )
        (run_dir / "task-result.json").write_text(task_result, encoding="utf-8")
        (run_dir / "records.jsonl").write_text(
            '{"source_url":"https://example.fr/p/1"}\n', encoding="utf-8"
        )
        (run_dir / "diagnostics").mkdir()
        (run_dir / "diagnostics" / "excluded.jsonl").write_text(
            '{"reason":"zero_price"}\n', encoding="utf-8"
        )
        (run_dir / "diagnostics" / "failed.jsonl").write_text(
            '{"reason":"timeout"}\n', encoding="utf-8"
        )
        (run_dir / "secret.txt").write_text("not exported", encoding="utf-8")
        expected = {
            "products.csv": (run_dir / "products.csv").read_bytes(),
            "task-result.json": (run_dir / "task-result.json").read_bytes(),
            "records.jsonl": (run_dir / "records.jsonl").read_bytes(),
            "diagnostics/excluded.jsonl": (
                run_dir / "diagnostics" / "excluded.jsonl"
            ).read_bytes(),
        }

        complete = self.client.get(f"/api/batches/{batch_id}/export")
        self.assertEqual(complete.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(complete.content)) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("batch.json"))
            for name, content in expected.items():
                self.assertEqual(
                    archive.read(f"sites/familidoo.fr/{name}"),
                    content,
                    name,
                )
        self.assertIn("sites/familidoo.fr/products.csv", names)
        self.assertIn("sites/familidoo.fr/diagnostics/failed.jsonl", names)
        self.assertNotIn("sites/familidoo.fr/secret.txt", names)
        ready = next(
            item for item in manifest["sites"] if item["site_key"] == "familidoo.fr"
        )
        self.assertEqual(ready["export_status"], "complete")
        self.assertEqual(ready["counts"]["valid_products"], 1)

    def test_unknown_batch_returns_404(self) -> None:
        self.assertEqual(self.client.get("/api/batches/missing").status_code, 404)
        self.assertEqual(
            self.client.post("/api/batches/missing/start").status_code, 404
        )
        self.assertEqual(
            self.client.get("/api/batches/missing/export").status_code, 404
        )


if __name__ == "__main__":
    unittest.main()
