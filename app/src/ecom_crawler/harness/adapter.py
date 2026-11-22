"""Harness adapter interface and the v1 OpenCode implementation."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .dependencies import DependencyPolicy, DependencyRequest
from .events import normalize_event
from .models import BuildTask, HarnessEvent, utc_now
from .opencode import OpenCodeClient, OpenCodeHttpError, OpenCodeServer
from .workspace import BuildWorkspace

ADAPTER_VERSION = "opencode-http/0.1"
TERMINAL_STATES = {"CANCELLED", "FINISHED"}


class HarnessStateError(ValueError):
    """Raised when a build operation is invalid for the current state."""


class HarnessUnsupportedError(NotImplementedError):
    """Raised for contract methods that are intentionally not wired yet."""


@dataclass
class BuildSession:
    build_id: str
    state: str
    workspace: BuildWorkspace
    session_id: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    model: dict[str, Any] | None = None
    harness: dict[str, Any] = field(default_factory=dict)
    outcome: str | None = None
    error: str | None = None

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def to_dict(self) -> dict[str, Any]:
        return {
            "build_id": self.build_id,
            "state": self.state,
            "session_id": self.session_id,
            "workspace": str(self.workspace.root),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "model": self.model,
            "harness": self.harness,
            "outcome": self.outcome,
            "error": self.error,
        }


class HarnessAdapter(ABC):
    """BuildService's only harness dependency (ADR 0005/0006)."""

    @abstractmethod
    def start_build(self, task: BuildTask) -> BuildSession:
        raise NotImplementedError

    @abstractmethod
    def send_prompt(self, build_id: str, text: str) -> dict[str, Any]:
        raise NotImplementedError

    def continue_prompt(self, build_id: str, text: str) -> dict[str, Any]:
        """Send another prompt to a finished session when the adapter supports it."""
        raise HarnessUnsupportedError(
            "this adapter cannot continue a finished build session"
        )

    @abstractmethod
    def stream_events(self, build_id: str) -> Iterator[HarnessEvent]:
        raise NotImplementedError

    @abstractmethod
    def reply_permission(
        self,
        build_id: str,
        request_id: str,
        decision: str,
        *,
        message: str | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_permissions(self, build_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def request_dependency(
        self,
        build_id: str,
        request: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def pause(self, build_id: str) -> BuildSession:
        raise NotImplementedError

    @abstractmethod
    def resume(self, build_id: str) -> BuildSession:
        raise NotImplementedError

    @abstractmethod
    def cancel(self, build_id: str) -> BuildSession:
        raise NotImplementedError

    @abstractmethod
    def collect_artifacts(self, build_id: str) -> dict[str, str]:
        raise NotImplementedError

    @abstractmethod
    def close(self, build_id: str) -> BuildSession:
        raise NotImplementedError


class OpenCodeHttpAdapter(HarnessAdapter):
    """v1 adapter: one ``opencode serve`` process per adapter instance."""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        server: OpenCodeServer | None = None,
        client: OpenCodeClient | None = None,
        model: dict[str, Any] | None = None,
        permissions: list[dict[str, Any]] | None = None,
        event_timeout: float | None = None,
        pause_gate: bool = True,
        dependency_tool: bool = True,
        dependency_policy: DependencyPolicy | None = None,
        capture_reasoning: bool = False,
    ) -> None:
        if server is not None and client is not None:
            raise ValueError("pass server or client, not both")
        self.workspace_root = Path(workspace_root).resolve()
        self.server = server
        self.client = client
        self.model = model
        self.permissions = permissions
        self.event_timeout = event_timeout
        self.pause_gate = pause_gate
        self.dependency_tool = dependency_tool
        self.dependency_policy = dependency_policy
        self.capture_reasoning = capture_reasoning
        self.sessions: dict[str, BuildSession] = {}
        self._lock = threading.RLock()
        self._owns_server = client is None

    def _ensure_client(self, *, cwd: Path | None = None) -> OpenCodeClient:
        with self._lock:
            if self.client is not None:
                # ``close`` stops the owned server; drop the stale client so a
                # later build can start a fresh server instead of using a dead
                # base URL.
                if self.server is not None and self.server.client is None:
                    self.client = None
                else:
                    return self.client
            if self.server is None:
                self.server = OpenCodeServer(cwd=cwd)
            elif cwd is not None and self.server.cwd is None:
                self.server.cwd = cwd
            self.client = self.server.start()
            return self.client

    def _require(self, build_id: str) -> BuildSession:
        session = self.sessions.get(build_id)
        if session is None:
            raise KeyError(f"unknown build: {build_id}")
        return session

    def _set_state(
        self,
        session: BuildSession,
        state: str,
        *,
        outcome: str | None = None,
        error: str | None = None,
    ) -> BuildSession:
        session.state = state
        session.updated_at = utc_now()
        if outcome is not None:
            session.outcome = outcome
        if error is not None:
            session.error = error
        session.workspace.update_result(
            state=session.state,
            outcome=session.outcome,
            session_id=session.session_id,
            harness=session.harness,
            model=session.model,
            error=session.error,
            session=session.to_dict(),
        )
        return session

    def _append_adapter_event(
        self,
        session: BuildSession,
        event_type: str,
        **data: Any,
    ) -> HarnessEvent:
        event = HarnessEvent(
            type=event_type,
            source_type="adapter",
            session_id=session.session_id,
            data=data,
            created_at=utc_now(),
        )
        session.workspace.append_event(event)
        return event

    def start_build(self, task: BuildTask) -> BuildSession:
        with self._lock:
            if task.build_id in self.sessions:
                raise HarnessStateError(f"build already exists: {task.build_id}")
            workspace = BuildWorkspace.create(
                self.workspace_root,
                task,
                pause_gate=self.pause_gate,
                dependency_tool=self.dependency_tool,
            )
            client = self._ensure_client(cwd=workspace.work_dir)
            try:
                created = client.create_session(
                    directory=str(workspace.work_dir),
                    title=f"Build {task.build_id}",
                    model=task.model or self.model,
                    permissions=self.permissions,
                )
            except Exception as exc:
                workspace.update_result(
                    state="FINISHED",
                    outcome="failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
                raise
            harness = {
                "name": "opencode",
                "version": getattr(self.server, "version", None),
                "adapter_version": ADAPTER_VERSION,
                "transport": "http+sse",
            }
            session = BuildSession(
                build_id=task.build_id,
                state="CREATED",
                workspace=workspace,
                session_id=str(created["id"]),
                model=task.model or self.model,
                harness=harness,
            )
            self.sessions[task.build_id] = session
            self._append_adapter_event(session, "build_created")
            self._set_state(session, "CREATED")
            return session

    def send_prompt(self, build_id: str, text: str) -> dict[str, Any]:
        with self._lock:
            session = self._require(build_id)
            if session.terminal:
                raise HarnessStateError(
                    f"cannot prompt build {build_id} in state {session.state}"
                )
            if session.workspace.is_paused():
                raise HarnessStateError(f"build {build_id} is paused")
            client = self._ensure_client()
            if session.session_id is None:
                raise HarnessStateError(f"build {build_id} has no session")
            result = client.send_prompt(session.session_id, text)
            self._append_adapter_event(
                session, "prompt_sent", characters=len(text)
            )
            self._set_state(session, "RUNNING")
            return result

    def continue_prompt(self, build_id: str, text: str) -> dict[str, Any]:
        """Prompt a session again after it finished, keeping its conversation."""
        with self._lock:
            session = self._require(build_id)
            # BuildService flips the state to RUNNING before restarting the
            # event pump, so both states are valid at this boundary.
            if session.state not in {"FINISHED", "RUNNING"}:
                raise HarnessStateError(
                    f"cannot continue build {build_id} in state {session.state}"
                )
            if session.workspace.is_paused():
                raise HarnessStateError(f"build {build_id} is paused")
            client = self._ensure_client()
            if session.session_id is None:
                raise HarnessStateError(f"build {build_id} has no session")
            result = client.send_prompt(session.session_id, text)
            session.outcome = None
            session.error = None
            self._append_adapter_event(
                session, "prompt_sent", characters=len(text), repair=True
            )
            self._set_state(session, "RUNNING")
            return result

    def stream_events(self, build_id: str) -> Iterator[HarnessEvent]:
        session = self._require(build_id)
        client = self._ensure_client()
        if session.session_id is None:
            raise HarnessStateError(f"build {build_id} has no session")
        for raw in client.events(timeout=self.event_timeout):
            event = normalize_event(
                raw,
                capture_reasoning=self.capture_reasoning,
            )
            if event.session_id and event.session_id != session.session_id:
                continue
            session.workspace.append_event(event)
            yield event

    def reply_permission(
        self,
        build_id: str,
        request_id: str,
        decision: str,
        *,
        message: str | None = None,
    ) -> None:
        with self._lock:
            session = self._require(build_id)
            if session.session_id is None:
                raise HarnessStateError(f"build {build_id} has no session")
            try:
                self._ensure_client().reply_permission(
                    session.session_id,
                    request_id,
                    decision,
                    message=message,
                )
            except OpenCodeHttpError as exc:
                if exc.status == 404 and exc.code == "PermissionNotFoundError":
                    self._append_adapter_event(
                        session,
                        "permission_already_settled",
                        request_id=request_id,
                    )
                    return
                raise
            self._append_adapter_event(
                session,
                "permission_replied",
                request_id=request_id,
                decision=decision,
            )

    def list_permissions(self, build_id: str) -> list[dict[str, Any]]:
        session = self._require(build_id)
        if session.session_id is None:
            return []
        return self._ensure_client().list_permissions(session.session_id)

    def request_dependency(
        self,
        build_id: str,
        request: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        session = self._require(build_id)
        if self.dependency_policy is None:
            raise HarnessUnsupportedError(
                "no dependency policy is configured for this adapter"
            )
        decision = self.dependency_policy.request(
            DependencyRequest.from_dict(request),
            approved=approved,
        )
        event_type = {
            "available": "dependency_available",
            "installed": "dependency_installed",
            "failed": "dependency_failed",
            "denied": "dependency_denied",
            "approval_required": "dependency_approval_required",
        }.get(decision.status, "dependency_requested")
        self._append_adapter_event(
            session,
            event_type,
            name=decision.name,
            version=decision.version,
            status=decision.status,
            detail=decision.detail,
        )
        return decision.to_dict()

    def pause(self, build_id: str) -> BuildSession:
        with self._lock:
            session = self._require(build_id)
            if session.terminal:
                return session
            session.workspace.set_paused(True)
            self._append_adapter_event(session, "build_pausing")
            return self._set_state(session, "PAUSING")

    def resume(self, build_id: str) -> BuildSession:
        with self._lock:
            session = self._require(build_id)
            if session.state not in {"PAUSING", "PAUSED"}:
                raise HarnessStateError(
                    f"cannot resume build {build_id} in state {session.state}"
                )
            session.workspace.set_paused(False)
            self._append_adapter_event(session, "build_resumed")
            return self._set_state(session, "RUNNING")

    def cancel(self, build_id: str) -> BuildSession:
        with self._lock:
            session = self._require(build_id)
            if session.terminal:
                return session
            self._set_state(session, "CANCELLING")
            client = self._ensure_client()
            if session.session_id is None:
                return self._set_state(session, "CANCELLED", outcome="cancelled")
            errors: list[str] = []
            try:
                for permission in client.list_permissions(session.session_id):
                    request_id = permission.get("id")
                    if request_id:
                        client.reply_permission(
                            session.session_id,
                            str(request_id),
                            "reject",
                            message="build cancelled",
                        )
            except Exception as exc:  # noqa: BLE001 - cancellation boundary
                errors.append(f"permission cleanup: {type(exc).__name__}: {exc}")
            try:
                client.interrupt(session.session_id, resume=False)
            except Exception as exc:  # noqa: BLE001 - cancellation boundary
                errors.append(f"interrupt: {type(exc).__name__}: {exc}")
            try:
                client.delete_session(session.session_id)
            except Exception as exc:  # noqa: BLE001 - cancellation boundary
                errors.append(f"delete session: {type(exc).__name__}: {exc}")
            error = "; ".join(errors) if errors else None
            self._append_adapter_event(
                session, "build_cancelled", errors=errors
            )
            return self._set_state(
                session,
                "CANCELLED",
                outcome="cancelled",
                error=error,
            )

    def collect_artifacts(self, build_id: str) -> dict[str, str]:
        with self._lock:
            session = self._require(build_id)
            artifacts = session.workspace.artifact_map()
            session.workspace.update_result(artifacts=artifacts)
            return artifacts

    def close(self, build_id: str) -> BuildSession:
        with self._lock:
            session = self._require(build_id)
            if not session.terminal:
                if session.session_id is not None:
                    try:
                        self._ensure_client().delete_session(session.session_id)
                    except Exception as exc:  # noqa: BLE001 - close boundary
                        session.error = f"delete session: {type(exc).__name__}: {exc}"
                self._set_state(session, "FINISHED", outcome=session.outcome or "closed")
            if self._owns_server and self.server is not None:
                self.server.stop()
                self.client = None
            session.workspace.update_result(
                state=session.state,
                outcome=session.outcome,
                artifacts=session.workspace.artifact_map(),
                harness=session.harness,
                session_id=session.session_id,
                error=session.error,
            )
            return session

    def status(self, build_id: str) -> BuildSession:
        return self._require(build_id)
