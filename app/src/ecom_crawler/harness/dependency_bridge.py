"""Two sides of the build-side ``request_dependency`` bridge.

The OpenCode plugin exposes one structured tool and speaks a small file
protocol under ``control/dependencies``:

* the tool writes ``requests/<id>.json`` and polls ``responses/<id>.json``;
* the host-side :class:`DependencyBridge` evaluates the request through the
  adapter policy, installs allowlisted packages (or holds an approval), and
  writes exactly one response.

Files keep the bridge independent of the harness transport and match the
existing pause-gate control convention.  The host never trusts the request
file for package validation; :class:`DependencyPolicy` does that again.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .models import HarnessEvent, utc_now

if TYPE_CHECKING:
    from .adapter import BuildSession, HarnessAdapter

PLUGIN_ID = "request-dependency"
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
APPROVAL_DECISIONS = {"once", "always", "approve", "approved", "allow"}
logger = logging.getLogger(__name__)
STATUS_EVENTS = {
    "available": "dependency_available",
    "installed": "dependency_installed",
    "failed": "dependency_failed",
    "denied": "dependency_denied",
    "approval_required": "dependency_approval_required",
    "cancelled": "dependency_denied",
    "timeout": "dependency_failed",
    "error": "dependency_failed",
}

PACKAGE_JSON = """\
{
  "name": "request-dependency",
  "private": true,
  "type": "module",
  "exports": { ".": "./index.js" }
}
"""

BRIDGE_SOURCE = r"""import { randomUUID } from "node:crypto"
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs"
import { join } from "node:path"

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const atomicWrite = (path, text) => {
  const temporary = `${path}.${process.pid}.tmp`
  writeFileSync(temporary, text, "utf8")
  renameSync(temporary, path)
}

