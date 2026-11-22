from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from ecom_crawler.harness.adapter import BuildSession
from ecom_crawler.harness.dependency_bridge import (
    DependencyBridge,
    install_dependency_tool,
)
from ecom_crawler.harness.models import BuildTask
from ecom_crawler.harness.workspace import BuildWorkspace

NODE = shutil.which("node")


class FakeDependencyAdapter:
    def __init__(self, decision: dict[str, Any] | None = None) -> None:
        self.decision = decision
        self.calls: list[tuple[dict[str, Any], bool]] = []

    def request_dependency(
        self,
        build_id: str,
        request: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        self.calls.append((dict(request), approved))
        if self.decision is not None:
            return dict(self.decision)
        return {
            "status": "installed",
            "package": request.get("package"),
            "version": request.get("version"),
            "approved": approved,
        }


class DependencyBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        task = BuildTask(build_id="build-deps", market="GB", locale="en-GB")
        self.workspace = BuildWorkspace.create(
            self.root / "sessions",
            task,
            pause_gate=False,
        )
        self.session = BuildSession(
            build_id=task.build_id,
            state="RUNNING",
            workspace=self.workspace,
            session_id="ses_deps",
        )
        self.events: list[Any] = []
        self.adapter = FakeDependencyAdapter()
        self.bridge = DependencyBridge(
            self.session,
            self.adapter,
            on_event=self.events.append,
            poll_interval=0.02,
        )

    def tearDown(self) -> None:
        self.bridge.stop()
        self.temporary.cleanup()

    def _wait(self, predicate: Any, message: str, timeout: float = 15) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail(message)

    def _write_request(
        self, request_id: str, payload: dict[str, Any] | str
    ) -> Path:
        path = self.workspace.dependency_requests_dir / f"{request_id}.json"
        text = (
            payload
            if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False)
        )
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
        return path

    def _response(self, request_id: str) -> dict[str, Any] | None:
        path = self.workspace.dependency_responses_dir / f"{request_id}.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def test_request_is_answered_and_event_is_emitted(self) -> None:
        self.bridge.start()
        self._write_request(
            "req-1",
            {
                "request_id": "req-1",
                "package": "pyyaml",
                "manager": "pip",
                "version": "6.0.3",
                "scope": "build",
            },
        )
        self._wait(
            lambda: self._response("req-1") is not None,
            "bridge did not answer the request",
        )
        response = self._response("req-1")
        assert response is not None
        self.assertEqual(response["status"], "installed")
        self.assertEqual(response["package"], "pyyaml")
        self.assertEqual(self.adapter.calls[0][0]["package"], "pyyaml")
        self.assertFalse(self.adapter.calls[0][1])
        self.assertTrue(
            any(event.type == "dependency_installed" for event in self.events)
        )

    def test_approval_is_held_until_resolved(self) -> None:
        self.adapter.decision = {
            "status": "approval_required",
            "package": "brandnew",
            "version": "1.2.3",
            "detail": "not in allowlist",
        }
        self.bridge.start()
        self._write_request(
            "req-approval",
            {
                "request_id": "req-approval",
                "package": "brandnew",
                "manager": "pip",
                "version": "1.2.3",
            },
        )
        self._wait(
            lambda: self.bridge.pending_ids() == ["req-approval"],
            "request was not held for approval",
        )
        self.assertIsNone(self._response("req-approval"))
        self.assertTrue(
            any(
                event.type == "dependency_approval_required"
                for event in self.events
            )
        )

        self.adapter.decision = None
        result = self.bridge.resolve("req-approval", "once")
        self.assertEqual(result["status"], "installed")
        self.assertTrue(result["approved"])
        response = self._response("req-approval")
        assert response is not None
        self.assertEqual(response["status"], "installed")
        self.assertEqual(self.adapter.calls[-1][1], True)
        self.assertEqual(self.bridge.pending_ids(), [])

    def test_reject_writes_denied_and_clears_pending(self) -> None:
        self.adapter.decision = {
            "status": "approval_required",
            "package": "brandnew",
        }
        self.bridge.start()
        self._write_request(
            "req-reject",
            {"request_id": "req-reject", "package": "brandnew"},
        )
        self._wait(
            lambda: self.bridge.pending_ids() == ["req-reject"],
            "request was not held",
        )
        result = self.bridge.resolve("req-reject", "reject", message="not needed")
        self.assertEqual(result["status"], "denied")
        self.assertIn("not needed", result["detail"])
        response = self._response("req-reject")
        assert response is not None
        self.assertEqual(response["status"], "denied")

    def test_paused_bridge_holds_requests_until_resume(self) -> None:
        paused = {"value": True}
        bridge = DependencyBridge(
            self.session,
            self.adapter,
            is_paused=lambda: paused["value"],
            on_event=self.events.append,
            poll_interval=0.02,
        )
        bridge.start()
        try:
            self._write_request(
                "req-paused",
                {"request_id": "req-paused", "package": "pyyaml"},
            )
            time.sleep(0.2)
            self.assertIsNone(self._response("req-paused"))
            paused["value"] = False
            self._wait(
                lambda: self._response("req-paused") is not None,
                "request did not resume after unpause",
            )
        finally:
            bridge.stop()

    def test_approval_timeout_denies_request(self) -> None:
        self.adapter.decision = {
            "status": "approval_required",
            "package": "brandnew",
        }
        bridge = DependencyBridge(
            self.session,
            self.adapter,
            on_event=self.events.append,
            poll_interval=0.02,
            approval_timeout=0.1,
        )
        bridge.start()
        try:
            self._write_request(
                "req-timeout",
                {"request_id": "req-timeout", "package": "brandnew"},
            )
            self._wait(
                lambda: self._response("req-timeout") is not None,
                "timed-out approval was not answered",
            )
            response = self._response("req-timeout")
            assert response is not None
            self.assertEqual(response["status"], "denied")
            self.assertIn("timed out", response["detail"])
        finally:
            bridge.stop()

    def test_invalid_request_file_is_denied(self) -> None:
        self.bridge.start()
        self._write_request("req-broken", "{not json")
        self._wait(
            lambda: self._response("req-broken") is not None,
            "invalid request was not answered",
        )
        response = self._response("req-broken")
        assert response is not None
        self.assertEqual(response["status"], "denied")
        self.assertIn("invalid request", response["detail"])

    def test_stop_cancels_pending_requests(self) -> None:
        self.adapter.decision = {
            "status": "approval_required",
            "package": "brandnew",
        }
        self.bridge.start()
        self._write_request(
            "req-stop",
            {"request_id": "req-stop", "package": "brandnew"},
        )
        self._wait(
            lambda: self.bridge.pending_ids() == ["req-stop"],
            "request was not held",
        )
        self.bridge.stop()
        response = self._response("req-stop")
        assert response is not None
        self.assertEqual(response["status"], "cancelled")
        self.assertEqual(self.bridge.pending_ids(), [])


