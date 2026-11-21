"""Read-only FastAPI surface for the first D08 slice."""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..runtime.models import Task, WorkItem
from ..runtime.rule import load_rule
from ..runtime.store import TaskStore

STATIC_DIR = Path(__file__).with_name("static")
EXPORT_FILES = (
    "products.csv",
    "task-result.json",
    "records.jsonl",
    "diagnostics/excluded.jsonl",
    "diagnostics/failed.jsonl",
)
ITEM_STATES = ("PENDING", "IN_FLIGHT", "DONE", "EXCLUDED", "FAILED")


def _load_result(out_root: Path, task_id: str) -> dict[str, Any]:
    path = out_root / task_id / "task-result.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _rule_site(task: Task) -> tuple[str | None, str | None]:
    rule_path = task.input.get("rule_path")
    if not rule_path:
        return None, None
    try:
        site = load_rule(Path(str(rule_path))).site
    except Exception:  # noqa: BLE001 - a missing rule must not break the list
        return None, None
    name = site.get("name")
    market = site.get("market")
    return (str(name) if name else None, str(market) if market else None)


def _counts(store: TaskStore, task: Task, result: dict[str, Any]) -> dict[str, int]:
    raw = result.get("counts")
    if isinstance(raw, dict) and raw:
        return {str(key): int(value) for key, value in raw.items() if isinstance(value, int)}
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
    site_key, market = _rule_site(task)
    return {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "plan_id": task.plan_id,
        "plan_version": task.plan_version,
        "site_key": site_key or task.plan_id,
        "market": market,
        "state": task.state,
        "outcome": task.outcome,
        "stop_reason": task.stop_reason,
        "counts": _counts(store, task, result),
        "coverage": result.get("coverage") or {"status": "UNKNOWN"},
        "quality_exceptions": result.get("quality_exceptions") or [],
        "archived_at": None,
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


def _error(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def create_app(db_path: str | Path, out_root: str | Path) -> FastAPI:
    store = TaskStore(db_path)
    root = Path(out_root)
    root.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title="ecom-crawler",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store = store
    app.state.out_root = root

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
            "worker": "external",
        }

    @app.get("/api/tasks")
    def list_tasks(
        state: Annotated[list[str] | None, Query()] = None,
        task_type: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        tasks = store.list_tasks(set(state) if state else None)
        if task_type:
            tasks = [task for task in tasks if task.task_type == task_type]
        total = len(tasks)
        page = tasks[offset : offset + limit]
        return {
            "total": total,
            "items": [_summary(store, task, root) for task in page],
        }

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        task = store.get_task(task_id)
        if task is None:
            raise _error("NOT_FOUND", f"unknown task: {task_id}", 404)
        return _summary(store, task, root)

    @app.get("/api/tasks/{task_id}/items")
    def list_items(
        task_id: str,
        kind: Annotated[str, Query(pattern="^(url|product)$")] = "product",
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        if store.get_task(task_id) is None:
            raise _error("NOT_FOUND", f"unknown task: {task_id}", 404)
        item_type = "navigation" if kind == "url" else "product"
        items = store.items(task_id, item_type)
        return {
            "total": len(items),
            "items": [_item_payload(item) for item in items[offset : offset + limit]],
        }

    @app.get("/api/tasks/{task_id}/export")
    def export_task(task_id: str, partial: bool = False) -> Response:
        task = store.get_task(task_id)
        if task is None:
            raise _error("NOT_FOUND", f"unknown task: {task_id}", 404)
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
    return app
