from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest import mock

from ecom_crawler.harness.adapter import (
    HarnessStateError,
    HarnessUnsupportedError,
    OpenCodeHttpAdapter,
)
from ecom_crawler.harness.dependencies import DependencyPolicy
from ecom_crawler.harness.events import normalize_event
from ecom_crawler.harness.models import BuildTask
from ecom_crawler.harness.opencode import (
    OpenCodeClient,
    OpenCodeServer,
    child_environment,
)
from ecom_crawler.harness.workspace import BuildWorkspace
from tests.support import serve_http_fixture

PASSWORD = "test-password"
AUTH = "Basic " + base64.b64encode(f"opencode:{PASSWORD}".encode()).decode()
SESSION_ID = "ses_test"


class FakeState:
    def __init__(self) -> None:
        self.session: dict[str, Any] | None = None
        self.prompt: str | None = None
        self.permissions: list[dict[str, Any]] = []
        self.decisions: list[tuple[str, str]] = []
        self.interrupts = 0
        self.deleted = 0
        self.events_sent = 0
        self.lock = threading.Lock()


class FakeHandler(BaseHTTPRequestHandler):
    state: FakeState

    def log_message(self, format: str, *args: object) -> None:
        return

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == AUTH

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        if not self._authorized():
            self._json(401, {"_tag": "UnauthorizedError", "message": "auth"})
            return
        if self.path == "/api/info":
            self._json(200, {"version": "test-1.0", "pid": 1, "hostname": "test"})
            return
        if self.path == f"/api/session/{SESSION_ID}":
            self._json(200, {"data": self.state.session})
            return
        if self.path == f"/api/session/{SESSION_ID}/permission":
            self._json(200, {"data": self.state.permissions})
            return
        if self.path == "/api/event":
            self._events()
            return
        self._json(404, {"_tag": "NotFound", "message": self.path})

    def do_POST(self) -> None:
        if not self._authorized():
            self._json(401, {"_tag": "UnauthorizedError", "message": "auth"})
            return
        if self.path == "/api/session":
            body = self._body()
            self.state.session = {
                "id": SESSION_ID,
                "projectID": "project-test",
                "cost": 0,
                "tokens": {
                    "input": 0,
                    "output": 0,
                    "reasoning": 0,
                    "cache": {"read": 0, "write": 0},
                },
                "time": {"created": 1, "updated": 1},
                "title": body.get("title"),
                "location": body.get("location"),
                "model": body.get("model"),
                "permissions": body.get("permissions"),
            }
            self._json(200, {"data": self.state.session})
            return
        if self.path == f"/api/session/{SESSION_ID}/prompt":
            body = self._body()
            self.state.prompt = str(body.get("text") or "")
            self._json(
                200,
                {
                    "data": {
                        "id": "msg_1",
                        "sessionID": SESSION_ID,
                        "type": "user",
                        "time": {"created": 2},
                        "payload": {"text": self.state.prompt},
                        "delivery": "steer",
                    }
                },
            )
            return
        if self.path == f"/api/session/{SESSION_ID}/generate":
            if self._body() != {"prompt": "Reply OK."}:
                self._json(400, {"message": "unexpected probe request"})
                return
            self._json(200, {"data": {"text": "OK", "tokens": {"output": 1}}})
            return
        if self.path == f"/api/session/{SESSION_ID}/permission":
            body = self._body()
            request = {
                "id": "perm_1",
                "sessionID": SESSION_ID,
                "action": body.get("action"),
                "resources": body.get("resources") or [],
            }
            self.state.permissions = [request]
            self._json(200, {"data": {"id": "perm_1", "effect": "ask"}})
            return
        if self.path == f"/api/session/{SESSION_ID}/permission/perm_1/reply":
            body = self._body()
            self.state.decisions.append(("perm_1", str(body.get("decision"))))
            self.state.permissions = [
                item
                for item in self.state.permissions
                if item.get("id") != "perm_1"
            ]
            self.send_response(204)
            self.end_headers()
            return
        if self.path == f"/api/session/{SESSION_ID}/interrupt":
            self.state.interrupts += 1
            self._json(200, {"data": {"interrupted": True}})
            return
        self._json(404, {"_tag": "NotFound", "message": self.path})

    def do_DELETE(self) -> None:
        if not self._authorized():
            self._json(401, {"_tag": "UnauthorizedError", "message": "auth"})
            return
        if self.path == f"/api/session/{SESSION_ID}":
            self.state.deleted += 1
            self.send_response(204)
            self.end_headers()
            return
        self._json(404, {"_tag": "NotFound", "message": self.path})

    def _events(self) -> None:
        events = [
            {"id": "evt_1", "type": "server.connected", "data": {}},
            {
                "id": "evt_2",
                "type": "session.execution.started",
                "data": {"sessionID": SESSION_ID},
            },
            {
                "id": "evt_3",
                "type": "session.tool.called",
                "data": {
                    "sessionID": SESSION_ID,
                    "assistantMessageID": "msg_1",
                    "id": "call_1",
                    "input": {},
                    "executed": True,
                    "native": {"name": "read"},
                },
            },
            {
                "id": "evt_4",
                "type": "permission.asked",
                "data": {
                    "id": "perm_1",
                    "sessionID": SESSION_ID,
                    "action": "shell",
                    "resources": ["ls"],
                },
            },
            {
                "id": "evt_5",
                "type": "session.text.delta",
                "data": {
                    "sessionID": SESSION_ID,
                    "assistantMessageID": "msg_1",
                    "ordinal": 0,
                    "delta": "hello",
                },
            },
            {
                "id": "evt_6",
                "type": "session.reasoning.delta",
                "data": {
                    "sessionID": SESSION_ID,
                    "assistantMessageID": "msg_1",
                    "ordinal": 0,
                    "delta": "private reasoning",
                },
            },
            {
                "id": "evt_7",
                "type": "session.execution.succeeded",
                "data": {"sessionID": SESSION_ID, "outcome": "succeeded"},
            },
            {
                "id": "evt_8",
                "type": "session.idle",
                "data": {"sessionID": SESSION_ID},
            },
        ]
        with self.state.lock:
            self.state.permissions = [
                {
                    "id": "perm_1",
                    "sessionID": SESSION_ID,
                    "action": "shell",
                    "resources": ["ls"],
                }
            ]
            self.state.events_sent += 1
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for event in events:
            self.wfile.write(
                f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode()
            )
            self.wfile.flush()
        self.close_connection = True


class HarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        FakeHandler.state = FakeState()
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHandler)
        self.enterContext(serve_http_fixture(server))
        self.client = OpenCodeClient(
            f"http://127.0.0.1:{server.server_port}",
            PASSWORD,
        )

    def _task(self, build_id: str = "build-1") -> BuildTask:
        return BuildTask(
            build_id=build_id,
            site={"entry_url": "https://fixture.test/"},
            scope={"max_pages": 1},
            market="GB",
            locale="en-GB",
        )

    def test_client_session_and_permission_roundtrip(self) -> None:
        info = self.client.info()
        self.assertEqual(info["version"], "test-1.0")
        session = self.client.create_session(
            directory=str(self.root / "work"),
            title="Test build",
        )
        self.assertEqual(session["id"], SESSION_ID)
        self.assertEqual(self.client.generate_probe(SESSION_ID), 1)
        self.client.send_prompt(SESSION_ID, "build a plan")
        self.assertEqual(FakeHandler.state.prompt, "build a plan")
        created = self.client.create_permission_request(
            SESSION_ID, action="shell", resources=["ls"]
        )
        self.assertEqual(created["effect"], "ask")
        permissions = self.client.list_permissions(SESSION_ID)
        self.assertEqual(permissions[0]["id"], "perm_1")
        self.client.reply_permission(SESSION_ID, "perm_1", "reject")
        self.assertEqual(FakeHandler.state.decisions, [("perm_1", "reject")])
        self.client.interrupt(SESSION_ID)
        self.assertEqual(FakeHandler.state.interrupts, 1)
        self.client.delete_session(SESSION_ID)
        self.assertEqual(FakeHandler.state.deleted, 1)

    def test_events_are_normalized_and_reasoning_is_redacted(self) -> None:
        events = list(self.client.events(timeout=10))
        self.assertEqual(len(events), 8)
        normalized = [normalize_event(event) for event in events]
        self.assertEqual(normalized[0].type, "server_connected")
        self.assertEqual(normalized[1].type, "phase_changed")
        self.assertEqual(normalized[2].type, "tool_started")
        self.assertEqual(normalized[2].data["tool"], "read")
        self.assertEqual(normalized[3].type, "permission_requested")
        self.assertEqual(normalized[3].data["id"], "perm_1")
        self.assertEqual(normalized[4].type, "message_delta")
        self.assertEqual(normalized[4].data["delta"], "hello")
        self.assertEqual(normalized[5].type, "reasoning_event")
        self.assertTrue(normalized[5].data["redacted"])
        self.assertNotIn("private reasoning", json.dumps(normalized[5].to_dict()))
        self.assertEqual(normalized[6].type, "finished")
        self.assertEqual(normalized[6].data["outcome"], "succeeded")
        self.assertEqual(normalized[7].data["phase"], "idle")

    def test_tool_input_and_output_are_normalized(self) -> None:
        started = normalize_event(
            {
                "type": "session.tool.called",
                "data": {
                    "sessionID": SESSION_ID,
                    "id": "call_1",
                    "native": {"name": "read"},
                },
            }
        )
        self.assertEqual(started.type, "tool_started")
        self.assertEqual(started.data["tool"], "read")
        self.assertEqual(started.data["call_id"], "call_1")

        named = normalize_event(
            {
                "type": "session.tool.input.started",
                "data": {
                    "sessionID": SESSION_ID,
                    "id": "call_1",
                    "name": "read",
                },
            }
        )
        self.assertEqual(named.type, "tool_input")
        self.assertEqual(named.data["tool"], "read")

        input_event = normalize_event(
            {
                "type": "session.tool.input.ended",
                "data": {
                    "sessionID": SESSION_ID,
                    "id": "call_1",
                    "name": "read",
                    "text": '{"path": "work/AGENTS.md"}',
                },
            }
        )
        self.assertEqual(input_event.type, "tool_input")
        self.assertEqual(input_event.data["input"], {"path": "work/AGENTS.md"})

        output_event = normalize_event(
            {
                "type": "session.tool.success",
                "data": {
                    "sessionID": SESSION_ID,
                    "id": "call_1",
                    "name": "read",
                    "content": [{"type": "text", "text": "read ok"}],
                    "metadata": {"exit": 0},
                },
            }
        )
        self.assertEqual(output_event.type, "tool_finished")
        self.assertEqual(output_event.data["output"], "read ok")

        secret = normalize_event(
            {
                "type": "session.tool.input.ended",
                "data": {
                    "sessionID": SESSION_ID,
                    "id": "call_2",
                    "text": "api_key=supersecret",
                },
            }
        )
        self.assertNotIn("supersecret", json.dumps(secret.to_dict()))

    def test_adapter_build_lifecycle(self) -> None:
        adapter = OpenCodeHttpAdapter(
            self.root / "sessions",
            client=self.client,
        )
        task = self._task()
        task.model = {
            "providerID": "opencode-go",
            "id": "deepseek-v4.1-flash",
            "variant": "high",
        }
        session = adapter.start_build(task)
        self.assertEqual(session.state, "CREATED")
        self.assertEqual(session.session_id, SESSION_ID)
        self.assertEqual(session.model, task.model)
        self.assertEqual(FakeHandler.state.session["model"], task.model)
        self.assertTrue((session.workspace.work_dir).is_dir())
        self.assertTrue(session.workspace.task_path.is_file())
        plugin = (
            session.workspace.work_dir
            / ".opencode"
            / "plugins"
            / "pause-gate"
            / "index.js"
        )
        self.assertTrue(plugin.is_file())
        self.assertIn("permission.hook", plugin.read_text(encoding="utf-8"))
        dependency_plugin = (
            session.workspace.work_dir
            / ".opencode"
            / "plugins"
            / "request-dependency"
            / "index.js"
        )
        self.assertTrue(dependency_plugin.is_file())
        self.assertIn(
            "request_dependency",
            dependency_plugin.read_text(encoding="utf-8"),
        )
        self.assertTrue(session.workspace.dependency_requests_dir.is_dir())
        self.assertTrue(session.workspace.dependency_responses_dir.is_dir())

        adapter.send_prompt(task.build_id, "make a plan")
        self.assertEqual(adapter.status(task.build_id).state, "RUNNING")
        self.assertEqual(FakeHandler.state.prompt, "make a plan")

        events = list(adapter.stream_events(task.build_id))
        self.assertEqual([event.type for event in events][:4], [
            "server_connected",
            "phase_changed",
            "tool_started",
            "permission_requested",
        ])
        event_lines = session.workspace.session_path.read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(len(event_lines), len(events) + 2)
        self.assertNotIn("private reasoning", "\n".join(event_lines))

        adapter.reply_permission(task.build_id, "perm_1", "once")
        self.assertEqual(FakeHandler.state.decisions[-1], ("perm_1", "once"))

        paused = adapter.pause(task.build_id)
        self.assertEqual(paused.state, "PAUSING")
        self.assertTrue(session.workspace.is_paused())
        resumed = adapter.resume(task.build_id)
        self.assertEqual(resumed.state, "RUNNING")
        self.assertFalse(session.workspace.is_paused())

        canceled = adapter.cancel(task.build_id)
        self.assertEqual(canceled.state, "CANCELLED")
        self.assertEqual(FakeHandler.state.interrupts, 1)
        self.assertEqual(FakeHandler.state.deleted, 1)

        adapter.close(task.build_id)
        result = json.loads(session.workspace.result_path.read_text(encoding="utf-8"))
        self.assertEqual(result["state"], "CANCELLED")
        self.assertTrue(result["artifacts"])

    def test_adapter_adopts_persisted_session_and_detaches_without_delete(self) -> None:
        adapter = OpenCodeHttpAdapter(
            self.root / "sessions",
            client=self.client,
        )
        task = self._task("build-recover")
        session = adapter.start_build(task)
        workspace = BuildWorkspace(root=session.workspace.root, build_id=task.build_id)
        FakeHandler.state.permissions = [
            {"id": "perm_1", "sessionID": SESSION_ID, "action": "shell"}
        ]

        recovered = OpenCodeHttpAdapter(
            self.root / "sessions",
            client=self.client,
        )
        adopted = recovered.adopt_build(
            task.build_id,
            session_id=SESSION_ID,
            workspace=workspace,
        )
        self.assertEqual(adopted.state, "FINISHED")
        self.assertEqual(adopted.outcome, "interrupted")
        self.assertTrue(adopted.harness.get("recovered"))
        self.assertEqual(FakeHandler.state.decisions, [("perm_1", "reject")])
        self.assertEqual(FakeHandler.state.permissions, [])
        event_types = [
            json.loads(line)["type"]
            for line in workspace.session_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertIn("build_recovered", event_types)

        detach_task = self._task("build-detach")
        recovered.start_build(detach_task)
        detached = recovered.detach(detach_task.build_id)
        self.assertEqual(detached.state, "FINISHED")
        self.assertEqual(detached.outcome, "interrupted")
        self.assertEqual(FakeHandler.state.interrupts, 1)
        self.assertEqual(FakeHandler.state.deleted, 0)
        recovered.shutdown()
        self.assertEqual(FakeHandler.state.deleted, 0)

        with self.assertRaises(HarnessStateError):
            recovered.adopt_build(
                "build-missing",
                session_id="ses_missing",
                workspace=workspace,
            )

    def test_adapter_uses_task_permissions(self) -> None:
        adapter = OpenCodeHttpAdapter(self.root / "sessions", client=self.client)
        task = self._task("build-permissions")
        permissions = [{"action": "skill", "resource": "*", "effect": "deny"}]
        task.extra["permissions"] = permissions
        adapter.start_build(task)
        self.assertEqual(FakeHandler.state.session["permissions"], permissions)

    def test_adapter_rejects_prompt_while_paused_and_unknown_build(self) -> None:
        adapter = OpenCodeHttpAdapter(self.root / "sessions", client=self.client)
        task = self._task("build-2")
        adapter.start_build(task)
        adapter.pause(task.build_id)
        with self.assertRaises(HarnessStateError):
            adapter.send_prompt(task.build_id, "blocked")
        with self.assertRaises(KeyError):
            adapter.status("missing")
        with self.assertRaises(HarnessUnsupportedError):
            adapter.request_dependency(task.build_id, {"package": "x"})
        adapter.cancel(task.build_id)
        adapter.close(task.build_id)

    def test_adapter_dependency_policy_and_event(self) -> None:
        policy = DependencyPolicy(
            allowlist={"pyyaml": {"version": "6.0.3", "license": "MIT"}},
            installer=lambda name, version, python: subprocess.CompletedProcess(
                args=[name, version],
                returncode=0,
                stdout="ok",
            ),
            build_python=Path(sys.executable),
        )
        adapter = OpenCodeHttpAdapter(
            self.root / "sessions",
            client=self.client,
            dependency_policy=policy,
        )
        task = self._task("build-deps")
        session = adapter.start_build(task)
        decision = adapter.request_dependency(
            task.build_id, {"name": "pyyaml", "manager": "uv"}
        )
        self.assertEqual(decision["status"], "installed")
        self.assertEqual(decision["license"], "MIT")
        events = session.workspace.session_path.read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertTrue(
            any(json.loads(line)["type"] == "dependency_installed" for line in events)
        )
        adapter.cancel(task.build_id)
        adapter.close(task.build_id)

    def test_adapter_dependency_approval_and_install(self) -> None:
        policy = DependencyPolicy(
            installer=lambda name, version, python: subprocess.CompletedProcess(
                args=[name, version],
                returncode=0,
                stdout="ok",
            ),
            build_python=Path(sys.executable),
        )
        adapter = OpenCodeHttpAdapter(
            self.root / "sessions",
            client=self.client,
            dependency_policy=policy,
        )
        task = self._task("build-approval")
        session = adapter.start_build(task)
        held = adapter.request_dependency(
            task.build_id,
            {
                "package": "brandnew",
                "manager": "pip",
                "version": "1.2.3",
            },
        )
        self.assertEqual(held["status"], "approval_required")
        installed = adapter.request_dependency(
            task.build_id,
            {
                "package": "brandnew",
                "manager": "pip",
                "version": "1.2.3",
            },
            approved=True,
        )
        self.assertEqual(installed["status"], "installed")
        self.assertTrue(installed["approved"])
        event_types = [
            json.loads(line)["type"]
            for line in session.workspace.session_path.read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        self.assertIn("dependency_approval_required", event_types)
        self.assertIn("dependency_installed", event_types)
        adapter.cancel(task.build_id)
        adapter.close(task.build_id)

    def test_workspace_rejects_existing_and_pause_fails_closed(self) -> None:
        task = self._task("build-3")
        workspace = BuildWorkspace.create(self.root / "sessions", task)
        self.assertFalse(workspace.is_paused())
        with self.assertRaises(FileExistsError):
            BuildWorkspace.create(self.root / "sessions", task)
        workspace.pause_path.write_text("{broken", encoding="utf-8")
        self.assertTrue(workspace.is_paused())

    def test_child_environment_keeps_baseline_and_explicit_values(self) -> None:
        with mock.patch.dict(
            os.environ, {"ECOM_TEST_AMBIENT": "ambient-secret"}, clear=False
        ):
            env = child_environment(
                {"ECOM_TEST_EXPLICIT": "explicit"}, inherit=False
            )
        self.assertNotIn("ECOM_TEST_AMBIENT", env)
        self.assertEqual(env["ECOM_TEST_EXPLICIT"], "explicit")
        self.assertEqual(env.get("PATH"), os.environ.get("PATH"))

    def test_server_process_manager_starts_and_stops(self) -> None:
        script = self.root / "fake_server.py"
        script.write_text(
            """\
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

port = int(sys.argv[sys.argv.index("--port") + 1])
password = os.environ["OPENCODE_PASSWORD"]
auth = "Basic " + __import__("base64").b64encode(
    f"opencode:{password}".encode()
).decode()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return
    def do_GET(self):
        if self.headers.get("Authorization") != auth:
            self.send_response(401)
            self.end_headers()
            return
        body = json.dumps(
            {
                "version": "fake-1.0",
                "pid": os.getpid(),
                "ambient": os.environ.get("ECOM_TEST_AMBIENT"),
                "explicit": os.environ.get("ECOM_TEST_EXPLICIT"),
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
print(f"server listening on http://127.0.0.1:{port}", flush=True)
server.serve_forever()
""",
            encoding="utf-8",
        )
        server = OpenCodeServer(
            command=[sys.executable, str(script)],
            startup_timeout=20,
            env={"ECOM_TEST_EXPLICIT": "kept"},
            inherit_env=False,
        )
        try:
            with mock.patch.dict(
                os.environ, {"ECOM_TEST_AMBIENT": "must-not-leak"}
            ):
                client = server.start()
            info = client.info()
            self.assertEqual(info["version"], "fake-1.0")
            self.assertEqual(info["explicit"], "kept")
            self.assertIsNone(info["ambient"])
            self.assertIsNotNone(server.process)
            self.assertIsNotNone(server.version)
        finally:
            server.stop()
        self.assertIsNone(server.process)


if __name__ == "__main__":
    unittest.main()
