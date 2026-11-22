"""Local FastAPI surface for the D08 read-only and control slices."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import threading
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..execution import build_task
from ..model import ContractError
from ..runtime.models import Task, WorkItem
from ..runtime.rule import RuleError, load_rule
from ..runtime.store import (
    RequestConflictError,
    TaskNotFoundError,
    TaskStore,
    TaskTransitionError,
)
from ..runtime.worker import Worker

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).with_name("static")
BATCH_DIST_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"
EXPORT_FILES = (
    "products.csv",
    "task-result.json",
    "records.jsonl",
    "diagnostics/excluded.jsonl",
    "diagnostics/failed.jsonl",
)


class Limits(BaseModel):
    max_urls: int = Field(default=100, ge=1, le=100000)
    max_products: int = Field(default=20, ge=1, le=10000)
    max_seconds: int = Field(default=180, ge=1, le=86400)
    max_attempts: int = Field(default=2, ge=1, le=10)


class CreateTaskRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    rule_id: str
    rule_version: str
    task_type: Literal["product", "discovery"] = "product"
    limits: Limits = Field(default_factory=Limits)


def _load_result(out_root: Path, task_id: str) -> dict[str, Any]:
    path = out_root / task_id / "task-result.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _counts(store: TaskStore, task: Task, result: dict[str, Any]) -> dict[str, int]:
    raw = result.get("counts")
    if isinstance(raw, dict) and raw:
        return {
            str(key): int(value)
            for key, value in raw.items()
            if isinstance(value, int) and not isinstance(value, bool)
        }
    items = store.item_counts(task.task_id)
    return {
        "pending": items.get("PENDING", 0),
        "in_flight": items.get("IN_FLIGHT", 0),
        "valid_products": items.get("DONE", 0),
        "excluded": items.get("EXCLUDED", 0),
        "failed": items.get("FAILED", 0),
    }


def _summary(store: TaskStore, task: Task, out_root: Path) -> dict[str, Any]:
    result = _load_result(out_root, task.task_id)
    return {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "plan_id": task.plan_id,
        "plan_version": task.plan_version,
        "site_key": task.site_key or task.plan_id,
        "market": task.market,
        "state": task.state,
        "outcome": task.outcome,
        "stop_reason": task.stop_reason,
        "counts": _counts(store, task, result),
        "coverage": result.get("coverage") or {"status": "UNKNOWN"},
        "quality_exceptions": result.get("quality_exceptions") or [],
        "archived_at": task.archived_at,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _item_payload(item: WorkItem) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "item_type": item.item_type,
        "url": item.url,
        "state": item.state,
        "occurred_at": item.updated_at,
        "attempts": item.attempts,
        "failure_class": item.failure_class,
        "result": item.result,
    }


def _safe_filename(task: Task) -> str:
    raw = f"{task.task_id}-{task.plan_version}.zip"
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", raw)


WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _error(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _forbidden(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "error": {
                "code": "FORBIDDEN",
                "message": message,
                "details": {},
            }
        },
    )


def _hostname_only(host_header: str) -> str:
    value = host_header.strip().lower()
    if value.startswith("["):
        closing = value.find("]")
        return value[1:closing] if closing >= 0 else value
    if value.count(":") == 1:
        return value.rsplit(":", 1)[0]
    return value


def _is_loopback_host(host_header: str) -> bool:
    return _hostname_only(host_header) in LOOPBACK_HOSTS


def _origin_matches_host(origin: str, host_header: str) -> bool:
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    if parsed.scheme != "http" or not parsed.netloc:
        return False
    if not _is_loopback_host(parsed.netloc):
        return False
    return parsed.netloc.lower() == host_header.strip().lower()


def _sse(event: str, data: Any) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _rule_entries(rules_dir: Path | None) -> list[dict[str, Any]]:
    if rules_dir is None or not rules_dir.is_dir():
        return []
    root = rules_dir.resolve()
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in {".yaml", ".yml"} or not path.is_file():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            continue
        entry: dict[str, Any] = {
            "path": resolved.relative_to(root).as_posix(),
            "rule_id": None,
            "rule_version": None,
            "task_types": [],
            "site": None,
            "market": None,
            "locale": None,
            "currency": None,
            "valid": False,
            "errors": [],
        }
        try:
            rule = load_rule(resolved)
        except Exception as exc:  # noqa: BLE001 - invalid rules are catalog data
            entry["errors"].append(f"{type(exc).__name__}: {exc}")
        else:
            site = rule.site if isinstance(rule.site, dict) else {}
            capabilities = (
                rule.capabilities if isinstance(rule.capabilities, dict) else {}
            )
            entry.update(
                {
                    "rule_id": rule.rule_id,
                    "rule_version": rule.rule_version,
                    "task_types": [
                        name
                        for name in ("product", "discovery")
                        if capabilities.get(name)
                    ],
                    "site": site.get("name"),
                    "market": site.get("market"),
                    "locale": site.get("locale"),
                    "currency": site.get("currency"),
                    "valid": True,
                }
            )
        entries.append(entry)

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entry in entries:
        if entry["valid"] and entry["rule_id"] and entry["rule_version"]:
            groups.setdefault(
                (str(entry["rule_id"]), str(entry["rule_version"])), []
            ).append(entry)
    for group in groups.values():
        if len(group) > 1:
            for entry in group:
                entry["valid"] = False
                entry["errors"].append("duplicate rule_id/version")
    entries.sort(
        key=lambda entry: (
            str(entry["rule_id"] or ""),
            str(entry["rule_version"] or ""),
            str(entry["path"]),
        )
    )
    return entries


def create_app(
    db_path: str | Path,
    out_root: str | Path,
    rules_dir: str | Path | None = None,
    *,
    manage_worker: bool = False,
    max_tasks: int = 1,
    max_browser_tasks: int = 1,
    per_domain_rps: float = 1.0,
    lease_ttl_seconds: float = 30.0,
    heartbeat_interval: float | None = None,
) -> FastAPI:
    store = TaskStore(db_path)
    root = Path(out_root)
    root.mkdir(parents=True, exist_ok=True)
    rules = Path(rules_dir).resolve() if rules_dir is not None else None

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> Any:
        stop = threading.Event() if manage_worker else None
        thread: threading.Thread | None = None
        if stop is not None:
            worker = Worker(
                store,
                out_root=root,
                max_tasks=max_tasks,
                max_browser_tasks=max_browser_tasks,
                per_domain_rps=per_domain_rps,
                lease_ttl_seconds=lease_ttl_seconds,
                heartbeat_interval=heartbeat_interval,
            )
            thread = threading.Thread(
                target=worker.run_forever,
                kwargs={"stop_event": stop},
                name="managed-worker",
                daemon=True,
            )
            thread.start()
        try:
            yield
        finally:
            if stop is not None:
                stop.set()
            if thread is not None:
                thread.join(timeout=10)
                if thread.is_alive():
                    logger.warning("managed worker did not stop within 10s")

    app = FastAPI(
        title="ecom-crawler",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.store = store
    app.state.out_root = root
    app.state.rules_dir = rules
    app.state.worker_managed = manage_worker

    @app.middleware("http")
    async def same_origin_guard(request: Request, call_next: Any) -> Any:
        host = request.headers.get("host", "")
        if not _is_loopback_host(host):
            return _forbidden("request host is not loopback")
        if request.method.upper() in WRITE_METHODS:
            origin = request.headers.get("origin", "")
            if not _origin_matches_host(origin, host):
                return _forbidden("write requests require a same-origin loopback Origin")
            if request.headers.get("x-requested-with") != "XMLHttpRequest":
                return _forbidden("write requests require X-Requested-With: XMLHttpRequest")
        return await call_next(request)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": detail.get("code", "ERROR"),
                    "message": detail.get("message", str(exc.detail)),
                    "details": {},
                }
            },
        )

    def require_task(task_id: str) -> Task:
        task = store.get_task(task_id)
        if task is None:
            raise _error("NOT_FOUND", f"unknown task: {task_id}", 404)
        return task

    def control(task_id: str, action: str) -> dict[str, Any]:
        try:
            task = getattr(store, f"request_{action}")(task_id)
        except TaskNotFoundError as exc:
            raise _error("NOT_FOUND", str(exc), 404) from exc
        except TaskTransitionError as exc:
            raise _error("INVALID_STATE", str(exc), 409) from exc
        return {
            "accepted": True,
            "task_id": task.task_id,
            "state": task.state,
            "archived_at": task.archived_at,
        }

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "db": str(store.path),
            "tasks": len(store.list_tasks()),
            "worker": "managed" if manage_worker else "external",
            "max_tasks": max_tasks if manage_worker else None,
            "max_browser_tasks": max_browser_tasks if manage_worker else None,
            "rules_configured": rules is not None and rules.is_dir(),
        }

    @app.get("/api/rules")
    def list_rules() -> dict[str, Any]:
        return {
            "configured": rules is not None and rules.is_dir(),
            "items": _rule_entries(rules),
        }

    @app.get("/api/tasks")
    def list_tasks(
        state: Annotated[list[str] | None, Query()] = None,
        task_type: Annotated[str | None, Query()] = None,
        include_archived: Annotated[bool, Query()] = False,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        tasks = store.list_tasks(set(state) if state else None)
        tasks = [
            task
            for task in tasks
            if include_archived or task.archived_at is None
        ]
        if task_type:
            tasks = [task for task in tasks if task.task_type == task_type]
        total = len(tasks)
        return {
            "total": total,
            "items": [_summary(store, task, root) for task in tasks[offset : offset + limit]],
        }

    @app.post("/api/tasks", status_code=201)
    def create_task(payload: CreateTaskRequest) -> JSONResponse:
        if rules is None or not rules.is_dir():
            raise _error("RULES_NOT_CONFIGURED", "serve --rules-dir is not set", 400)
        entries = _rule_entries(rules)
        matches = [
            entry
            for entry in entries
            if entry.get("rule_id") == payload.rule_id
            and entry.get("rule_version") == payload.rule_version
        ]
        if not matches:
            raise _error("NOT_FOUND", "rule package not found", 404)
        if len(matches) != 1 or not matches[0]["valid"]:
            raise _error("INVALID_RULE", "rule package is invalid or duplicated", 400)
        entry = matches[0]
        if payload.task_type not in entry["task_types"]:
            raise _error(
                "INVALID_TASK_TYPE",
                f"rule does not support {payload.task_type}",
                400,
            )
        try:
            task = build_task(
                rule_path=rules / str(entry["path"]),
                task_id=f"web-{uuid.uuid4().hex[:12]}",
                task_type=payload.task_type,
                max_urls=payload.limits.max_urls,
                max_products=payload.limits.max_products,
                max_seconds=payload.limits.max_seconds,
                max_attempts=payload.limits.max_attempts,
            )
        except (RuleError, ContractError) as exc:
            raise _error("INVALID_RULE", str(exc), 400) from exc
        request_json = json.dumps(
            payload.model_dump(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            task, created = store.create_task_idempotent(
                task,
                payload.request_id,
                request_json,
            )
        except RequestConflictError as exc:
            raise _error("CONFLICT", str(exc), 409) from exc
        except ValueError as exc:
            raise _error("CONFLICT", str(exc), 409) from exc
        return JSONResponse(
            status_code=201 if created else 200,
            content={"created": created, "task": _summary(store, task, root)},
        )

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        return _summary(store, require_task(task_id), root)

    @app.get("/api/tasks/{task_id}/items")
    def list_items(
        task_id: str,
        kind: Annotated[str, Query(pattern="^(url|product)$")] = "product",
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        require_task(task_id)
        item_type = "navigation" if kind == "url" else "product"
        items = store.items(task_id, item_type)
        return {
            "total": len(items),
            "items": [_item_payload(item) for item in items[offset : offset + limit]],
        }

    @app.post("/api/tasks/{task_id}/start", status_code=202)
    def start_task(task_id: str) -> dict[str, Any]:
        return control(task_id, "start")

    @app.post("/api/tasks/{task_id}/pause", status_code=202)
    def pause_task(task_id: str) -> dict[str, Any]:
        return control(task_id, "pause")

    @app.post("/api/tasks/{task_id}/resume", status_code=202)
    def resume_task(task_id: str) -> dict[str, Any]:
        return control(task_id, "resume")

    @app.post("/api/tasks/{task_id}/cancel", status_code=202)
    def cancel_task(task_id: str) -> dict[str, Any]:
        return control(task_id, "cancel")

    @app.post("/api/tasks/{task_id}/archive", status_code=202)
    def archive_task(task_id: str) -> dict[str, Any]:
        return control(task_id, "archive")

    @app.post("/api/tasks/{task_id}/restore", status_code=202)
    def restore_task(task_id: str) -> dict[str, Any]:
        return control(task_id, "restore")

    @app.get("/api/tasks/{task_id}/events")
    async def task_events(task_id: str) -> StreamingResponse:
        require_task(task_id)

        async def stream() -> Any:
            yield _sse("snapshot", _summary(store, require_task(task_id), root))
            path = root / task_id / "events.ndjson"
            offset = path.stat().st_size if path.is_file() else 0
            last_heartbeat = time.monotonic()
            while True:
                if path.is_file():
                    size = path.stat().st_size
                    if size < offset:
                        offset = 0
                    if size > offset:
                        with path.open("r", encoding="utf-8") as handle:
                            handle.seek(offset)
                            chunk = handle.read()
                            offset = handle.tell()
                        for line in chunk.splitlines():
                            if line.strip():
                                yield _sse("update", line)
                current = store.get_task(task_id)
                if current is None:
                    break
                if current.state in {"FINISHED", "CANCELLED"}:
                    yield _sse("end", {"state": current.state})
                    break
                if time.monotonic() - last_heartbeat >= 15:
                    yield ": keep-alive\n\n"
                    last_heartbeat = time.monotonic()
                await asyncio.sleep(0.5)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/tasks/{task_id}/export")
    def export_task(task_id: str, partial: bool = False) -> Response:
        task = require_task(task_id)
        if task.state not in {"FINISHED", "CANCELLED"} and not partial:
            raise _error("EXPORT_NOT_READY", "task is not finished; use partial=true", 409)
        run_dir = (root / task_id).resolve()
        if not run_dir.is_dir():
            raise _error("NOT_FOUND", f"no output directory for task: {task_id}", 404)
        buffer = io.BytesIO()
        written = 0
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in EXPORT_FILES:
                path = (run_dir / name).resolve()
                if not path.is_relative_to(run_dir) or not path.is_file():
                    continue
                archive.write(path, arcname=name)
                written += 1
        if written == 0:
            raise _error("NOT_FOUND", "no exportable files", 404)
        headers = {"Content-Disposition": f'attachment; filename="{_safe_filename(task)}"'}
        return Response(
            content=buffer.getvalue(),
            media_type="application/zip",
            headers=headers,
        )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    if (BATCH_DIST_DIR / "index.html").is_file():
        app.mount(
            "/batch",
            StaticFiles(directory=BATCH_DIST_DIR, html=True),
            name="batch",
        )
    return app
