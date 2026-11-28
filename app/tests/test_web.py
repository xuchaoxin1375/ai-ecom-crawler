from __future__ import annotations

import base64
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from ecom_crawler.runtime.identity import frontend_info
from ecom_crawler.runtime.models import Task, WorkItem
from ecom_crawler.runtime.store import TaskStore
from ecom_crawler.web.access import (
    SETTING_DEV_NO_AUTH,
    SETTING_LAN_ENABLED,
    SETTING_TOKEN,
)
from ecom_crawler.web.app import (
    FRONTEND_DIST_DIR,
    Limits,
    create_app,
)

CLIENT_HEADERS = {
    "Host": "127.0.0.1:8765",
    "Origin": "http://127.0.0.1:8765",
    "X-Requested-With": "XMLHttpRequest",
}


def basic_auth(token: str) -> dict[str, str]:
    return {
        "Authorization": "Basic "
        + base64.b64encode(f"ecom:{token}".encode()).decode()
    }


def make_task(
    task_id: str,
    state: str = "FINISHED",
    task_type: str = "product",
    site_key: str | None = None,
    batch_id: str | None = None,
) -> Task:
    return Task(
        task_id=task_id,
        plan_id="fixture-web",
        plan_version="1.0.0",
        task_type=task_type,
        state=state,
        outcome="COMPLETED" if state == "FINISHED" else None,
        stop_reason="NATURAL_END" if state == "FINISHED" else None,
        site_key=site_key,
        batch_id=batch_id,
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
        body = health.json()
        self.assertEqual(body["status"], "ok")
        self.assertIsInstance(body["pid"], int)
        self.assertEqual(body["port"], 8765)
        self.assertTrue(body["started_at"].endswith("Z"))
        self.assertEqual(len(body["instance_id"]), 12)
        self.assertEqual(len(body["code_fingerprint"]), 16)
        commit = body["git"]["commit"]
        self.assertTrue(commit is None or len(commit) == 40)
        self.assertIn(body["git"]["dirty"], (True, False, None))
        self.assertIn(body["frontend"]["kind"], {"react", "none"})
        self.assertIsInstance(body["frontend"]["mounted"], bool)
        self.assertNotIn("legacy_ui", body)
        self.assertEqual(self.client.get("/legacy").status_code, 404)
        self.assertEqual(self.client.get("/batch/").status_code, 404)
        self.assertEqual(self.client.get("/static/index.html").status_code, 404)
        if (FRONTEND_DIST_DIR / "index.html").is_file():
            index = self.client.get("/")
            self.assertEqual(index.status_code, 200)
            self.assertIn("采集", index.text)
            next_ui = self.client.get("/next/", follow_redirects=False)
            self.assertEqual(next_ui.status_code, 308)
            self.assertEqual(next_ui.headers["location"], "/")
            next_favicon = self.client.get(
                "/next/favicon.svg", follow_redirects=False
            )
            self.assertEqual(next_favicon.status_code, 308)
            self.assertEqual(next_favicon.headers["location"], "/favicon.svg")
            favicon = self.client.get("/favicon.svg")
            self.assertEqual(favicon.status_code, 200)
            assets = sorted((FRONTEND_DIST_DIR / "assets").glob("*.js"))
            if assets:
                asset = self.client.get(f"/assets/{assets[0].name}")
                self.assertEqual(asset.status_code, 200, asset.text)
        else:
            index = self.client.get("/", follow_redirects=False)
            self.assertEqual(index.status_code, 503)
            self.assertEqual(index.json()["error"]["code"], "UI_NOT_BUILT")

    def test_health_frontend_identity_is_snapshot_at_startup(self) -> None:
        dist = self.root / "frontend-dist"
        dist.mkdir()
        index = dist / "index.html"
        index.write_text("<html>old</html>", encoding="utf-8")
        with mock.patch("ecom_crawler.web.app.FRONTEND_DIST_DIR", dist), TestClient(
            create_app(self.db_path, self.out_root, self.rules_dir),
            headers=CLIENT_HEADERS,
        ) as client:
            first = client.get("/api/health").json()["frontend"]
            self.assertEqual(first["kind"], "react")
            self.assertTrue(first["mounted"])
            self.assertEqual(len(first["index_sha256"]), 16)
            index.write_text("<html>new</html>", encoding="utf-8")
            second = client.get("/api/health").json()["frontend"]
            self.assertEqual(second["index_sha256"], first["index_sha256"])
            self.assertNotEqual(frontend_info(dist)["sha256"], first["index_sha256"])

    def test_dev_identity_is_loopback_only_and_skips_auth(self) -> None:
        with TestClient(
            create_app(self.db_path, self.out_root, self.rules_dir, access_token="secret"),
            headers=CLIENT_HEADERS,
            client=("127.0.0.1", 50000),
        ) as client:
            self.assertEqual(client.get("/api/health").status_code, 401)
            identity = client.get("/api/dev/identity")
            self.assertEqual(identity.status_code, 200)
            self.assertEqual(identity.json()["pid"], os.getpid())
            self.assertEqual(identity.json()["port"], 8765)

        with TestClient(
            create_app(self.db_path, self.out_root, self.rules_dir, access_token="secret"),
            headers=CLIENT_HEADERS,
            client=("192.168.1.10", 50000),
        ) as remote:
            self.assertEqual(remote.get("/api/dev/identity").status_code, 404)

    def test_read_only_mode_rejects_writes_and_opens_ledger_read_only(self) -> None:
        app = create_app(
            self.db_path, self.out_root, self.rules_dir, read_only=True
        )
        self.assertTrue(app.state.read_only)
        self.assertFalse(app.state.worker_managed)
        self.assertIsNotNone(app.state.build_manager)
        self.assertTrue(app.state.build_manager.read_only)
        with TestClient(app, headers=CLIENT_HEADERS) as client:
            health = client.get("/api/health")
            self.assertEqual(health.status_code, 200, health.text)
            body = health.json()
            self.assertTrue(body["read_only"])
            self.assertEqual(body["worker"], "read-only")
            self.assertFalse(body["builds_available"])
            self.assertTrue(body["builds_readable"])
            build_config = client.get("/api/builds/config")
            self.assertEqual(build_config.status_code, 200, build_config.text)
            self.assertFalse(build_config.json()["available"])
            self.assertEqual(
                build_config.json()["unavailable_reason"], "read_only"
            )
            self.assertEqual(client.get("/api/batches").status_code, 200)
            self.assertEqual(client.get("/api/builds").status_code, 200)
            created = client.post(
                "/api/batches",
                json={"name": "blocked", "market": "FR"},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(created.status_code, 403, created.text)
            self.assertEqual(created.json()["error"]["code"], "READ_ONLY")
            paused = client.post(
                "/api/batches/b-1/pause",
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(paused.status_code, 403, paused.text)
        store = TaskStore(self.db_path, read_only=True)
        with self.assertRaises(sqlite3.OperationalError):
            store.update_task("task-1", state="PAUSED")

    def test_read_only_mode_cannot_manage_worker(self) -> None:
        with self.assertRaises(ValueError):
            create_app(
                self.db_path,
                self.out_root,
                self.rules_dir,
                manage_worker=True,
                read_only=True,
            )

    def test_root_requires_frontend_build(self) -> None:
        missing = self.root / "missing-dist"
        with mock.patch("ecom_crawler.web.app.FRONTEND_DIST_DIR", missing):
            client = TestClient(
                create_app(self.db_path, self.out_root, self.rules_dir),
                headers=CLIENT_HEADERS,
            )
            index = client.get("/", follow_redirects=False)
            self.assertEqual(index.status_code, 503)
            self.assertEqual(index.json()["error"]["code"], "UI_NOT_BUILT")

    def test_limits_accept_unbounded_full_catalog(self) -> None:
        limits = Limits(
            max_urls=None,
            max_products=None,
            max_seconds=None,
            max_attempts=2,
        )
        self.assertIsNone(limits.max_urls)
        self.assertIsNone(limits.max_products)
        self.assertIsNone(limits.max_seconds)
        self.assertEqual(limits.max_attempts, 2)

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

    def test_live_task_counts_use_canonical_keys(self) -> None:
        self.store.create_task(make_task("task-running", state="RUNNING"))
        for index, state in enumerate(
            ("DONE", "PENDING", "IN_FLIGHT", "EXCLUDED", "FAILED")
        ):
            self.store.add_item(
                WorkItem(
                    task_id="task-running",
                    item_id=f"running-product-{index}",
                    item_type="product",
                    url=f"https://fixture.test/live/{index}.html",
                    normalized_url=f"https://fixture.test/live/{index}.html",
                    state=state,
                    stage="product",
                )
            )
        self.store.add_item(
            WorkItem(
                task_id="task-running",
                item_id="running-nav",
                item_type="navigation",
                url="https://fixture.test/live",
                normalized_url="https://fixture.test/live",
                state="DONE",
                stage="discover",
            )
        )
        counts = self.client.get("/api/tasks/task-running").json()["counts"]
        self.assertEqual(counts["navigation_urls"], 1)
        self.assertEqual(counts["discovered_urls"], 6)
        self.assertEqual(counts["product_candidates"], 5)
        self.assertEqual(counts["pending_products"], 2)
        self.assertEqual(counts["in_flight_products"], 1)
        self.assertEqual(counts["processed_products"], 3)
        self.assertEqual(counts["valid_products"], 1)
        self.assertEqual(counts["excluded_products"], 1)
        self.assertEqual(counts["failed_products"], 1)
        self.assertEqual(counts["partial_description_products"], 0)
        self.assertEqual(counts["pending"], 2)
        self.assertEqual(counts["in_flight"], 1)
        self.assertEqual(counts["excluded"], 1)
        self.assertEqual(counts["failed"], 1)

        self.store.create_task(
            make_task(
                "task-discovery-running",
                state="RUNNING",
                task_type="discovery",
            )
        )
        for index, state in enumerate(("DONE", "PENDING", "EXCLUDED", "FAILED")):
            self.store.add_item(
                WorkItem(
                    task_id="task-discovery-running",
                    item_id=f"running-url-{index}",
                    item_type="product",
                    url=f"https://fixture.test/discovery/{index}.html",
                    normalized_url=f"https://fixture.test/discovery/{index}.html",
                    state=state,
                    stage="discover",
                )
            )
        self.store.add_item(
            WorkItem(
                task_id="task-discovery-running",
                item_id="discovery-nav",
                item_type="navigation",
                url="https://fixture.test/discovery",
                normalized_url="https://fixture.test/discovery",
                state="DONE",
                stage="discover",
            )
        )
        discovery = self.client.get(
            "/api/tasks/task-discovery-running"
        ).json()["counts"]
        self.assertEqual(discovery["navigation_urls"], 1)
        self.assertEqual(discovery["discovered_urls"], 5)
        self.assertEqual(discovery["url_candidates"], 4)
        self.assertEqual(discovery["pending_urls"], 1)
        self.assertEqual(discovery["valid_urls"], 1)
        self.assertEqual(discovery["excluded_urls"], 1)
        self.assertEqual(discovery["failed_urls"], 1)

    def test_list_filters_by_batch_and_site(self) -> None:
        self.store.create_task(
            make_task(
                "task-batch-a",
                site_key="alpha.test",
                batch_id="batch-a",
            )
        )
        self.store.create_task(
            make_task(
                "task-batch-b",
                site_key="beta.test",
                batch_id="batch-b",
                state="RUNNING",
            )
        )

        by_batch = self.client.get("/api/tasks?batch_id=batch-a").json()
        self.assertEqual([item["task_id"] for item in by_batch["items"]], ["task-batch-a"])

        by_site = self.client.get("/api/tasks?site_key=beta.test").json()
        self.assertEqual([item["task_id"] for item in by_site["items"]], ["task-batch-b"])

        # Tasks created before site_key existed fall back to plan_id.
        fallback = self.client.get("/api/tasks?site_key=fixture-web").json()
        self.assertEqual([item["task_id"] for item in fallback["items"]], ["task-1"])

        self.assertEqual(
            self.client.get("/api/tasks?batch_id=missing").json()["total"], 0
        )

    def test_list_sorts_by_requested_field(self) -> None:
        self.store.create_task(
            make_task("task-sort-b", site_key="beta.test", state="RUNNING")
        )
        self.store.create_task(
            make_task("task-sort-a", site_key="alpha.test", state="FINISHED")
        )

        by_task = self.client.get("/api/tasks?sort=task&order=asc").json()
        self.assertEqual(
            [item["site_key"] for item in by_task["items"]],
            ["alpha.test", "beta.test", "fixture-web"],
        )

        page = self.client.get(
            "/api/tasks?sort=task&order=asc&limit=1&offset=1"
        ).json()
        self.assertEqual(page["total"], 3)
        self.assertEqual([item["site_key"] for item in page["items"]], ["beta.test"])

        # task-1 is the only task with a result file and one valid product.
        by_results = self.client.get("/api/tasks?sort=results&order=desc").json()
        self.assertEqual(by_results["items"][0]["task_id"], "task-1")
        self.assertEqual(
            self.client.get("/api/tasks?sort=task&order=up").status_code,
            422,
        )

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

    def test_items_state_and_order_filters(self) -> None:
        done = self.client.get(
            "/api/tasks/task-1/items?kind=product&state=DONE&order=desc"
        ).json()
        self.assertEqual(done["total"], 2)
        self.assertEqual(done["items"][0]["item_id"], "p-1")
        failed = self.client.get(
            "/api/tasks/task-1/items?kind=product&state=FAILED"
        ).json()
        self.assertEqual(failed["total"], 1)
        self.assertEqual(failed["items"][0]["item_id"], "p-2")

    def test_items_can_include_full_description_from_export(self) -> None:
        csv_path = self.out_root / "task-1" / "products.csv"
        csv_path.write_text(
            "name,price_amount,price_currency,primary_image_url,description_html,"
            "category,brand,attributes,source_url\n"
            'Sample,6.45,EUR,,<p>Full description</p>,Textile,Fixture,'
            "Taille#S|M,https://fixture.test/p0.html\n",
            encoding="utf-8",
        )

        plain = self.client.get(
            "/api/tasks/task-1/items?kind=product&state=DONE"
        ).json()
        self.assertNotIn(
            "description_html",
            plain["items"][0]["result"].get("product_preview", {}),
        )

        enriched = self.client.get(
            "/api/tasks/task-1/items?kind=product&state=DONE&include_description=true"
        ).json()
        preview = enriched["items"][0]["result"]["product_preview"]
        self.assertEqual(preview["description_html"], "<p>Full description</p>")
        self.assertEqual(preview["attributes"], "Taille#S|M")

    def test_items_include_description_from_live_jsonl(self) -> None:
        self.store.create_task(make_task("running-1", state="RUNNING"))
        self.store.add_item(
            WorkItem(
                task_id="running-1",
                item_id="live-1",
                item_type="product",
                url="https://fixture.test/live.html",
                normalized_url="https://fixture.test/live.html",
                state="DONE",
                stage="product",
            )
        )
        task_dir = self.out_root / "running-1"
        task_dir.mkdir()
        (task_dir / "products.jsonl").write_text(
            json.dumps(
                {
                    "name": "Live sample",
                    "description_html": "<p>Live description</p>",
                    "attributes": "Taille#L",
                    "source_url": "https://fixture.test/live.html",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        payload = self.client.get(
            "/api/tasks/running-1/items?kind=product&state=DONE&include_description=true"
        ).json()
        preview = payload["items"][0]["result"]["product_preview"]
        self.assertEqual(preview["description_html"], "<p>Live description</p>")
        self.assertEqual(preview["attributes"], "Taille#L")

    def test_csv_preview_reads_export_header_and_rows(self) -> None:
        csv_path = self.out_root / "task-1" / "products.csv"
        csv_path.write_text(
            "name,price_amount,price_currency,source_url\n"
            "Sample,6.45,EUR,https://fixture.test/p0.html\n",
            encoding="utf-8",
        )
        payload = self.client.get("/api/tasks/task-1/csv?limit=10").json()
        self.assertEqual(payload["source"], "products.csv")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["columns"][0], "name")
        self.assertEqual(payload["rows"][0]["name"], "Sample")
        self.assertFalse(payload["live"])

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
        self.assertEqual(pause.status_code, 202)
        self.assertEqual(pause.json()["state"], "PAUSED")
        resume = self.client.post(f"/api/tasks/{task_id}/resume")
        self.assertEqual(resume.status_code, 202)
        self.assertEqual(resume.json()["state"], "QUEUED")
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

    def test_lan_access_requires_basic_token_and_allowed_host(self) -> None:
        token = "0123456789abcdef"
        auth = {
            "Authorization": "Basic "
            + base64.b64encode(f"ecom:{token}".encode()).decode()
        }
        lan_headers = {
            "Host": "192.168.1.20:8765",
            "Origin": "http://192.168.1.20:8765",
            "X-Requested-With": "XMLHttpRequest",
        }
        app = create_app(
            self.db_path,
            self.out_root,
            self.rules_dir,
            access_token=token,
            allowed_hosts={"192.168.1.20"},
        )
        self.assertTrue(app.state.auth_required)
        self.assertFalse(hasattr(app.state, "access_token"))
        client = TestClient(app, headers=lan_headers)

        missing = client.get("/api/health")
        self.assertEqual(missing.status_code, 401)
        self.assertNotIn("www-authenticate", missing.headers)

        wrong = client.get(
            "/api/health",
            headers={
                "Authorization": "Basic "
                + base64.b64encode(b"ecom:wrong-token").decode()
            },
        )
        self.assertEqual(wrong.status_code, 401)

        self.assertEqual(client.get("/api/health", headers=auth).status_code, 200)

        denied = TestClient(
            app,
            headers={
                **lan_headers,
                **auth,
                "Host": "evil.test",
                "Origin": "http://evil.test",
            },
        )
        self.assertEqual(denied.get("/api/health").status_code, 403)

        rule = self._first_rule()
        body = {
            "request_id": "req-lan",
            "rule_id": rule["rule_id"],
            "rule_version": rule["rule_version"],
            "task_type": "product",
        }
        created = client.post("/api/tasks", json=body, headers=auth)
        self.assertEqual(created.status_code, 201, created.text)

        cross = client.post(
            "/api/tasks",
            json={**body, "request_id": "req-lan-cross"},
            headers={**auth, "Origin": "http://evil.test"},
        )
        self.assertEqual(cross.status_code, 403)

        events = client.get("/api/tasks/task-1/events", headers=auth)
        self.assertEqual(events.status_code, 200)
        self.assertIn("event: end", events.text)

        loopback = TestClient(
            create_app(
                self.db_path,
                self.out_root,
                self.rules_dir,
                access_token=token,
            ),
            headers={"Host": "127.0.0.1:8765", **auth},
        )
        self.assertEqual(loopback.get("/api/health").status_code, 200)

        with tempfile.TemporaryDirectory() as temporary:
            empty = Path(temporary)
            with self.assertRaises(ValueError):
                create_app(
                    empty / "tasks.db",
                    empty / "out",
                    self.rules_dir,
                    allowed_hosts={"192.168.1.20"},
                )

    def test_login_session_custom_key_and_logout(self) -> None:
        token = "0123456789abcdef"
        lan_headers = {
            "Host": "192.168.1.20:8765",
            "Origin": "http://192.168.1.20:8765",
            "X-Requested-With": "XMLHttpRequest",
        }
        app = create_app(
            self.db_path,
            self.out_root,
            self.rules_dir,
            access_token=token,
            allowed_hosts={"192.168.1.20"},
            serve_host="0.0.0.0",
        )
        client = TestClient(app, headers=lan_headers)
        missing = client.get("/api/health")
        self.assertEqual(missing.status_code, 401)
        self.assertNotIn("www-authenticate", missing.headers)

        wrong = client.post("/api/auth/login", json={"key": "wrong"})
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.json()["error"]["code"], "INVALID_KEY")

        logged = client.post("/api/auth/login", json={"key": token})
        self.assertEqual(logged.status_code, 200, logged.text)
        cookie = logged.headers["set-cookie"]
        self.assertIn("ecom_session=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=lax", cookie)
        self.assertEqual(client.get("/api/health").status_code, 200)

        custom = client.post("/api/system/access/token", json={"token": "a"})
        self.assertEqual(custom.status_code, 200, custom.text)
        self.assertFalse(custom.json()["generated"])
        self.assertIsNone(custom.json()["token"])
        self.assertEqual(client.get("/api/health").status_code, 401)

        relogged = client.post("/api/auth/login", json={"key": "a"})
        self.assertEqual(relogged.status_code, 200, relogged.text)
        self.assertEqual(client.get("/api/health").status_code, 200)

        logged_out = client.post("/api/auth/logout")
        self.assertEqual(logged_out.status_code, 200)
        self.assertEqual(client.get("/api/health").status_code, 401)

    def test_dev_no_auth_bypasses_only_loopback_requests(self) -> None:
        token = "0123456789abcdef"
        lan_headers = {
            "Host": "192.168.1.20:8765",
            "Origin": "http://192.168.1.20:8765",
            "X-Requested-With": "XMLHttpRequest",
        }
        app = create_app(
            self.db_path,
            self.out_root,
            self.rules_dir,
            access_token=token,
            dev_no_auth=True,
            allowed_hosts={"192.168.1.20"},
            serve_host="0.0.0.0",
        )
        loopback = TestClient(
            app,
            headers=CLIENT_HEADERS,
            client=("127.0.0.1", 50000),
        )
        self.assertEqual(loopback.get("/api/health").status_code, 200)
        server = loopback.get("/api/system").json()["server"]
        self.assertFalse(server["dev_no_auth_setting"])
        self.assertTrue(server["dev_no_auth_active"])
        self.assertTrue(server["dev_no_auth_forced"])

        wrong_host = TestClient(
            app,
            headers={**lan_headers},
            client=("127.0.0.1", 50000),
        )
        self.assertEqual(wrong_host.get("/api/health").status_code, 401)

        remote = TestClient(
            app,
            headers=lan_headers,
            client=("192.168.1.10", 50000),
        )
        self.assertEqual(remote.get("/api/health").status_code, 401)
        self.assertEqual(
            remote.get("/api/health", headers=basic_auth(token)).status_code,
            200,
        )

        forced = loopback.put(
            "/api/system/access/dev-no-auth",
            json={"enabled": False},
        )
        self.assertEqual(forced.status_code, 409, forced.text)
        self.assertEqual(forced.json()["error"]["code"], "DEV_MODE_FORCED")

    def test_dev_no_auth_setting_persists_and_rejects_remote_toggle(self) -> None:
        token = "0123456789abcdef"
        lan_headers = {
            "Host": "192.168.1.20:8765",
            "Origin": "http://192.168.1.20:8765",
            "X-Requested-With": "XMLHttpRequest",
        }
        app = create_app(
            self.db_path,
            self.out_root,
            self.rules_dir,
            access_token=token,
            allowed_hosts={"192.168.1.20"},
            serve_host="0.0.0.0",
        )
        store = TaskStore(self.db_path)
        token_before = store.get_setting(SETTING_TOKEN)
        lan_before = store.get_setting(SETTING_LAN_ENABLED)
        loopback = TestClient(
            app,
            headers={**CLIENT_HEADERS, **basic_auth(token)},
            client=("127.0.0.1", 50000),
        )
        self.assertEqual(loopback.get("/api/health").status_code, 200)

        enabled = loopback.put(
            "/api/system/access/dev-no-auth",
            json={"enabled": True},
        )
        self.assertEqual(enabled.status_code, 200, enabled.text)
        access = enabled.json()["access"]
        self.assertTrue(access["dev_no_auth_setting"])
        self.assertTrue(access["dev_no_auth_active"])
        self.assertFalse(access["dev_no_auth_forced"])
        self.assertEqual(store.get_setting(SETTING_DEV_NO_AUTH), "1")
        self.assertEqual(store.get_setting(SETTING_TOKEN), token_before)
        self.assertEqual(store.get_setting(SETTING_LAN_ENABLED), lan_before)

        anonymous = TestClient(
            app,
            headers=CLIENT_HEADERS,
            client=("127.0.0.1", 50000),
        )
        self.assertEqual(anonymous.get("/api/health").status_code, 200)
        self.assertTrue(
            anonymous.get("/api/system").json()["server"]["dev_no_auth_active"]
        )

        remote = TestClient(
            app,
            headers={**lan_headers, **basic_auth(token)},
            client=("192.168.1.10", 50000),
        )
        rejected = remote.put(
            "/api/system/access/dev-no-auth",
            json={"enabled": False},
        )
        self.assertEqual(rejected.status_code, 403, rejected.text)
        self.assertEqual(
            rejected.json()["error"]["code"], "DEV_MODE_LOOPBACK_ONLY"
        )

        restored = create_app(
            self.db_path,
            self.out_root,
            self.rules_dir,
            allowed_hosts={"192.168.1.20"},
            serve_host="0.0.0.0",
        )
        restored_loopback = TestClient(
            restored,
            headers=CLIENT_HEADERS,
            client=("127.0.0.1", 50000),
        )
        self.assertEqual(restored_loopback.get("/api/health").status_code, 200)
        disabled = restored_loopback.put(
            "/api/system/access/dev-no-auth",
            json={"enabled": False},
        )
        self.assertEqual(disabled.status_code, 200, disabled.text)
        self.assertFalse(disabled.json()["access"]["dev_no_auth_active"])
        self.assertEqual(restored_loopback.get("/api/health").status_code, 401)

    def test_login_rate_limit_locks_after_failures(self) -> None:
        token = "0123456789abcdef"
        headers = {
            "Host": "192.168.1.20:8765",
            "Origin": "http://192.168.1.20:8765",
            "X-Requested-With": "XMLHttpRequest",
        }
        app = create_app(
            self.db_path,
            self.out_root,
            self.rules_dir,
            access_token=token,
            allowed_hosts={"192.168.1.20"},
            serve_host="0.0.0.0",
        )
        client = TestClient(app, headers=headers)
        for _ in range(5):
            response = client.post("/api/auth/login", json={"key": "wrong"})
            self.assertEqual(response.status_code, 401)
        blocked = client.post("/api/auth/login", json={"key": token})
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()["error"]["code"], "TOO_MANY_ATTEMPTS")
        self.assertIn("retry-after", blocked.headers)

    def test_read_only_allows_login_but_blocks_key_changes(self) -> None:
        token = "0123456789abcdef"
        headers = {
            "Host": "192.168.1.20:8765",
            "Origin": "http://192.168.1.20:8765",
            "X-Requested-With": "XMLHttpRequest",
        }
        app = create_app(
            self.db_path,
            self.out_root,
            self.rules_dir,
            read_only=True,
            access_token=token,
            allowed_hosts={"192.168.1.20"},
            serve_host="0.0.0.0",
        )
        client = TestClient(app, headers=headers)
        logged = client.post("/api/auth/login", json={"key": token})
        self.assertEqual(logged.status_code, 200, logged.text)
        self.assertEqual(client.get("/api/health").status_code, 200)
        changed = client.post("/api/system/access/token", json={"token": "a"})
        self.assertEqual(changed.status_code, 403)
        self.assertEqual(changed.json()["error"]["code"], "READ_ONLY")
        dev_mode = client.put(
            "/api/system/access/dev-no-auth",
            json={"enabled": True},
        )
        self.assertEqual(dev_mode.status_code, 403)
        self.assertEqual(dev_mode.json()["error"]["code"], "READ_ONLY")

    def test_spa_shell_is_public_but_api_requires_session(self) -> None:
        token = "0123456789abcdef"
        app = create_app(
            self.db_path,
            self.out_root,
            self.rules_dir,
            access_token=token,
        )
        client = TestClient(app, headers={"Host": "127.0.0.1:8765"})
        root = client.get("/", follow_redirects=False)
        self.assertNotEqual(root.status_code, 401)
        self.assertEqual(client.get("/api/health").status_code, 401)

    def test_custom_token_validation(self) -> None:
        token = "0123456789abcdef"
        app = create_app(
            self.db_path,
            self.out_root,
            self.rules_dir,
            access_token=token,
        )
        client = TestClient(app, headers={**CLIENT_HEADERS, **basic_auth(token)})
        for value in ("", "   ", "abc\ndef", "x" * 257):
            response = client.post("/api/system/access/token", json={"token": value})
            self.assertEqual(response.status_code, 400, value)
            self.assertEqual(response.json()["error"]["code"], "INVALID_ACCESS_KEY")
        accepted = client.post("/api/system/access/token", json={"token": "a"})
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertFalse(accepted.json()["generated"])
        self.assertIsNone(accepted.json()["token"])


        token = "0123456789abcdef"
        headers = {
            "Host": "192.168.1.20:8765",
            "Origin": "http://192.168.1.20:8765",
            "X-Requested-With": "XMLHttpRequest",
        }
        app = create_app(
            self.db_path,
            self.out_root,
            self.rules_dir,
            read_only=True,
            access_token=token,
            allowed_hosts={"192.168.1.20"},
        )
        self.assertEqual(
            TestClient(app, headers=headers).post("/api/tasks", json={}).status_code,
            401,
        )
        auth = {
            "Authorization": "Basic "
            + base64.b64encode(f"ecom:{token}".encode()).decode()
        }
        client = TestClient(app, headers={**headers, **auth})
        self.assertTrue(client.get("/api/health").json()["read_only"])
        rejected = client.post("/api/tasks", json={})
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(rejected.json()["error"]["code"], "READ_ONLY")

    def test_system_status_reports_access_and_resources(self) -> None:
        token = "0123456789abcdef"
        headers = {
            "Host": "192.168.1.20:8765",
            "Origin": "http://192.168.1.20:8765",
            "X-Requested-With": "XMLHttpRequest",
            **basic_auth(token),
        }
        app = create_app(
            self.db_path,
            self.out_root,
            self.rules_dir,
            access_token=token,
            allowed_hosts={"192.168.1.20"},
            serve_host="0.0.0.0",
            serve_port=8765,
            access_urls=["http://192.168.1.20:8765/next/"],
        )
        client = TestClient(app, headers=headers)
        body = client.get("/api/system").json()
        self.assertEqual(body["server"]["host"], "0.0.0.0")
        self.assertEqual(body["server"]["port"], 8765)
        self.assertTrue(body["server"]["lan_capable"])
        self.assertTrue(body["server"]["lan_enabled"])
        self.assertTrue(body["server"]["auth_required"])
        self.assertFalse(body["server"]["dev_no_auth_setting"])
        self.assertFalse(body["server"]["dev_no_auth_active"])
        self.assertFalse(body["server"]["dev_no_auth_forced"])
        self.assertEqual(body["server"]["session_ttl_seconds"], 30 * 24 * 60 * 60)
        self.assertEqual(
            body["server"]["urls"],
            ["http://192.168.1.20:8765/next/"],
        )
        self.assertEqual(body["runtime"]["worker"], "external")
        self.assertGreaterEqual(body["work"]["tasks_total"], 1)
        self.assertGreater(body["storage"]["disk_total_bytes"], 0)
        self.assertIsInstance(body["runtime"]["threads"], int)
        resources = body["resources"]
        self.assertTrue(resources["available"])
        self.assertGreater(resources["memory_total_bytes"], 0)
        self.assertGreaterEqual(resources["memory_percent"], 0)
        self.assertLessEqual(resources["memory_percent"], 100)
        self.assertGreaterEqual(resources["process_rss_bytes"], 0)
        self.assertTrue(resources["sampled_at"].endswith("Z"))
        if resources["cpu_percent"] is not None:
            self.assertGreaterEqual(resources["cpu_percent"], 0)
            self.assertLessEqual(resources["cpu_percent"], 100)
            self.assertGreater(resources["cpu_window_ms"], 0)

    def test_collection_slots_apply_on_restart_and_cli_overrides_saved_value(self) -> None:
        path = "/api/system/collection-slots"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db_path, out_root = root / "tasks.db", root / "out"
            with TestClient(create_app(db_path, out_root, manage_worker=True), headers=CLIENT_HEADERS) as client:
                runtime = client.get("/api/system").json()["runtime"]
                self.assertEqual(runtime["max_tasks"], 1)
                self.assertEqual(runtime["collection_slots"], {"next_start": 1, "source": "default"})
                for invalid in (0, -1, 2.5, True, "3", 2**53):
                    with self.subTest(invalid=invalid):
                        self.assertEqual(client.put(path, json={"max_tasks": invalid}).status_code, 422)
                saved = client.put(path, json={"max_tasks": 3})
                self.assertEqual(saved.status_code, 200, saved.text)
                runtime = client.get("/api/system").json()["runtime"]
                self.assertEqual(runtime["max_tasks"], 1)
                self.assertEqual(runtime["collection_slots"], {"next_start": 3, "source": "settings"})

            override = create_app(db_path, out_root, manage_worker=True, max_tasks=1)
            with TestClient(override, headers=CLIENT_HEADERS) as client:
                runtime = client.get("/api/system").json()["runtime"]
                self.assertEqual(runtime["collection_slots"], {"next_start": 1, "source": "cli"})
                self.assertEqual(client.put(path, json={"max_tasks": None}).status_code, 409)
            with TestClient(create_app(db_path, out_root, manage_worker=True), headers=CLIENT_HEADERS) as client:
                self.assertEqual(client.get("/api/health").json()["max_tasks"], 3)
                reset = client.put(path, json={"max_tasks": None})
                self.assertEqual(reset.json(), {"next_start": 1, "source": "default"})
                self.assertEqual(client.get("/api/health").json()["max_tasks"], 3)
            with TestClient(create_app(db_path, out_root, manage_worker=True), headers=CLIENT_HEADERS) as client:
                self.assertEqual(client.get("/api/health").json()["max_tasks"], 1)
            for read_only, status in ((False, 409), (True, 403)):
                preview = create_app(db_path, out_root, read_only=read_only)
                with TestClient(preview, headers=CLIENT_HEADERS) as client:
                    self.assertIsNone(client.get("/api/system").json()["runtime"]["collection_slots"])
                    self.assertEqual(client.put(path, json={"max_tasks": 2}).status_code, status)

    def test_build_slots_are_persisted_independently_of_collection_slots(self) -> None:
        path = "/api/system/build-slots"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rules = root / "rules"
            rules.mkdir()
            db_path = root / "tasks.db"
            app = create_app(db_path, root / "out", rules, manage_worker=True)
            with TestClient(app, headers=CLIENT_HEADERS) as client:
                self.assertEqual(client.get("/api/system").json()["runtime"]["max_builds"], 1)
                self.assertEqual(client.put(path, json={"max_tasks": 0}).status_code, 422)
                saved = client.put(path, json={"max_tasks": 2})
                self.assertEqual(saved.json(), {"next_start": 2, "source": "settings"})
                self.assertEqual(client.get("/api/system").json()["runtime"]["max_builds"], 1)
            restarted = create_app(db_path, root / "out", rules, manage_worker=True)
            with TestClient(restarted, headers=CLIENT_HEADERS) as client:
                runtime = client.get("/api/system").json()["runtime"]
                self.assertEqual((runtime["max_builds"], runtime["max_tasks"]), (2, 1))
            override = create_app(db_path, root / "out", rules, max_builds=1)
            with TestClient(override, headers=CLIENT_HEADERS) as client:
                self.assertEqual(
                    client.get("/api/system").json()["runtime"]["build_slots"],
                    {"next_start": 1, "source": "cli"},
                )
                self.assertEqual(client.put(path, json={"max_tasks": None}).status_code, 409)
            with TestClient(create_app(db_path, root / "out", rules), headers=CLIENT_HEADERS) as client:
                self.assertEqual(client.put(path, json={"max_tasks": None}).json(),
                                 {"next_start": 1, "source": "default"})
            preview = create_app(db_path, root / "out", rules, read_only=True)
            with TestClient(preview, headers=CLIENT_HEADERS) as client:
                self.assertEqual(client.put(path, json={"max_tasks": 2}).status_code, 403)

    def test_system_lan_toggle_persists_and_blocks_lan(self) -> None:
        token = "0123456789abcdef"
        lan_headers = {
            "Host": "192.168.1.20:8765",
            "Origin": "http://192.168.1.20:8765",
            "X-Requested-With": "XMLHttpRequest",
        }
        loop_headers = {
            **CLIENT_HEADERS,
            **basic_auth(token),
        }
        app = create_app(
            self.db_path,
            self.out_root,
            self.rules_dir,
            access_token=token,
            allowed_hosts={"192.168.1.20"},
            serve_host="0.0.0.0",
        )
        lan_client = TestClient(
            app,
            headers={**lan_headers, **basic_auth(token)},
        )
        disabled = lan_client.put(
            "/api/system/access",
            json={"lan_enabled": False},
        )
        self.assertEqual(disabled.status_code, 200, disabled.text)
        self.assertFalse(disabled.json()["access"]["lan_enabled"])
        self.assertEqual(lan_client.get("/api/health").status_code, 403)

        loopback = TestClient(app, headers=loop_headers)
        self.assertEqual(loopback.get("/api/health").status_code, 200)

        restored = create_app(
            self.db_path,
            self.out_root,
            self.rules_dir,
            allowed_hosts={"192.168.1.20"},
            serve_host="0.0.0.0",
        )
        restored_lan = TestClient(
            restored,
            headers={**lan_headers, **basic_auth(token)},
        )
        self.assertEqual(restored_lan.get("/api/health").status_code, 403)
        restored_loop = TestClient(restored, headers=loop_headers)
        self.assertEqual(restored_loop.get("/api/health").status_code, 200)
        enabled = restored_loop.put(
            "/api/system/access",
            json={"lan_enabled": True},
        )
        self.assertEqual(enabled.status_code, 200, enabled.text)
        self.assertEqual(restored_lan.get("/api/health").status_code, 200)

    def test_system_token_rotation_invalidates_old_token(self) -> None:
        token = "0123456789abcdef"
        lan_headers = {
            "Host": "192.168.1.20:8765",
            "Origin": "http://192.168.1.20:8765",
            "X-Requested-With": "XMLHttpRequest",
        }
        app = create_app(
            self.db_path,
            self.out_root,
            self.rules_dir,
            access_token=token,
            allowed_hosts={"192.168.1.20"},
            serve_host="0.0.0.0",
        )
        client = TestClient(
            app,
            headers={**lan_headers, **basic_auth(token)},
        )
        rotated = client.post("/api/system/access/token")
        self.assertEqual(rotated.status_code, 200, rotated.text)
        self.assertEqual(rotated.headers["cache-control"], "no-store")
        new_token = rotated.json()["token"]
        self.assertNotEqual(new_token, token)
        self.assertTrue(rotated.json()["generated"])
        self.assertTrue(rotated.json()["access"]["token_configured"])
        self.assertTrue(rotated.json()["access"]["token_updated_at"])
        self.assertEqual(client.get("/api/health").status_code, 401)
        self.assertEqual(
            client.get("/api/health", headers=basic_auth(new_token)).status_code,
            200,
        )

        restored = create_app(
            self.db_path,
            self.out_root,
            self.rules_dir,
            allowed_hosts={"192.168.1.20"},
            serve_host="0.0.0.0",
        )
        old_client = TestClient(
            restored,
            headers={**lan_headers, **basic_auth(token)},
        )
        new_client = TestClient(
            restored,
            headers={**lan_headers, **basic_auth(new_token)},
        )
        self.assertEqual(old_client.get("/api/health").status_code, 401)
        self.assertEqual(new_client.get("/api/health").status_code, 200)

    def test_system_access_requires_capability(self) -> None:
        token = "0123456789abcdef"
        app = create_app(
            self.db_path,
            self.out_root,
            self.rules_dir,
            access_token=token,
        )
        client = TestClient(
            app,
            headers={**CLIENT_HEADERS, **basic_auth(token)},
        )
        response = client.put(
            "/api/system/access",
            json={"lan_enabled": True},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "LAN_NOT_CAPABLE")
        rotated = client.post("/api/system/access/token")
        self.assertEqual(rotated.status_code, 200)
        self.assertTrue(rotated.json()["token"])

    def test_system_writes_rejected_in_read_only(self) -> None:
        token = "0123456789abcdef"
        app = create_app(
            self.db_path,
            self.out_root,
            self.rules_dir,
            read_only=True,
            access_token=token,
        )
        client = TestClient(
            app,
            headers={**CLIENT_HEADERS, **basic_auth(token)},
        )
        access = client.put(
            "/api/system/access",
            json={"lan_enabled": True},
        )
        self.assertEqual(access.status_code, 403)
        self.assertEqual(access.json()["error"]["code"], "READ_ONLY")
        rotated = client.post("/api/system/access/token")
        self.assertEqual(rotated.status_code, 403)
        self.assertEqual(rotated.json()["error"]["code"], "READ_ONLY")

    def test_non_loopback_without_token_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                create_app(
                    root / "tasks.db",
                    root / "out",
                    self.rules_dir,
                    serve_host="0.0.0.0",
                )

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