class DependencyToolInstallTests(unittest.TestCase):
    def test_plugin_files_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plugin = install_dependency_tool(Path(temporary) / "work")
            self.assertTrue((plugin / "package.json").is_file())
            self.assertTrue((plugin / "bridge.js").is_file())
            self.assertTrue((plugin / "index.js").is_file())
            self.assertIn(
                "request_dependency",
                (plugin / "index.js").read_text(encoding="utf-8"),
            )

    @unittest.skipUnless(NODE, "Node.js is not installed")
    def test_plugin_javascript_parses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plugin = install_dependency_tool(Path(temporary) / "work")
            for name in ("bridge.js", "index.js"):
                completed = subprocess.run(
                    [NODE, "--check", str(plugin / name)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=30,
                    check=False,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    f"{name}: {completed.stderr}",
                )

    @unittest.skipUnless(NODE, "Node.js is not installed")
    def test_node_bridge_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plugin = install_dependency_tool(root / "work")
            control = root / "control" / "dependencies"
            driver = root / "driver.mjs"
            bridge_url = json.dumps((plugin / "bridge.js").as_uri())
            control_dir = json.dumps(str(control))
            driver.write_text(
                f"""\
import {{ requestDependency }} from {bridge_url}
const result = await requestDependency(
  {{
    package: "pyyaml",
    manager: "pip",
    version: "6.0.3",
    reason: "fixture",
    source: "PyPI",
    license: "MIT",
    scope: "build",
    fallback: "parse JSON",
  }},
  {{ controlDir: {control_dir}, timeoutMs: 10000, pollMs: 20 }},
)
console.log(JSON.stringify(result))
""",
                encoding="utf-8",
            )
            process = subprocess.Popen(
                [NODE, str(driver)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            try:
                requests_dir = control / "requests"
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if requests_dir.is_dir() and list(requests_dir.glob("*.json")):
                        break
                    time.sleep(0.02)
                request_path = next(requests_dir.glob("*.json"))
                payload = json.loads(request_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["package"], "pyyaml")
                self.assertEqual(payload["manager"], "pip")
                self.assertEqual(payload["fallback"], "parse JSON")
                responses_dir = control / "responses"
                responses_dir.mkdir(parents=True, exist_ok=True)
                (responses_dir / f"{payload['request_id']}.json").write_text(
                    json.dumps(
                        {
                            "status": "installed",
                            "package": "pyyaml",
                            "version": "6.0.3",
                        }
                    ),
                    encoding="utf-8",
                )
                stdout, stderr = process.communicate(timeout=15)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
            self.assertEqual(process.returncode, 0, stderr)
            result = json.loads(stdout.strip().splitlines()[-1])
            self.assertEqual(result["status"], "installed")
            self.assertEqual(result["package"], "pyyaml")


    @unittest.skipUnless(NODE, "Node.js is not installed")
    def test_plugin_registers_and_executes_with_fake_opencode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = root / "work"
            plugin = install_dependency_tool(work)
            stub = work / "node_modules" / "@opencode" / "plugin"
            stub.mkdir(parents=True)
            (stub / "package.json").write_text(
                json.dumps(
                    {
                        "name": "@opencode/plugin",
                        "type": "module",
                        "exports": "./index.js",
                    }
                ),
                encoding="utf-8",
            )
            (stub / "index.js").write_text(
                "export const Plugin = { define: (definition) => definition }\n",
                encoding="utf-8",
            )
            driver = root / "driver.mjs"
            driver.write_text(
                f"""\
import plugin from {json.dumps((plugin / "index.js").as_uri())}

const registered = []
const ctx = {{
  location: {{ directory: {json.dumps(str(work))} }},
  options: {{ timeout_ms: 10000 }},
  tool: {{
    transform: async (callback) => {{
      callback({{ add: (tool) => registered.push(tool) }})
    }},
  }},
}}
await plugin.setup(ctx)
if (registered.length !== 1) {{
  throw new Error("expected one registered tool, got " + registered.length)
}}
const tool = registered[0]
if (tool.name !== "request_dependency") {{
  throw new Error("unexpected tool: " + tool.name)
}}
const result = await tool.execute(
  {{
    package: "pyyaml",
    manager: "pip",
    version: "6.0.3",
    reason: "fixture",
    source: "PyPI",
    license: "MIT",
    scope: "build",
    fallback: "parse JSON",
  }},
  {{ signal: null }},
)
console.log(JSON.stringify(result))
""",
                encoding="utf-8",
            )
            process = subprocess.Popen(
                [NODE, str(driver)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            try:
                requests_dir = work.parent / "control" / "dependencies" / "requests"
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if requests_dir.is_dir() and list(requests_dir.glob("*.json")):
                        break
                    time.sleep(0.02)
                request_path = next(requests_dir.glob("*.json"))
                payload = json.loads(request_path.read_text(encoding="utf-8"))
                responses_dir = requests_dir.parent / "responses"
                responses_dir.mkdir(parents=True, exist_ok=True)
                (responses_dir / f"{payload['request_id']}.json").write_text(
                    json.dumps(
                        {
                            "status": "installed",
                            "package": "pyyaml",
                            "version": "6.0.3",
                        }
                    ),
                    encoding="utf-8",
                )
                stdout, stderr = process.communicate(timeout=15)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
            self.assertEqual(process.returncode, 0, stderr)
            content = json.loads(stdout.strip().splitlines()[-1])["content"]
            result = json.loads(content)
            self.assertEqual(result["status"], "installed")
            log_path = work.parent / "control" / "dependency-bridge.log"
            self.assertTrue(log_path.is_file())
            self.assertIn(
                "registered request_dependency",
                log_path.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
