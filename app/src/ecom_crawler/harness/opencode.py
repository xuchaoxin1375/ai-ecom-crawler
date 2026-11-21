"""HTTP/SSE client and subprocess manager for ``opencode serve``.

Only the v2 endpoints named in ADR 0006 are used here.  The server API is
experimental, so this module is the single place that knows endpoint paths,
request shapes and the Basic-auth convention (username ``opencode`` plus
``OPENCODE_PASSWORD``).
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, Self

from ..runtime.resources import terminate_process

OPENCODE_USERNAME = "opencode"
SERVER_LOG_LINES = 200


class OpenCodeError(ValueError):
    """Base error for the OpenCode adapter."""


class OpenCodeProtocolError(OpenCodeError):
    """Raised when the server response does not match the known contract."""


class OpenCodeHttpError(OpenCodeError):
    def __init__(self, status: int, code: str, message: str, body: Any) -> None:
        super().__init__(f"OpenCode HTTP {status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.body = body


class OpenCodeServerError(OpenCodeError):
    """Raised when the local server cannot be started or stopped."""


def resolve_opencode_command() -> list[str]:
    """Resolve a spawnable OpenCode command on Windows, macOS and Linux."""
    configured = os.environ.get("OPENCODE_BIN")
    if configured:
        return [configured]
    for name in ("opencode.exe", "opencode"):
        found = shutil.which(name)
        if not found:
            continue
        path = Path(found)
        if path.suffix.lower() in {".cmd", ".bat"}:
            candidate = (
                path.parent
                / "node_modules"
                / "@opencode"
                / "cli"
                / "bin"
                / "opencode.exe"
            )
            if candidate.is_file():
                return [str(candidate)]
            if os.name == "nt":
                return ["cmd.exe", "/c", str(path)]
        return [str(path)]
    raise OpenCodeServerError(
        "opencode executable not found; set OPENCODE_BIN or add opencode to PATH"
    )


def find_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _basic_auth(password: str) -> str:
    token = base64.b64encode(
        f"{OPENCODE_USERNAME}:{password}".encode()
    ).decode("ascii")
    return f"Basic {token}"


def _parse_sse(response: Any) -> Iterator[dict[str, Any]]:
    data_lines: list[str] = []
    for raw_line in response:
        line = raw_line.decode("utf-8", "replace") if isinstance(raw_line, bytes) else raw_line
        line = line.rstrip("\r\n")
        if not line:
            if data_lines:
                payload = "\n".join(data_lines)
                data_lines = []
                try:
                    value = json.loads(payload)
                except json.JSONDecodeError as exc:
                    raise OpenCodeProtocolError(
                        f"invalid SSE JSON: {payload[:200]}"
                    ) from exc
                if isinstance(value, dict):
                    yield value
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if field == "data":
            data_lines.append(value)


class OpenCodeClient:
    """Small stdlib HTTP client for the v1 OpenCode endpoint subset."""

    def __init__(
        self,
        base_url: str,
        password: str,
        *,
        timeout: float = 30.0,
        stream_timeout: float = 300.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.password = password
        self.timeout = max(float(timeout), 0.1)
        self.stream_timeout = max(float(stream_timeout), 0.1)
        self._headers = {
            "Authorization": _basic_auth(password),
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=self._headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout if timeout is None else timeout
            ) as response:
                body = response.read()
                if not body:
                    return None
                try:
                    return json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise OpenCodeProtocolError(
                        f"invalid JSON from {path}: {body[:200]!r}"
                    ) from exc
        except urllib.error.HTTPError as exc:
            body = exc.read()
            code = "HTTP_ERROR"
            message = str(exc)
            parsed: Any = None
            try:
                parsed = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                parsed = body.decode("utf-8", "replace")[:1000]
            if isinstance(parsed, dict):
                code = str(parsed.get("_tag") or parsed.get("code") or code)
                message = str(parsed.get("message") or message)
            raise OpenCodeHttpError(exc.code, code, message, parsed) from exc
        except urllib.error.URLError as exc:
            raise OpenCodeError(f"cannot reach {path}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise OpenCodeError(f"timeout for {path}") from exc

    def info(self) -> dict[str, Any]:
        payload = self._request("GET", "/api/info")
        if not isinstance(payload, dict):
            raise OpenCodeProtocolError("server info is not an object")
        return payload

    def create_session(
        self,
        *,
        directory: str,
        title: str | None = None,
        model: dict[str, Any] | None = None,
        permissions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"location": {"directory": directory}}
        if title:
            payload["title"] = title
        if model:
            payload["model"] = model
        if permissions is not None:
            payload["permissions"] = permissions
        response = self._request("POST", "/api/session", payload)
        data = response.get("data") if isinstance(response, dict) else None
        if not isinstance(data, dict) or not data.get("id"):
            raise OpenCodeProtocolError("session.create returned no data.id")
        return data

    def get_session(self, session_id: str) -> dict[str, Any]:
        response = self._request("GET", f"/api/session/{_quote(session_id)}")
        data = response.get("data") if isinstance(response, dict) else None
        if not isinstance(data, dict):
            raise OpenCodeProtocolError("session.get returned no data")
        return data

    def delete_session(self, session_id: str) -> None:
        self._request("DELETE", f"/api/session/{_quote(session_id)}")

    def send_prompt(self, session_id: str, text: str, **extra: Any) -> dict[str, Any]:
        payload = {"text": text, **extra}
        response = self._request(
            "POST", f"/api/session/{_quote(session_id)}/prompt", payload
        )
        data = response.get("data") if isinstance(response, dict) else None
        if not isinstance(data, dict):
            raise OpenCodeProtocolError("session.prompt returned no data")
        return data

    def switch_model(self, session_id: str, model: dict[str, Any]) -> None:
        self._request(
            "POST",
            f"/api/session/{_quote(session_id)}/model",
            {"model": model},
        )

    def interrupt(self, session_id: str, *, resume: bool = False) -> dict[str, Any]:
        query = "?resume=true" if resume else ""
        response = self._request(
            "POST", f"/api/session/{_quote(session_id)}/interrupt{query}"
        )
        return response if isinstance(response, dict) else {}

    def create_permission_request(
        self,
        session_id: str,
        *,
        action: str,
        resources: list[str],
        save: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action": action,
            "resources": resources,
        }
        if save is not None:
            payload["save"] = save
        if metadata is not None:
            payload["metadata"] = metadata
        response = self._request(
            "POST",
            f"/api/session/{_quote(session_id)}/permission",
            payload,
        )
        data = response.get("data") if isinstance(response, dict) else None
        if not isinstance(data, dict):
            raise OpenCodeProtocolError("permission.create returned no data")
        return data

    def list_permissions(self, session_id: str) -> list[dict[str, Any]]:
        response = self._request(
            "GET", f"/api/session/{_quote(session_id)}/permission"
        )
        data = response.get("data") if isinstance(response, dict) else None
        if data is None:
            return []
        if not isinstance(data, list):
            raise OpenCodeProtocolError("permission.list data is not a list")
        return [item for item in data if isinstance(item, dict)]

    def reply_permission(
        self,
        session_id: str,
        request_id: str,
        decision: str,
        *,
        message: str | None = None,
    ) -> None:
        if decision not in {"once", "always", "reject"}:
            raise ValueError(f"unsupported permission decision: {decision}")
        payload: dict[str, Any] = {"decision": decision}
        if message:
            payload["message"] = message
        self._request(
            "POST",
            f"/api/session/{_quote(session_id)}/permission/{_quote(request_id)}/reply",
            payload,
        )

    def messages(self, session_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            f"/api/session/{_quote(session_id)}/message?limit={int(limit)}",
        )
        data = response.get("data") if isinstance(response, dict) else None
        if data is None:
            return []
        if isinstance(data, dict):
            items = data.get("items") or data.get("messages")
            return list(items or [])
        return list(data) if isinstance(data, list) else []

    def export_session(
        self, session_id: str, *, sanitize: bool = True
    ) -> dict[str, Any]:
        query = "?sanitize=true" if sanitize else ""
        response = self._request(
            "GET",
            f"/api/experimental/session/{_quote(session_id)}/export{query}",
        )
        data = response.get("data") if isinstance(response, dict) else None
        if not isinstance(data, dict):
            raise OpenCodeProtocolError("session.export returned no data")
        return data

    def events(
        self,
        *,
        types: Sequence[str] | None = None,
        timeout: float | None = None,
    ) -> Iterator[dict[str, Any]]:
        query = ""
        if types:
            query = "?" + urllib.parse.urlencode([("types", item) for item in types])
        request = urllib.request.Request(
            self.base_url + "/api/event" + query,
            headers={
                "Authorization": _basic_auth(self.password),
                "Accept": "text/event-stream",
            },
        )
        try:
            response = urllib.request.urlopen(
                request,
                timeout=self.stream_timeout if timeout is None else timeout,
            )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:1000]
            raise OpenCodeHttpError(exc.code, "HTTP_ERROR", body, body) from exc
        try:
            yield from _parse_sse(response)
        finally:
            response.close()


class OpenCodeServer:
    """Own one loopback ``opencode serve`` process and its Basic-auth secret."""

    def __init__(
        self,
        *,
        command: Sequence[str] | None = None,
        host: str = "127.0.0.1",
        port: int | None = None,
        password: str | None = None,
        startup_timeout: float = 30.0,
        env: dict[str, str] | None = None,
    ) -> None:
        self.command = list(command) if command else None
        self.host = host
        self.port = int(port) if port else None
        self.password = password or secrets.token_urlsafe(24)
        self.startup_timeout = max(float(startup_timeout), 1.0)
        self.extra_env = dict(env or {})
        self.process: subprocess.Popen[str] | None = None
        self.client: OpenCodeClient | None = None
        self.base_url: str | None = None
        self.version: str | None = None
        self.info: dict[str, Any] = {}
        self.logs: deque[str] = deque(maxlen=SERVER_LOG_LINES)
        self._reader: threading.Thread | None = None
        self._lock = threading.RLock()

    def start(self) -> OpenCodeClient:
        with self._lock:
            if self.client is not None:
                return self.client
            command = self.command or resolve_opencode_command()
            port = self.port or find_free_port(self.host)
            env = os.environ.copy()
            env["OPENCODE_PASSWORD"] = self.password
            env.update(self.extra_env)
            try:
                self.process = subprocess.Popen(
                    [
                        *command,
                        "serve",
                        "--hostname",
                        self.host,
                        "--port",
                        str(port),
                        "--print-logs",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                    start_new_session=os.name != "nt",
                )
            except OSError as exc:
                raise OpenCodeServerError(f"cannot start opencode serve: {exc}") from exc
            self._reader = threading.Thread(
                target=self._read_output,
                name="opencode-server-log",
                daemon=True,
            )
            self._reader.start()
            self.base_url = f"http://{self.host}:{port}"
            self.client = OpenCodeClient(self.base_url, self.password)
            deadline = time.monotonic() + self.startup_timeout
            last_error: Exception | None = None
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise OpenCodeServerError(
                        f"opencode serve exited with {self.process.returncode}: "
                        + " | ".join(self.logs)
                    )
                try:
                    info = self.client.info()
                except Exception as exc:  # noqa: BLE001 - readiness loop
                    last_error = exc
                    time.sleep(0.1)
                    continue
                self.info = info
                self.version = str(info.get("version") or "") or None
                return self.client
            self.stop()
            raise OpenCodeServerError(
                f"opencode serve did not become ready: {last_error}"
            )

    def _read_output(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            self.logs.append(line.rstrip())
        try:
            process.stdout.close()
        except OSError:
            pass

    def stop(self) -> None:
        with self._lock:
            process = self.process
            if process is None:
                return
            if process.poll() is None:
                self._terminate_tree(process)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            if self._reader is not None:
                self._reader.join(timeout=2)
            self.process = None
            self.client = None

    @staticmethod
    def _terminate_tree(process: subprocess.Popen[str]) -> None:
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                return
            except (OSError, subprocess.SubprocessError):
                pass
            terminate_process(process.pid, grace_seconds=1.0)
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            terminate_process(process.pid, grace_seconds=1.0)
            return
        time.sleep(0.2)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *args: object) -> bool:
        self.stop()
        return False


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")
