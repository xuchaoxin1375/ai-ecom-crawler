from __future__ import annotations

import queue
import tempfile
import threading
import time
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml
from fastapi.testclient import TestClient

from ecom_crawler.builds import BuildManager
from ecom_crawler.harness.adapter import BuildSession
from ecom_crawler.harness.models import BuildTask, HarnessEvent, utc_now
from ecom_crawler.harness.workspace import BuildWorkspace
from ecom_crawler.runtime.models import Batch, BatchSite, BuildRecord
from ecom_crawler.runtime.store import TaskStore
from ecom_crawler.web.app import create_app

CLIENT_HEADERS = {
    "Host": "127.0.0.1:8765",
    "Origin": "http://127.0.0.1:8765",
    "X-Requested-With": "XMLHttpRequest",
}


def rule_payload(site_key: str = "example.fr") -> dict[str, Any]:
    return {
        "schema_version": "1.1",
        "rule_id": "example-fr-build",
        "rule_version": "2026.11.23-1",
        "kind": "declarative",
        "status": "candidate",
        "site": {
            "name": "Example",
            "entry_urls": [f"https://{site_key}/"],
            "allowed_origins": [f"https://{site_key}"],
            "allowed_path_prefixes": ["/"],
            "market": "FR",
            "locale": "fr-FR",
            "currency": "EUR",
        },
        "scope": {
            "include": [],
            "exclude": ["/cart"],
            "max_products": 2,
            "max_seconds": 30,
        },
        "capabilities": {"discovery": True, "product": True},
        "discovery": {
            "strategies": ["entry_links"],
            "entry_url": f"https://{site_key}/",
            "link_selector": "a.product",
            "product_url_patterns": ["/products/[^/]+$"],
            "url_identity": "canonical",
        },
        "fetch": {
            "default_engine": "static",
            "concurrency": 1,
            "delay_ms": 1000,
            "retry": {"max_attempts": 1, "backoff_ms": 1000},
            "timeout_ms": 45000,
            "browser": False,
        },
        "extract": {
            "fields": {
                "name": {
                    "required": True,
                    "fallbacks": [
                        {"type": "json_ld", "path": "name", "label": "json_ld"},
                        {"type": "css_text", "selector": "h1", "label": "h1"},
                    ],
                },
                "price.amount": {
                    "required": True,
                    "fallbacks": [
                        {
                            "type": "json_ld",
                            "path": "offers.price",
                            "label": "json_ld_price",
                            "take": "min_positive",
                        }
                    ],
                },
                "price.currency": {
                    "required": True,
                    "fallbacks": [
                        {
                            "type": "json_ld",
                            "path": "offers.priceCurrency",
                            "label": "json_ld_currency",
                        }
                    ],
                },
                "primary_image_url": {
                    "required": True,
                    "fallbacks": [
                        {"type": "json_ld", "path": "image", "label": "json_ld_image"}
                    ],
                },
                "source_url": {
                    "required": True,
                    "fallbacks": [{"type": "canonical", "label": "canonical"}],
                },
            }
        },
        "normalize": {
            "price": {
                "tax_basis": "exclusive_or_inclusive",
                "choose": "smaller_public_pair",
                "positive_only": True,
            },
            "description": {
                "mode": "clean_html",
                "statuses": ["complete", "partial", "not_provided", "failed"],
            },
            "options": {"exclude_quantity": True, "strip_price_delta": True},
        },
        "validate": {
            "required_fields": [
                "name",
                "price.amount",
                "price.currency",
                "primary_image_url",
                "source_url",
            ]
        },
        "output": {
            "url_list": {"enabled": True, "format": "csv"},
            "product_csv": {"enabled": True, "columns": 9, "format": "csv"},
            "task_result": True,
        },
    }


