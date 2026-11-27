from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import queue
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import yaml
from fastapi.testclient import TestClient

from ecom_crawler.build_models import BuildModelPool, ModelPoolError
from ecom_crawler.builds import (
    BuildError,
    BuildManager,
    _duplicate_product_sample_error,
    _live_timeline,
    _merge_reasoning_timeline,
    _probe_robots,
    _rule_needs_browser,
    _seconds_since,
    _trace_timeline,
    default_permissions,
    default_validator,
    dependency_policy_from_env,
    normalize_permission_rules,
)
from ecom_crawler.execution import run_task
from ecom_crawler.harness.adapter import BuildSession
from ecom_crawler.harness.dependencies import DependencyPolicy
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
from ecom_crawler.runtime.worker import Worker
from ecom_crawler.web.app import create_app
from tests.support import serve_http_fixture
from tests.test_execution import RULE_TEMPLATE, fixture_server

CLIENT_HEADERS = {
    "Host": "127.0.0.1:8765",
    "Origin": "http://127.0.0.1:8765",
    "X-Requested-With": "XMLHttpRequest",
}


def rule_payload(
    site_key: str = "example.fr",
    version: str = "2026.11.23-1",
    rule_id: str = "example-fr-build",
) -> dict[str, Any]:
    return {
        "schema_version": "1.1",
        "rule_id": rule_id,
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


def shopify_rule_payload(site_key: str = "example.fr") -> dict[str, Any]:
    payload = rule_payload(site_key)
    payload["schema_version"] = "1.3"
    payload["scope"]["max_products"] = 10
    payload["product_source"] = {
        "type": "shopify_json",
        "url": f"https://{site_key}/products.json",
        "product_url_template": f"https://{site_key}/products/{{handle}}",
        "currency": "EUR",
        "description": {"min_chars": 200, "fallback_concurrency": 1},
        "variants": {"price": "min_positive"},
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
        gate: threading.Event | None = None,
        hang: bool = False,
        persisted: dict[str, BuildSession] | None = None,
    ) -> None:
        self.root = root
        self.write_rule = write_rule
        self.finish = finish
        self.rule_payloads = rule_payloads or []
        self.gate = gate
        self.hang = hang
        self.persisted = dict(persisted or {})
        self.queue: queue.Queue[HarnessEvent | None] = queue.Queue()
        self.queues: dict[str, queue.Queue[HarnessEvent | None]] = {}
        self.current_build: str | None = None
        self.sessions: dict[str, BuildSession] = {}
        self.started: list[str] = []
        self.prompts: list[tuple[str, str]] = []
        self.continued: list[tuple[str, str]] = []
        self.closed: list[str] = []
        self.canceled: list[str] = []
        self.adopted: list[str] = []
        self.detached: list[str] = []
        self.shutdown_called = False
        self.usage_payload: dict[str, Any] | None = None
        self._stop = threading.Event()

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
        self.started.append(task.build_id)
        self.queues[task.build_id] = queue.Queue()
        return session

    def send_prompt(self, build_id: str, text: str) -> dict[str, Any]:
        index = len(self.prompts)
        self.prompts.append((build_id, text))
        if not self.hang:
            self._complete_async(build_id, index)
        else:
            self.sessions[build_id].state = "RUNNING"
        return {"id": "msg_fake"}

    def continue_prompt(self, build_id: str, text: str) -> dict[str, Any]:
        index = len(self.prompts)
        self.continued.append((build_id, text))
        self.prompts.append((build_id, text))
        self.sessions[build_id].state = "RUNNING"
        self.queues.setdefault(build_id, queue.Queue())
        self._complete_async(build_id, index)
        return {"id": f"msg_fake_repair_{len(self.continued)}"}

    def adopt_build(
        self,
        build_id: str,
        *,
        session_id: str,
        workspace: BuildWorkspace,
        model: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> BuildSession:
        self.adopted.append(build_id)
        session = self.sessions.get(build_id) or self.persisted.get(build_id)
        if session is None:
            session = BuildSession(
                build_id=build_id,
                state="FINISHED",
                workspace=workspace,
                session_id=session_id,
                model=model,
                outcome="interrupted",
                error=error,
            )
        self.sessions[build_id] = session
        if self.current_build is None:
            self.current_build = build_id
        self.queues.setdefault(build_id, queue.Queue())
        return session

    def detach(self, build_id: str) -> BuildSession:
        self.detached.append(build_id)
        session = self.sessions[build_id]
        if session.state not in {"CANCELLED", "FINISHED"}:
            session.state = "FINISHED"
            session.outcome = "interrupted"
            session.error = "服务停止，构建会话已中断"
        self.queues.setdefault(build_id, queue.Queue()).put(None)
        return session

    def shutdown(self) -> None:
        self.shutdown_called = True
        self._stop.set()
        for events in tuple(self.queues.values()):
            events.put(None)

    def _complete_async(self, build_id: str, index: int) -> None:
        self.sessions[build_id].state = "RUNNING"

        def complete() -> None:
            # Keep the simulated prompt asynchronous, but do not let a gated
            # completion write to the workspace after cancellation or teardown.
            session = self.sessions[build_id]
            if self.gate is not None:
                deadline = time.monotonic() + 10
                while not self.gate.wait(timeout=0.05):
                    if (
                        self._stop.is_set()
                        or session.state in {"FINISHED", "CANCELLED"}
                        or time.monotonic() >= deadline
                    ):
                        return
            if self._stop.is_set() or session.state in {"FINISHED", "CANCELLED"}:
                return
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
                    build_id=build_id,
                    outcome="succeeded",
                )

        threading.Thread(target=complete, name=f"fake-build-{build_id}", daemon=True).start()

    def stream_events(self, build_id: str) -> Iterator[HarnessEvent]:
        events = self.queues[build_id]
        while not self._stop.is_set():
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

    def usage(self, build_id: str) -> dict[str, Any] | None:
        return self.usage_payload

    def emit(
        self, event_type: str, source_type: str, *, build_id: str | None = None, **data: Any
    ) -> None:
        target = build_id or self.current_build
        if target is None:
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
        self.queues[target].put(
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
        from ecom_crawler import build_models

        build_models._discovery_cache = None
        build_models._metadata_cache.clear()
        self._existing_threads = set(threading.enumerate())
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._clean_workspace)
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

    def _clean_workspace(self) -> None:
        # BuildManager releases its slot before dispatching the next build. A
        # watcher can already have removed itself from the manager's registry
        # but still be dispatching. Wait for the test's threads, not the slot.
        prefixes = ("build-watch-", "build-events-", "dependency-bridge-", "fake-build-")
        deadline = time.monotonic() + 5
        while True:
            pending = [
                thread
                for thread in threading.enumerate()
                if thread not in self._existing_threads and thread.name.startswith(prefixes)
            ]
            if not pending:
                break
            if time.monotonic() >= deadline:
                self.fail(f"Build fixture left threads running: {[thread.name for thread in pending]}")
            for thread in pending:
                thread.join(timeout=max(0, deadline - time.monotonic()))
        self.temporary.cleanup()

    def _stop_manager(self, manager: BuildManager, adapter: FakeBuildAdapter) -> None:
        if not adapter.shutdown_called:
            manager.shutdown()

    def _manager(
        self,
        adapter: FakeBuildAdapter | None,
        *,
        adapter_factory: Callable[[], FakeBuildAdapter] | None = None,
        max_concurrent: int = 1,
        currencies: dict[str, int] | None = None,
        validator: Any | None = None,
        max_repair_rounds: int = 0,
        robots_probe: Any | None = None,
        skills_dir: Path | None = None,
        activation_mode: str = "legacy",
        extra_permissions: list[dict[str, Any]] | None = None,
        dependency_policy: DependencyPolicy | None = None,
        max_seconds: int = 10,
        browser_validation_seconds: int | None = None,
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
                resolved = currencies or {"EUR": 2}
                currency = next(iter(resolved))
                samples = [
                    {
                        "source_url": f"https://example.fr/p/{index}",
                        "name": f"Example product {index}",
                        "price_amount": f"{index}0.00",
                        "price_currency": currency,
                        "primary_image_url": (
                            f"https://example.fr/images/{index}.jpg"
                        ),
                        "description_html": (
                            f"<p>Example product {index} description with "
                            "enough detail for the host check.</p>"
                        ),
                    }
                    for index in (1, 2)
                ]
                return {
                    "counts": {"valid_products": 2, "failed_products": 0},
                    "outcome": "COMPLETED",
                    "stop_reason": "NATURAL_END",
                    "currencies": resolved,
                    "product_samples": samples,
                }

        manager = BuildManager(
            self.store,
            self.root / "out",
            self.rules,
            adapter=adapter,
            adapter_factory=adapter_factory,
            max_concurrent=max_concurrent,
            validator=validator,
            max_seconds=max_seconds,
            validation_seconds=5,
            browser_validation_seconds=browser_validation_seconds,
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
            extra_permissions=extra_permissions,
            dependency_policy=dependency_policy,
        )
        if adapter is None:
            self.addCleanup(manager.shutdown)
        else:
            self.addCleanup(self._stop_manager, manager, adapter)
        return manager

    def _client(self, manager: BuildManager) -> TestClient:
        app = create_app(
            self.root / "tasks.db",
            self.root / "out",
            self.rules,
            build_manager=manager,
            manage_worker=False,
        )
        return TestClient(app, headers=CLIENT_HEADERS)

    def _wait_for_build_state(
        self, client: TestClient, build_id: str, *states: str, timeout: float = 10
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            response = client.get(f"/api/builds/{build_id}")
            self.assertEqual(response.status_code, 200, response.text)
            last = response.json()["build"]
            if last["state"] in states:
                return last
            if last["state"] in {"FINISHED", "CANCELLED"}:
                break
            time.sleep(0.05)
        self.fail(
            f"Build {build_id} did not reach {states}: "
            f"state={last.get('state')}, outcome={last.get('outcome')}, "
            f"error={last.get('error')}"
        )

    def _wait_ready(self, client: TestClient, build_id: str, timeout: float = 10) -> dict[str, Any]:
        return self._wait_for_build_state(client, build_id, "FINISHED", "CANCELLED", timeout=timeout)

    def test_seconds_since_accepts_naive_legacy_timestamps(self) -> None:
        self.assertEqual(
            _seconds_since(
                "2026-11-24 12:00:00",
                end="2026-11-24 12:00:10",
            ),
            10.0,
        )

    def test_batch_onboarding_queues_collection_only_after_validation(self) -> None:
        adapter = FakeBuildAdapter(self.root, rule_payloads=[listing_rule_payload()])
        with mock.patch.dict(os.environ, {
            "ECOM_BUILD_MAX_INPUT_TOKENS": "230000",
            "ECOM_BUILD_MAX_OUTPUT_TOKENS": "45000",
        }):
            manager = self._manager(adapter, activation_mode="manual")
        with self._client(manager) as client:
            created = client.post("/api/batches", json={
                "name": "Onboarding", "market": "FR", "collection_mode": "sample",
                "sites": ["https://example.fr/"],
            })
            self.assertEqual(created.status_code, 201, created.text)
            batch_id = created.json()["batch"]["batch_id"]
            path = f"/api/batches/{batch_id}/start"
            regular = client.post(path, json={})
            self.assertEqual(regular.status_code, 202, regular.text)
            self.assertEqual(regular.json()["onboarding"], [])
            started = client.post(path, json={"onboard": True, "promote_trial": True})
            self.assertEqual(started.status_code, 202, started.text)
            self.assertEqual(started.json()["batch"]["collection_mode"], "formal")
            build_id = started.json()["onboarding"][0]["build_id"]
            result = self._wait_ready(client, build_id)
            self.assertEqual(result["outcome"], "succeeded", result.get("error"))
            self.assertEqual(result["catalog"]["catalog_scope"], "batch")
            request = self.store.get_build(build_id).request
            self.assertEqual(request["max_input_tokens"], 230000)
            self.assertEqual(request["max_output_tokens"], 45000)
            site_key = started.json()["onboarding"][0]["site_key"]
            site = self.store.get_batch_site(batch_id, site_key)
            task = self.store.get_task(site.task_id)
            self.assertEqual(task.state, "QUEUED")
            self.assertEqual(task.input["collection_mode"], "formal")
            self.assertIsNone(task.limits["max_products"])
            self.assertIsNone(task.limits["max_seconds"])
            self.assertEqual(len(self.store.list_batch_tasks(batch_id)), 1)
            cancelled = client.post(f"/api/batches/{batch_id}/cancel").json()
            self.assertEqual(cancelled["cancelled_onboarding"], [])
            self.assertEqual(self.store.get_task(task.task_id).state, "CANCELLED")

    def test_onboarding_budget_settings_apply_only_to_new_builds(self) -> None:
        manager = self._manager(FakeBuildAdapter(self.root, hang=True))
        endpoint = "/api/builds/config/onboarding-budget"
        first = {"max_seconds": 1200, "max_input_tokens": 750_000, "max_output_tokens": 100_000}
        second = {**first, "max_output_tokens": 150_000}
        with self._client(manager) as client:
            default = client.get("/api/builds/config").json()["onboarding_budget"]
            saved = client.put(endpoint, json=first)
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertTrue(saved.json()["onboarding_budget_override"])
            self.assertEqual(client.put(endpoint, json={**first, "max_seconds": 1}).status_code, 422)
            self.assertEqual(client.get("/api/builds/config").json()["onboarding_budget"], first)
            batch = client.post("/api/batches", json={
                "name": "Budget", "market": "FR", "collection_mode": "sample",
                "sites": ["https://budget-first.test/", "https://budget-second.test/"],
            }).json()["batch"]
            path = f"/api/batches/{batch['batch_id']}/start"
            build_ids = []
            for index, site in enumerate(batch["sites"]):
                if index:
                    self.assertEqual(client.put(endpoint, json=second).status_code, 200)
                result = client.post(path, json={"onboard": True, "site_keys": [site["site_key"]]})
                self.assertEqual(result.status_code, 202, result.text)
                build_ids.append(result.json()["onboarding"][0]["build_id"])
            for build_id, expected in zip(build_ids, (first, second)):
                response = client.get(f"/api/builds/{build_id}").json()["build"]
                self.assertEqual(response["onboarding_budget"], expected)
                self.assertEqual(self.store.get_build(build_id).request["max_total_seconds"], 1200)
            self.assertEqual(self.store.get_build(build_ids[1]).state, "QUEUED")
            with TestClient(
                create_app(self.root / "tasks.db", self.root / "out", self.rules, read_only=True),
                headers=CLIENT_HEADERS,
            ) as preview:
                self.assertEqual(preview.get("/api/builds/config").json()["onboarding_budget"], second)
                self.assertEqual(preview.delete(endpoint).status_code, 403)
            restored = client.delete(endpoint).json()
            self.assertEqual(restored["onboarding_budget"], default)
            self.assertFalse(restored["onboarding_budget_override"])

    def test_formal_batch_onboarding_rejects_sample_only_rule(self) -> None:
        manager = self._manager(FakeBuildAdapter(self.root))
        with self._client(manager) as client:
            batch = client.post("/api/batches", json={
                "name": "Formal", "market": "FR", "collection_mode": "formal",
                "sites": ["https://example.fr/"],
            }).json()["batch"]
            path = f"/api/batches/{batch['batch_id']}/start"
            started = client.post(path, json={"onboard": True})
            build_id = started.json()["onboarding"][0]["build_id"]
            result = self._wait_ready(client, build_id)
            self.assertEqual(result["outcome"], "failed")
            self.assertIn("entry_links alone", result["error"])
            self.assertEqual(self.store.list_batch_tasks(batch["batch_id"]), [])

    def test_batch_cancel_stops_running_and_queued_automatic_onboarding(self) -> None:
        adapter = FakeBuildAdapter(self.root, hang=True)
        manager = self._manager(adapter)
        with self._client(manager) as client:
            batch = client.post("/api/batches", json={
                "name": "Cancelable", "market": "FR", "collection_mode": "formal",
                "sites": ["https://first.example/", "https://second.example/", "https://manual.example/"],
            }).json()["batch"]
            path = f"/api/batches/{batch['batch_id']}"
            first, second, manual = [site["site_key"] for site in batch["sites"]]
            response = client.post(f"{path}/start", json={
                "site_keys": [first, second], "onboard": True,
            })
            self.assertEqual(response.status_code, 202, response.text)
            running, queued = [entry["build_id"] for entry in response.json()["onboarding"]]
            unrelated = client.post(f"{path}/sites/{manual}/build")
            self.assertEqual(unrelated.status_code, 202, unrelated.text)
            separate_build = unrelated.json()["build"]["build_id"]
            self.assertEqual(self.store.get_build(queued).state, "QUEUED")
            self.assertEqual(adapter.started, [running])
            current = client.get(path).json()["sites"]
            self.assertEqual([site["build"]["cancellable_onboarding"] for site in current], [True, True, False])

            cancelled = client.post(f"{path}/cancel").json()
            self.assertCountEqual(cancelled["cancelled_onboarding"], [running, queued])
            self.assertEqual(self.store.get_build(queued).state, "CANCELLED")
            self.assertEqual(self._wait_ready(client, running)["state"], "CANCELLED")
            self._wait_for_build_state(client, separate_build, "RUNNING")
            self.assertEqual(adapter.started, [running, separate_build])
            self.assertEqual(adapter.canceled, [running])
            replay = client.post(f"{path}/cancel").json()
            self.assertEqual(replay["cancelled_onboarding"], [])
            self.assertEqual(self.store.list_batch_tasks(batch["batch_id"]), [])

    def test_batch_cancel_during_validation_blocks_the_automatic_task(self) -> None:
        origin = "http://validating-catalog.test"
        rule = yaml.safe_load(RULE_TEMPLATE.replace("__BASE__", origin))
        rule["discovery"]["sources"] = [{
            "type": "listing", "url": f"{origin}/list", "product_link_selector": "a.product",
        }]
        validation_started = threading.Event()
        finish_validation = threading.Event()

        def validator(*args: Any, **kwargs: Any) -> dict[str, Any]:
            validation_started.set()
            if not finish_validation.wait(10):
                raise TimeoutError("validation fixture was not released")
            return default_validator(*args, **kwargs)

        adapter = FakeBuildAdapter(self.root, rule_payloads=[rule])
        manager = self._manager(adapter, validator=validator)
        with fixture_server(proxy_origin=origin) as proxy, self._client(manager) as client:
            batch = client.post("/api/batches", json={
                "name": "Cancel during validation", "market": "GB",
                "collection_mode": "formal", "sites": [origin],
            }).json()["batch"]
            path = f"/api/batches/{batch['batch_id']}"
            started = client.post(f"{path}/start", json={"onboard": True, "proxy": proxy})
            build_id = started.json()["onboarding"][0]["build_id"]
            try:
                self.assertTrue(validation_started.wait(5))
                self.assertEqual(self.store.get_build(build_id).state, "VALIDATING")
                self.assertEqual(client.post(f"{path}/cancel").json()["cancelled_onboarding"], [build_id])
            finally:
                finish_validation.set()
            result = self._wait_ready(client, build_id)
            self.assertEqual(result["outcome"], "succeeded", result["error"])
            self.assertEqual(self.store.list_batch_tasks(batch["batch_id"]), [])
            started_manually = client.post(f"{path}/start")
            self.assertEqual(len(started_manually.json()["accepted"]), 1)

    def test_batch_cancel_before_validation_prevents_validation(self) -> None:
        validator = mock.Mock(side_effect=AssertionError("cancelled build entered validation"))
        adapter = FakeBuildAdapter(self.root, rule_payloads=[listing_rule_payload()])
        manager = self._manager(adapter, validator=validator)
        about_to_validate = threading.Event()
        proceed = threading.Event()
        claim = self.store.claim_build_validation

        def claim_after_cancel(build_id: str) -> bool:
            about_to_validate.set()
            if not proceed.wait(10):
                raise TimeoutError("validation claim fixture was not released")
            return claim(build_id)

        with mock.patch.object(self.store, "claim_build_validation", claim_after_cancel), self._client(manager) as client:
            batch = client.post("/api/batches", json={
                "name": "Cancel before validation", "market": "FR",
                "collection_mode": "formal", "sites": ["https://example.fr/"],
            }).json()["batch"]
            path = f"/api/batches/{batch['batch_id']}"
            started = client.post(f"{path}/start", json={"onboard": True})
            build_id = started.json()["onboarding"][0]["build_id"]
            try:
                self.assertTrue(about_to_validate.wait(5))
                self.assertEqual(client.post(f"{path}/cancel").json()["cancelled_onboarding"], [build_id])
            finally:
                proceed.set()
            self.assertEqual(self._wait_ready(client, build_id)["state"], "CANCELLED")
            validator.assert_not_called()
            self.assertEqual(self.store.list_batch_tasks(batch["batch_id"]), [])

    def test_formal_onboarding_validates_only_the_submitted_product(self) -> None:
        origin = "http://new-product.test"
        entry = f"{origin}/p2.html?variant=blue"
        rule = yaml.safe_load(RULE_TEMPLATE.replace("__BASE__", origin))
        rule["site"]["entry_urls"] = [entry]
        rule["discovery"]["entry_url"] = entry
        adapter = FakeBuildAdapter(self.root, rule_payloads=[rule])
        manager = self._manager(adapter, validator=default_validator)
        requested: list[str] = []
        with fixture_server(proxy_origin=origin, requests=requested) as proxy, self._client(manager) as client:
            batch = client.post("/api/batches", json={
                "name": "Product", "market": "GB", "collection_mode": "formal",
                "sites": [entry],
            }).json()["batch"]
            result = client.post(
                f"/api/batches/{batch['batch_id']}/start", json={"onboard": True, "proxy": proxy},
            ).json()
            build = self._wait_ready(client, result["onboarding"][0]["build_id"])
            self.assertEqual(build["outcome"], "succeeded", build["error"])
            self.assertEqual(build["validation"]["candidate_smoke"]["valid_products"], 1)
            brief = (Path(build["workspace"]) / "input" / "build-brief.md").read_text(encoding="utf-8")
            self.assertIn("inspect that one product only", brief)
            self.assertIn("Reuse the first successful static response", brief)
            self.assertEqual(requested, ["/p2.html?variant=blue"])
            task, = self.store.list_batch_tasks(batch["batch_id"])
            self.assertEqual(task.input["target_entry"], entry)

    def test_formal_onboarding_validates_from_the_submitted_directory_page(self) -> None:
        origin = "http://new-catalog.test"
        entry = f"{origin}/list?brand=one&brand=two&p=2"
        rule = yaml.safe_load(RULE_TEMPLATE.replace("__BASE__", origin))
        rule["site"]["entry_urls"] = [entry]
        rule["discovery"]["sources"] = [{
            "type": "listing", "url": entry, "product_link_selector": "a.product",
            "advance": {"type": "page_param", "param": "p", "max_pages": 3},
        }]
        adapter = FakeBuildAdapter(self.root, rule_payloads=[rule])
        manager = self._manager(adapter, validator=default_validator)
        requested: list[str] = []
        with fixture_server(proxy_origin=origin, requests=requested) as proxy, self._client(manager) as client:
            batch = client.post("/api/batches", json={
                "name": "Filtered catalog", "market": "GB", "collection_mode": "formal",
                "sites": [entry],
            }).json()["batch"]
            response = client.post(
                f"/api/batches/{batch['batch_id']}/start", json={"onboard": True, "proxy": proxy},
            )
            self.assertEqual(response.status_code, 202, response.text)
            build = self._wait_ready(client, response.json()["onboarding"][0]["build_id"])
            self.assertEqual(build["outcome"], "succeeded", build["error"])
            self.assertIn("/list?brand=one&brand=two&p=3", requested)
            samples = build["validation"]["candidate_smoke"]["product_samples"]
            self.assertEqual({sample["source_url"] for sample in samples}, {
                f"{origin}/p2.html", f"{origin}/p3.html",
            })
            task, = self.store.list_batch_tasks(batch["batch_id"])
            self.assertEqual(task.input["target_entry"], entry)

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
        self.assertIn(("request_dependency", "*", "allow"), entries)
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

    def test_extra_permissions_are_appended_after_defaults(self) -> None:
        adapter = FakeBuildAdapter(self.root)
        manager = self._manager(
            adapter,
            extra_permissions=[
                {"action": "shell", "resource": "*", "effect": "ask"}
            ],
        )
        with self._client(manager) as client:
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={"max_products": 2, "max_seconds": 60},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 202, response.text)
            build_id = response.json()["build"]["build_id"]
            result = self._wait_ready(client, build_id)
            task_payload = json.loads(
                (Path(result["workspace"]) / "input" / "build-task.json").read_text(
                    encoding="utf-8"
                )
            )
        permissions = task_payload["permissions"]
        self.assertEqual(
            permissions[-1],
            {"action": "shell", "resource": "*", "effect": "ask"},
        )
        self.assertIn(
            {"action": "shell", "resource": "*", "effect": "allow"},
            permissions,
        )

    def test_normalize_permission_rules_rejects_unknown_effect(self) -> None:
        with self.assertRaises(BuildError):
            normalize_permission_rules(
                [{"action": "shell", "resource": "*", "effect": "maybe"}]
            )

    def test_dependency_policy_from_env_is_opt_in(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "ECOM_BUILD_PYTHON": str(Path(sys.executable)),
                "ECOM_BUILD_DEPENDENCY_ALLOWLIST": "six==1.17.0,pyyaml==6.0.3",
            },
            clear=False,
        ):
            policy = dependency_policy_from_env()
        self.assertEqual(policy.build_python, Path(sys.executable))
        self.assertEqual(policy.allowlist["six"], {"version": "1.17.0"})
        self.assertEqual(policy.allowlist["pyyaml"], {"version": "6.0.3"})
        self.assertIn("pip", policy.installers)
        self.assertIn("uv", policy.installers)

    def test_dependency_installer_configured_needs_python_and_installer(self) -> None:
        adapter = FakeBuildAdapter(self.root)
        empty = self._manager(adapter)
        self.assertFalse(empty.dependency_installer_configured)

        policy = DependencyPolicy(build_python=Path(sys.executable))
        manager = self._manager(adapter, dependency_policy=policy)
        self.assertFalse(manager.dependency_installer_configured)

        policy = DependencyPolicy(
            build_python=Path(sys.executable),
            installers={"pip": lambda *_: None},
        )
        manager = self._manager(adapter, dependency_policy=policy)
        self.assertTrue(manager.dependency_installer_configured)

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
            self.assertIn("Before planning discovery, load", agents)
            self.assertIn("before any challenge probe, load", agents)
            self.assertIn("browse` and `htmlmini` MCP tools are available", agents)
            self.assertIn("## Visual evidence", agents)
            self.assertIn("../out/evidence/visual/baseline.json", agents)
            self.assertIn("review.status", agents)
            self.assertIn("Read local files from", agents)
            self.assertIn("in place of generic skill defaults", agents)
            self.assertIn("Use the recorded exit", agents)
            self.assertIn("honor Retry-After", agents)
            self.assertNotIn("Read local files from", brief)
            self.assertIn("../out/evidence/visual/", brief)
            self.assertIn("follow the visual evidence instructions", brief)
            self.assertIn("pending_manual", agents)
            self.assertIn("capture_method: rendered", agents)
            self.assertNotIn("pending_manual", brief)
            self.assertNotIn("alternate same-market", brief)
            self.assertIn("A passing initial build is activated", brief)
            self.assertIn("product_source", brief)
            self.assertIn("schema_version: \"1.3\"", brief)
            self.assertIn("shopify_json", brief)
            self.assertIn("default_engine: stealth", brief)
            self.assertIn("resilient-browser-fetch", brief)
            self.assertIn("Host validation budget", brief)
            self.assertIn("Keep the entry page or a listing source first", brief)
            self.assertIn("A sitemap-only source makes the first request", brief)
            self.assertIn("product_link_selector", brief)
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

    def test_model_pool_rotates_and_pins_queued_builds(self) -> None:
        manager = self._manager(FakeBuildAdapter(self.root, hang=True))
        pool = "opencode-go/deepseek-v4.1-flash#high,yjwd-gpt-enterprise/gpt-6.1-terra#medium"
        manager.model_pool = BuildModelPool(pool)
        self.store.add_batch_sites([
            BatchSite(batch_id="b-1", site_key=key, domain=key, input_value=f"https://{key}/",
                      readiness="needs_onboarding")
            for key in ("manual.test", "second.test", "third.test", "invalid.test")
        ])
        with self._client(manager) as client:
            def submit(site: str, ref: str | None = None):
                return client.post(f"/api/batches/b-1/sites/{site}/build", json={"model_ref": ref})

            self.assertEqual(submit("invalid.test", "opencode-go/deepseek-v4.1-flash#medium").status_code, 409)
            allocations = []
            for site, ref in (
                ("example.fr", None),
                ("manual.test", "yjwd-gpt-enterprise/gpt-6.1-terra#high"),
                ("second.test", None),
                ("third.test", None),
            ):
                response = submit(site, ref)
                self.assertEqual(response.status_code, 202, response.text)
                allocations.append(response.json()["build"])
                # Recreating the in-memory pool does not reset the ledger cursor.
                manager.model_pool = BuildModelPool(pool)
            self.assertEqual([(item["model"]["id"], item["model"]["variant"]) for item in allocations], [
                ("deepseek-v4.1-flash", "high"), ("gpt-6.1-terra", "high"),
                ("gpt-6.1-terra", "medium"), ("deepseek-v4.1-flash", "high"),
            ])
            self.assertEqual(allocations[2]["state"], "QUEUED")
            self.assertEqual(self.store.get_build(allocations[2]["build_id"]).model, allocations[2]["model"])

    def test_model_pool_default_model_pins_new_builds(self) -> None:
        manager = self._manager(FakeBuildAdapter(self.root, hang=True))
        terra = "yjwd-gpt-enterprise/gpt-6.1-terra"
        manager.model_pool = BuildModelPool(
            "opencode-go/deepseek-v4.1-flash#high,"
            "yjwd-gpt-enterprise/gpt-6.1-terra#medium"
        )
        manager.model_pool.set_default(f"{terra}#medium")
        self.store.add_batch_sites([
            BatchSite(
                batch_id="b-1",
                site_key="second.test",
                domain="second.test",
                input_value="https://second.test/",
                readiness="needs_onboarding",
            )
        ])
        with self._client(manager) as client:
            for site in ("example.fr", "second.test"):
                response = client.post(
                    f"/api/batches/b-1/sites/{site}/build", json={}
                )
                self.assertEqual(response.status_code, 202, response.text)
                build = response.json()["build"]
                self.assertEqual(
                    build["model"],
                    {
                        "providerID": "yjwd-gpt-enterprise",
                        "id": "gpt-6.1-terra",
                        "variant": "medium",
                    },
                )
                record = self.store.get_build(build["build_id"])
                self.assertEqual(record.request["model_selection"], "pinned")

    def test_model_pool_default_setting_persists_and_resets(self) -> None:
        manager = self._manager(FakeBuildAdapter(self.root))
        deepseek = "opencode-go/deepseek-v4.1-flash"
        terra = "yjwd-gpt-enterprise/gpt-6.1-terra"
        with self._client(manager) as client:
            response = client.put(
                "/api/builds/config/models",
                json={
                    "refs": [f"{deepseek}#high", f"{terra}#medium"],
                    "default_ref": f"{terra}#medium",
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["default_model"], f"{terra}#medium")
            self.assertEqual(
                self.store.get_setting("build_model_default"), f"{terra}#medium"
            )

            started = client.post(
                "/api/batches/b-1/sites/example.fr/build", json={}
            )
            self.assertEqual(started.status_code, 202, started.text)
            self.assertEqual(
                started.json()["build"]["model"],
                {
                    "providerID": "yjwd-gpt-enterprise",
                    "id": "gpt-6.1-terra",
                    "variant": "medium",
                },
            )

            restarted = BuildManager(
                self.store,
                self.root / "out-restart-default",
                self.rules,
                adapter=FakeBuildAdapter(self.root),
            )
            self.addCleanup(restarted.shutdown)
            self.assertEqual(restarted.model_pool.default_ref, f"{terra}#medium")

            reset = client.delete("/api/builds/config/models")
            self.assertEqual(reset.status_code, 200, reset.text)
            self.assertIsNone(reset.json()["default_model"])
            self.assertIsNone(self.store.get_setting("build_model_default"))

    def test_model_pool_rejects_invalid_default_model(self) -> None:
        manager = self._manager(FakeBuildAdapter(self.root))
        deepseek = "opencode-go/deepseek-v4.1-flash"
        terra = "yjwd-gpt-enterprise/gpt-6.1-terra"
        with self._client(manager) as client:
            outside = client.put(
                "/api/builds/config/models",
                json={"refs": [f"{deepseek}#high"], "default_ref": f"{terra}#medium"},
            )
            self.assertEqual(outside.status_code, 400)
            self.assertEqual(outside.json()["error"]["code"], "MODEL_POOL_INVALID")
            self.assertIsNone(manager.model_pool.default_ref)
            self.assertIsNone(self.store.get_setting("build_model_default"))

            mismatch = client.put(
                "/api/builds/config/models",
                json={"refs": [f"{deepseek}#high"], "default_ref": f"{deepseek}#max"},
            )
            self.assertEqual(mismatch.status_code, 400)
            self.assertEqual(mismatch.json()["error"]["code"], "MODEL_POOL_INVALID")

    def test_available_models_endpoint_uses_discovery(self) -> None:
        manager = self._manager(FakeBuildAdapter(self.root))
        models = [
            {
                "id": "commandcode/deepseek/deepseek-v4.1-flash",
                "provider": "commandcode",
                "model": "deepseek/deepseek-v4.1-flash",
                "label": "CommandCode DeepSeek V4.1 Flash",
                "variants": ["low", "high", "max"],
                "probe_supported": False,
                "known": True,
            },
            {
                "id": "custom/provider-model",
                "provider": "custom",
                "model": "provider-model",
                "label": "provider-model",
                "variants": [],
                "probe_supported": False,
                "known": False,
            },
        ]
        with (
            mock.patch(
                "ecom_crawler.web.app.discover_models", return_value=models
            ) as discover,
            self._client(manager) as client,
        ):
            response = client.get("/api/builds/models/available?refresh=1")
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body["models"], models)
            self.assertIsNone(body["error"])
            discover.assert_called_once()
            self.assertTrue(discover.call_args.kwargs["refresh"])

        with (
            mock.patch(
                "ecom_crawler.web.app.discover_models",
                side_effect=ModelPoolError("OpenCode 模型列表读取失败"),
            ),
            self._client(manager) as client,
        ):
            response = client.get("/api/builds/models/available")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["models"], [])
            self.assertIn("读取失败", response.json()["error"])

    def test_discovery_maps_opencode_metadata(self) -> None:
        from ecom_crawler import build_models

        api_models = [
            {
                "providerID": "commandcode",
                "modelID": "deepseek/deepseek-v4.1-flash",
                "name": "CommandCode DeepSeek V4.1 Flash",
                "type": "chat",
                "enabled": True,
                "variants": [{"id": "low"}, {"id": "high"}, {"id": "max"}],
                "limit": {"context": 1_000_000, "output": 384_000},
                "capabilities": {
                    "tools": True,
                    "input": ["text", "image"],
                    "output": ["text"],
                },
                "compatibility": {"maxTokensField": "max_tokens"},
                "status": "active",
            },
            {
                "providerID": "other",
                "modelID": "plain",
                "name": "Plain Chat",
                "type": "chat",
                "enabled": True,
                "variants": [],
                "limit": {"context": 128_000, "output": 4_096},
                "capabilities": {
                    "tools": False,
                    "input": ["text"],
                    "output": ["text"],
                },
                "status": "active",
            },
            {
                "providerID": "other",
                "modelID": "embedding",
                "name": "Embedding",
                "type": "embedding",
                "enabled": True,
                "variants": [],
                "limit": {"context": 8_000, "output": 1_024},
                "capabilities": {"tools": False, "input": ["text"], "output": []},
                "status": "active",
            },
        ]
        with mock.patch.object(
            build_models,
            "_discover_from_opencode_api",
            return_value=api_models,
        ) as discover:
            models = build_models.discover_models(refresh=True)
        self.assertEqual(
            [model["id"] for model in models],
            ["commandcode/deepseek/deepseek-v4.1-flash", "other/plain"],
        )
        first = models[0]
        self.assertTrue(first["known"])
        self.assertEqual(first["label"], "CommandCode DeepSeek V4.1 Flash")
        self.assertEqual(first["variants"], ["low", "high", "max"])
        self.assertEqual(first["context_window"], 1_000_000)
        self.assertEqual(first["max_output_tokens"], 384_000)
        self.assertTrue(first["probe_supported"])
        self.assertTrue(first["capabilities"]["tools"])
        self.assertEqual(first["capabilities"]["input"], ["text", "image"])
        self.assertEqual(first["max_tokens_field"], "max_tokens")
        self.assertEqual(
            build_models.model_metadata(first["id"])["label"],
            "CommandCode DeepSeek V4.1 Flash",
        )
        discover.assert_called_once()

    def test_discovery_falls_back_to_cli_ids_when_api_is_unavailable(self) -> None:
        from ecom_crawler import build_models

        completed = mock.Mock(
            returncode=0,
            stdout=(
                "commandcode/deepseek/deepseek-v4.1-flash\n"
                "unlisted/model\n"
                "not-a-model\n"
            ),
        )
        with (
            mock.patch.object(
                build_models,
                "_discover_from_opencode_api",
                side_effect=ModelPoolError("api unavailable"),
            ),
            mock.patch.object(
                build_models, "resolve_opencode_command", return_value=["opencode"]
            ),
            mock.patch.object(
                build_models, "child_environment", return_value={}
            ),
            mock.patch.object(
                build_models.subprocess, "run", return_value=completed
            ) as run,
        ):
            models = build_models.discover_models(refresh=True)
        self.assertEqual(
            [model["id"] for model in models],
            [
                "commandcode/deepseek/deepseek-v4.1-flash",
                "unlisted/model",
            ],
        )
        self.assertTrue(models[0]["known"])
        self.assertEqual(models[0]["variants"], ["low", "high", "max"])
        self.assertFalse(models[1]["known"])
        self.assertIsNone(models[1]["context_window"])
        pool = BuildModelPool("unlisted/model#custom")
        self.assertEqual(pool.refs(), ["unlisted/model#custom"])
        run.assert_called_once()

    def test_commandcode_deepseek_is_a_known_model(self) -> None:
        from ecom_crawler.build_models import known_models

        entry = next(
            item
            for item in known_models()
            if item["id"] == "commandcode/deepseek/deepseek-v4.1-flash"
        )
        self.assertEqual(entry["label"], "CommandCode DeepSeek V4.1 Flash")
        self.assertEqual(entry["variants"], ["low", "high", "max"])
        self.assertTrue(entry["probe_supported"])

    def test_model_pool_probe_only_on_post_and_excludes_failed_default(self) -> None:
        manager = self._manager(FakeBuildAdapter(self.root))
        terra = "yjwd-gpt-enterprise/gpt-6.1-terra"
        deepseek = "opencode-go/deepseek-v4.1-flash"
        manager.model_pool = BuildModelPool(f"{deepseek}#high,{terra}#medium")
        with (
            mock.patch("ecom_crawler.build_models.probe_chat", side_effect=[0, 5, 0]) as probe,
            self._client(manager) as client,
        ):
            self.assertEqual(client.get("/api/builds/config").json()["models"][1]["health"], {})
            probe.assert_not_called()
            for ref, expected in ((f"{terra}#medium", "failed"), (f"{terra}#high", "ok"),
                                  (f"{deepseek}#high", "failed")):
                response = client.post("/api/builds/models/check", json={"model_ref": ref})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["status"], expected)
                self.assertIn("checked_at", response.json())
                if ref == f"{terra}#medium":
                    self.assertEqual(manager.model_pool.balanced(deepseek)["id"], "deepseek-v4.1-flash")
            self.assertEqual(probe.call_count, 3)
            health = client.get("/api/builds/config").json()["models"][1]["health"]
            self.assertEqual({variant: result["status"] for variant, result in health.items()},
                             {"medium": "failed", "high": "ok"})
            response = client.post("/api/batches/b-1/sites/example.fr/build", json={})
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(manager.adapter.started, [])

    def test_model_probe_allows_model_outside_pool(self) -> None:
        manager = self._manager(FakeBuildAdapter(self.root))
        manager.model_pool = BuildModelPool("opencode-go/deepseek-v4.1-flash#high")
        with (
            mock.patch(
                "ecom_crawler.build_models.probe_chat", return_value=5
            ) as probe,
            self._client(manager) as client,
        ):
            response = client.post(
                "/api/builds/models/check",
                json={"model_ref": "yjwd-gpt-enterprise/gpt-6.1-terra#medium"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "ok")
            self.assertEqual(probe.call_count, 1)
            self.assertNotIn(
                "yjwd-gpt-enterprise/gpt-6.1-terra",
                [model["id"] for model in client.get("/api/builds/config").json()["models"]],
            )

    def test_model_probe_retries_alternate_max_tokens_field(self) -> None:
        from ecom_crawler.harness.opencode import OpenCodeHttpError

        manager = self._manager(FakeBuildAdapter(self.root))
        manager.model_pool = BuildModelPool("")
        error = OpenCodeHttpError(400, "HTTP_ERROR", "bad parameter", None)
        with (
            mock.patch(
                "ecom_crawler.build_models.probe_chat",
                side_effect=[error, 9],
            ) as probe,
            mock.patch(
                "ecom_crawler.build_models.model_metadata", return_value=None
            ),
            self._client(manager) as client,
        ):
            response = client.post(
                "/api/builds/models/check",
                json={"model_ref": "commandcode/deepseek/deepseek-v4.1-flash#low"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "ok")
            self.assertEqual(probe.call_count, 2)
            self.assertEqual(
                [call.kwargs["max_tokens_field"] for call in probe.call_args_list],
                ["max_tokens", "max_completion_tokens"],
            )

    def test_probe_accepts_reasoning_or_text_activity(self) -> None:
        from ecom_crawler.harness.opencode import OpenCodeClient

        client = OpenCodeClient("http://127.0.0.1:9", "secret")
        cases = [
            (
                {"data": {"text": "", "tokens": {"input": 10, "output": 0, "reasoning": 64}}},
                64,
            ),
            (
                {"data": {"text": "OK", "tokens": {"input": 10, "output": 0, "reasoning": 0}}},
                1,
            ),
            (
                {"data": {"text": "", "tokens": {"input": 10, "output": 0, "reasoning": 0}}},
                0,
            ),
        ]
        for payload, expected in cases:
            with mock.patch.object(client, "_request", return_value=payload):
                self.assertEqual(client.generate_probe("session-1"), expected)

    def test_model_pool_settings_persist_and_hot_apply(self) -> None:
        env_pool = "opencode-go/deepseek-v4.1-flash#high"
        with mock.patch.dict(os.environ, {"ECOM_BUILD_MODEL_POOL": env_pool}, clear=False):
            manager = self._manager(FakeBuildAdapter(self.root, hang=True))
            self.assertEqual(manager.model_pool_source, "env")
            with self._client(manager) as client:
                response = client.put(
                    "/api/builds/config/models",
                    json={
                        "refs": [
                            "opencode-go/deepseek-v4.1-flash#max",
                            "yjwd-gpt-enterprise/gpt-6.1-terra#medium",
                        ]
                    },
                )
                self.assertEqual(response.status_code, 200, response.text)
                body = response.json()
                self.assertEqual(body["model_pool_source"], "settings")
                self.assertTrue(body["model_pool_editable"])
                self.assertTrue(body["model_pool_override"])
                self.assertEqual(
                    [model["variant"] for model in body["models"]],
                    ["max", "medium"],
                )
                self.assertEqual(
                    self.store.get_setting("build_model_pool"),
                    "opencode-go/deepseek-v4.1-flash#max,"
                    "yjwd-gpt-enterprise/gpt-6.1-terra#medium",
                )

                # Invalid saves reject without changing the active pool.
                bad = client.put(
                    "/api/builds/config/models", json={"refs": ["not-a-model"]}
                )
                self.assertEqual(bad.status_code, 400)
                self.assertEqual(bad.json()["error"]["code"], "MODEL_POOL_INVALID")
                self.assertEqual(
                    manager.model_pool.refs(),
                    [
                        "opencode-go/deepseek-v4.1-flash#max",
                        "yjwd-gpt-enterprise/gpt-6.1-terra#medium",
                    ],
                )

                # A restarted manager reads the persisted pool, not the env.
                restarted = BuildManager(
                    self.store,
                    self.root / "out-restart",
                    self.rules,
                    adapter=FakeBuildAdapter(self.root),
                )
                self.addCleanup(restarted.shutdown)
                self.assertEqual(restarted.model_pool_source, "settings")
                self.assertEqual(restarted.model_pool.refs(), manager.model_pool.refs())

                # New builds pick up the saved pool immediately.
                started = client.post(
                    "/api/batches/b-1/sites/example.fr/build", json={}
                )
                self.assertEqual(started.status_code, 202, started.text)
                self.assertEqual(
                    started.json()["build"]["model"]["variant"], "max"
                )

                # Reset removes the override and returns to the startup env.
                reset = client.delete("/api/builds/config/models")
                self.assertEqual(reset.status_code, 200, reset.text)
                self.assertEqual(reset.json()["model_pool_source"], "env")
                self.assertFalse(reset.json()["model_pool_override"])
                self.assertEqual(
                    [model["variant"] for model in reset.json()["models"]],
                    ["high"],
                )
                self.assertIsNone(self.store.get_setting("build_model_pool"))

    def test_model_pool_settings_can_be_empty(self) -> None:
        manager = self._manager(FakeBuildAdapter(self.root))
        with self._client(manager) as client:
            response = client.put("/api/builds/config/models", json={"refs": []})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["models"], [])
            self.assertEqual(response.json()["model_pool_source"], "settings")
            self.assertEqual(self.store.get_setting("build_model_pool"), "")
            started = client.post(
                "/api/batches/b-1/sites/example.fr/build", json={}
            )
            self.assertEqual(started.status_code, 202, started.text)
            self.assertEqual(
                started.json()["build"]["model"],
                {"providerID": "opencode-go", "id": "deepseek-v4.1-flash", "variant": "high"},
            )

    def test_invalid_stored_model_pool_falls_back_to_env(self) -> None:
        self.store.set_setting("build_model_pool", "not-a-ref")
        self.store.set_setting(
            "build_model_default", "yjwd-gpt-enterprise/gpt-6.1-terra#medium"
        )
        env_pool = "opencode-go/deepseek-v4.1-flash#high"
        with mock.patch.dict(
            os.environ, {"ECOM_BUILD_MODEL_POOL": env_pool}, clear=False
        ):
            manager = self._manager(FakeBuildAdapter(self.root))
        self.assertEqual(manager.model_pool_source, "env")
        self.assertTrue(manager.model_pool_override)
        self.assertEqual(manager.model_pool.refs(), [env_pool])
        self.assertIsNone(manager.model_pool.default_ref)
        manager.reset_model_pool()
        self.assertFalse(manager.model_pool_override)
        self.assertIsNone(self.store.get_setting("build_model_pool"))
        self.assertIsNone(self.store.get_setting("build_model_default"))

    def test_model_pool_settings_write_is_read_only_guarded(self) -> None:
        app = create_app(
            self.root / "tasks.db",
            self.root / "out",
            self.rules,
            read_only=True,
        )
        with TestClient(app, headers=CLIENT_HEADERS) as client:
            response = client.put(
                "/api/builds/config/models",
                json={"refs": ["opencode-go/deepseek-v4.1-flash#high"]},
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["error"]["code"], "READ_ONLY")
            self.assertIsNone(self.store.get_setting("build_model_pool"))

    def test_pilot_rehearsal_validates_six_and_exports_ten(self) -> None:
        site = "pilot-fixture.test"
        origin = f"http://{site}"
        good_rule = yaml.safe_load(RULE_TEMPLATE.replace("__BASE__", origin))
        bad_rule = yaml.safe_load(RULE_TEMPLATE.replace("__BASE__", origin))
        bad_rule["discovery"]["link_selector"] = "a.product:not(:first-of-type)"
        adapter = FakeBuildAdapter(self.root, rule_payloads=[bad_rule, good_rule])
        fixture_rps = 50

        def run_fixture_validation(**options: Any) -> tuple[dict[str, Any], Path]:
            # This test exercises the complete build/export flow against the local fixture.
            options["per_domain_rps"] = fixture_rps
            return run_task(**options)

        with (
            mock.patch.dict(
                os.environ,
                {
                    "ECOM_BUILD_DISABLED": "0",
                    "ECOM_FETCH_PROXY": "",
                    "NO_PROXY": "127.0.0.1",
                    "no_proxy": "127.0.0.1",
                },
            ),
            mock.patch("ecom_crawler.builds.run_task", new=run_fixture_validation),
            fixture_server(products=10, proxy_origin=origin) as proxy,
        ):
            manager = BuildManager(
                self.store,
                self.root / "out",
                self.rules,
                adapter=adapter,
                model={"providerID": "fake", "id": "fixture"},
                default_proxy=proxy,
                max_products=6,
                validation_seconds=120,
                max_repair_rounds=1,
                repair_seconds=240,
                activation_mode="manual",
                skills_dir=self.root / "skills",
                dependency_policy=DependencyPolicy.empty(),
            )
            self.addCleanup(self._stop_manager, manager, adapter)
            with self._client(manager) as client:
                created = client.post(
                    "/api/batches",
                    json={"name": "Offline pilot", "market": "GB", "sites": [origin]},
                )
                self.assertEqual(created.status_code, 201, created.text)
                batch = created.json()["batch"]["batch_id"]
                site_path = f"/api/batches/{batch}/sites/{site}"
                started = client.post(
                    f"{site_path}/build",
                    json={"max_products": 6, "max_seconds": 600, "repair_rounds": 1},
                )
                self.assertEqual(started.status_code, 202, started.text)
                build_id = started.json()["build"]["build_id"]
                build = self._wait_ready(client, build_id, timeout=25)
                self.assertEqual(build["outcome"], "succeeded", build["error"])
                self.assertEqual(len(build["repairs"]), 1)
                self.assertTrue(build["repairs"][0]["resolved"])
                validation = build["validation"]
                self.assertEqual(validation["status"], "PASSED", validation)
                smoke = validation["candidate_smoke"]
                self.assertTrue(smoke["executed"])
                self.assertEqual(smoke["valid_products"], 6)
                self.assertEqual(smoke["failed_products"], 0)
                self.assertEqual(smoke["currencies"], {"GBP": 6})

                active = self.store.get_site_rule(site)
                self.assertIsNotNone(active)
                assert active is not None
                digest = hashlib.sha256((self.rules / active.path).read_bytes()).hexdigest()
                self.assertEqual(digest, active.sha256)
                self.assertEqual(active.rule_version, good_rule["rule_version"])
                site_payload = client.get(f"/api/batches/{batch}").json()["sites"][0]
                self.assertEqual(site_payload["readiness"], "ready")
                self.assertIn("已激活方案", site_payload["note"])
                trace = client.get(f"/api/builds/{build_id}/trace?format=json")
                self.assertEqual(trace.status_code, 200, trace.text)
                trace_data = trace.json()
                self.assertEqual(trace_data["build_id"], build_id)
                self.assertEqual(trace_data["validation"]["status"], "PASSED")
                self.assertEqual(len(trace_data["repairs"]), 1)

                submitted = client.post(
                    f"/api/batches/{batch}/start",
                    json={"limits": {"max_products": 10, "max_seconds": 180, "max_attempts": 2}},
                )
                self.assertEqual(submitted.status_code, 202, submitted.text)
                self.assertEqual(submitted.json()["skipped"], [])
                accepted = submitted.json()["accepted"]
                self.assertEqual(len(accepted), 1)
                task_id = accepted[0]["task_id"]
                queued = self.store.get_task(task_id)
                assert queued is not None
                self.assertEqual(queued.input.get("proxy"), proxy)
                worker = Worker(
                    self.store, out_root=self.root / "out", max_tasks=1, per_domain_rps=fixture_rps,
                )
                worker.run_once(poll_interval=0.05)
                self.assertEqual(worker.active_leases, {})
                self.assertEqual(adapter.started, [build_id])
                task = self.store.get_task(task_id)
                self.assertIsNotNone(task)
                assert task is not None
                self.assertEqual((task.state, task.outcome), ("FINISHED", "COMPLETED"), task)
                self.assertEqual((task.plan_version, task.rule_sha256), (active.rule_version, digest))
                batch_site = self.store.get_batch_site(batch, site)
                assert batch_site is not None
                self.assertEqual(batch_site.readiness, "ready")
                self.assertIn("执行完成", batch_site.note)

                export = client.get(f"/api/batches/{batch}/export")
                self.assertEqual(export.status_code, 200, export.text[:400])
                with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
                    manifest = json.loads(archive.read("batch.json"))
                    self.assertEqual(manifest["batch"]["batch_id"], batch)
                    self.assertEqual(manifest["sites"][0]["task_id"], task_id)
                    self.assertEqual(manifest["sites"][0]["export_status"], "complete")
                    task_dir = self.root / "out" / task_id
                    result_bytes = archive.read(f"sites/{site}/task-result.json")
                    csv_bytes = archive.read(f"sites/{site}/products.csv")
                    self.assertEqual(result_bytes, (task_dir / "task-result.json").read_bytes())
                    self.assertEqual(csv_bytes, (task_dir / "products.csv").read_bytes())
                counts = json.loads(result_bytes)["counts"]
                self.assertEqual(counts["valid_products"], 10)
                self.assertEqual(counts["failed_products"], 0)
                rows = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig")))
                self.assertEqual(
                    rows.fieldnames,
                    [
                        "name", "price_amount", "price_currency", "primary_image_url",
                        "description_html", "category", "brand", "attributes", "source_url",
                    ],
                )
                products = list(rows)
                self.assertCountEqual(
                    [row["name"] for row in products], [f"Product {i}" for i in range(1, 11)]
                )
                exported = {row["name"]: row for row in products}
                for i in range(1, 11):
                    with self.subTest(product=i):
                        row = exported[f"Product {i}"]
                        self.assertEqual((row["price_amount"], row["price_currency"]), ("10.00", "GBP"))
                        self.assertEqual(row["primary_image_url"], f"{origin}/img/{i}.jpg")
                        self.assertEqual(row["source_url"], f"{origin}/p{i}.html")
                        self.assertIn(f"Body {i}.", row["description_html"])
                        self.assertEqual(row["category"], "Fixtures")
                        self.assertEqual(row["brand"], "Fixture Brand")

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
            self.assertIn("for operator activation", brief)
            self.assertIn("Egress:", brief)
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

    def test_per_build_wall_clock_budget_times_out(self) -> None:
        adapter = FakeBuildAdapter(self.root, hang=True)
        manager = self._manager(adapter)
        site = self.store.get_batch_site("b-1", "example.fr")
        record = manager.start(self.batch, site, max_seconds=1)
        deadline = time.monotonic() + 8
        current = None
        while time.monotonic() < deadline:
            current = self.store.get_build(record.build_id)
            if current is not None and current.state == "FINISHED":
                break
            time.sleep(0.05)
        self.assertIsNotNone(current)
        self.assertEqual(current.state, "FINISHED", current)
        self.assertEqual(current.outcome, "failed", current)
        self.assertIn("wall-clock budget", current.error or "")
        self.assertIn("1s", current.error or "")
        self.assertIn(record.build_id, adapter.canceled)
        manager.shutdown()

    def test_per_build_budget_overrides_shorter_global_default(self) -> None:
        adapter = FakeBuildAdapter(self.root, hang=True)
        manager = self._manager(adapter, max_seconds=1)
        site = self.store.get_batch_site("b-1", "example.fr")
        record = manager.start(self.batch, site, max_seconds=4)
        time.sleep(2)
        current = self.store.get_build(record.build_id)
        self.assertIsNotNone(current)
        self.assertEqual(current.state, "RUNNING", current)
        self.assertNotIn(record.build_id, adapter.canceled)
        manager.shutdown()

    def test_total_wall_clock_budget_overrides_initial_turn_budget(self) -> None:
        adapter = FakeBuildAdapter(self.root, hang=True)
        manager = self._manager(adapter)
        site = self.store.get_batch_site("b-1", "example.fr")
        record = manager.start(self.batch, site, max_seconds=60, max_total_seconds=1)
        deadline = time.monotonic() + 8
        current = None
        while time.monotonic() < deadline:
            current = self.store.get_build(record.build_id)
            if current is not None and current.state == "FINISHED":
                break
            time.sleep(0.05)
        self.assertIsNotNone(current)
        self.assertEqual(current.state, "FINISHED", current)
        self.assertEqual(current.outcome, "failed", current)
        self.assertEqual(current.error_class, "budget", current)
        self.assertIn("total wall-clock budget", current.error or "")
        self.assertIn(record.build_id, adapter.canceled)
        manager.shutdown()

    def test_token_budget_stops_hanging_build(self) -> None:
        adapter = FakeBuildAdapter(self.root, hang=True)
        adapter.usage_payload = {"input": 600_000, "output": 10, "reasoning": 0}
        manager = self._manager(adapter)
        manager.usage_poll_seconds = 0.2
        site = self.store.get_batch_site("b-1", "example.fr")
        record = manager.start(
            self.batch,
            site,
            max_seconds=60,
            max_input_tokens=500_000,
            max_output_tokens=50_000,
        )
        deadline = time.monotonic() + 8
        current = None
        while time.monotonic() < deadline:
            current = self.store.get_build(record.build_id)
            if current is not None and current.state == "FINISHED":
                break
            time.sleep(0.05)
        self.assertIsNotNone(current)
        self.assertEqual(current.state, "FINISHED", current)
        self.assertEqual(current.outcome, "failed", current)
        self.assertEqual(current.error_class, "budget", current)
        self.assertIn("token budget", current.error or "")
        self.assertIn("input 600000/500000", current.error or "")
        self.assertIn(record.build_id, adapter.canceled)
        manager.shutdown()

    def test_dev_trace_enables_live_and_persisted_reasoning_by_default(self) -> None:
        env = {
            "ECOM_BUILD_DEV_TRACE": "1",
            "ECOM_BUILD_CAPTURE_REASONING": "",
            "ECOM_BUILD_PERSIST_REASONING": "",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            adapter = FakeBuildAdapter(self.root, hang=True)
            manager = self._manager(adapter)
            self.assertTrue(manager.reasoning_capture_enabled)
            self.assertTrue(manager.persist_reasoning_enabled)
            site = self.store.get_batch_site("b-1", "example.fr")
            record = manager.start(self.batch, site)
            self.assertTrue(record.request.get("capture_reasoning"))
            manager.shutdown()

    def test_explicit_reasoning_switches_override_dev_trace(self) -> None:
        env = {
            "ECOM_BUILD_DEV_TRACE": "1",
            "ECOM_BUILD_CAPTURE_REASONING": "0",
            "ECOM_BUILD_PERSIST_REASONING": "0",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            adapter = FakeBuildAdapter(self.root, hang=True)
            manager = self._manager(adapter)
            self.assertFalse(manager.reasoning_capture_enabled)
            self.assertFalse(manager.persist_reasoning_enabled)
            manager.shutdown()

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
            batch_before = client.get("/api/batches/b-1").json()
            site_before = next(
                item
                for item in batch_before["sites"]
                if item["site_key"] == "example.fr"
            )
            self.assertTrue(
                site_before["note"].startswith(
                    "候选方案：example-fr-build@2026.11.23-2，"
                )
            )
            self.store.update_batch_site(
                "b-1",
                "example.fr",
                note=(
                    "候选方案：example-fr-build@2026.11.23-9，"
                    "有界验证 6 条有效、0 失败；待人工激活"
                ),
            )
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
            self.assertTrue(candidate["validation"]["candidate_smoke"]["executed"])
            self.assertTrue(candidate["validation"]["regression"]["executed"])
            self.assertEqual(candidate["validation"]["regression"]["checked"], 2)
            self.assertEqual(candidate["validation"]["regression"]["regressions"], [])
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
            batch_after = client.get("/api/batches/b-1").json()
            site_after = next(
                item
                for item in batch_after["sites"]
                if item["site_key"] == "example.fr"
            )
            self.assertEqual(
                site_after["note"],
                "已激活方案：example-fr-build@2026.11.23-2",
            )

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

            def exported_task() -> str:
                response = client.get("/api/batches/b-1/export")
                self.assertEqual(response.status_code, 200, response.text)
                with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                    return json.loads(archive.read("batch.json"))["sites"][0]["task_id"]

            self.assertEqual(client.get("/api/batches/b-1").json()["status"], "RUNNING")
            self.assertEqual(exported_task(), "task-existing")
            replay = client.post(
                f"/api/feedback/{feedback_id}/rerun",
                json={"request_id": "rerun-1", "limits": {"max_products": 3, "max_urls": 5, "max_seconds": 60}},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(replay.status_code, 202, replay.text)
            self.assertFalse(replay.json()["created"])
            self.assertEqual(replay.json()["task"]["task_id"], rerun_task_id)

            self.store.update_task(rerun_task_id, state="FINISHED", outcome="FAILED")
            not_adopted = client.post(
                f"/api/feedback/{feedback_id}/resolve",
                json={"request_id": "resolve-failed", "resolution": "RESOLVED"},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(not_adopted.status_code, 409, not_adopted.text)
            self.assertEqual(exported_task(), "task-existing")

            self.store.update_task(
                rerun_task_id,
                state="FINISHED",
                outcome="COMPLETED",
                stop_reason="NATURAL_END",
            )
            self.assertEqual(exported_task(), "task-existing")
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
            self.assertEqual(exported_task(), rerun_task_id)
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
            batch_rollback = client.get("/api/batches/b-1").json()
            site_rollback = next(
                item
                for item in batch_rollback["sites"]
                if item["site_key"] == "example.fr"
            )
            self.assertEqual(
                site_rollback["note"],
                "已激活方案：example-fr-build@2026.11.23-1",
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

    def test_activation_rejects_candidate_without_regression(self) -> None:
        def validator(*_: Any, **__: Any) -> dict[str, Any]:
            return {
                "counts": {"valid_products": 2, "failed_products": 0},
                "outcome": "COMPLETED",
                "stop_reason": "NATURAL_END",
                "currencies": {"EUR": 2},
            }

        adapter = FakeBuildAdapter(
            self.root,
            rule_payloads=[
                rule_payload(version="2026.11.23-1"),
                rule_payload(version="2026.11.23-2"),
            ],
        )
        manager = self._manager(
            adapter, validator=validator, activation_mode="manual"
        )
        with self._client(manager) as client:
            first = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            ).json()["build"]
            self.assertEqual(
                self._wait_ready(client, first["build_id"])["outcome"],
                "succeeded",
            )
            repair = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={"mode": "repair"},
                headers=CLIENT_HEADERS,
            ).json()["build"]
            self.assertEqual(
                self._wait_ready(client, repair["build_id"])["outcome"],
                "succeeded",
            )
            site_rule = client.get("/api/sites/example.fr/rule").json()
            candidate = next(
                item
                for item in site_rule["candidates"]
                if item["rule_version"] == "2026.11.23-2"
            )
            self.assertEqual(candidate["validation_status"], "INCOMPLETE")
            self.assertFalse(candidate["validation"]["regression"]["executed"])
            blocked = client.post(
                "/api/sites/example.fr/rule/activate",
                json={
                    "request_id": "activate-incomplete",
                    "rule_version": "2026.11.23-2",
                    "expected_active_version": "2026.11.23-1",
                },
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(blocked.status_code, 409, blocked.text)
            self.assertEqual(
                blocked.json()["error"]["code"], "VALIDATION_REQUIRED"
            )
            self.assertEqual(
                client.get("/api/sites/example.fr/rule").json()["active"][
                    "rule_version"
                ],
                "2026.11.23-1",
            )

    def test_activation_rejects_price_regression(self) -> None:
        def validator(
            *_: Any, **kwargs: Any
        ) -> dict[str, Any]:
            price = "8.00" if kwargs.get("discover", True) else "10.00"
            samples = [
                {
                    "source_url": f"https://example.fr/p/{index}",
                    "name": f"Example product {index}",
                    "price_amount": price,
                    "price_currency": "EUR",
                    "primary_image_url": f"https://example.fr/{index}.jpg",
                    "description_html": (
                        f"<p>Example product {index} has a complete description.</p>"
                    ),
                }
                for index in (1, 2)
            ]
            return {
                "counts": {"valid_products": 2, "failed_products": 0},
                "outcome": "COMPLETED",
                "stop_reason": "NATURAL_END",
                "currencies": {"EUR": 2},
                "product_samples": samples,
            }

        adapter = FakeBuildAdapter(
            self.root,
            rule_payloads=[
                rule_payload(version="2026.11.23-1"),
                rule_payload(version="2026.11.23-2"),
            ],
        )
        manager = self._manager(
            adapter, validator=validator, activation_mode="manual"
        )
        with self._client(manager) as client:
            first = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            ).json()["build"]
            self.assertEqual(
                self._wait_ready(client, first["build_id"])["outcome"],
                "succeeded",
            )
            repair = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={"mode": "repair"},
                headers=CLIENT_HEADERS,
            ).json()["build"]
            self.assertEqual(
                self._wait_ready(client, repair["build_id"])["outcome"],
                "succeeded",
            )
            site_rule = client.get("/api/sites/example.fr/rule").json()
            candidate = next(
                item
                for item in site_rule["candidates"]
                if item["rule_version"] == "2026.11.23-2"
            )
            self.assertEqual(candidate["validation_status"], "FAILED")
            regressions = candidate["validation"]["regression"]["regressions"]
            self.assertTrue(
                any(item["field"] == "price_amount" for item in regressions)
            )
            blocked = client.post(
                "/api/sites/example.fr/rule/activate",
                json={
                    "request_id": "activate-regression",
                    "rule_version": "2026.11.23-2",
                    "expected_active_version": "2026.11.23-1",
                },
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(blocked.status_code, 409, blocked.text)
            self.assertEqual(
                blocked.json()["error"]["code"], "VALIDATION_FAILED"
            )
            self.assertEqual(
                client.get("/api/sites/example.fr/rule").json()["active"][
                    "rule_version"
                ],
                "2026.11.23-1",
            )

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
        self.assertIn("Do not fetch, print or read robots.txt", agents)
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
        with serve_http_fixture(server):
            note, sitemaps = _probe_robots(
                f"http://127.0.0.1:{server.server_port}/"
            )
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

    def test_two_repair_rounds_keep_earlier_round_unresolved(self) -> None:
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
            if validator_calls["count"] <= 1:
                return {
                    "counts": {"valid_products": 0, "failed_products": 2},
                    "outcome": "FAILED",
                    "stop_reason": "NATURAL_END",
                    "stop_detail": "injected validation failure 1",
                    "failure_samples": [
                        {
                            "url": "https://example.fr/p1",
                            "reason": "injected_fetch_failure",
                        }
                    ],
                    "currencies": {},
                }
            return {
                "counts": {"valid_products": 2, "failed_products": 0},
                "outcome": "COMPLETED",
                "stop_reason": "NATURAL_END",
                "currencies": {"EUR": 2},
            }

        adapter = FakeBuildAdapter(
            self.root,
            rule_payloads=[
                invalid_selector_payload(),
                rule_payload(),
                rule_payload(version="2026.11.23-3"),
            ],
        )
        manager = self._manager(
            adapter, validator=validator, max_repair_rounds=2
        )
        with self._client(manager) as client:
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={"repair_rounds": 2},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 202, response.text)
            build_id = response.json()["build"]["build_id"]
            result = self._wait_ready(client, build_id)
            self.assertEqual(result["outcome"], "succeeded", result["error"])
            self.assertEqual(result["repair_limit"], 2)
            self.assertEqual(result["repair_round"], 2)
            self.assertEqual(len(result["repairs"]), 2)
            self.assertFalse(result["repairs"][0]["resolved"])
            self.assertTrue(result["repairs"][1]["resolved"])
            self.assertIn("invalid CSS selector", result["repairs"][0]["error"])
            self.assertIn(
                "injected validation failure 1", result["repairs"][1]["error"]
            )
            self.assertEqual(validator_calls["count"], 2)
            self.assertEqual(len(adapter.continued), 2)
            self.assertIn("automatic repair round 1 of 2", adapter.continued[0][1])
            self.assertIn("automatic repair round 2 of 2", adapter.continued[1][1])
            self.assertIn("injected validation failure 1", adapter.continued[1][1])

            trace = client.get(f"/api/builds/{build_id}/trace?format=json").json()
            self.assertEqual(trace["repair_limit"], 2)
            self.assertEqual(len(trace["repairs"]), 2)
            self.assertFalse(trace["repairs"][0]["resolved"])
            self.assertTrue(trace["repairs"][1]["resolved"])

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

    def test_target_catalog_patches_scope_and_accepts_product_source(self) -> None:
        adapter = FakeBuildAdapter(
            self.root, rule_payloads=[shopify_rule_payload()]
        )
        manager = self._manager(adapter)
        with self._client(manager) as client:
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={
                    "catalog_scope": "target",
                    "catalog_products": 10,
                    "repair_rounds": 0,
                },
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 202, response.text)
            build_id = response.json()["build"]["build_id"]
            result = self._wait_ready(client, build_id)
            self.assertEqual(result["outcome"], "succeeded", result["error"])
            self.assertEqual(result["catalog"]["catalog_scope"], "target")
            self.assertEqual(result["catalog"]["catalog_products"], 10)
            self.assertEqual(
                result["validation"]["products_budget"],
                6,
            )
            batch = client.get("/api/batches/b-1").json()
            site = batch["sites"][0]
            rule_path = self.rules / site["rule"]["path"]
            payload = yaml.safe_load(rule_path.read_text(encoding="utf-8"))
            self.assertGreaterEqual(payload["scope"]["max_products"], 10)
            self.assertEqual(payload["product_source"]["type"], "shopify_json")
            brief = (
                Path(result["workspace"]) / "input" / "build-brief.md"
            ).read_text(encoding="utf-8")
            self.assertIn("bounded target", brief)
            self.assertIn("product_source", brief)

    def test_target_catalog_rejects_entry_links_only(self) -> None:
        adapter = FakeBuildAdapter(self.root)
        manager = self._manager(adapter)
        with self._client(manager) as client:
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={
                    "catalog_scope": "target",
                    "catalog_products": 10,
                    "repair_rounds": 0,
                },
                headers=CLIENT_HEADERS,
            )
            build_id = response.json()["build"]["build_id"]
            result = self._wait_ready(client, build_id)
            self.assertEqual(result["outcome"], "failed")
            self.assertIn("target catalog build requires", result["error"] or "")

    def test_regression_skips_html_to_product_source_switch(self) -> None:
        adapter = FakeBuildAdapter(self.root)
        manager = self._manager(adapter)
        source_path = self.rules / "source-html.yaml"
        source_path.write_text(
            yaml.safe_dump(rule_payload(), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        new_rule = mock.Mock(product_source={"type": "shopify_json"})
        with mock.patch.object(
            manager, "_source_rule_path", return_value=source_path
        ):
            result = manager._run_regression(
                mock.Mock(mode="repair"),
                None,
                [{"source_url": "https://example.fr/p/1"}],
                self.root / "regression-switch",
                None,
                {},
                has_parent=True,
                new_rule=new_rule,
            )
        self.assertFalse(result["executed"])
        self.assertFalse(result["required"])
        self.assertEqual(result["regressions"], [])
        self.assertIn("product_source", result["reason"])

    def test_reinstall_same_build_rule_version_is_idempotent(self) -> None:
        adapter = FakeBuildAdapter(self.root)
        manager = self._manager(adapter)
        rule_path = self.root / "idempotent-rule.yaml"
        rule_path.write_text(
            yaml.safe_dump(
                rule_payload(version="2026.11.24-9"),
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        record = mock.Mock(
            build_id="build-idempotent",
            batch_id="b-1",
            site_key="example.fr",
            mode="build",
            proxy=None,
            feedback_id=None,
        )
        counts = {"valid_products": 2, "failed_products": 0}
        task_result = {
            "stop_reason": "NATURAL_END",
            "outcome": "COMPLETED",
            "currencies": {"EUR": 2},
        }
        first = manager._install_rule(rule_path, record, counts, task_result)
        second = manager._install_rule(rule_path, record, counts, task_result)
        self.assertEqual(first[2], second[2])
        self.assertEqual(first[3], second[3])
        stored = self.store.get_rule_version("example-fr-build", "2026.11.24-9")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.sha256, first[3])

    def test_browser_rule_raises_host_validation_budget(self) -> None:
        payload = rule_payload()
        payload["fetch"]["default_engine"] = "browser"
        payload["fetch"]["browser"] = {"headless": True}
        seen: dict[str, int] = {}

        def validator(
            rule_path: Path,
            work_dir: Path,
            max_products: int,
            max_seconds: int,
            proxy: str | None = None,
            **_: Any,
        ) -> dict[str, Any]:
            seen["max_products"] = max_products
            seen["max_seconds"] = max_seconds
            return {
                "counts": {"valid_products": 2, "failed_products": 0},
                "outcome": "COMPLETED",
                "stop_reason": "NATURAL_END",
                "currencies": {"EUR": 2},
            }

        adapter = FakeBuildAdapter(self.root, rule_payloads=[payload])
        manager = self._manager(
            adapter,
            validator=validator,
            browser_validation_seconds=30,
        )
        with self._client(manager) as client:
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={"max_products": 6, "max_seconds": 60, "repair_rounds": 0},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 202, response.text)
            build_id = response.json()["build"]["build_id"]
            result = self._wait_ready(client, build_id)
            self.assertEqual(result["outcome"], "succeeded", result["error"])
            self.assertEqual(seen["max_products"], 6)
            self.assertEqual(seen["max_seconds"], 30)
            self.assertEqual(result["validation"]["products_budget"], 6)
            self.assertEqual(result["validation"]["seconds_budget"], 30)

    def test_stealth_rule_counts_as_browser_for_validation_budget(self) -> None:
        rule = mock.Mock(
            kind="declarative",
            fetch={"default_engine": "stealth"},
        )
        self.assertTrue(_rule_needs_browser(rule))
        rule = mock.Mock(
            kind="declarative",
            fetch={
                "default_engine": "static",
                "per_url_type": {"product": {"engine": "stealth"}},
            },
        )
        self.assertTrue(_rule_needs_browser(rule))

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

    def test_build_timeline_merges_live_tool_input_and_output(self) -> None:
        from types import SimpleNamespace

        events = [
            SimpleNamespace(
                type="tool_started",
                data={"tool": "call_1", "call_id": "call_1"},
                created_at="2026-11-27T04:00:01Z",
            ),
            SimpleNamespace(
                type="tool_input",
                data={
                    "tool": "read",
                    "call_id": "call_1",
                    "input": {"path": "work/AGENTS.md"},
                },
                created_at="2026-11-27T04:00:02Z",
            ),
            SimpleNamespace(
                type="tool_finished",
                data={
                    "tool": "read",
                    "call_id": "call_1",
                    "status": "success",
                    "output": "read ok",
                },
                created_at="2026-11-27T04:00:03Z",
            ),
        ]
        timeline, truncated = _live_timeline(events)
        self.assertFalse(truncated)
        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0]["name"], "read")
        self.assertEqual(timeline[0]["input"], {"path": "work/AGENTS.md"})
        self.assertEqual(timeline[0]["output"], "read ok")
        self.assertEqual(timeline[0]["status"], "success")

    def test_build_timeline_deduplicates_final_reasoning_event(self) -> None:
        from types import SimpleNamespace

        events = [
            SimpleNamespace(
                type="reasoning",
                data={"delta": "first "},
                created_at="2026-11-25T04:00:01Z",
            ),
            SimpleNamespace(
                type="reasoning",
                data={"delta": "second"},
                created_at="2026-11-25T04:00:02Z",
            ),
            SimpleNamespace(
                type="reasoning",
                data={"delta": "first second"},
                created_at="2026-11-25T04:00:02Z",
            ),
            SimpleNamespace(
                type="tool_started",
                data={"tool": "read"},
                created_at="2026-11-25T04:00:03Z",
            ),
        ]
        timeline, truncated = _live_timeline(events)
        self.assertFalse(truncated)
        self.assertEqual([item["kind"] for item in timeline], ["reasoning", "tool"])
        self.assertEqual(timeline[0]["text"], "first second")

    def test_two_builds_run_independently_and_release_slots(self) -> None:
        adapters: list[FakeBuildAdapter] = []

        def new_adapter() -> FakeBuildAdapter:
            adapter = FakeBuildAdapter(self.root, hang=True)
            adapters.append(adapter)
            return adapter

        manager = self._manager(None, adapter_factory=new_adapter, max_concurrent=2)
        targets = ["https://first.example.fr/", "https://second.example.fr/", "https://third.example.fr/"]
        with self._client(manager) as client:
            batch = client.post("/api/batches", json={
                "name": "Independent builds", "market": "FR",
                "collection_mode": "formal", "sites": targets,
            }).json()["batch"]
            prefix = f"/api/batches/{batch['batch_id']}/sites"
            records = []
            for site in batch["sites"]:
                response = client.post(f"{prefix}/{site['site_key']}/build")
                self.assertEqual(response.status_code, 202, response.text)
                records.append(response.json()["build"])
            first, second, third = [record["build_id"] for record in records]
            self.assertEqual([record["state"] for record in records], ["RUNNING", "RUNNING", "QUEUED"])
            self.assertEqual([adapter.started for adapter in adapters], [[first], [second]])
            response = client.post(f"/api/builds/{first}/pause")
            self.assertEqual(response.status_code, 202, response.text)
            self.assertEqual(self.store.get_build(second).state, "RUNNING")
            response = client.post(f"/api/builds/{first}/cancel")
            self.assertEqual(response.status_code, 202, response.text)
            self._wait_for_build_state(client, third, "RUNNING")
            self.assertEqual(self.store.get_build(first).state, "CANCELLED")
            self.assertEqual(self.store.get_build(second).state, "RUNNING")
            self.assertEqual(adapters[0].canceled, [first])
            self.assertTrue(adapters[0].shutdown_called)
            self.assertEqual(adapters[1].canceled, [])
            self.assertEqual(adapters[2].started, [third])
        self.assertTrue(all(adapter.shutdown_called for adapter in adapters))
        self.assertEqual(self.store.get_build(second).outcome, "interrupted")
        self.assertEqual(self.store.get_build(third).outcome, "interrupted")

    def test_second_build_waits_in_queue_then_starts(self) -> None:
        gate = threading.Event()
        adapter = FakeBuildAdapter(
            self.root,
            rule_payloads=[
                rule_payload("example.fr"),
                rule_payload(
                    "example2.fr",
                    version="2026.11.23-2",
                    rule_id="example2-fr-build",
                ),
            ],
            gate=gate,
        )
        manager = self._manager(adapter)
        self.store.add_batch_sites(
            [
                BatchSite(
                    batch_id="b-1",
                    site_key="example2.fr",
                    domain="example2.fr",
                    input_value="https://example2.fr/",
                    readiness="needs_onboarding",
                )
            ]
        )
        with self._client(manager) as client:
            first = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={"max_products": 3},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(first.status_code, 202, first.text)
            first_build = first.json()["build"]
            self.assertEqual(first_build["state"], "RUNNING")

            second = client.post(
                "/api/batches/b-1/sites/example2.fr/build",
                json={"max_products": 3},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(second.status_code, 202, second.text)
            second_build = second.json()["build"]
            self.assertEqual(second_build["state"], "QUEUED")
            self.assertEqual(second_build["queue_position"], 1)
            self.assertEqual(adapter.started, [first_build["build_id"]])

            queued = self.store.get_build(second_build["build_id"])
            assert queued is not None
            self.assertEqual(queued.request["max_products"], 3)
            self.assertEqual(queued.request["catalog"]["catalog_scope"], "sample")

            gate.set()
            first_done = self._wait_ready(client, first_build["build_id"])
            self.assertEqual(first_done["outcome"], "succeeded", first_done.get("error"))
            second_done = self._wait_ready(client, second_build["build_id"])
            self.assertEqual(
                second_done["outcome"], "succeeded", second_done.get("error")
            )
            self.assertEqual(
                adapter.started,
                [first_build["build_id"], second_build["build_id"]],
            )

    def test_cancel_queued_build_releases_site_and_starts_next(self) -> None:
        gate = threading.Event()
        adapter = FakeBuildAdapter(
            self.root,
            rule_payloads=[
                rule_payload("example.fr"),
                rule_payload("example3.fr", version="2026.11.23-2", rule_id="example3-fr-build"),
            ],
            gate=gate,
        )
        manager = self._manager(adapter)
        self.store.add_batch_sites(
            [
                BatchSite(
                    batch_id="b-1",
                    site_key="example2.fr",
                    domain="example2.fr",
                    input_value="https://example2.fr/",
                    readiness="needs_onboarding",
                ),
                BatchSite(
                    batch_id="b-1",
                    site_key="example3.fr",
                    domain="example3.fr",
                    input_value="https://example3.fr/",
                    readiness="needs_onboarding",
                ),
            ]
        )
        with self._client(manager) as client:
            first = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            ).json()["build"]
            second = client.post(
                "/api/batches/b-1/sites/example2.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            ).json()["build"]
            third = client.post(
                "/api/batches/b-1/sites/example3.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            ).json()["build"]
            self.assertEqual(second["state"], "QUEUED")
            self.assertEqual(second["queue_position"], 1)
            self.assertEqual(third["state"], "QUEUED")
            self.assertEqual(third["queue_position"], 2)

            canceled = client.post(
                f"/api/builds/{second['build_id']}/cancel",
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(canceled.status_code, 202, canceled.text)
            self.assertEqual(canceled.json()["build"]["state"], "CANCELLED")
            site = self.store.get_batch_site("b-1", "example2.fr")
            assert site is not None
            self.assertEqual(site.readiness, "needs_onboarding")
            remaining = client.get(f"/api/builds/{third['build_id']}").json()["build"]
            self.assertEqual(remaining["queue_position"], 1)

            gate.set()
            self.assertEqual(
                self._wait_ready(client, first["build_id"])["outcome"], "succeeded"
            )
            done = self._wait_ready(client, third["build_id"])
            self.assertEqual(done["outcome"], "succeeded", done.get("error"))
            self.assertEqual(
                adapter.started, [first["build_id"], third["build_id"]]
            )

    def test_reconcile_resumes_queued_build_after_restart(self) -> None:
        gate = threading.Event()
        adapter = FakeBuildAdapter(
            self.root,
            rule_payloads=[
                rule_payload("example.fr"),
                rule_payload(
                    "example2.fr",
                    version="2026.11.23-2",
                    rule_id="example2-fr-build",
                ),
            ],
            gate=gate,
        )
        manager = self._manager(adapter)
        self.store.add_batch_sites(
            [
                BatchSite(
                    batch_id="b-1",
                    site_key="example2.fr",
                    domain="example2.fr",
                    input_value="https://example2.fr/",
                    readiness="needs_onboarding",
                )
            ]
        )
        with self._client(manager) as client:
            first = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            ).json()["build"]
            second = client.post(
                "/api/batches/b-1/sites/example2.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            ).json()["build"]
            self.assertEqual(second["state"], "QUEUED")
        manager.shutdown()

        interrupted = self.store.get_build(first["build_id"])
        assert interrupted is not None
        self.assertEqual(interrupted.state, "FINISHED")
        queued = self.store.get_build(second["build_id"])
        assert queued is not None
        self.assertEqual(queued.state, "QUEUED")
        site = self.store.get_batch_site("b-1", "example2.fr")
        assert site is not None
        self.assertEqual(site.readiness, "building")

        restarted_adapter = FakeBuildAdapter(
            self.root,
            rule_payloads=[
                rule_payload(
                    "example2.fr",
                    version="2026.11.23-2",
                    rule_id="example2-fr-build",
                )
            ],
        )
        restarted = self._manager(restarted_adapter)
        with self._client(restarted) as client:
            done = self._wait_ready(client, second["build_id"])
            self.assertEqual(done["outcome"], "succeeded", done.get("error"))
        self.assertEqual(restarted_adapter.started, [second["build_id"]])

    def test_queued_repair_fails_when_source_rule_changes(self) -> None:
        gate = threading.Event()
        adapter = FakeBuildAdapter(
            self.root,
            rule_payloads=[
                rule_payload("example.fr"),
                rule_payload(
                    "example2.fr",
                    version="2026.11.23-2",
                    rule_id="example2-fr-build",
                ),
            ],
            gate=gate,
        )
        manager = self._manager(adapter)
        self.store.add_batch_sites(
            [
                BatchSite(
                    batch_id="b-1",
                    site_key="example2.fr",
                    domain="example2.fr",
                    input_value="https://example2.fr/",
                    readiness="needs_onboarding",
                )
            ]
        )
        with self._client(manager) as client:
            built = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            ).json()["build"]
            gate.set()
            self.assertEqual(self._wait_ready(client, built["build_id"])["outcome"], "succeeded")
            gate.clear()

            blocking = client.post(
                "/api/batches/b-1/sites/example2.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            ).json()["build"]
            self._wait_for_build_state(client, blocking["build_id"], "RUNNING")
            repair = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={"mode": "repair", "reason": "queued repair"},
                headers=CLIENT_HEADERS,
            ).json()["build"]
            self.assertEqual(repair["state"], "QUEUED")

            site = self.store.get_batch_site("b-1", "example.fr")
            assert site is not None and site.rule_path
            rule_file = self.rules / site.rule_path
            rule_file.write_text(
                rule_file.read_text(encoding="utf-8") + "\n# changed while queued\n",
                encoding="utf-8",
            )

            canceled = client.post(
                f"/api/builds/{blocking['build_id']}/cancel",
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(canceled.status_code, 202, canceled.text)
            failed = self._wait_ready(client, repair["build_id"])
            self.assertEqual(failed["state"], "FINISHED")
            self.assertEqual(failed["outcome"], "failed")
            self.assertIn("源规则文件在排队期间发生变化", failed["error"] or "")
            site = self.store.get_batch_site("b-1", "example.fr")
            assert site is not None
            self.assertEqual(site.readiness, "ready")
            self.assertEqual(site.rule_path, rule_file.name)

    def test_continue_rejected_while_another_build_runs(self) -> None:
        gate = threading.Event()
        adapter = FakeBuildAdapter(self.root, write_rule=False, gate=gate)
        manager = self._manager(adapter, max_repair_rounds=0)
        self.store.add_batch_sites(
            [
                BatchSite(
                    batch_id="b-1",
                    site_key="example2.fr",
                    domain="example2.fr",
                    input_value="https://example2.fr/",
                    readiness="needs_onboarding",
                )
            ]
        )
        with self._client(manager) as client:
            failed = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            ).json()["build"]
            gate.set()
            failed_result = self._wait_ready(client, failed["build_id"])
            self.assertEqual(failed_result["outcome"], "failed")
            gate.clear()

            running = client.post(
                "/api/batches/b-1/sites/example2.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            ).json()["build"]
            self._wait_for_build_state(client, running["build_id"], "RUNNING")

            response = client.post(
                f"/api/builds/{failed['build_id']}/continue",
                json={
                    "request_id": "continue-busy",
                    "message": "fix the failed rule",
                },
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()["error"]["code"], "BUILD_CONFLICT")
            self.assertIn("another build is still active", response.text)

            cancelled = client.post(
                f"/api/builds/{running['build_id']}/cancel",
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(cancelled.status_code, 202, cancelled.text)
            self._wait_for_build_state(client, running["build_id"], "CANCELLED")

    def test_shutdown_marks_build_interrupted_and_continue_reloads_session(self) -> None:
        adapter = FakeBuildAdapter(self.root, hang=True)
        manager = self._manager(adapter)
        with self._client(manager) as client:
            response = client.post(
                "/api/batches/b-1/sites/example.fr/build",
                json={},
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 202, response.text)
            build_id = response.json()["build"]["build_id"]
            self.assertEqual(response.json()["build"]["state"], "RUNNING")
        manager.shutdown()

        record = self.store.get_build(build_id)
        assert record is not None
        self.assertEqual(record.state, "FINISHED")
        self.assertEqual(record.outcome, "interrupted")
        self.assertIn("会话已保留", record.error or "")
        self.assertEqual(record.error_class, "service_stop")
        site = self.store.get_batch_site("b-1", "example.fr")
        assert site is not None
        self.assertEqual(site.readiness, "needs_onboarding")
        self.assertEqual(adapter.detached, [build_id])

        restarted_adapter = FakeBuildAdapter(
            self.root, persisted=dict(adapter.sessions)
        )
        restarted = self._manager(restarted_adapter)
        with self._client(restarted) as client:
            response = client.post(
                f"/api/builds/{build_id}/continue",
                json={
                    "request_id": "continue-after-restart",
                    "message": "continue after restart",
                },
                headers=CLIENT_HEADERS,
            )
            self.assertEqual(response.status_code, 202, response.text)
            done = self._wait_ready(client, build_id)
            self.assertEqual(done["outcome"], "succeeded", done.get("error"))
            self.assertIsNone(done["error_class"])
        self.assertEqual(restarted_adapter.adopted, [build_id])
        self.assertEqual(restarted_adapter.continued[0][1], "continue after restart")
        self.assertTrue(list(self.rules.glob("*.yaml")))

    def test_reconcile_finalizes_finished_agent_workspace_without_prompt(self) -> None:
        workspace = self.root / "out" / "builds" / "build-finished"
        plan = workspace / "out" / "plan"
        plan.mkdir(parents=True)
        (plan / "rule.yaml").write_text(
            yaml.safe_dump(rule_payload(), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        (workspace / "out" / "result.json").write_text(
            json.dumps(
                {
                    "build_id": "build-finished",
                    "state": "FINISHED",
                    "outcome": "succeeded",
                }
            ),
            encoding="utf-8",
        )
        (workspace / "out" / "session.ndjson").write_text(
            json.dumps(
                {
                    "type": "finished",
                    "source_type": "session.execution.succeeded",
                    "session_id": "ses_finished",
                    "data": {"outcome": "succeeded"},
                    "created_at": utc_now(),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.store.create_build(
            BuildRecord(
                build_id="build-finished",
                batch_id="b-1",
                site_key="example.fr",
                state="VALIDATING",
                session_id="ses_finished",
                workspace=str(workspace),
            )
        )
        self.store.update_batch_site(
            "b-1",
            "example.fr",
            readiness="building",
            build_id="build-finished",
            note="验证中",
        )
        calls: list[str] = []

        def validator(
            rule_path: Path,
            work_dir: Path,
            max_products: int,
            max_seconds: int,
            proxy: str | None = None,
            **_: Any,
        ) -> dict[str, Any]:
            calls.append(str(rule_path))
            return {
                "counts": {"valid_products": 2, "failed_products": 0},
                "outcome": "COMPLETED",
                "stop_reason": "NATURAL_END",
                "currencies": {"EUR": 2},
            }

        adapter = FakeBuildAdapter(self.root)
        manager = self._manager(adapter, validator=validator)
        interrupted = manager.reconcile()
        self.assertEqual(interrupted, [])
        deadline = time.monotonic() + 10
        record = self.store.get_build("build-finished")
        while time.monotonic() < deadline:
            record = self.store.get_build("build-finished")
            if record is not None and record.state == "FINISHED":
                break
            time.sleep(0.05)
        assert record is not None
        self.assertEqual(record.state, "FINISHED")
        self.assertEqual(record.outcome, "succeeded", record.error)
        self.assertIsNone(record.error_class)
        self.assertEqual(len(calls), 1)
        self.assertEqual(adapter.prompts, [])
        self.assertTrue(list(self.rules.glob("*.yaml")))

    def test_batch_onboarding_resumes_after_activation_or_enqueue(self) -> None:
        for after_enqueue in (False, True):
            with self.subTest(after_enqueue=after_enqueue):
                suffix = "after" if after_enqueue else "before"
                domain = f"{suffix}.example.fr"
                rule = listing_rule_payload(domain)
                rule["rule_id"] = f"{suffix}-build"
                adapter = FakeBuildAdapter(self.root, rule_payloads=[rule])
                manager = self._manager(adapter)
                fault = threading.Event()
                original_enqueue = self.store.create_task_for_site

                def enqueue(
                    *args: Any, commit: bool = after_enqueue,
                    original: Any = original_enqueue, interrupted: threading.Event = fault,
                    **kwargs: Any,
                ) -> bool:
                    if commit:
                        original(*args, **kwargs)
                    interrupted.set()
                    raise RuntimeError("injected interruption at automatic enqueue")

                with self._client(manager) as client:
                    batch = client.post("/api/batches", json={
                        "name": suffix, "market": "FR", "collection_mode": "formal",
                        "sites": [f"https://{domain}/"],
                    }).json()["batch"]
                    path = f"/api/batches/{batch['batch_id']}"
                    with (
                        mock.patch.object(self.store, "create_task_for_site", enqueue),
                        self.assertLogs("ecom_crawler.builds", level="ERROR") as messages,
                    ):
                        start = client.post(f"{path}/start", json={"onboard": True})
                        self.assertEqual(start.status_code, 202, start.text)
                        build_id = start.json()["onboarding"][0]["build_id"]
                        self.assertTrue(fault.wait(10), self.store.get_build(build_id))
                        # The watcher logs the fault before shutdown discards its thread.
                        watcher = manager._watchers.get(build_id)
                        if watcher is not None:
                            watcher.join(timeout=5)
                    self.assertTrue(any("build watcher failed" in item for item in messages.output))
                    existing_tasks = self.store.list_batch_tasks(batch["batch_id"])
                    self.assertEqual(len(existing_tasks), int(after_enqueue))
                    activation = self.store.get_activation_by_request(f"{build_id}-activate")
                    self.assertIsNotNone(activation)

                validator = mock.Mock(side_effect=AssertionError("validation already completed"))
                restarted_adapter = FakeBuildAdapter(self.root)
                new_manager = self._manager(restarted_adapter, validator=validator)
                with self._client(new_manager) as client:
                    result = self._wait_ready(client, build_id)
                    self.assertEqual(result["outcome"], "succeeded", result.get("error"))
                    self.assertEqual(result["validation"]["status"], "PASSED")
                    start = client.post(f"{path}/start", json={"onboard": True})
                    self.assertEqual(start.json()["accepted"], [])
                    tasks = self.store.list_batch_tasks(batch["batch_id"])
                    self.assertEqual(len(tasks), 1)
                    self.assertEqual(tasks[0].rule_sha256, activation.to_sha256)
                    if after_enqueue:
                        self.assertEqual(tasks[0].task_id, existing_tasks[0].task_id)
                self.assertEqual(
                    self.store.get_activation_by_request(f"{build_id}-activate"), activation
                )
                validator.assert_not_called()
                self.assertEqual(restarted_adapter.prompts, [])

    def test_reconcile_finishes_both_host_validations_after_lowering_capacity(self) -> None:
        build_ids = []
        for index in range(2):
            domain = f"recovery-{index}.example.fr"
            build_id = f"recover-{index}"
            build_ids.append(build_id)
            workspace = self.root / build_id
            plan = workspace / "out" / "plan"
            plan.mkdir(parents=True)
            (plan / "rule.yaml").write_text(
                yaml.safe_dump(rule_payload(domain, rule_id=build_id)), encoding="utf-8",
            )
            self.store.add_batch_sites([BatchSite(
                batch_id="b-1", site_key=domain, domain=domain,
                input_value=f"https://{domain}/", readiness="building", build_id=build_id,
            )])
            self.store.create_build(BuildRecord(
                build_id=build_id, batch_id="b-1", site_key=domain,
                state="VALIDATING", session_id=f"ses_{build_id}", workspace=str(workspace),
            ))
        adapters: list[FakeBuildAdapter] = []

        def new_adapter() -> FakeBuildAdapter:
            adapter = FakeBuildAdapter(self.root)
            adapters.append(adapter)
            return adapter

        manager = self._manager(None, adapter_factory=new_adapter, max_concurrent=1)
        with self._client(manager) as client:
            for build_id in build_ids:
                result = self._wait_ready(client, build_id)
                self.assertEqual(result["outcome"], "succeeded", result.get("error"))
                self.assertEqual(result["validation"]["status"], "PASSED")
        self.assertEqual(len(adapters), 2)
        self.assertTrue(all(adapter.shutdown_called and not adapter.prompts for adapter in adapters))

    def test_reconcile_marks_session_backed_build_interrupted(self) -> None:
        workspace = self.root / "out" / "builds" / "build-resumable"
        (workspace / "out").mkdir(parents=True)
        self.store.create_build(
            BuildRecord(
                build_id="build-resumable",
                batch_id="b-1",
                site_key="example.fr",
                state="RUNNING",
                session_id="ses_resumable",
                workspace=str(workspace),
            )
        )
        self.store.update_batch_site(
            "b-1",
            "example.fr",
            readiness="building",
            build_id="build-resumable",
            note="构建中",
        )
        adapter = FakeBuildAdapter(self.root)
        manager = self._manager(adapter)
        interrupted = manager.reconcile()
        self.assertEqual(interrupted, ["build-resumable"])
        record = self.store.get_build("build-resumable")
        assert record is not None
        self.assertEqual(record.state, "FINISHED")
        self.assertEqual(record.outcome, "interrupted")
        self.assertEqual(record.error_class, "service_restart")
        self.assertIn("会话已保留", record.error or "")
        described = manager.describe("build-resumable")
        self.assertTrue(described["recoverable"])

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


class DuplicateProductSampleTests(unittest.TestCase):
    def test_rejects_identical_names(self) -> None:
        samples = [
            {"name": "Premier Angling", "primary_image_url": f"https://x/{i}.jpg"}
            for i in range(3)
        ]
        error = _duplicate_product_sample_error(samples)
        self.assertIn("share name", error or "")

    def test_rejects_identical_images(self) -> None:
        samples = [
            {"name": f"Product {i}", "primary_image_url": "https://x/avatar.jpg"}
            for i in range(3)
        ]
        error = _duplicate_product_sample_error(samples)
        self.assertIn("share primary image", error or "")

    def test_allows_distinct_or_short_samples(self) -> None:
        self.assertIsNone(
            _duplicate_product_sample_error(
                [{"name": "Same"}, {"name": "Same"}]
            )
        )
        self.assertIsNone(
            _duplicate_product_sample_error(
                [
                    {"name": "A", "primary_image_url": "https://x/a.jpg"},
                    {"name": "B", "primary_image_url": "https://x/b.jpg"},
                    {"name": "C", "primary_image_url": "https://x/c.jpg"},
                ]
            )
        )


if __name__ == "__main__":
    unittest.main()
