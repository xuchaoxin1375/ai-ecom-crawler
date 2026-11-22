"""Local FastAPI surface for the D08 read-only and control slices."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
import os
import re
import threading
import time
import uuid
import zipfile
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..builds import BuildError, BuildManager
from ..execution import build_task
from ..harness.adapter import HarnessStateError
from ..model import ContractError
from ..runtime.batch import parse_site_text, parse_sites, rule_domains
from ..runtime.models import Batch, BatchSite, Task, WorkItem, utc_now
from ..runtime.rule import RuleError, load_rule
from ..runtime.store import (
    BatchNotFoundError,
    BatchTransitionError,
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
    proxy: str | None = Field(default=None, max_length=500)


class BatchCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    country: str | None = Field(default=None, max_length=80)
    market: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=80)
    category: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=2000)
    sites: list[str] = Field(default_factory=list, max_length=5000)
    sites_text: str = Field(default="", max_length=500000)
    preview: bool = False


class BatchImportRequest(BaseModel):
    sites: list[str] = Field(default_factory=list, max_length=5000)
    sites_text: str = Field(default="", max_length=500000)


class BatchStartRequest(BaseModel):
    limits: Limits = Field(default_factory=Limits)
    proxy: str | None = Field(default=None, max_length=500)


class BuildStartRequest(BaseModel):
    max_products: int = Field(default=6, ge=1, le=50)
    max_seconds: int = Field(default=600, ge=60, le=3600)
    proxy: str | None = Field(default=None, max_length=500)
    capture_reasoning: bool = False


class BuildPermissionRequest(BaseModel):
    decision: Literal["once", "always", "reject"] = "once"
    message: str | None = Field(default=None, max_length=2000)


class BuildDependencyRequest(BaseModel):
    decision: Literal["once", "reject"] = "once"
    message: str | None = Field(default=None, max_length=2000)


def _mask_proxy(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "configured"
    if parsed.username or parsed.password:
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://***@{host}{port}"
    return value


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
        "domain_key": task.domain_key,
        "batch_id": task.batch_id,
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
        "started_at": task.started_at,
        "finished_at": task.finished_at,
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
            "domains": [],
            "status": None,
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
                    "domains": sorted(rule_domains(site)),
                    "status": rule.raw.get("status", "candidate"),
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
    build_manager: BuildManager | None = None,
    proxy: str | None = None,
) -> FastAPI:
    store = TaskStore(db_path)
    root = Path(out_root)
    root.mkdir(parents=True, exist_ok=True)
    rules = Path(rules_dir).resolve() if rules_dir is not None else None
    if (
        build_manager is None
        and rules is not None
        and os.environ.get("ECOM_BUILD_DISABLED") != "1"
    ):
        build_manager = BuildManager(store, root, rules, default_proxy=proxy)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> Any:
        if build_manager is not None:
            build_manager.reconcile()
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
                proxy=proxy,
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
            if build_manager is not None:
                build_manager.shutdown()
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
    app.state.build_manager = build_manager
    app.state.proxy = proxy

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

    ACTIVE_TASK_STATES = {"QUEUED", "RUNNING", "PAUSING", "PAUSED", "CANCELLING"}
    READINESS_SKIP = {
        "needs_onboarding": "待接入：没有受管规则包",
        "building": "构建中：规则包尚未可采",
        "invalid": "无效条目：不进入采集",
        "duplicate": "重复条目：不进入采集",
    }

    def require_batch(batch_id: str) -> Batch:
        batch = store.get_batch(batch_id)
        if batch is None:
            raise _error("NOT_FOUND", f"unknown batch: {batch_id}", 404)
        return batch

    def site_values(payload: BatchCreateRequest | BatchImportRequest) -> list[str]:
        values = [value.strip() for value in payload.sites if value.strip()]
        values.extend(parse_site_text(payload.sites_text))
        return values

    def match_rule(
        site_key: str, entries: list[dict[str, Any]]
    ) -> tuple[dict[str, Any] | None, int]:
        matches = [
            entry
            for entry in entries
            if entry.get("valid")
            and entry.get("status") != "deprecated"
            and site_key in entry.get("domains", [])
        ]
        if not matches:
            return None, 0
        rank = {"verified": 2, "candidate": 1}
        matches.sort(
            key=lambda entry: (
                rank.get(str(entry.get("status")), 0),
                str(entry.get("rule_version") or ""),
                str(entry.get("path") or ""),
            )
        )
        return matches[-1], len(matches)

    def unique_site_key(prefix: str, value: str, used: set[str]) -> str:
        digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
        base = f"!{prefix}:{digest}"
        key = base
        index = 2
        while key in used:
            key = f"{base}:{index}"
            index += 1
        return key

    def import_sites(
        batch_id: str,
        values: list[str],
        existing: list[BatchSite],
        entries: list[dict[str, Any]],
        *,
        persist: bool,
    ) -> tuple[dict[str, Any], list[BatchSite]]:
        parsed = parse_sites(values)
        existing_input: dict[str, BatchSite] = {}
        for site in existing:
            existing_input.setdefault(site.input_value.strip(), site)
        existing_keys = {
            site.site_key: site
            for site in existing
            if not site.site_key.startswith("!")
        }
        used = {site.site_key for site in existing}
        rows: list[BatchSite] = []
        items: list[dict[str, Any]] = []
        counts: Counter[str] = Counter()
        for item in parsed:
            counts["total"] += 1
            same_input = existing_input.get(item.input_value.strip())
            rule: dict[str, Any] | None = None
            stored_key: str | None = None
            stored = False
            if same_input is not None:
                readiness = "duplicate"
                note = f"已在批次中：{same_input.domain}"
            elif not item.valid:
                readiness = "duplicate" if item.duplicate_of else "invalid"
                note = (
                    f"与首次出现的 {item.duplicate_of} 重复"
                    if item.duplicate_of
                    else (item.error or "网址无效")
                )
                stored = True
            elif item.site_key in existing_keys:
                readiness = "duplicate"
                note = f"与批次内 {existing_keys[item.site_key].domain} 重复"
                stored = True
            else:
                rule, match_count = match_rule(item.site_key or "", entries)
                if rule is None:
                    readiness = "needs_onboarding"
                    note = "未匹配受管规则包"
                else:
                    readiness = "ready"
                    note = f"已匹配 {rule['rule_id']}@{rule['rule_version']}"
                    if match_count > 1:
                        note += f"（{match_count} 个匹配，使用优先级最高的版本）"
                stored = True
            if stored:
                if readiness in {"ready", "needs_onboarding", "building"} and item.site_key:
                    site_key = item.site_key
                else:
                    site_key = unique_site_key(readiness, item.input_value, used)
                used.add(site_key)
                stored_key = site_key
                rows.append(
                    BatchSite(
                        batch_id=batch_id,
                        site_key=site_key,
                        domain=item.domain,
                        input_value=item.input_value,
                        readiness=readiness,
                        rule_id=rule["rule_id"] if rule else None,
                        rule_version=rule["rule_version"] if rule else None,
                        rule_path=rule["path"] if rule else None,
                        note=note,
                    )
                )
            counts[readiness] += 1
            items.append(
                {
                    "input_value": item.input_value,
                    "domain": item.domain,
                    "site_key": stored_key,
                    "readiness": readiness,
                    "reason": note,
                    "stored": stored,
                    "rule": (
                        {
                            "rule_id": rule["rule_id"],
                            "rule_version": rule["rule_version"],
                            "path": rule["path"],
                        }
                        if rule
                        else None
                    ),
                }
            )
        if persist and rows:
            store.add_batch_sites(rows)
        counts["accepted"] = counts["ready"] + counts["needs_onboarding"]
        summary = {
            key: counts[key]
            for key in (
                "total",
                "ready",
                "needs_onboarding",
                "duplicate",
                "invalid",
                "accepted",
            )
        }
        summary["stored"] = len(rows)
        return {"summary": summary, "items": items}, rows

    def batch_status(
        batch: Batch,
        sites: list[BatchSite],
        summaries: dict[str, dict[str, Any]],
    ) -> str:
        if batch.archived_at:
            return "ARCHIVED"
        if any(
            summary["state"] in ACTIVE_TASK_STATES
            for summary in summaries.values()
        ):
            return "RUNNING"
        started = [site for site in sites if site.task_id]
        ready = [site for site in sites if site.readiness == "ready"]
        needs = [
            site
            for site in sites
            if site.readiness in {"needs_onboarding", "building"}
        ]
        invalid = [
            site
            for site in sites
            if site.readiness in {"invalid", "duplicate"}
        ]
        if not started:
            if ready and (needs or invalid):
                return "PARTIAL_READY"
            return "DRAFT"
        unfinished = [site for site in ready if not site.task_id]
        complete = (
            len(summaries) == len(started)
            and all(
                summary["state"] == "FINISHED"
                and summary["outcome"] == "COMPLETED"
                for summary in summaries.values()
            )
            and not unfinished
            and not needs
        )
        return "FINISHED" if complete else "PARTIAL"

    def build_summary(build_id: str | None) -> dict[str, Any] | None:
        if not build_id:
            return None
        record = store.get_build(build_id)
        if record is None:
            return None
        return {
            "build_id": record.build_id,
            "state": record.state,
            "outcome": record.outcome,
            "proxy": _mask_proxy(record.proxy),
            "error": record.error,
            "rule": (
                {
                    "rule_id": record.rule_id,
                    "rule_version": record.rule_version,
                    "path": record.rule_path,
                }
                if record.rule_id
                else None
            ),
            "updated_at": record.updated_at,
        }

    def batch_payload(batch: Batch, *, detail: bool = False) -> dict[str, Any]:
        sites = store.list_batch_sites(batch.batch_id)
        tasks = {
            task.task_id: task
            for task in store.list_batch_tasks(batch.batch_id)
        }
        summaries = {
            task_id: _summary(store, task, root)
            for task_id, task in tasks.items()
        }
        readiness = Counter(site.readiness for site in sites)
        states = Counter(summary["state"] for summary in summaries.values())
        failed_tasks = sum(
            1
            for summary in summaries.values()
            if summary["state"] == "FINISHED"
            and summary["outcome"] == "FAILED"
        )
        partial_tasks = sum(
            1
            for summary in summaries.values()
            if summary["state"] == "FINISHED"
            and summary["outcome"] == "PARTIAL"
        )
        counts = {
            "sites": len(sites),
            "ready": readiness.get("ready", 0),
            "needs_onboarding": readiness.get("needs_onboarding", 0),
            "building": readiness.get("building", 0),
            "invalid": readiness.get("invalid", 0),
            "duplicate": readiness.get("duplicate", 0),
            "startable": sum(
                1
                for site in sites
                if site.readiness == "ready" and not site.task_id
            ),
            "tasks": len(summaries),
            "draft": states.get("DRAFT", 0),
            "queued": states.get("QUEUED", 0),
            "running": sum(
                states.get(state, 0)
                for state in ("RUNNING", "PAUSING", "CANCELLING")
            ),
            "paused": states.get("PAUSED", 0),
            "finished": states.get("FINISHED", 0),
            "cancelled": states.get("CANCELLED", 0),
            "failed": failed_tasks,
            "partial_tasks": partial_tasks,
        }
        payload: dict[str, Any] = {
            "batch_id": batch.batch_id,
            "name": batch.name,
            "country": batch.country,
            "market": batch.market,
            "language": batch.language,
            "category": batch.category,
            "note": batch.note,
            "status": batch_status(batch, sites, summaries),
            "archived_at": batch.archived_at,
            "created_at": batch.created_at,
            "updated_at": batch.updated_at,
            "counts": counts,
            "valid_products": sum(
                int(summary["counts"].get("valid_products", 0))
                for summary in summaries.values()
            ),
            "failed_products": sum(
                int(summary["counts"].get("failed_products", 0))
                for summary in summaries.values()
            ),
        }
        if detail:
            payload["sites"] = [
                {
                    "site_key": site.site_key,
                    "domain": site.domain,
                    "input_value": site.input_value,
                    "readiness": site.readiness,
                    "note": site.note,
                    "rule": (
                        {
                            "rule_id": site.rule_id,
                            "rule_version": site.rule_version,
                            "path": site.rule_path,
                        }
                        if site.rule_id
                        else None
                    ),
                    "task_id": site.task_id,
                    "task": summaries.get(site.task_id) if site.task_id else None,
                    "build_id": site.build_id,
                    "build": build_summary(site.build_id),
                    "proxy": _mask_proxy(site.proxy),
                    "proxy_configured": bool(site.proxy),
                    "created_at": site.created_at,
                    "updated_at": site.updated_at,
                }
                for site in sites
            ]
        return payload

    def control_batch(batch_id: str, action: str) -> dict[str, Any]:
        batch = require_batch(batch_id)
        if batch.archived_at is not None:
            raise _error("INVALID_STATE", "batch is archived", 409)
        accepted: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for site in store.list_batch_sites(batch_id):
            if not site.task_id:
                continue
            item = {
                "site_key": site.site_key,
                "domain": site.domain,
                "task_id": site.task_id,
            }
            task = store.get_task(site.task_id)
            if task is None:
                skipped.append({**item, "reason": "任务不存在"})
                continue
            if action == "pause" and task.state == "QUEUED":
                skipped.append(
                    {**item, "reason": "排队任务尚未运行，不能暂停；可取消"}
                )
                continue
            if task.state in {"FINISHED", "CANCELLED"}:
                skipped.append({**item, "reason": f"任务已结束（{task.state}）"})
                continue
            try:
                updated = getattr(store, f"request_{action}")(site.task_id)
            except TaskNotFoundError as exc:
                skipped.append({**item, "reason": str(exc)})
            except TaskTransitionError as exc:
                skipped.append({**item, "reason": str(exc)})
            else:
                accepted.append(
                    {**item, "state": updated.state, "outcome": updated.outcome}
                )
        return {
            "accepted": accepted,
            "skipped": skipped,
            "batch": batch_payload(batch, detail=True),
        }

    @app.get("/", include_in_schema=False)
    def index() -> Response:
        if (BATCH_DIST_DIR / "index.html").is_file():
            return RedirectResponse(url="/batch/", status_code=307)
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/legacy", include_in_schema=False)
    def legacy_index() -> FileResponse:
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
                proxy=payload.proxy,
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

    @app.get("/api/batches")
    def list_batches(
        status: Annotated[str | None, Query()] = None,
        country: Annotated[str | None, Query()] = None,
        category: Annotated[str | None, Query()] = None,
        include_archived: Annotated[bool, Query()] = False,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        batches = store.list_batches(include_archived=include_archived)
        items = [batch_payload(batch) for batch in batches]
        if status:
            wanted = status.strip().upper()
            items = [item for item in items if item["status"] == wanted]
        if country:
            wanted = country.strip().casefold()
            items = [
                item
                for item in items
                if (item["country"] or "").casefold() == wanted
            ]
        if category:
            wanted = category.strip().casefold()
            items = [
                item
                for item in items
                if (item["category"] or "").casefold() == wanted
            ]
        total = len(items)
        return {"total": total, "items": items[offset : offset + limit]}

    @app.post("/api/batches", status_code=201)
    def create_batch(payload: BatchCreateRequest) -> JSONResponse:
        entries = _rule_entries(rules)
        values = site_values(payload)
        if payload.preview:
            report, _ = import_sites("", values, [], entries, persist=False)
            return JSONResponse(
                status_code=200,
                content={
                    "created": False,
                    "preview": {
                        "name": payload.name.strip(),
                        "country": payload.country,
                        "market": payload.market,
                        "language": payload.language,
                        "category": payload.category,
                        "import": report,
                    },
                },
            )
        batch = Batch(
            batch_id=f"b-{uuid.uuid4().hex[:12]}",
            name=payload.name.strip(),
            country=payload.country,
            market=payload.market,
            language=payload.language,
            category=payload.category,
            note=payload.note,
        )
        try:
            store.create_batch(batch)
        except ValueError as exc:
            raise _error("CONFLICT", str(exc), 409) from exc
        report, _ = import_sites(
            batch.batch_id,
            values,
            [],
            entries,
            persist=True,
        )
        return JSONResponse(
            status_code=201,
            content={
                "created": True,
                "batch": batch_payload(require_batch(batch.batch_id), detail=True),
                "import": report,
            },
        )

    @app.get("/api/batches/{batch_id}")
    def get_batch(batch_id: str) -> dict[str, Any]:
        return batch_payload(require_batch(batch_id), detail=True)

    @app.post("/api/batches/{batch_id}/import")
    def import_batch(batch_id: str, payload: BatchImportRequest) -> dict[str, Any]:
        batch = require_batch(batch_id)
        if batch.archived_at is not None:
            raise _error("INVALID_STATE", "batch is archived", 409)
        report, _ = import_sites(
            batch_id,
            site_values(payload),
            store.list_batch_sites(batch_id),
            _rule_entries(rules),
            persist=True,
        )
        return {
            "batch_id": batch_id,
            "import": report,
            "batch": batch_payload(require_batch(batch_id), detail=True),
        }

    @app.post("/api/batches/{batch_id}/start", status_code=202)
    def start_batch(
        batch_id: str, payload: BatchStartRequest | None = None
    ) -> dict[str, Any]:
        batch = require_batch(batch_id)
        if batch.archived_at is not None:
            raise _error("INVALID_STATE", "batch is archived", 409)
        limits = payload.limits if payload is not None else Limits()
        proxy_override = payload.proxy if payload is not None else None
        entries = _rule_entries(rules)
        accepted: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for site in store.list_batch_sites(batch_id):
            item = {
                "site_key": site.site_key,
                "domain": site.domain,
                "task_id": site.task_id,
            }
            if site.task_id:
                skipped.append({**item, "reason": "站点已开始"})
                continue
            if site.readiness != "ready":
                skipped.append(
                    {
                        **item,
                        "reason": READINESS_SKIP.get(
                            site.readiness, f"站点状态为 {site.readiness}"
                        ),
                    }
                )
                continue
            if rules is None or not rules.is_dir():
                skipped.append({**item, "reason": "服务未配置规则目录"})
                continue
            rule = next(
                (
                    entry
                    for entry in entries
                    if entry.get("valid")
                    and entry.get("rule_id") == site.rule_id
                    and entry.get("rule_version") == site.rule_version
                ),
                None,
            )
            if rule is None:
                skipped.append({**item, "reason": "规则包不可用或已变更"})
                continue
            if "product" not in rule.get("task_types", []):
                skipped.append({**item, "reason": "规则包不支持商品任务"})
                continue
            try:
                task = build_task(
                    rule_path=rules / str(rule["path"]),
                    task_id=f"web-{uuid.uuid4().hex[:12]}",
                    task_type="product",
                    max_urls=limits.max_urls,
                    max_products=limits.max_products,
                    max_seconds=limits.max_seconds,
                    max_attempts=limits.max_attempts,
                    proxy=proxy_override or site.proxy,
                )
            except (RuleError, ContractError) as exc:
                skipped.append({**item, "reason": f"规则包无法构建任务：{exc}"})
                continue
            task.batch_id = batch_id
            task.site_key = site.site_key
            task.domain_key = site.site_key
            task.market = batch.market or rule.get("market")
            try:
                created = store.create_task_for_site(task, site_key=site.site_key)
            except BatchNotFoundError:
                skipped.append({**item, "reason": "站点在批次中不存在"})
                continue
            if not created:
                skipped.append({**item, "reason": "站点已开始"})
                continue
            try:
                store.request_start(task.task_id)
            except TaskTransitionError as exc:
                store.request_cancel(task.task_id)
                skipped.append({**item, "reason": f"任务受理失败：{exc}"})
                continue
            accepted.append(
                {
                    "site_key": site.site_key,
                    "domain": site.domain,
                    "task_id": task.task_id,
                }
            )
        return {
            "accepted": accepted,
            "skipped": skipped,
            "batch": batch_payload(require_batch(batch_id), detail=True),
        }

    @app.post("/api/batches/{batch_id}/pause", status_code=202)
    def pause_batch(batch_id: str) -> dict[str, Any]:
        return control_batch(batch_id, "pause")

    @app.post("/api/batches/{batch_id}/cancel", status_code=202)
    def cancel_batch(batch_id: str) -> dict[str, Any]:
        return control_batch(batch_id, "cancel")

    @app.post("/api/batches/{batch_id}/archive", status_code=202)
    def archive_batch(batch_id: str) -> dict[str, Any]:
        try:
            batch = store.request_archive_batch(batch_id)
        except BatchNotFoundError as exc:
            raise _error("NOT_FOUND", str(exc), 404) from exc
        except BatchTransitionError as exc:
            raise _error("INVALID_STATE", str(exc), 409) from exc
        return {"accepted": True, "batch": batch_payload(batch, detail=True)}

    @app.post("/api/batches/{batch_id}/restore", status_code=202)
    def restore_batch(batch_id: str) -> dict[str, Any]:
        try:
            batch = store.request_restore_batch(batch_id)
        except BatchNotFoundError as exc:
            raise _error("NOT_FOUND", str(exc), 404) from exc
        return {"accepted": True, "batch": batch_payload(batch, detail=True)}

    @app.get("/api/batches/{batch_id}/export")
    def export_batch(batch_id: str, partial: bool = False) -> Response:
        batch = require_batch(batch_id)
        sites = store.list_batch_sites(batch_id)
        tasks = {
            task.task_id: task
            for task in store.list_batch_tasks(batch_id)
        }
        if not partial and any(
            task.state in ACTIVE_TASK_STATES or task.state == "DRAFT"
            for task in tasks.values()
        ):
            raise _error(
                "EXPORT_NOT_READY",
                "batch has active tasks; use partial=true",
                409,
            )
        manifest_sites: list[dict[str, Any]] = []
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for site in sites:
                task = tasks.get(site.task_id) if site.task_id else None
                summary = _summary(store, task, root) if task else None
                files: list[str] = []
                if task is not None:
                    run_dir = root / task.task_id
                    if run_dir.is_dir():
                        for name in EXPORT_FILES:
                            path = (run_dir / name).resolve()
                            if not path.is_relative_to(run_dir.resolve()):
                                continue
                            if not path.is_file():
                                continue
                            safe_site = re.sub(
                                r"[^A-Za-z0-9_.-]+", "-", site.site_key
                            )
                            archive.write(
                                path, arcname=f"sites/{safe_site}/{name}"
                            )
                            files.append(name)
                if not site.task_id:
                    export_status = (
                        "not_started"
                        if site.readiness == "ready"
                        else site.readiness
                    )
                elif summary is None:
                    export_status = "missing"
                elif summary["state"] == "CANCELLED":
                    export_status = "partial" if files else "cancelled"
                elif summary["state"] in ACTIVE_TASK_STATES or summary["state"] == "DRAFT":
                    export_status = "running"
                elif summary["outcome"] == "COMPLETED":
                    export_status = "complete" if files else "missing"
                elif summary["outcome"] == "PARTIAL":
                    export_status = "partial"
                else:
                    export_status = "failed"
                manifest_sites.append(
                    {
                        "site_key": site.site_key,
                        "domain": site.domain,
                        "input_value": site.input_value,
                        "readiness": site.readiness,
                        "note": site.note,
                        "task_id": site.task_id,
                        "task_state": summary["state"] if summary else None,
                        "outcome": summary["outcome"] if summary else None,
                        "stop_reason": summary["stop_reason"] if summary else None,
                        "export_status": export_status,
                        "files": files,
                        "counts": summary["counts"] if summary else None,
                        "coverage": summary["coverage"] if summary else None,
                        "quality_exceptions": (
                            summary["quality_exceptions"] if summary else []
                        ),
                    }
                )
            manifest = {
                "generated_at": utc_now(),
                "batch": batch_payload(batch),
                "sites": manifest_sites,
            }
            archive.writestr(
                "batch.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
            text = io.StringIO()
            writer = csv.writer(text)
            writer.writerow(
                [
                    "site_key",
                    "domain",
                    "readiness",
                    "task_id",
                    "task_state",
                    "outcome",
                    "export_status",
                    "valid_products",
                    "failed_products",
                    "stop_reason",
                ]
            )
            for item in manifest_sites:
                counts = item["counts"] or {}
                writer.writerow(
                    [
                        item["site_key"],
                        item["domain"],
                        item["readiness"],
                        item["task_id"] or "",
                        item["task_state"] or "",
                        item["outcome"] or "",
                        item["export_status"],
                        counts.get("valid_products", 0),
                        counts.get("failed_products", 0),
                        item["stop_reason"] or "",
                    ]
                )
            archive.writestr("sites.csv", text.getvalue().encode("utf-8-sig"))
        headers = {
            "Content-Disposition": (
                f'attachment; filename="'
                f"{re.sub(r'[^A-Za-z0-9_.-]+', '-', batch.batch_id)}-batch.zip\""
            )
        }
        return Response(
            content=buffer.getvalue(),
            media_type="application/zip",
            headers=headers,
        )

    def require_build(build_id: str) -> dict[str, Any]:
        if build_manager is None:
            raise _error(
                "BUILD_UNAVAILABLE",
                "build agent is not configured; start serve with --rules-dir",
                409,
            )
        record = store.get_build(build_id)
        if record is None:
            raise _error("NOT_FOUND", f"unknown build: {build_id}", 404)
        return build_manager.describe(build_id)

    def build_failure(exc: Exception) -> HTTPException:
        if isinstance(exc, KeyError):
            return _error("NOT_FOUND", str(exc), 404)
        return _error("BUILD_CONFLICT", str(exc), 409)

    @app.get("/api/builds")
    def list_builds(
        batch_id: str | None = None,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        if build_manager is None:
            raise _error("BUILD_UNAVAILABLE", "build agent is not configured", 409)
        records = store.list_builds(batch_id=batch_id, limit=limit)
        return {
            "builds": [
                build_manager.describe(record.build_id, event_limit=1)
                for record in records
            ]
        }

    @app.post(
        "/api/batches/{batch_id}/sites/{site_key}/build",
        status_code=202,
    )
    def start_site_build(
        batch_id: str,
        site_key: str,
        payload: BuildStartRequest | None = None,
    ) -> dict[str, Any]:
        if build_manager is None:
            raise _error(
                "BUILD_UNAVAILABLE",
                "build agent is not configured; start serve with --rules-dir",
                409,
            )
        batch = require_batch(batch_id)
        site = store.get_batch_site(batch_id, site_key)
        if site is None:
            raise _error("NOT_FOUND", f"unknown batch site: {site_key}", 404)
        request = payload or BuildStartRequest()
        try:
            record = build_manager.start(
                batch,
                site,
                max_products=request.max_products,
                max_seconds=request.max_seconds,
                proxy=request.proxy,
                capture_reasoning=request.capture_reasoning,
            )
        except BuildError as exc:
            raise _error("BUILD_CONFLICT", str(exc), 409) from exc
        return {
            "accepted": True,
            "build": build_manager.describe(record.build_id),
        }

    @app.get("/api/builds/{build_id}")
    def get_build(build_id: str) -> dict[str, Any]:
        return {"build": require_build(build_id)}

    @app.get("/api/builds/{build_id}/messages")
    def get_build_messages(build_id: str) -> dict[str, Any]:
        require_build(build_id)
        try:
            return build_manager.messages(build_id)
        except KeyError as exc:
            raise _error("NOT_FOUND", str(exc), 404) from exc

    @app.get("/api/builds/{build_id}/trace")
    def get_build_trace(
        build_id: str,
        format: Literal["json", "md"] = "md",
    ) -> FileResponse:
        require_build(build_id)
        record = store.get_build(build_id)
        if record is None or not record.workspace:
            raise _error("NOT_FOUND", f"unknown build: {build_id}", 404)
        name = "trace.md" if format == "md" else "trace.json"
        path = Path(record.workspace) / "out" / name
        if not path.is_file():
            raise _error("NOT_FOUND", f"build trace is not available: {name}", 404)
        return FileResponse(
            path,
            media_type="text/markdown; charset=utf-8"
            if format == "md"
            else "application/json",
            filename=f"{build_id}-{name}",
        )

    @app.post("/api/builds/{build_id}/pause", status_code=202)
    def pause_build(build_id: str) -> dict[str, Any]:
        require_build(build_id)
        try:
            payload = build_manager.pause(build_id)
        except (HarnessStateError, ValueError) as exc:
            raise build_failure(exc) from exc
        return {"accepted": True, "build": payload}

    @app.post("/api/builds/{build_id}/resume", status_code=202)
    def resume_build(build_id: str) -> dict[str, Any]:
        require_build(build_id)
        try:
            payload = build_manager.resume(build_id)
        except (HarnessStateError, ValueError) as exc:
            raise build_failure(exc) from exc
        return {"accepted": True, "build": payload}

    @app.post("/api/builds/{build_id}/cancel", status_code=202)
    def cancel_build(build_id: str) -> dict[str, Any]:
        require_build(build_id)
        try:
            payload = build_manager.cancel(build_id)
        except (HarnessStateError, ValueError) as exc:
            raise build_failure(exc) from exc
        return {"accepted": True, "build": payload}

    @app.post(
        "/api/builds/{build_id}/permissions/{request_id}",
        status_code=202,
    )
    def reply_build_permission(
        build_id: str,
        request_id: str,
        payload: BuildPermissionRequest,
    ) -> dict[str, Any]:
        require_build(build_id)
        try:
            result = build_manager.reply_permission(
                build_id,
                request_id,
                payload.decision,
                message=payload.message,
            )
        except (HarnessStateError, ValueError) as exc:
            raise build_failure(exc) from exc
        return {"accepted": True, "build": result}

    @app.post(
        "/api/builds/{build_id}/dependencies/{request_id}",
        status_code=202,
    )
    def reply_build_dependency(
        build_id: str,
        request_id: str,
        payload: BuildDependencyRequest,
    ) -> dict[str, Any]:
        require_build(build_id)
        try:
            result = build_manager.reply_dependency(
                build_id,
                request_id,
                payload.decision,
                message=payload.message,
            )
        except (HarnessStateError, ValueError) as exc:
            raise build_failure(exc) from exc
        return {"accepted": True, "build": result}

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    if (BATCH_DIST_DIR / "index.html").is_file():
        app.mount(
            "/batch",
            StaticFiles(directory=BATCH_DIST_DIR, html=True),
            name="batch",
        )
    return app