class FakeBuildAdapter:
    def __init__(
        self,
        root: Path,
        *,
        write_rule: bool = True,
        finish: bool = True,
    ) -> None:
        self.root = root
        self.write_rule = write_rule
        self.finish = finish
        self.queue: queue.Queue[HarnessEvent | None] = queue.Queue()
        self.sessions: dict[str, BuildSession] = {}
        self.prompts: list[tuple[str, str]] = []
        self.closed: list[str] = []
        self.canceled: list[str] = []

    def start_build(self, task: BuildTask) -> BuildSession:
        workspace = BuildWorkspace.create(
            self.root / "sessions", task, pause_gate=False, dependency_tool=False
        )
        session = BuildSession(
            build_id=task.build_id,
            state="CREATED",
            workspace=workspace,
            session_id=f"ses_{task.build_id}",
            harness={"name": "fake", "version": "1.0", "adapter_version": "fake/1"},
        )
        self.sessions[task.build_id] = session
        return session

    def send_prompt(self, build_id: str, text: str) -> dict[str, Any]:
        self.prompts.append((build_id, text))
        self.sessions[build_id].state = "RUNNING"

        def complete() -> None:
            time.sleep(0.05)
            session = self.sessions[build_id]
            if self.write_rule:
                plan = session.workspace.out_dir / "plan"
                plan.mkdir(parents=True, exist_ok=True)
                (plan / "rule.yaml").write_text(
                    yaml.safe_dump(rule_payload(), allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
            if self.finish:
                self.emit(
                    "finished",
                    "session.execution.succeeded",
                    outcome="succeeded",
                )

        threading.Thread(target=complete, daemon=True).start()
        return {"id": "msg_fake"}

    def stream_events(self, build_id: str) -> Iterator[HarnessEvent]:
        while True:
            event = self.queue.get()
            if event is None:
                return
            yield event

    def reply_permission(
        self,
        build_id: str,
        request_id: str,
        decision: str,
        *,
        message: str | None = None,
    ) -> None:
        return None

    def list_permissions(self, build_id: str) -> list[dict[str, Any]]:
        return []

    def request_dependency(
        self,
        build_id: str,
        request: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        return {"status": "available", "package": request.get("package")}

    def pause(self, build_id: str) -> BuildSession:
        self.sessions[build_id].state = "PAUSING"
        return self.sessions[build_id]

    def resume(self, build_id: str) -> BuildSession:
        self.sessions[build_id].state = "RUNNING"
        return self.sessions[build_id]

    def cancel(self, build_id: str) -> BuildSession:
        self.canceled.append(build_id)
        session = self.sessions[build_id]
        session.state = "CANCELLED"
        session.outcome = "cancelled"
        return session

    def collect_artifacts(self, build_id: str) -> dict[str, str]:
        return self.sessions[build_id].workspace.artifact_map()

    def close(self, build_id: str) -> BuildSession:
        self.closed.append(build_id)
        session = self.sessions[build_id]
        if session.state not in {"CANCELLED"}:
            session.state = "FINISHED"
            session.outcome = "closed"
        self.queue.put(None)
        return session

    def emit(self, event_type: str, source_type: str, **data: Any) -> None:
        self.queue.put(
            HarnessEvent(
                type=event_type,
                source_type=source_type,
                session_id=None,
                data=data,
                created_at=utc_now(),
            )
        )


class BuildWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temporary.name)
        self.store = TaskStore(self.root / "tasks.db")
        self.rules = self.root / "rules"
        self.rules.mkdir()
        self.batch = Batch(batch_id="b-1", name="France", market="FR", language="fr-FR")
        self.store.create_batch(self.batch)
        self.store.add_batch_sites(
            [
                BatchSite(
                    batch_id="b-1",
                    site_key="example.fr",
                    domain="example.fr",
                    input_value="https://example.fr/",
                    readiness="needs_onboarding",
                )
            ]
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _manager(
        self,
        adapter: FakeBuildAdapter,
        *,
        currencies: dict[str, int] | None = None,
    ) -> BuildManager:
        def validator(
            rule_path: Path,
            work_dir: Path,
            max_products: int,
            max_seconds: int,
            proxy: str | None = None,
        ) -> dict[str, Any]:
            return {
                "counts": {"valid_products": 2, "failed_products": 0},
                "outcome": "COMPLETED",
                "stop_reason": "NATURAL_END",
                "currencies": currencies or {"EUR": 2},
            }

        return BuildManager(
            self.store,
            self.root / "out",
            self.rules,
            adapter=adapter,
            validator=validator,
            max_seconds=10,
            validation_seconds=5,
            max_products=2,
        )

    def _client(self, manager: BuildManager) -> TestClient:
        app = create_app(
            self.root / "tasks.db",
            self.root / "out",
            self.rules,
            build_manager=manager,
            manage_worker=False,
        )
        return TestClient(app, headers=CLIENT_HEADERS)

    def _wait_ready(self, client: TestClient, build_id: str, timeout: float = 10) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            response = client.get(f"/api/builds/{build_id}")
            self.assertEqual(response.status_code, 200, response.text)
            last = response.json()["build"]
            if last["state"] in {"FINISHED", "CANCELLED"}:
                break
            time.sleep(0.05)
        return last

    def test_build_site_then_batch_start(self) -> None:
        adapter = FakeBuildAdapter(self.root)
        manager = self._manager(adapter)
        with self._client(manager) as client:
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={
                    "max_products": 2,
                    "max_seconds": 60,
                    "proxy": "http://127.0.0.1:17216",
                },
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 202, response.text)
            build_id = response.json()["build"]["build_id"]
            result = self._wait_ready(client, build_id)
            self.assertEqual(result["state"], "FINISHED")
            self.assertEqual(result["outcome"], "succeeded")
            self.assertEqual(result["rule"]["rule_id"], "example-fr-build")
            self.assertTrue(result["proxy_configured"])
            self.assertTrue(result["trace_available"])
            trace_md = client.get(f"/api/builds/{build_id}/trace?format=md")
            self.assertEqual(trace_md.status_code, 200, trace_md.text)
            self.assertIn("Build trace", trace_md.text)
            trace_json = client.get(f"/api/builds/{build_id}/trace?format=json")
            self.assertEqual(trace_json.status_code, 200, trace_json.text)
            self.assertFalse(trace_json.json()["reasoning_retained"])
            messages = client.get(f"/api/builds/{build_id}/messages")
            self.assertEqual(messages.status_code, 200, messages.text)
            self.assertFalse(messages.json()["live"])
            self.assertEqual(messages.json()["reasoning"], [])

            batch = client.get("/api/batches/b-1").json()
            site = batch["sites"][0]
            self.assertEqual(site["readiness"], "ready")
            self.assertEqual(site["rule"]["rule_id"], "example-fr-build")
            self.assertTrue((self.rules / site["rule"]["path"]).is_file())

            started = client.post("/api/batches/b-1/start", json={}, headers=CLIENT_HEADERS)
            self.assertEqual(started.status_code, 202, started.text)
            payload = started.json()
            self.assertEqual(len(payload["accepted"]), 1)
            task_id = payload["accepted"][0]["task_id"]
            self.assertTrue(task_id.startswith("web-"))
            self.assertEqual(payload["skipped"], [])
            task = self.store.get_task(task_id)
            assert task is not None
            self.assertEqual(task.input.get("proxy"), "http://127.0.0.1:17216")

    def test_missing_rule_fails_and_releases_site(self) -> None:
        adapter = FakeBuildAdapter(self.root, write_rule=False)
        manager = self._manager(adapter)
        with self._client(manager) as client:
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 202, response.text)
            build_id = response.json()["build"]["build_id"]
            result = self._wait_ready(client, build_id)
            self.assertEqual(result["state"], "FINISHED")
            self.assertEqual(result["outcome"], "failed")
            self.assertIn("rule.yaml", result["error"] or "")

            batch = client.get("/api/batches/b-1").json()
            site = batch["sites"][0]
            self.assertEqual(site["readiness"], "needs_onboarding")
            self.assertIn("构建失败", site["note"])

    def test_cancel_releases_site(self) -> None:
        adapter = FakeBuildAdapter(self.root, finish=False)
        manager = self._manager(adapter)
        with self._client(manager) as client:
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 202, response.text)
            build_id = response.json()["build"]["build_id"]
            canceled = client.post(
                f"/api/builds/{build_id}/cancel", headers=CLIENT_HEADERS
            )
            self.assertEqual(canceled.status_code, 202, canceled.text)
            self.assertEqual(canceled.json()["build"]["state"], "CANCELLED")
            batch = client.get("/api/batches/b-1").json()
            self.assertEqual(batch["sites"][0]["readiness"], "needs_onboarding")

    def test_currency_mismatch_fails_without_installing_rule(self) -> None:
        adapter = FakeBuildAdapter(self.root)
        manager = self._manager(adapter, currencies={"CNY": 2})
        with self._client(manager) as client:
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 202, response.text)
            build_id = response.json()["build"]["build_id"]
            result = self._wait_ready(client, build_id)
            self.assertEqual(result["outcome"], "failed")
            self.assertIn("currency mismatch", result["error"] or "")
            batch = client.get("/api/batches/b-1").json()
            self.assertEqual(batch["sites"][0]["readiness"], "needs_onboarding")
            self.assertEqual(list(self.rules.glob("*.yaml")), [])

    def test_reconcile_interrupts_stale_build(self) -> None:
        self.store.create_build(
            BuildRecord(
                build_id="build-stale",
                batch_id="b-1",
                site_key="example.fr",
                state="RUNNING",
            )
        )
        self.store.update_batch_site(
            "b-1",
            "example.fr",
            readiness="building",
            build_id="build-stale",
            note="构建中",
        )
        adapter = FakeBuildAdapter(self.root)
        manager = self._manager(adapter)
        interrupted = manager.reconcile()
        self.assertEqual(interrupted, ["build-stale"])
        record = self.store.get_build("build-stale")
        assert record is not None
        self.assertEqual(record.state, "FINISHED")
        self.assertEqual(record.outcome, "failed")
        site = self.store.get_batch_site("b-1", "example.fr")
        assert site is not None
        self.assertEqual(site.readiness, "needs_onboarding")


if __name__ == "__main__":
    unittest.main()
