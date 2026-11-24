from __future__ import annotations

import json
import os
import queue
import tempfile
import threading
import time
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import yaml
from fastapi.testclient import TestClient

from ecom_crawler.builds import (
    BuildManager,
    _live_timeline,
    _merge_reasoning_timeline,
    _probe_robots,
    _trace_timeline,
    default_permissions,
)
from ecom_crawler.harness.adapter import BuildSession
from ecom_crawler.harness.models import BuildTask, HarnessEvent, utc_now
from ecom_crawler.harness.workspace import BuildWorkspace
from ecom_crawler.runtime.models import (
    Batch,
    BatchSite,
    BuildRecord,
    RuleVersion,
    Task,
)
from ecom_crawler.runtime.store import TaskStore
from ecom_crawler.web.app import create_app

CLIENT_HEADERS = {
    "Host": "127.0.0.1:8765",
    "Origin": "http://127.0.0.1:8765",
    "X-Requested-With": "XMLHttpRequest",
}


def rule_payload(
    site_key: str = "example.fr", version: str = "2026.11.23-1"
) -> dict[str, Any]:
    return {
        "schema_version": "1.1",
        "rule_id": "example-fr-build",
        "rule_version": version,
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


def invalid_selector_payload(site_key: str = "example.fr") -> dict[str, Any]:
    payload = rule_payload(site_key)
    payload["discovery"]["link_selector"] = "a.product:not(:first-of-type)"
    return payload


def listing_rule_payload(site_key: str = "example.fr") -> dict[str, Any]:
    payload = rule_payload(site_key)
    payload["discovery"] = {
        "sources": [
            {
                "type": "listing",
                "url": f"https://{site_key}/products",
                "product_link_selector": "a.product",
                "advance": {"type": "page_param", "param": "p", "max_pages": 2},
            }
        ],
        "product_url_patterns": ["/products/[^/]+$"],
        "url_identity": "canonical",
    }
    return payload


class FakeBuildAdapter:
    def __init__(
        self,
        root: Path,
        *,
        write_rule: bool = True,
        finish: bool = True,
        rule_payloads: list[dict[str, Any]] | None = None,
    ) -> None:
        self.root = root
        self.write_rule = write_rule
        self.finish = finish
        self.rule_payloads = rule_payloads or []
        self.queue: queue.Queue[HarnessEvent | None] = queue.Queue()
        self.queues: dict[str, queue.Queue[HarnessEvent | None]] = {}
        self.current_build: str | None = None
        self.sessions: dict[str, BuildSession] = {}
        self.prompts: list[tuple[str, str]] = []
        self.continued: list[tuple[str, str]] = []
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
        self.current_build = task.build_id
        self.queues[task.build_id] = queue.Queue()
        return session

    def send_prompt(self, build_id: str, text: str) -> dict[str, Any]:
        index = len(self.prompts)
        self.prompts.append((build_id, text))
        self._complete_async(build_id, index)
        return {"id": "msg_fake"}

    def continue_prompt(self, build_id: str, text: str) -> dict[str, Any]:
        index = len(self.prompts)
        self.continued.append((build_id, text))
        self.prompts.append((build_id, text))
        self.sessions[build_id].state = "RUNNING"
        self._complete_async(build_id, index)
        return {"id": f"msg_fake_repair_{len(self.continued)}"}

    def _complete_async(self, build_id: str, index: int) -> None:
        self.sessions[build_id].state = "RUNNING"

        def complete() -> None:
            time.sleep(0.05)
            session = self.sessions[build_id]
            if self.write_rule:
                plan = session.workspace.out_dir / "plan"
                plan.mkdir(parents=True, exist_ok=True)
                payload = (
                    self.rule_payloads[min(index, len(self.rule_payloads) - 1)]
                    if self.rule_payloads
                    else rule_payload()
                )
                (plan / "rule.yaml").write_text(
                    yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
            if self.finish:
                self.emit(
                    "finished",
                    "session.execution.succeeded",
                    outcome="succeeded",
                )

        threading.Thread(target=complete, daemon=True).start()

    def stream_events(self, build_id: str) -> Iterator[HarnessEvent]:
        events = self.queues[build_id]
        while True:
            event = events.get()
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
        self.queues[build_id].put(None)
        return session

    def emit(self, event_type: str, source_type: str, **data: Any) -> None:
        if self.current_build is None:
            self.queue.put(
                HarnessEvent(
                    type=event_type,
                    source_type=source_type,
                    session_id=None,
                    data=data,
                    created_at=utc_now(),
                )
            )
            return
        self.queues[self.current_build].put(
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
        validator: Any | None = None,
        max_repair_rounds: int = 0,
        robots_probe: Any | None = None,
        skills_dir: Path | None = None,
        activation_mode: str = "legacy",
    ) -> BuildManager:
        if validator is None:

            def validator(
                rule_path: Path,
                work_dir: Path,
                max_products: int,
                max_seconds: int,
                proxy: str | None = None,
                **_: Any,
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
            max_repair_rounds=max_repair_rounds,
            repair_seconds=5,
            activation_mode=activation_mode,
            archive_mode="off",
            robots_probe=robots_probe
            or (lambda entry_url, proxy: ("robots.txt not found", [])),
            skills_dir=skills_dir
            if skills_dir is not None
            else self.root / "skills",
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

    def test_build_permissions_share_skills_and_keep_workspace_boundaries(self) -> None:
        workspace = self.root / "out" / "build-permissions"
        skill_root = self.root / "host-skills"
        rules = default_permissions(workspace, skill_roots=[str(skill_root)])
        entries = {
            (str(rule["action"]), str(rule["resource"]), str(rule["effect"]))
            for rule in rules
        }
        self.assertIn(("skill", "*", "allow"), entries)
        self.assertIn(("browse_*", "*", "allow"), entries)
        self.assertIn(("htmlmini_*", "*", "allow"), entries)
        self.assertIn(("websearch", "*", "allow"), entries)
        self.assertIn(("webfetch", "*", "allow"), entries)
        self.assertIn(("question", "*", "deny"), entries)
        self.assertIn(("*_*", "*", "deny"), entries)
        self.assertIn(("external_directory", "*", "deny"), entries)
        root = workspace.resolve().as_posix().rstrip("/")
        self.assertIn(("external_directory", f"{root}/input/*", "allow"), entries)
        self.assertIn(("external_directory", f"{root}/out/*", "allow"), entries)
        self.assertIn(("edit", f"{root}/input/*", "deny"), entries)
        self.assertIn(("read", f"{root}/control/*", "deny"), entries)
        self.assertIn(("read", f"{root}/logs/*", "deny"), entries)
        shared = skill_root.resolve().as_posix().rstrip("/")
        self.assertIn(("external_directory", shared, "allow"), entries)
        self.assertIn(("external_directory", f"{shared}/*", "allow"), entries)
        self.assertIn(("edit", f"{shared}/*", "deny"), entries)

    def test_build_records_shared_skills(self) -> None:
        skills = self.root / "skills"
        workflow = skills / "product-crawl-workflow"
        (workflow / "references").mkdir(parents=True)
        (workflow / "SKILL.md").write_text(
            "---\nname: Product crawl workflow\n---\n\nUse the workflow.\n",
            encoding="utf-8",
        )
        (workflow / "references" / "stage-strategy.md").write_text(
            "stages\n", encoding="utf-8"
        )
        browser = skills / "browser-automation"
        browser.mkdir(parents=True)
        (browser / "SKILL.md").write_text(
            "---\nname: Browser automation\n---\n\nUse the browser.\n",
            encoding="utf-8",
        )

        adapter = FakeBuildAdapter(self.root)
        manager = self._manager(adapter, skills_dir=skills)
        with self._client(manager) as client:
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 202, response.text)
            build_id = response.json()["build"]["build_id"]
            result = self._wait_ready(client, build_id)
            self.assertEqual(result["outcome"], "succeeded")
            workspace = Path(result["workspace"])
            self.assertFalse((workspace / "work" / ".opencode" / "skills").exists())
            task_payload = json.loads(
                (workspace / "input" / "build-task.json").read_text(encoding="utf-8")
            )
            manifest = task_payload["skills"]
            self.assertIn(
                skills.resolve().as_posix(),
                [Path(root).as_posix() for root in manifest["roots"]],
            )
            items = {item["id"]: item for item in manifest["items"]}
            self.assertIn("product-crawl-workflow", items)
            self.assertIn("browser-automation", items)
            self.assertEqual(len(items["product-crawl-workflow"]["sha256"]), 64)
            permissions = task_payload["permissions"]
            self.assertIn(
                {"action": "skill", "resource": "*", "effect": "allow"},
                permissions,
            )
            shared = skills.resolve().as_posix().rstrip("/")
            self.assertIn(
                {
                    "action": "external_directory",
                    "resource": shared,
                    "effect": "allow",
                },
                permissions,
            )
            self.assertIn(
                {
                    "action": "edit",
                    "resource": f"{shared}/*",
                    "effect": "deny",
                },
                permissions,
            )

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
            workspace = Path(result["workspace"])
            task_payload = json.loads(
                (workspace / "input" / "build-task.json").read_text(encoding="utf-8")
            )
            permissions = task_payload["permissions"]
            self.assertIn(
                {"action": "skill", "resource": "*", "effect": "allow"},
                permissions,
            )
            root = Path(task_payload["workspace"]).resolve().as_posix().rstrip("/")
            self.assertIn(
                {
                    "action": "external_directory",
                    "resource": f"{root}/input/*",
                    "effect": "allow",
                },
                permissions,
            )
            self.assertIn(
                {
                    "action": "edit",
                    "resource": f"{root}/input/*",
                    "effect": "deny",
                },
                permissions,
            )
            agents = (workspace / "work" / "AGENTS.md").read_text(encoding="utf-8")
            brief = (workspace / "input" / "build-brief.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Host skills are available read-only", agents)
            self.assertIn("browse` and `htmlmini` MCP tools are available", agents)
            self.assertIn("Read local files from", agents)
            self.assertIn("Read local files from", brief)
            self.assertIn(
                "robots.txt",
                (workspace / "input" / "build-brief.md").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertIn(
                "robots.txt",
                (workspace / "work" / "AGENTS.md").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertTrue((self.rules / site["rule"]["path"]).is_file())

            started = client.post(
                "/api/batches/b-1/start",
                json={
                    "limits": {
                        "max_urls": 200,
                        "max_products": 100,
                        "max_seconds": 600,
                    },
                    "archive_mode": "sample",
                    "archive_sample_limit": 5,
                },
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(started.status_code, 202, started.text)
            payload = started.json()
            self.assertEqual(len(payload["accepted"]), 1)
            task_id = payload["accepted"][0]["task_id"]
            self.assertTrue(task_id.startswith("web-"))
            self.assertEqual(payload["skipped"], [])
            task = self.store.get_task(task_id)
            assert task is not None
            self.assertEqual(task.input.get("proxy"), "http://127.0.0.1:17216")
            self.assertEqual(task.input["archive"]["mode"], "sample")
            self.assertEqual(task.input["archive"]["sample_limit"], 5)
            self.assertEqual(task.limits["max_products"], 100)

    def test_repair_ready_site_uses_existing_rule(self) -> None:
        adapter = FakeBuildAdapter(
            self.root,
            rule_payloads=[
                rule_payload(version="2026.11.23-1"),
                rule_payload(version="2026.11.23-2"),
            ],
        )
        manager = self._manager(adapter)
        with self._client(manager) as client:
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 202, response.text)
            first_id = response.json()["build"]["build_id"]
            first = self._wait_ready(client, first_id)
            self.assertEqual(first["outcome"], "succeeded")

            self.store.update_batch_site(
                "b-1", "example.fr", task_id="task-existing"
            )
            self.store.create_task(
                Task(
                    task_id="task-existing",
                    plan_id="example-fr-build",
                    plan_version="2026.11.23-1",
                    task_type="product",
                    state="FINISHED",
                    outcome="PARTIAL",
                    stop_reason="QUALITY_BLOCKED",
                    batch_id="b-1",
                    site_key="example.fr",
                )
            )
            task_dir = self.root / "out" / "task-existing"
            task_dir.mkdir(parents=True)
            (task_dir / "task-result.json").write_text(
                json.dumps(
                    {
                        "counts": {
                            "discovered_urls": 12,
                            "valid_products": 9,
                            "excluded_products": 1,
                            "failed_products": 2,
                        },
                        "coverage": {
                            "status": "PARTIAL",
                            "covered": 9,
                            "denominator": 12,
                        },
                        "content_audit": {
                            "products_checked": 9,
                            "description_gaps": 2,
                        },
                        "quality_exceptions": [
                            {
                                "source_url": "https://example.fr/p/1",
                                "description_status": "partial",
                                "partial_reason": "specification block missing",
                            },
                            {
                                "source_url": "https://example.fr/p/2",
                                "description_status": "partial",
                                "partial_reason": "promo badge mixed in",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={
                    "mode": "repair",
                    "reason": "description only contains composition",
                },
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 202, response.text)
            repair = response.json()["build"]
            self.assertEqual(repair["mode"], "repair")
            result = self._wait_ready(client, repair["build_id"])
            self.assertEqual(result["state"], "FINISHED")
            self.assertEqual(result["outcome"], "succeeded")

            batch = client.get("/api/batches/b-1").json()
            site = batch["sites"][0]
            self.assertEqual(site["readiness"], "ready")
            self.assertEqual(site["task_id"], "task-existing")
            self.assertEqual(site["rule"]["rule_version"], "2026.11.23-2")

            prompt = adapter.prompts[-1][1]
            self.assertIn("repair-brief.md", prompt)
            self.assertIn("existing-rule.yaml", prompt)
            workspace = Path(adapter.sessions[repair["build_id"]].workspace.root)
            self.assertTrue((workspace / "input" / "existing-rule.yaml").is_file())
            context = yaml.safe_load(
                (workspace / "input" / "repair-context.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(context["previous_rule_version"], "2026.11.23-1")
            self.assertIn("2026.11.23-1", context["existing_rule_versions"])
            runtime = context["runtime_task"]
            self.assertEqual(runtime["task_id"], "task-existing")
            self.assertEqual(runtime["state"], "FINISHED")
            self.assertEqual(runtime["outcome"], "PARTIAL")
            self.assertEqual(runtime["counts"]["valid_products"], 9)
            self.assertEqual(runtime["counts"]["failed_products"], 2)
            self.assertEqual(runtime["quality_exception_count"], 2)
            self.assertEqual(
                runtime["sample_urls"],
                ["https://example.fr/p/1", "https://example.fr/p/2"],
            )
            brief = (workspace / "input" / "repair-brief.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("## Current task evidence", brief)
            self.assertIn("Existing managed versions", brief)
            self.assertIn("2026.11.23-1", brief)
            self.assertIn("task-existing", brief)
            self.assertIn("valid_products 9", brief)
            self.assertIn("2 description gaps", brief)
            self.assertIn("https://example.fr/p/1", brief)
            self.assertTrue((workspace / "out" / "plan" / "rule.yaml").is_file())

    def test_repair_rejects_active_task(self) -> None:
        adapter = FakeBuildAdapter(
            self.root,
            rule_payloads=[
                rule_payload(version="2026.11.23-1"),
                rule_payload(version="2026.11.23-2"),
            ],
        )
        manager = self._manager(adapter)
        with self._client(manager) as client:
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 202, response.text)
            self._wait_ready(client, response.json()["build"]["build_id"])

            self.store.update_batch_site(
                "b-1", "example.fr", task_id="task-running"
            )
            self.store.create_task(
                Task(
                    task_id="task-running",
                    plan_id="example-fr-build",
                    plan_version="2026.11.23-1",
                    task_type="product",
                    state="RUNNING",
                    batch_id="b-1",
                    site_key="example.fr",
                )
            )
            repair = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={"mode": "repair", "reason": "description gap"},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(repair.status_code, 409, repair.text)
            self.assertEqual(repair.json()["error"]["code"], "BUILD_CONFLICT")
            self.assertIn("active task", repair.json()["error"]["message"])

    def test_repair_rejects_same_rule_version(self) -> None:
        adapter = FakeBuildAdapter(
            self.root,
            rule_payloads=[rule_payload(version="2026.11.23-1")],
        )
        manager = self._manager(adapter)
        with self._client(manager) as client:
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 202, response.text)
            self._wait_ready(client, response.json()["build"]["build_id"])

            repair = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={"mode": "repair", "reason": "description gap"},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(repair.status_code, 202, repair.text)
            result = self._wait_ready(client, repair.json()["build"]["build_id"])
            self.assertEqual(result["state"], "FINISHED")
            self.assertEqual(result["outcome"], "failed")
            self.assertIn("bump rule_version", result["error"])

    def test_read_only_build_preview_keeps_build_history(self) -> None:
        self.store.create_build(
            BuildRecord(
                build_id="build-readonly",
                batch_id="b-1",
                site_key="example.fr",
                state="FINISHED",
                outcome="failed",
                error="previous failure",
            )
        )
        with mock.patch.dict(os.environ, {"ECOM_BUILD_DISABLED": "1"}):
            app = create_app(
                self.root / "tasks.db",
                self.root / "out",
                self.rules,
                manage_worker=False,
            )
            with TestClient(app, headers=CLIENT_HEADERS) as client:
                listing = client.get("/api/builds")
                self.assertEqual(listing.status_code, 200, listing.text)
                self.assertEqual(
                    [item["build_id"] for item in listing.json()["builds"]],
                    ["build-readonly"],
                )
                config = client.get("/api/builds/config").json()
                self.assertFalse(config["available"])
                response = client.post(
                    "/api/batches/b-1/sites/example.fr/build",
                    json={},
                    headers=CLIENT_HEADERS,
                )
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(
                    response.json()["error"]["code"], "BUILD_UNAVAILABLE"
                )
                self.assertIn("disabled", response.json()["error"]["message"])
                continued = client.post(
                    "/api/builds/build-readonly/continue",
                    json={
                        "request_id": "readonly-continue",
                        "message": "try again",
                    },
                    headers=CLIENT_HEADERS,
                )
                self.assertEqual(continued.status_code, 409, continued.text)
                self.assertEqual(
                    continued.json()["error"]["code"], "BUILD_UNAVAILABLE"
                )

    def test_failed_build_can_continue_once(self) -> None:
        adapter = FakeBuildAdapter(self.root, write_rule=False, finish=True)
        manager = self._manager(adapter, max_repair_rounds=0)
        with self._client(manager) as client:
            started = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(started.status_code, 202, started.text)
            build_id = started.json()["build"]["build_id"]
            failed = self._wait_ready(client, build_id)
            self.assertEqual(failed["outcome"], "failed", failed)
            deadline = time.monotonic() + 5
            while build_id in manager._watchers and time.monotonic() < deadline:
                time.sleep(0.05)

            adapter.write_rule = True
            body = {
                "request_id": "continue-1",
                "message": "retry with a valid rule",
            }
            response = client.post(
                f"/api/builds/{build_id}/continue",
                json=body,
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 202, response.text)
            self.assertTrue(response.json()["accepted"])
            result = self._wait_ready(client, build_id)
            self.assertEqual(result["outcome"], "succeeded", result)
            self.assertEqual(len(adapter.continued), 1)
            self.assertEqual(
                [item["state"] for item in result["continuations"]],
                ["ACCEPTED"],
            )

            replay = client.post(
                f"/api/builds/{build_id}/continue",
                json=body,
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(replay.status_code, 202, replay.text)
            self.assertEqual(len(adapter.continued), 1)

            conflict = client.post(
                f"/api/builds/{build_id}/continue",
                json={
                    "request_id": "continue-1",
                    "message": "different instruction",
                },
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(conflict.status_code, 409, conflict.text)
            self.assertEqual(conflict.json()["error"]["code"], "CONFLICT")

            not_failed = client.post(
                f"/api/builds/{build_id}/continue",
                json={
                    "request_id": "continue-2",
                    "message": "another round",
                },
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(not_failed.status_code, 409, not_failed.text)
            self.assertEqual(
                not_failed.json()["error"]["code"], "BUILD_NOT_CONTINUABLE"
            )

    def test_manual_continue_keeps_failed_auto_repair_unresolved(self) -> None:
        adapter = FakeBuildAdapter(
            self.root,
            rule_payloads=[
                invalid_selector_payload(),
                invalid_selector_payload(),
                rule_payload(),
            ],
        )
        manager = self._manager(adapter, max_repair_rounds=1)
        with self._client(manager) as client:
            started = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={"repair_rounds": 1},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(started.status_code, 202, started.text)
            build_id = started.json()["build"]["build_id"]
            failed = self._wait_ready(client, build_id)
            self.assertEqual(failed["outcome"], "failed", failed)
            self.assertEqual(failed["repair_round"], 1)
            self.assertFalse(failed["repairs"][0]["resolved"])
            deadline = time.monotonic() + 5
            while build_id in manager._watchers and time.monotonic() < deadline:
                time.sleep(0.05)

            response = client.post(
                f"/api/builds/{build_id}/continue",
                json={
                    "request_id": "continue-after-auto-repair",
                    "message": "use a valid selector",
                },
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 202, response.text)
            result = self._wait_ready(client, build_id)
            self.assertEqual(result["outcome"], "succeeded", result["error"])
            self.assertEqual(result["repair_round"], 1)
            self.assertFalse(result["repairs"][0]["resolved"])
            self.assertEqual(len(adapter.continued), 2)
            self.assertIn("automatic repair round 1", adapter.continued[0][1])
            self.assertEqual(adapter.continued[1][1], "use a valid selector")
            trace = client.get(f"/api/builds/{build_id}/trace?format=json").json()
            self.assertFalse(trace["repairs"][0]["resolved"])

    def test_continue_requires_live_session(self) -> None:
        self.store.create_build(
            BuildRecord(
                build_id="build-old",
                batch_id="b-1",
                site_key="example.fr",
                state="FINISHED",
                outcome="failed",
                error="old failure",
            )
        )
        manager = self._manager(FakeBuildAdapter(self.root))
        with self._client(manager) as client:
            response = client.post(
                "/api/builds/build-old/continue",
                json={
                    "request_id": "continue-old",
                    "message": "try again",
                },
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(
                response.json()["error"]["code"], "BUILD_SESSION_UNAVAILABLE"
            )
            continuation = self.store.get_build_continuation("continue-old")
            assert continuation is not None
            self.assertEqual(continuation.state, "FAILED")

    def test_candidate_activation_rerun_and_rollback(self) -> None:
        initial_rule = rule_payload(version="2026.11.23-1")
        repaired_rule = rule_payload(version="2026.11.23-2")
        repaired_rule["extract"]["fields"]["description_html"] = {
            "required": False,
            "fallbacks": [
                {
                    "type": "css_text",
                    "selector": "div.description",
                    "label": "description",
                }
            ],
        }
        adapter = FakeBuildAdapter(
            self.root,
            rule_payloads=[initial_rule, repaired_rule],
        )
        manager = self._manager(
            adapter,
            activation_mode="manual",
            max_repair_rounds=0,
        )
        with self._client(manager) as client:
            first = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(first.status_code, 202, first.text)
            self._wait_ready(client, first.json()["build"]["build_id"])

            self.store.create_task(
                Task(
                    task_id="task-existing",
                    plan_id="example-fr-build",
                    plan_version="2026.11.23-1",
                    task_type="product",
                    state="FINISHED",
                    outcome="COMPLETED",
                    stop_reason="NATURAL_END",
                    batch_id="b-1",
                    site_key="example.fr",
                )
            )
            self.store.update_batch_site(
                "b-1", "example.fr", task_id="task-existing"
            )
            feedback = client.post(
                "/api/tasks/task-existing/feedback",
                json={
                    "request_id": "fb-1",
                    "category": "DESCRIPTION",
                    "samples": ["https://example.fr/p/1"],
                    "expectation": "description should contain specs",
                },
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(feedback.status_code, 201, feedback.text)
            feedback_id = feedback.json()["feedback"]["feedback_id"]

            repair = client.post(
                f"/api/feedback/{feedback_id}/repair",
                json={
                    "request_id": "fb-repair-1",
                    "reason": "merge description blocks",
                },
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(repair.status_code, 202, repair.text)
            build_id = repair.json()["build"]["build_id"]
            result = self._wait_ready(client, build_id)
            self.assertEqual(result["outcome"], "succeeded", result)
            listing = client.get(
                "/api/builds?site_key=example.fr&limit=10"
            ).json()["builds"]
            self.assertTrue(
                any(
                    item["build_id"] == build_id and item["mode"] == "repair"
                    for item in listing
                )
            )

            pending = client.get(f"/api/feedback/{feedback_id}").json()
            self.assertEqual(pending["status"], "AWAITING_ACTIVATION")
            site_rule = client.get("/api/sites/example.fr/rule").json()
            self.assertEqual(site_rule["active"]["rule_version"], "2026.11.23-1")
            self.assertEqual(
                [item["rule_version"] for item in site_rule["candidates"]],
                ["2026.11.23-2"],
            )
            candidate = site_rule["candidates"][0]
            self.assertEqual(candidate["validation_status"], "PASSED")
            self.assertEqual(candidate["change_summary"]["parent_version"], "2026.11.23-1")
            self.assertIn(
                "extract.fields.description_html",
                candidate["change_summary"]["changed_fields"],
            )
            self.assertIn(
                "extract.fields.description_html",
                candidate["change_summary"]["changed_selectors"],
            )
            self.assertEqual(candidate["validation"]["status"], "PASSED")
            self.assertEqual(
                len(candidate["validation"]["evidence_sha256"]), 64
            )
            self.assertEqual(
                candidate["validation"]["content_audit"]["products_checked"], 0
            )
            self.assertEqual(site_rule["stale_tasks"], 0)

            version_detail = client.get(
                "/api/rules/example-fr-build/versions/2026.11.23-2"
            ).json()
            self.assertEqual(
                version_detail["change_summary"], candidate["change_summary"]
            )
            self.assertEqual(
                version_detail["validation"], candidate["validation"]
            )
            self.assertTrue(version_detail["source_feedback_id"])

            activated = client.post(
                "/api/sites/example.fr/rule/activate",
                json={
                    "request_id": "activate-1",
                    "rule_version": "2026.11.23-2",
                    "expected_active_version": "2026.11.23-1",
                },
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(activated.status_code, 200, activated.text)
            self.assertTrue(activated.json()["activated"])
            self.assertEqual(
                client.get(f"/api/feedback/{feedback_id}").json()["status"],
                "AWAITING_RERUN",
            )
            active_after = client.get("/api/sites/example.fr/rule").json()
            self.assertEqual(
                active_after["active"]["rule_version"], "2026.11.23-2"
            )
            self.assertEqual(active_after["stale_tasks"], 1)

            rerun = client.post(
                f"/api/feedback/{feedback_id}/rerun",
                json={
                    "request_id": "rerun-1",
                    "limits": {"max_products": 3, "max_urls": 5, "max_seconds": 60},
                },
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(rerun.status_code, 202, rerun.text)
            rerun_task_id = rerun.json()["task"]["task_id"]
            self.assertEqual(
                rerun.json()["feedback"]["status"], "RERUN_PENDING"
            )
            self.assertEqual(
                self.store.get_task(rerun_task_id).plan_version, "2026.11.23-2"
            )

            self.store.update_task(
                rerun_task_id,
                state="FINISHED",
                outcome="COMPLETED",
                stop_reason="NATURAL_END",
            )
            resolved = client.post(
                f"/api/feedback/{feedback_id}/resolve",
                json={
                    "request_id": "resolve-1",
                    "resolution": "RESOLVED",
                    "note": "rerun looks good",
                },
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(resolved.status_code, 200, resolved.text)
            self.assertEqual(resolved.json()["feedback"]["status"], "RESOLVED")
            self.assertEqual(self.store.get_task("task-existing").state, "FINISHED")

            rolled_back = client.post(
                "/api/sites/example.fr/rule/rollback",
                json={
                    "request_id": "rollback-1",
                    "expected_active_version": "2026.11.23-2",
                },
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(rolled_back.status_code, 200, rolled_back.text)
            self.assertTrue(rolled_back.json()["rolled_back"])
            self.assertEqual(
                client.get("/api/sites/example.fr/rule").json()["active"][
                    "rule_version"
                ],
                "2026.11.23-1",
            )

            candidate = self.store.create_rule_version(
                RuleVersion(
                    rule_id="example-fr-build",
                    rule_version="2026.11.24-3",
                    sha256="a" * 64,
                    path="example-fr-build-2026.11.23-2.yaml",
                    status="candidate",
                )
            )
            rejected = client.post(
                f"/api/rules/{candidate.rule_id}/versions/"
                f"{candidate.rule_version}/reject",
                json={"reason": "regression", "retry": False},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(rejected.status_code, 200, rejected.text)
            self.assertEqual(rejected.json()["status"], "rejected")

    def test_content_audit_gap_fails_validation(self) -> None:
        def validator(*_: Any, **__: Any) -> dict[str, Any]:
            return {
                "counts": {"valid_products": 2, "failed_products": 0},
                "outcome": "COMPLETED",
                "stop_reason": "NATURAL_END",
                "currencies": {"EUR": 2},
                "content_audit": {
                    "products_checked": 2,
                    "description_gaps": 1,
                    "samples": [
                        {
                            "source_url": "https://example.fr/products/1",
                            "missing_blocks": ["feature_specs"],
                        }
                    ],
                },
            }

        adapter = FakeBuildAdapter(self.root)
        manager = self._manager(adapter, validator=validator)
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
            self.assertIn("content audit", result["error"] or "")
            batch = client.get("/api/batches/b-1").json()
            self.assertEqual(batch["sites"][0]["readiness"], "needs_onboarding")

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

    def test_build_continues_when_robots_disallows(self) -> None:
        adapter = FakeBuildAdapter(self.root)
        manager = self._manager(
            adapter,
            robots_probe=lambda entry_url, proxy: (
                "robots.txt disallows the entry URL",
                ["https://example.fr/sitemap.xml"],
            ),
        )
        site = self.store.get_batch_site("b-1", "example.fr")
        record = manager.start(self.batch, site)
        self.assertIn(record.build_id, adapter.sessions)
        self.assertEqual(len(adapter.prompts), 1)
        workspace = Path(adapter.sessions[record.build_id].workspace.root)
        brief = (workspace / "input" / "build-brief.md").read_text(encoding="utf-8")
        agents = (workspace / "work" / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("https://example.fr/sitemap.xml", brief)
        self.assertIn("Do not fetch or read robots.txt", brief)
        self.assertIn("Do not analyze", agents)
        self.assertNotIn("If it disallows", brief)
        manager.shutdown()

    def test_robots_probe_extracts_sitemap_lines(self) -> None:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/robots.txt":
                    body = (
                        b"User-agent: *\n"
                        b"Disallow: /\n"
                        b"Crawl-delay: 10\n"
                        b"Sitemap: https://example.test/sitemap.xml\n"
                        b"Sitemap: /sitemap-products.xml\n"
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_error(404)

            def log_message(self, format: str, *args: Any) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            note, sitemaps = _probe_robots(
                f"http://127.0.0.1:{server.server_port}/"
            )
        finally:
            server.shutdown()
            server.server_close()
        self.assertIn("2", note)
        self.assertEqual(
            sitemaps,
            [
                "https://example.test/sitemap.xml",
                f"http://127.0.0.1:{server.server_port}/sitemap-products.xml",
            ],
        )
        self.assertNotIn("Disallow", note)
        self.assertNotIn("Crawl-delay", note)

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

    def test_preflight_failure_repairs_in_same_session(self) -> None:
        validator_calls = {"count": 0}

        def validator(
            rule_path: Path,
            work_dir: Path,
            max_products: int,
            max_seconds: int,
            proxy: str | None = None,
            **_: Any,
        ) -> dict[str, Any]:
            validator_calls["count"] += 1
            return {
                "counts": {"valid_products": 2, "failed_products": 0},
                "outcome": "COMPLETED",
                "stop_reason": "NATURAL_END",
                "currencies": {"EUR": 2},
            }

        adapter = FakeBuildAdapter(
            self.root,
            rule_payloads=[invalid_selector_payload(), rule_payload()],
        )
        manager = self._manager(
            adapter, validator=validator, max_repair_rounds=1
        )
        with self._client(manager) as client:
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={"repair_rounds": 1},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 202, response.text)
            build_id = response.json()["build"]["build_id"]
            result = self._wait_ready(client, build_id)
            self.assertEqual(result["outcome"], "succeeded", result["error"])
            self.assertEqual(result["repair_limit"], 1)
            self.assertEqual(result["repair_round"], 1)
            self.assertTrue(result["repairs"][0]["resolved"])
            self.assertEqual(validator_calls["count"], 1)
            self.assertEqual(len(adapter.continued), 1)
            prompt = adapter.continued[0][1]
            self.assertIn("automatic repair round 1", prompt)
            self.assertIn(":not(:first-of-type)", prompt)
            self.assertIn("invalid CSS selector", prompt)

            trace = client.get(f"/api/builds/{build_id}/trace?format=json").json()
            self.assertEqual(len(trace["repairs"]), 1)
            self.assertTrue(trace["repairs"][0]["resolved"])
            self.assertEqual(trace["repair_limit"], 1)

    def test_repair_metadata_survives_manager_restart(self) -> None:
        def validator(
            rule_path: Path,
            work_dir: Path,
            max_products: int,
            max_seconds: int,
            proxy: str | None = None,
            **_: Any,
        ) -> dict[str, Any]:
            return {
                "counts": {"valid_products": 2, "failed_products": 0},
                "outcome": "COMPLETED",
                "stop_reason": "NATURAL_END",
                "currencies": {"EUR": 2},
            }

        adapter = FakeBuildAdapter(
            self.root,
            rule_payloads=[invalid_selector_payload(), rule_payload()],
        )
        manager = self._manager(adapter, validator=validator, max_repair_rounds=1)
        with self._client(manager) as client:
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={"repair_rounds": 1},
                headers=CLIENT_HEADERS,
            )
            build_id = response.json()["build"]["build_id"]
            self.assertEqual(self._wait_ready(client, build_id)["outcome"], "succeeded")
            manager._repair_limits.clear()
            manager._repairs.clear()
            manager._trace_meta_cache.clear()
            restored = manager.describe(build_id)
            self.assertEqual(restored["repair_limit"], 1)
            self.assertEqual(restored["repair_round"], 1)
            self.assertTrue(restored["repairs"][0]["resolved"])

    def test_preflight_failure_without_repair_fails_fast(self) -> None:
        adapter = FakeBuildAdapter(
            self.root, rule_payloads=[invalid_selector_payload()]
        )
        manager = self._manager(adapter, max_repair_rounds=1)
        with self._client(manager) as client:
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={"repair_rounds": 0},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 202, response.text)
            build_id = response.json()["build"]["build_id"]
            result = self._wait_ready(client, build_id)
            self.assertEqual(result["outcome"], "failed")
            self.assertIn("invalid CSS selector", result["error"] or "")
            self.assertEqual(result["repair_round"], 0)
            self.assertEqual(adapter.continued, [])
            self.assertEqual(list(self.rules.glob("*.yaml")), [])

    def test_host_validation_error_includes_stop_detail_and_samples(self) -> None:
        def validator(
            rule_path: Path,
            work_dir: Path,
            max_products: int,
            max_seconds: int,
            proxy: str | None = None,
            **_: Any,
        ) -> dict[str, Any]:
            return {
                "counts": {"valid_products": 0, "failed_products": 3},
                "outcome": "FAILED",
                "stop_reason": "PLAN_ERROR",
                "stop_detail": "PlanError: invalid CSS selector 'a:not(:first-of-type)'",
                "failure_samples": [
                    {
                        "url": "https://example.fr/products/1",
                        "reason": "plan_error",
                        "detail": "invalid selector",
                    }
                ],
            }

        adapter = FakeBuildAdapter(self.root)
        manager = self._manager(adapter, validator=validator)
        with self._client(manager) as client:
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={"repair_rounds": 0},
                headers=CLIENT_HEADERS,
            )
            build_id = response.json()["build"]["build_id"]
            result = self._wait_ready(client, build_id)
            self.assertEqual(result["outcome"], "failed")
            error = result["error"] or ""
            self.assertIn("detail:", error)
            self.assertIn("first-of-type", error)
            self.assertIn("https://example.fr/products/1", error)

    def test_full_catalog_build_patches_rule_scope(self) -> None:
        adapter = FakeBuildAdapter(self.root, rule_payloads=[listing_rule_payload()])
        manager = self._manager(adapter)
        with self._client(manager) as client:
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={
                    "catalog_scope": "full",
                    "catalog_products": 100,
                    "repair_rounds": 0,
                },
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 202, response.text)
            build_id = response.json()["build"]["build_id"]
            result = self._wait_ready(client, build_id)
            self.assertEqual(result["outcome"], "succeeded", result["error"])
            batch = client.get("/api/batches/b-1").json()
            site = batch["sites"][0]
            rule_path = self.rules / site["rule"]["path"]
            payload = yaml.safe_load(rule_path.read_text(encoding="utf-8"))
            self.assertGreaterEqual(payload["scope"]["max_products"], 100)
            self.assertEqual(result["catalog"]["catalog_scope"], "full")

    def test_full_catalog_rejects_entry_links_only(self) -> None:
        adapter = FakeBuildAdapter(self.root)
        manager = self._manager(adapter)
        with self._client(manager) as client:
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={
                    "catalog_scope": "full",
                    "catalog_products": 100,
                    "repair_rounds": 0,
                },
                headers=CLIENT_HEADERS,
            )
            build_id = response.json()["build"]["build_id"]
            result = self._wait_ready(client, build_id)
            self.assertEqual(result["outcome"], "failed")
            self.assertIn("full catalog build requires", result["error"] or "")

    def test_build_timeline_merges_trace_parts(self) -> None:
        trace = {
            "messages": [
                {"created_at": "2026-11-23T04:00:03Z", "text": "written"},
            ],
            "reasoning": [
                {"created_at": "2026-11-23T04:00:01Z", "text": "inspect"},
            ],
            "tools": [
                {
                    "created_at": "2026-11-23T04:00:02Z",
                    "name": "read",
                    "status": "completed",
                    "input": {"path": "brief.md"},
                    "output": "ok",
                    "duration_ms": 12,
                }
            ],
        }
        timeline, truncated = _trace_timeline(trace)
        self.assertFalse(truncated)
        self.assertEqual(
            [item["kind"] for item in timeline],
            ["reasoning", "tool", "text"],
        )

    def test_merge_reasoning_timeline_keeps_live_reasoning(self) -> None:
        trace_timeline = [
            {
                "kind": "tool",
                "created_at": "2026-11-23T04:00:02Z",
                "name": "read",
                "status": "success",
            },
            {
                "kind": "text",
                "created_at": "2026-11-23T04:00:03Z",
                "text": "done",
            },
        ]
        live_timeline = [
            {
                "kind": "reasoning",
                "created_at": "2026-11-23T04:00:01Z",
                "text": "inspect",
            },
            {
                "kind": "tool",
                "created_at": "2026-11-23T04:00:02Z",
                "name": "read",
                "status": "success",
            },
            {
                "kind": "reasoning",
                "created_at": "2026-11-23T04:00:04Z",
                "text": "finish",
            },
        ]
        merged = _merge_reasoning_timeline(trace_timeline, live_timeline)
        self.assertEqual(
            [item["kind"] for item in merged],
            ["reasoning", "tool", "text", "reasoning"],
        )
        self.assertEqual(merged[0]["text"], "inspect")
        self.assertEqual(merged[-1]["text"], "finish")

    def test_build_timeline_groups_live_deltas(self) -> None:
        from types import SimpleNamespace

        events = [
            SimpleNamespace(
                type="reasoning",
                data={"delta": "first "},
                created_at="2026-11-23T04:00:01Z",
            ),
            SimpleNamespace(
                type="reasoning",
                data={"delta": "second"},
                created_at="2026-11-23T04:00:02Z",
            ),
            SimpleNamespace(
                type="tool_started",
                data={"tool": "read"},
                created_at="2026-11-23T04:00:03Z",
            ),
            SimpleNamespace(
                type="tool_finished",
                data={"status": "success"},
                created_at="2026-11-23T04:00:04Z",
            ),
            SimpleNamespace(
                type="message_delta",
                data={"delta": "done"},
                created_at="2026-11-23T04:00:05Z",
            ),
        ]
        timeline, truncated = _live_timeline(events)
        self.assertFalse(truncated)
        self.assertEqual([item["kind"] for item in timeline], ["reasoning", "tool", "text"])
        self.assertEqual(timeline[0]["text"], "first second")
        self.assertEqual(timeline[1]["status"], "success")
        self.assertEqual(timeline[2]["text"], "done")

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
