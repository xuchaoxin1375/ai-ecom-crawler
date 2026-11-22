"""Minimal BuildService over a HarnessAdapter (v1: one active build)."""

from __future__ import annotations

import threading
from collections import deque
from typing import Any

from .adapter import BuildSession, HarnessAdapter, HarnessStateError
from .dependency_bridge import DependencyBridge
from .models import BuildTask, HarnessEvent, utc_now

TERMINAL_STATES = {"CANCELLED", "FINISHED"}


class BuildService:
    """Own one active build session and its event/permission surface.

    This is deliberately a Python service boundary, not the Web UI.  The
    future build-session UI can read ``status``/``events`` and call the control
    methods without learning OpenCode specifics.
    """

    def __init__(self, adapter: HarnessAdapter, *, max_events: int = 2000) -> None:
        self.adapter = adapter
        self.sessions: dict[str, BuildSession] = {}
        self.events: dict[str, deque[HarnessEvent]] = {}
        self.held_permissions: dict[str, set[str]] = {}
        self.pending_permissions: dict[str, set[str]] = {}
        self.bridges: dict[str, DependencyBridge] = {}
        self._pumps: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        self._active_id: str | None = None
        self._max_events = max(1, int(max_events))

    @property
    def active_build_id(self) -> str | None:
        with self._lock:
            return self._active_id

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
    ) -> None:
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
        )

    def start_build(self, task: BuildTask) -> BuildSession:
        with self._lock:
            if self._active_id is not None:
                active = self.sessions.get(self._active_id)
                if active is not None and active.state not in TERMINAL_STATES:
                    raise HarnessStateError(
                        f"build {self._active_id} is still active"
                    )
            if task.build_id in self.sessions:
                raise HarnessStateError(f"build already exists: {task.build_id}")
            session = self.adapter.start_build(task)
            self.sessions[task.build_id] = session
            self.events[task.build_id] = deque(maxlen=self._max_events)
            self.held_permissions[task.build_id] = set()
            self.pending_permissions[task.build_id] = set()
            self._active_id = task.build_id
            thread = threading.Thread(
                target=self._pump,
                args=(task.build_id,),
                name=f"build-events-{task.build_id}",
                daemon=True,
            )
            self._pumps[task.build_id] = thread
            thread.start()
            bridge = DependencyBridge(
                session,
                self.adapter,
                is_paused=lambda: self._build_state(task.build_id)
                in {"PAUSING", "PAUSED"},
                is_active=lambda: self._build_state(task.build_id)
                not in TERMINAL_STATES,
                on_event=lambda event: self._record_event(
                    task.build_id, event
                ),
            )
            self.bridges[task.build_id] = bridge
            bridge.start()
            return session

    def _build_state(self, build_id: str) -> str:
        with self._lock:
            session = self.sessions.get(build_id)
            return session.state if session is not None else "FINISHED"

    def _record_event(self, build_id: str, event: HarnessEvent) -> None:
        with self._lock:
            log = self.events.get(build_id)
            if log is not None:
                log.append(event)

    def _stop_bridge(
        self,
        build_id: str,
        *,
        status: str = "cancelled",
        detail: str = "build closed before the dependency request was resolved",
    ) -> None:
        with self._lock:
            bridge = self.bridges.pop(build_id, None)
        if bridge is not None:
            bridge.stop(status=status, detail=detail)

    def _pump(self, build_id: str) -> None:
        session = self.sessions[build_id]
        try:
            for event in self.adapter.stream_events(build_id):
                with self._lock:
                    self.events[build_id].append(event)
                    self._handle_event(session, event)
                    terminal = session.state in TERMINAL_STATES
                if terminal:
                    self._stop_bridge(
                        build_id,
                        status="cancelled",
                        detail="build finished before the dependency request was resolved",
                    )
        except Exception as exc:  # noqa: BLE001 - event boundary
            with self._lock:
                self.events[build_id].append(
                    HarnessEvent(
                        type="error",
                        source_type="adapter.stream",
                        session_id=session.session_id,
                        data={"error": f"{type(exc).__name__}: {exc}"},
                        created_at=utc_now(),
                    )
                )
                session.error = f"{type(exc).__name__}: {exc}"
                if session.state not in TERMINAL_STATES:
                    self._set_state(session, "FINISHED", outcome="failed")
        finally:
            with self._lock:
                if session.state not in TERMINAL_STATES:
                    self._set_state(session, "FINISHED", outcome="closed")
                if self._active_id == build_id:
                    self._active_id = None
            self._stop_bridge(build_id)

    def _handle_event(self, session: BuildSession, event: HarnessEvent) -> None:
        if event.source_type == "session.execution.started":
            # A start event can arrive after a pause request; the pause wins.
            if session.state not in TERMINAL_STATES | {"PAUSING", "PAUSED"}:
                self._set_state(session, "RUNNING")
            return
        if event.type == "finished":
            self._set_state(
                session,
                "FINISHED",
                outcome=str(event.data.get("outcome") or "finished"),
            )
            if self._active_id == session.build_id:
                self._active_id = None
            return
        if event.type == "error" and event.source_type == "session.execution.failed":
            self._set_state(
                session,
                "FINISHED",
                outcome=str(event.data.get("outcome") or "failed"),
            )
            if self._active_id == session.build_id:
                self._active_id = None
            return
        if event.type == "permission_requested":
            request_id = event.data.get("id")
            if not request_id:
                return
            request_id = str(request_id)
            self.pending_permissions[session.build_id].add(request_id)
            if session.state in {"PAUSING", "PAUSED"}:
                self.held_permissions[session.build_id].add(request_id)
            return
        if event.type == "permission_replied":
            request_id = event.data.get("requestID")
            if request_id:
                self.pending_permissions[session.build_id].discard(str(request_id))
                self.held_permissions[session.build_id].discard(str(request_id))

    def send_prompt(self, build_id: str, text: str) -> dict[str, Any]:
        with self._lock:
            session = self._require(build_id)
            if session.state in TERMINAL_STATES:
                raise HarnessStateError(
                    f"cannot prompt build {build_id} in state {session.state}"
                )
            result = self.adapter.send_prompt(build_id, text)
            self._set_state(session, "RUNNING")
            return result

    def pause(self, build_id: str) -> BuildSession:
        with self._lock:
            session = self._require(build_id)
            if session.state in TERMINAL_STATES:
                return session
            session = self.adapter.pause(build_id)
            self.sessions[build_id] = session
            self._set_state(session, "PAUSING")
            self.held_permissions[build_id].update(
                self.pending_permissions[build_id]
            )
            return session

    def resume(self, build_id: str) -> BuildSession:
        with self._lock:
            session = self._require(build_id)
            if session.state not in {"PAUSING", "PAUSED"}:
                raise HarnessStateError(
                    f"cannot resume build {build_id} in state {session.state}"
                )
            session = self.adapter.resume(build_id)
            self.sessions[build_id] = session
            self._set_state(session, "RUNNING")
            held = sorted(self.held_permissions.get(build_id, set()))
            for request_id in held:
                try:
                    self.adapter.reply_permission(
                        build_id, request_id, "once"
                    )
                except Exception as exc:  # noqa: BLE001 - held permission boundary
                    session.error = f"held permission {request_id}: {exc}"
                self.held_permissions[build_id].discard(request_id)
                self.pending_permissions[build_id].discard(request_id)
            return session

    def reply_permission(
        self,
        build_id: str,
        request_id: str,
        decision: str,
        *,
        message: str | None = None,
    ) -> None:
        with self._lock:
            self._require(build_id)
            self.adapter.reply_permission(
                build_id, request_id, decision, message=message
            )
            self.held_permissions[build_id].discard(request_id)
            self.pending_permissions[build_id].discard(request_id)

    def cancel(self, build_id: str) -> BuildSession:
        with self._lock:
            session = self._require(build_id)
            if session.state in TERMINAL_STATES:
                return session
        self._stop_bridge(
            build_id,
            status="cancelled",
            detail="build cancelled before the dependency request was resolved",
        )
        with self._lock:
            session = self._require(build_id)
            if session.state in TERMINAL_STATES:
                return session
            session = self.adapter.cancel(build_id)
            self.sessions[build_id] = session
            self._set_state(session, "CANCELLED", outcome="cancelled")
            self.held_permissions[build_id].clear()
            self.pending_permissions[build_id].clear()
            if self._active_id == build_id:
                self._active_id = None
            return session

    def close(self, build_id: str) -> BuildSession:
        with self._lock:
            self._require(build_id)
        self._stop_bridge(
            build_id,
            status="cancelled",
            detail="build closed before the dependency request was resolved",
        )
        with self._lock:
            session = self._require(build_id)
            session = self.adapter.close(build_id)
            self.sessions[build_id] = session
            if session.state not in TERMINAL_STATES:
                self._set_state(session, "FINISHED", outcome="closed")
            self.held_permissions[build_id].clear()
            self.pending_permissions[build_id].clear()
            if self._active_id == build_id:
                self._active_id = None
            return session

    def status(self, build_id: str) -> BuildSession:
        with self._lock:
            return self._require(build_id)

    def event_log(self, build_id: str, *, since: int = 0) -> list[HarnessEvent]:
        with self._lock:
            self._require(build_id)
            return list(self.events[build_id])[max(0, int(since)) :]

    def pending_permission_ids(self, build_id: str) -> list[str]:
        with self._lock:
            self._require(build_id)
            return sorted(self.pending_permissions[build_id])

    def held_permission_ids(self, build_id: str) -> list[str]:
        with self._lock:
            self._require(build_id)
            return sorted(self.held_permissions[build_id])

    def list_permissions(self, build_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._require(build_id)
            return self.adapter.list_permissions(build_id)

    def request_dependency(
        self,
        build_id: str,
        request: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            self._require(build_id)
            return self.adapter.request_dependency(
                build_id, request, approved=approved
            )

    def pending_dependency_ids(self, build_id: str) -> list[str]:
        with self._lock:
            self._require(build_id)
            bridge = self.bridges.get(build_id)
        return bridge.pending_ids() if bridge is not None else []

    def reply_dependency(
        self,
        build_id: str,
        request_id: str,
        decision: str,
        *,
        message: str | None = None,
    ) -> dict[str, Any]:
        """Resolve one ``approval_required`` dependency request."""
        with self._lock:
            self._require(build_id)
            bridge = self.bridges.get(build_id)
        if bridge is None:
            raise HarnessStateError(
                f"build {build_id} has no active dependency bridge"
            )
        return bridge.resolve(request_id, decision, message=message)

    def result(self, build_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._require(build_id)
            return session.workspace.read_result()