export async function requestDependency(input, options = {}) {
  const controlDir = options.controlDir
  const timeoutMs = Number(options.timeoutMs) || 600000
  const pollMs = Number(options.pollMs) || 100
  if (!controlDir) {
    return { status: "error", package: "", detail: "control directory is not configured" }
  }
  const pkg = input && typeof input.package === "string" ? input.package.trim() : ""
  if (!pkg) {
    return { status: "denied", package: "", detail: "package is required" }
  }
  const requestId = randomUUID()
  const requestsDir = join(controlDir, "requests")
  const responsesDir = join(controlDir, "responses")
  mkdirSync(requestsDir, { recursive: true })
  mkdirSync(responsesDir, { recursive: true })
  const payload = {
    request_id: requestId,
    package: pkg,
    manager: input.manager || "uv",
    version: input.version || null,
    reason: input.reason || null,
    source: input.source || null,
    license: input.license || null,
    scope: input.scope || "build",
    fallback: input.fallback || null,
    created_at: new Date().toISOString(),
  }
  atomicWrite(
    join(requestsDir, `${requestId}.json`),
    JSON.stringify(payload, null, 2) + "\n",
  )
  const responsePath = join(responsesDir, `${requestId}.json`)
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (options.signal && options.signal.aborted) {
      return {
        status: "cancelled",
        request_id: requestId,
        package: pkg,
        detail: "tool execution was cancelled",
      }
    }
    if (existsSync(responsePath)) {
      let lastError = ""
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          return JSON.parse(readFileSync(responsePath, "utf8"))
        } catch (error) {
          lastError = String(error)
          await sleep(20)
        }
      }
      return {
        status: "error",
        request_id: requestId,
        package: pkg,
        detail: `invalid host response: ${lastError}`,
      }
    }
    await sleep(Math.min(pollMs, Math.max(deadline - Date.now(), 1)))
  }
  return {
    status: "timeout",
    request_id: requestId,
    package: pkg,
    detail: `no host response within ${timeoutMs} ms`,
  }
}
"""

PLUGIN_SOURCE = r"""import { Plugin } from "@opencode/plugin"
import { appendFileSync, mkdirSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { requestDependency } from "./bridge.js"

const controlDir = (ctx) => resolve(ctx.location.directory, "..", "control", "dependencies")
const logPath = (ctx) => resolve(ctx.location.directory, "..", "control", "dependency-bridge.log")

const log = (ctx, text) => {
  try {
    mkdirSync(dirname(logPath(ctx)), { recursive: true })
    appendFileSync(logPath(ctx), `${new Date().toISOString()} ${text}\n`)
  } catch {
    // Logging must never change the tool result.
  }
}

export default Plugin.define({
  id: "request-dependency",
  async setup(ctx) {
    const options = ctx.options || {}
    const timeoutMs = Number(options.timeout_ms) || 600000
    await ctx.tool.transform((editor) => {
      editor.add({
        name: "request_dependency",
        description:
          "Request one missing build dependency. The host checks the build baseline " +
          "and allowlist, installs into the build environment, or returns " +
          "approval_required. Do not run pip, uv or npm install directly.",
        input: {
          type: "object",
          properties: {
            package: { type: "string", description: "Package name, for example pyyaml" },
            manager: {
              type: "string",
              enum: ["uv", "pip", "npm", "system"],
              description: "Package manager expected to install it",
            },
            version: {
              type: "string",
              description: "Exact pinned version, for example 1.2.3; never 'latest'",
            },
            reason: { type: "string", description: "Why the build baseline is not enough" },
            source: {
              type: "string",
              description: "Official registry or approved mirror",
            },
            license: { type: "string", description: "Package license, or unknown" },
            scope: {
              type: "string",
              enum: ["build", "system"],
              description: "build installs into the build environment; system needs the operator",
            },
            fallback: {
              type: "string",
              description: "Alternative path if the dependency cannot be installed",
            },
          },
          required: [
            "package",
            "manager",
            "version",
            "reason",
            "source",
            "license",
            "scope",
            "fallback",
          ],
          additionalProperties: false,
        },
        options: { codemode: false },
        execute: async (input, context) => {
          const result = await requestDependency(input, {
            controlDir: controlDir(ctx),
            timeoutMs,
            signal: context && context.signal,
          })
          log(ctx, `request ${input.package} -> ${result.status}`)
          return { content: JSON.stringify(result, null, 2) }
        },
      })
    })
    log(ctx, "registered request_dependency")
  },
})
"""


def install_dependency_tool(work_dir: str | Path) -> Path:
    """Write the request-dependency plugin into a build workspace."""
    plugin_dir = Path(work_dir) / ".opencode" / "plugins" / PLUGIN_ID
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "package.json").write_text(PACKAGE_JSON, encoding="utf-8")
    (plugin_dir / "bridge.js").write_text(BRIDGE_SOURCE, encoding="utf-8")
    (plugin_dir / "index.js").write_text(PLUGIN_SOURCE, encoding="utf-8")
    return plugin_dir


def _safe_request_id(value: str, fallback: str) -> str:
    candidate = str(value or "").strip()
    return candidate if REQUEST_ID_RE.fullmatch(candidate) else fallback


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _read_request_text(path: Path) -> tuple[str | None, Exception | None]:
    """Read a request, retrying transient Windows sharing errors."""
    for attempt in range(3):
        try:
            return path.read_text(encoding="utf-8"), None
        except FileNotFoundError:
            return None, None
        except PermissionError as exc:
            if attempt == 2:
                return None, exc
            time.sleep(0.02)
        except OSError as exc:
            return None, exc
    return None, None


@dataclass
class PendingDependency:
    request_id: str
    payload: dict[str, Any]
    created_at: float = field(default_factory=time.monotonic)


class DependencyBridge:
    """Watch one build workspace and answer dependency requests.

    The bridge is host-side only.  It holds ``approval_required`` requests
    until :meth:`resolve` receives an operator decision, and cancels pending
    requests when the build closes.  A paused build does not lose requests:
    they stay on disk and are evaluated after resume.
    """

    def __init__(
        self,
        session: BuildSession,
        adapter: HarnessAdapter,
        *,
        is_paused: Callable[[], bool] | None = None,
        is_active: Callable[[], bool] | None = None,
        on_event: Callable[[HarnessEvent], None] | None = None,
        poll_interval: float = 0.2,
        approval_timeout: float = 300.0,
    ) -> None:
        self.session = session
        self.adapter = adapter
        self.is_paused = is_paused or (lambda: False)
        self.is_active = is_active or (lambda: True)
        self.on_event = on_event
        self.poll_interval = max(0.02, float(poll_interval))
        self.approval_timeout = max(0.0, float(approval_timeout))
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._pending: dict[str, PendingDependency] = {}
        self._thread: threading.Thread | None = None

    @property
    def requests_dir(self) -> Path:
        return self.session.workspace.dependency_requests_dir

    @property
    def responses_dir(self) -> Path:
        return self.session.workspace.dependency_responses_dir

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                name=f"dependency-bridge-{self.session.build_id}",
                daemon=True,
            )
            self._thread.start()

    def pending_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._pending)

    def process_once(self) -> None:
        if not self.is_active() or self.is_paused():
            return
        self._expire_pending()
        try:
            request_paths = sorted(self.requests_dir.glob("*.json"))
        except OSError:
            return
        for request_path in request_paths:
            request_id = _safe_request_id(request_path.stem, "")
            if not request_id:
                continue
            response_path = self.responses_dir / f"{request_id}.json"
            if response_path.is_file():
                continue
            with self._lock:
                if request_id in self._pending:
                    continue
            text, read_error = _read_request_text(request_path)
            if text is None:
                if read_error is None:
                    continue
                self._write_response(
                    request_id,
                    {
                        "status": "denied",
                        "package": "",
                        "request_id": request_id,
                        "detail": f"invalid request file: {type(read_error).__name__}",
                    },
                )
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                self._write_response(
                    request_id,
                    {
                        "status": "denied",
                        "package": "",
                        "request_id": request_id,
                        "detail": f"invalid request file: {type(exc).__name__}",
                    },
                )
                continue
            if not isinstance(payload, dict):
                self._write_response(
                    request_id,
                    {
                        "status": "denied",
                        "package": "",
                        "request_id": request_id,
                        "detail": "request file must be a JSON object",
                    },
                )
                continue
            payload.setdefault("request_id", request_id)
            try:
                decision = self.adapter.request_dependency(
                    self.session.build_id, payload
                )
            except Exception as exc:  # noqa: BLE001 - adapter boundary
                decision = {
                    "status": "error",
                    "package": str(payload.get("package") or ""),
                    "request_id": request_id,
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            if decision.get("status") == "approval_required":
                with self._lock:
                    self._pending[request_id] = PendingDependency(
                        request_id=request_id,
                        payload=payload,
                    )
                self._emit(request_id, decision)
                continue
            self._write_response(request_id, decision)
            self._emit(request_id, decision)

    def resolve(
        self,
        request_id: str,
        decision: str,
        *,
        message: str | None = None,
    ) -> dict[str, Any]:
        """Apply an operator decision to one held request."""
        with self._lock:
            pending = self._pending.pop(request_id, None)
        if pending is None:
            raise KeyError(f"unknown pending dependency: {request_id}")
        if decision in APPROVAL_DECISIONS:
            try:
                result = self.adapter.request_dependency(
                    self.session.build_id,
                    pending.payload,
                    approved=True,
                )
            except Exception as exc:  # noqa: BLE001 - adapter boundary
                result = {
                    "status": "error",
                    "package": str(pending.payload.get("package") or ""),
                    "request_id": request_id,
                    "detail": f"{type(exc).__name__}: {exc}",
                }
        else:
            result = {
                "status": "denied",
                "package": str(pending.payload.get("package") or ""),
                "version": pending.payload.get("version"),
                "request_id": request_id,
                "detail": message or "operator rejected the dependency request",
                "approved": False,
            }
        self._write_response(request_id, result)
        self._emit(request_id, result)
        return result

    def stop(
        self,
        *,
        status: str = "cancelled",
        detail: str = "build closed before the dependency request was resolved",
    ) -> None:
        self._stop.set()
        with self._lock:
            thread = self._thread
            self._thread = None
            pending = list(self._pending.values())
            self._pending.clear()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        for item in pending:
            response = {
                "status": status,
                "package": str(item.payload.get("package") or ""),
                "version": item.payload.get("version"),
                "request_id": item.request_id,
                "detail": detail,
                "approved": False,
            }
            self._write_response(item.request_id, response)
            self._emit(item.request_id, response, write_file=True)
        for request_path in sorted(self.requests_dir.glob("*.json")):
            request_id = _safe_request_id(request_path.stem, "")
            if not request_id:
                continue
            if (self.responses_dir / f"{request_id}.json").is_file():
                continue
            response = {
                "status": status,
                "package": "",
                "request_id": request_id,
                "detail": detail,
                "approved": False,
            }
            self._write_response(request_id, response)
            self._emit(request_id, response, write_file=True)

    def close(self, **kwargs: Any) -> None:
        self.stop(**kwargs)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.process_once()
            except Exception:
                # A broken request must not kill the poller; the next pass
                # re-reads the same files and can recover.
                logger.exception("dependency bridge pass failed")
            self._stop.wait(self.poll_interval)

    def _expire_pending(self) -> None:
        if self.approval_timeout <= 0:
            return
        now = time.monotonic()
        expired: list[PendingDependency] = []
        with self._lock:
            for request_id, item in list(self._pending.items()):
                if now - item.created_at >= self.approval_timeout:
                    expired.append(item)
                    self._pending.pop(request_id, None)
        for item in expired:
            response = {
                "status": "denied",
                "package": str(item.payload.get("package") or ""),
                "version": item.payload.get("version"),
                "request_id": item.request_id,
                "detail": "dependency approval timed out",
                "approved": False,
            }
            self._write_response(item.request_id, response)
            self._emit(item.request_id, response, write_file=True)

    def _write_response(
        self,
        request_id: str,
        payload: dict[str, Any],
    ) -> None:
        _atomic_json(self.responses_dir / f"{request_id}.json", payload)

    def _emit(
        self,
        request_id: str,
        payload: dict[str, Any],
        *,
        write_file: bool = False,
    ) -> None:
        event_type = STATUS_EVENTS.get(
            str(payload.get("status") or ""), "dependency_requested"
        )
        event = HarnessEvent(
            type=event_type,
            source_type="dependency_bridge",
            session_id=self.session.session_id,
            data={"request_id": request_id, **payload},
            created_at=utc_now(),
        )
        if write_file:
            try:
                self.session.workspace.append_event(event)
            except OSError:
                pass
        if self.on_event is not None:
            self.on_event(event)
