from __future__ import annotations

import json
import os
import queue
import tempfile
import time
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ecom_crawler.harness.adapter import BuildSession, HarnessStateError
from ecom_crawler.harness.models import BuildTask, HarnessEvent, utc_now
from ecom_crawler.harness.service import BuildService
from ecom_crawler.harness.workspace import BuildWorkspace


class FakeAdapter:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.queue: queue.Queue[HarnessEvent | None] = queue.Queue()
        self.sessions: dict[str, BuildSession] = {}
        self.prompts: list[tuple[str, str]] = []
        self.replies: list[tuple[str, str, str]] = []
        self.pending: list[dict[str, Any]] = []
        self.canceled: list[str] = []
        self.closed: list[str] = []
        self.dependency_calls: list[tuple[dict[str, Any], bool]] = []

    def start_build(self, task: BuildTask) -> BuildSession:
        workspace = BuildWorkspace.create(
            self.root / "sessions", task, pause_gate=False
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
        self.replies.append((build_id, request_id, decision))
        self.pending = [
            item for item in self.pending if item.get("id") != request_id
        ]

    def list_permissions(self, build_id: str) -> list[dict[str, Any]]:
        return list(self.pending)

    def request_dependency(
        self,
        build_id: str,
        request: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        self.dependency_calls.append((dict(request), approved))
        package = str(request.get("package") or request.get("name") or "")
        if package == "unknownpkg" and not approved:
            return {
                "status": "approval_required",
                "package": package,
                "version": request.get("version"),
                "detail": "not in allowlist",
            }
        return {
            "status": "installed",
            "package": package,
            "version": request.get("version"),
            "approved": approved,
        }

    def pause(self, build_id: str) -> BuildSession:
        session = self.sessions[build_id]
        session.state = "PAUSING"
        return session

    def resume(self, build_id: str) -> BuildSession:
        session = self.sessions[build_id]
        session.state = "RUNNING"
        return session

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


class BuildServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.adapter = FakeAdapter(self.root)
        self.service = BuildService(self.adapter)

    def tearDown(self) -> None:
        self.adapter.queue.put(None)
        self.temporary.cleanup()

    def _task(self, build_id: str = "build-service") -> BuildTask:
        return BuildTask(build_id=build_id, market="GB", locale="en-GB")

    def _wait(self, predicate: Any, message: str, timeout: float = 5) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail(message)

    def test_lifecycle_permission_and_finished_event(self) -> None:
        task = self._task()
        session = self.service.start_build(task)
        self.assertEqual(session.state, "CREATED")
        self.service.send_prompt(task.build_id, "build")
        self.assertEqual(self.service.status(task.build_id).state, "RUNNING")

        self.adapter.emit(
            "phase_changed", "session.execution.started", phase="executing"
        )
        self._wait(
            lambda: self.service.status(task.build_id).state == "RUNNING",
            "execution start was not applied",
        )
        self.service.pause(task.build_id)
        self.assertEqual(self.service.status(task.build_id).state, "PAUSING")
        self.adapter.pending = [
            {"id": "perm_1", "action": "shell", "resources": ["echo"]}
        ]
        self.adapter.emit(
            "permission_requested",
            "permission.asked",
            id="perm_1",
            action="shell",
            resources=["echo"],
        )
        self._wait(
            lambda: "perm_1" in self.service.held_permission_ids(task.build_id),
            "permission was not held while paused",
        )
        self.service.resume(task.build_id)
        self.assertEqual(self.service.status(task.build_id).state, "RUNNING")
        self.assertEqual(self.adapter.replies, [(task.build_id, "perm_1", "once")])

        self.adapter.emit(
            "finished",
            "session.execution.succeeded",
            outcome="succeeded",
        )
        self._wait(
            lambda: self.service.status(task.build_id).state == "FINISHED",
            "finish event was not applied",
        )
        self.assertEqual(
            self.service.status(task.build_id).outcome,
            "succeeded",
        )
        events = self.service.event_log(task.build_id)
        self.assertTrue(any(event.type == "permission_requested" for event in events))
        self.assertTrue(any(event.type == "finished" for event in events))
        result = self.service.result(task.build_id)
        self.assertEqual(result["state"], "FINISHED")
        self.service.close(task.build_id)
        self.assertEqual(self.service.status(task.build_id).state, "FINISHED")

    def test_one_active_build_and_cancel(self) -> None:
        first = self._task("build-a")
        second = self._task("build-b")
        self.service.start_build(first)
        with self.assertRaises(HarnessStateError):
            self.service.start_build(second)
        self.service.cancel(first.build_id)
        self.assertEqual(self.service.status(first.build_id).state, "CANCELLED")
        self.assertEqual(self.adapter.canceled, [first.build_id])
        self.service.start_build(second)
        self.service.close(second.build_id)
        self.assertEqual(self.adapter.closed, [second.build_id])

    def test_dependency_delegation(self) -> None:
        task = self._task("build-deps")
        self.service.start_build(task)
        decision = self.service.request_dependency(
            task.build_id, {"name": "pyyaml"}
        )
        self.assertEqual(decision["status"], "installed")
        self.assertEqual(decision["package"], "pyyaml")
        self.service.cancel(task.build_id)
        self.service.close(task.build_id)

    def _write_request(
        self, build_id: str, request_id: str, package: str
    ) -> Path:
        path = (
            self.adapter.sessions[build_id]
            .workspace.dependency_requests_dir
            / f"{request_id}.json"
        )
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "request_id": request_id,
                    "package": package,
                    "manager": "pip",
                    "version": "1.0.0",
                }
            ),
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path

    def _response(self, build_id: str, request_id: str) -> dict[str, Any] | None:
        path = (
            self.adapter.sessions[build_id]
            .workspace.dependency_responses_dir
            / f"{request_id}.json"
        )
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def test_bridge_answers_allowlisted_request(self) -> None:
        task = self._task("build-bridge")
        self.service.start_build(task)
        self._write_request(task.build_id, "req-ok", "pyyaml")
        self._wait(
            lambda: self._response(task.build_id, "req-ok") is not None,
            "bridge did not answer the request",
        )
        response = self._response(task.build_id, "req-ok")
        assert response is not None
        self.assertEqual(response["status"], "installed")
        self.assertTrue(
            any(
                event.type == "dependency_installed"
                for event in self.service.event_log(task.build_id)
            )
        )
        self.service.cancel(task.build_id)
        self.service.close(task.build_id)

    def test_bridge_holds_unknown_package_for_approval(self) -> None:
        task = self._task("build-approval")
        self.service.start_build(task)
        self._write_request(task.build_id, "req-unknown", "unknownpkg")
        self._wait(
            lambda: self.service.pending_dependency_ids(task.build_id)
            == ["req-unknown"],
            "request was not held for approval",
        )
        self.assertIsNone(self._response(task.build_id, "req-unknown"))
        decision = self.service.reply_dependency(
            task.build_id, "req-unknown", "once"
        )
        self.assertEqual(decision["status"], "installed")
        self.assertTrue(decision["approved"])
        self.assertEqual(
            self.service.pending_dependency_ids(task.build_id), []
        )
        response = self._response(task.build_id, "req-unknown")
        assert response is not None
        self.assertEqual(response["status"], "installed")
        self.service.cancel(task.build_id)
        self.service.close(task.build_id)

    def test_cancel_stops_pending_dependency(self) -> None:
        task = self._task("build-cancel-deps")
        self.service.start_build(task)
        self._write_request(task.build_id, "req-cancel", "unknownpkg")
        self._wait(
            lambda: self.service.pending_dependency_ids(task.build_id)
            == ["req-cancel"],
            "request was not held",
        )
        self.service.cancel(task.build_id)
        response = self._response(task.build_id, "req-cancel")
        assert response is not None
        self.assertEqual(response["status"], "cancelled")
        self.assertEqual(
            self.service.pending_dependency_ids(task.build_id), []
        )


if __name__ == "__main__":
    unittest.main()
