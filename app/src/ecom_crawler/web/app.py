"""Local FastAPI surface for the D08 read-only and control slices."""

from __future__ import annotations

import asyncio
import base64
import binascii
import csv
import hashlib
import io
import json
import logging
import os
import platform
import re
import secrets
import shutil
import threading
import time
import uuid
import zipfile
from collections import Counter
from collections.abc import Iterable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
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
from ..build_models import ModelPoolError, discover_models, known_models
from ..builds import ACTIVE_BUILD_STATES, BuildError, BuildManager
from ..execution import build_task
from ..executor.runner import CSV_COLUMNS
from ..harness.adapter import HarnessStateError
from ..harness.dependencies import DependencyPolicy
from ..model import ContractError
from ..runtime.batch import (
    BATCH_COLLECTION_LIMITS,
    normalize_site,
    parse_site_text,
    parse_sites,
    rule_covers_entry,
    rule_domains,
    target_entry,
)
from ..runtime.models import (
    Batch,
    BatchSite,
    BuildContinuation,
    BuildRecord,
    QualityFeedback,
    RuleVersion,
    SiteRule,
    Task,
    WorkItem,
    utc_now,
)
from ..runtime.rule import RuleError, load_rule
from ..runtime.store import (
    BatchNotFoundError,
    BatchTransitionError,
    BuildContinuationConflictError,
    FeedbackNotFoundError,
    FeedbackRequestConflictError,
    FeedbackTransitionError,
    RequestConflictError,
    RuleActivationConflictError,
    RuleVersionError,
    TaskNotFoundError,
    TaskStore,
    TaskTransitionError,
)
from ..runtime.worker import Worker
from .access import (
    LOOPBACK_HOSTS,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    SETTING_LAN_ENABLED,
    SETTING_TOKEN,
    LoginRateLimiter,
    create_session,
    hash_token,
    is_loopback_bind,
    is_loopback_host,
    new_token,
    normalize_host_name,
    parse_token_setting,
    token_setting,
    validate_access_token,
    verify_session,
    verify_token,
)

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).with_name("static")
BATCH_DIST_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"
V2_DIST_DIR = Path(__file__).resolve().parents[3] / "frontend-v2" / "dist"
EXPORT_FILES = (
    "products.csv",
    "task-result.json",
    "records.jsonl",
    "diagnostics/excluded.jsonl",
    "diagnostics/failed.jsonl",
)


class Limits(BaseModel):
    max_urls: int | None = Field(default=100, ge=1, le=100000)
    max_products: int | None = Field(default=20, ge=1, le=10000)
    max_seconds: int | None = Field(default=180, ge=1, le=86400)
    max_attempts: int = Field(default=2, ge=1, le=10)


class CreateTaskRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    rule_id: str
    rule_version: str
    task_type: Literal["product", "discovery"] = "product"
    limits: Limits = Field(default_factory=Limits)
    proxy: str | None = Field(default=None, max_length=500)


FeedbackCategory = Literal[
    "DISCOVERY",
    "IDENTITY",
    "PRICE_CURRENCY_UNIT",
    "DESCRIPTION",
    "BASIC_FIELDS",
    "ACCESS_RUNTIME",
    "BUSINESS_EXPECTATION",
    "OTHER",
]
FeedbackStatus = Literal[
    "OPEN",
    "TRIAGED",
    "REPAIRING",
    "AWAITING_ACTIVATION",
    "AWAITING_RERUN",
    "RERUN_PENDING",
    "RESOLVED",
    "WONTFIX",
]
FeedbackTriage = Literal["RULE_REPAIR", "RUNTIME", "BUSINESS", "DUPLICATE"]
FeedbackResolution = Literal["RESOLVED", "WONTFIX", "DUPLICATE"]


class FeedbackCreateRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    category: FeedbackCategory
    samples: list[str] = Field(default_factory=list, max_length=50)
    expectation: str = Field(min_length=1, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)
    scope: str | None = Field(default=None, max_length=500)
    created_by: str | None = Field(default=None, max_length=120)


class FeedbackTriageRequest(BaseModel):
    request_id: str | None = Field(default=None, max_length=200)
    triage: FeedbackTriage
    note: str | None = Field(default=None, max_length=2000)
    duplicate_of: str | None = Field(default=None, max_length=200)
    actor: str | None = Field(default=None, max_length=120)


class FeedbackRuleRef(BaseModel):
    rule_id: str
    rule_version: str | None = None
    sha256: str | None = None


class FeedbackRecord(BaseModel):
    feedback_id: str
    task_id: str
    batch_id: str | None = None
    site_key: str | None = None
    category: FeedbackCategory
    samples: list[str]
    expectation: str
    note: str | None = None
    scope: str
    status: FeedbackStatus
    triage: FeedbackTriage | None = None
    triage_note: str | None = None
    triage_source: str | None = None
    duplicate_of: str | None = None
    repair_build_id: str | None = None
    rerun_task_id: str | None = None
    resolution: FeedbackResolution | None = None
    resolution_note: str | None = None
    created_by: str
    resolved_by: str | None = None
    created_at: str
    updated_at: str
    closed_at: str | None = None
    rule: FeedbackRuleRef | None = None


class FeedbackCreateResponse(BaseModel):
    created: bool
    feedback: FeedbackRecord


class FeedbackListResponse(BaseModel):
    total: int
    items: list[FeedbackRecord]


class FeedbackTriageResponse(BaseModel):
    feedback: FeedbackRecord


class FeedbackRepairRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    model_ref: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=2000)
    max_products: int = Field(default=6, ge=1, le=50)
    max_seconds: int = Field(default=600, ge=60, le=3600)
    max_total_seconds: int | None = Field(default=None, ge=60, le=7200)
    max_input_tokens: int | None = Field(default=None, ge=1000, le=100_000_000)
    max_output_tokens: int | None = Field(default=None, ge=1000, le=10_000_000)
    repair_rounds: int | None = Field(default=None, ge=0, le=10)
    archive_mode: Literal["off", "sample", "full"] = "off"
    archive_sample_limit: int = Field(default=20, ge=1, le=1000)
    archive_root: str | None = Field(default=None, max_length=1000)
    archive_max_bytes: int | None = Field(default=None, ge=0)
    capture_reasoning: bool | None = Field(default=None)


class FeedbackRerunRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    limits: Limits = Field(default_factory=lambda: Limits())
    archive_mode: Literal["off", "sample", "full"] = "off"


class FeedbackResolveRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    resolution: Literal["RESOLVED", "WONTFIX"]
    note: str | None = Field(default=None, max_length=2000)
    actor: str | None = Field(default=None, max_length=120)


class RuleVersionRecord(BaseModel):
    rule_id: str
    rule_version: str
    sha256: str
    parent_version: str | None = None
    status: Literal["candidate", "active", "superseded", "rejected", "retired"]
    source_build_id: str | None = None
    source_feedback_id: str | None = None
    path: str
    created_at: str
    activated_at: str | None = None
    activated_by: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    notes: str | None = None
    change_summary: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None


class RuleVersionListResponse(BaseModel):
    total: int
    items: list[RuleVersionRecord]


class SiteRuleActive(BaseModel):
    rule_version: str
    sha256: str
    path: str
    activated_at: str | None = None


class SiteRuleCandidate(BaseModel):
    rule_version: str
    sha256: str
    build_id: str | None = None
    validation_status: str | None = None
    change_summary: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    created_at: str


class SiteRuleResponse(BaseModel):
    site_key: str
    rule_id: str | None = None
    active: SiteRuleActive | None = None
    candidates: list[SiteRuleCandidate] = Field(default_factory=list)
    stale_tasks: int = 0
    open_feedback: int = 0


class RuleActivateRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    rule_id: str | None = Field(default=None, max_length=200)
    rule_version: str = Field(min_length=1, max_length=120)
    expected_active_version: str | None = Field(default=None, max_length=120)
    expected_active_sha256: str | None = Field(default=None, max_length=64)
    feedback_id: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=2000)
    actor: str | None = Field(default=None, max_length=120)


class RuleRollbackRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    to_version: str | None = Field(default=None, max_length=120)
    expected_active_version: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=2000)
    actor: str | None = Field(default=None, max_length=120)


class RuleRejectRequest(BaseModel):
    request_id: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=2000)
    feedback_id: str | None = Field(default=None, max_length=200)
    retry: bool = False
    actor: str | None = Field(default=None, max_length=120)


class BatchCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    collection_mode: Literal["sample", "formal"] | None = None
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
    site_keys: list[str] = Field(default_factory=list, max_length=200)
    proxy: str | None = Field(default=None, max_length=500)
    archive_mode: Literal["off", "sample", "full"] = "off"
    archive_root: str | None = Field(default=None, max_length=1000)
    archive_sample_limit: int = Field(default=20, ge=1, le=1000)
    archive_max_bytes: int | None = Field(default=None, ge=0)
    archive_reuse: bool = False
    offline: bool = False
    rerun_finished: bool = False
    onboard: bool = False
    promote_trial: bool = False


class BuildStartRequest(BaseModel):
    mode: Literal["build", "repair"] = "build"
    model_ref: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=2000)
    max_products: int = Field(default=6, ge=1, le=50)
    max_seconds: int = Field(default=600, ge=60, le=3600)
    max_total_seconds: int | None = Field(default=None, ge=60, le=7200)
    max_input_tokens: int | None = Field(default=None, ge=1000, le=100_000_000)
    max_output_tokens: int | None = Field(default=None, ge=1000, le=10_000_000)
    proxy: str | None = Field(default=None, max_length=500)
    capture_reasoning: bool | None = Field(default=None)
    repair_rounds: int | None = Field(default=None, ge=0, le=10)
    archive_mode: Literal["off", "sample", "full"] = "off"
    archive_root: str | None = Field(default=None, max_length=1000)
    archive_sample_limit: int = Field(default=20, ge=1, le=1000)
    archive_max_bytes: int | None = Field(default=None, ge=0)
    catalog_scope: Literal["sample", "target", "full"] = "sample"
    catalog_products: int | None = Field(default=None, ge=1, le=10000)
    feedback_id: str | None = Field(default=None, max_length=200)
    request_id: str | None = Field(default=None, max_length=200)


class BuildModelCheckRequest(BaseModel):
    model_ref: str = Field(min_length=1, max_length=200)


class BuildModelPoolRequest(BaseModel):
    refs: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        default_factory=list, max_length=16
    )
    default_ref: str | None = Field(default=None, max_length=200)


class BuildPermissionRequest(BaseModel):
    decision: Literal["once", "always", "reject"] = "once"
    message: str | None = Field(default=None, max_length=2000)


class BuildContinueRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=4000)


class BuildDependencyRequest(BaseModel):
    decision: Literal["once", "reject"] = "once"
    message: str | None = Field(default=None, max_length=2000)


class SystemAccessRequest(BaseModel):
    lan_enabled: bool


class SystemTokenRequest(BaseModel):
    token: str | None = None


class LoginRequest(BaseModel):
    key: str


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


def _valid_http_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _rule_sha256(rules_dir: Path | None, rule_path: str | None) -> str | None:
    if rules_dir is None or not rule_path:
        return None
    root = rules_dir.resolve()
    path = (rules_dir / rule_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _feedback_payload(feedback: QualityFeedback) -> FeedbackRecord:
    return FeedbackRecord(
        feedback_id=feedback.feedback_id,
        task_id=feedback.task_id,
        batch_id=feedback.batch_id,
        site_key=feedback.site_key,
        category=feedback.category,
        samples=list(feedback.samples),
        expectation=feedback.expectation,
        note=feedback.note,
        scope=feedback.scope,
        status=feedback.status,
        triage=feedback.triage,
        triage_note=feedback.triage_note,
        triage_source=feedback.triage_source,
        duplicate_of=feedback.duplicate_of,
        repair_build_id=feedback.repair_build_id,
        rerun_task_id=feedback.rerun_task_id,
        resolution=feedback.resolution,
        resolution_note=feedback.resolution_note,
        created_by=feedback.created_by,
        resolved_by=feedback.resolved_by,
        created_at=feedback.created_at,
        updated_at=feedback.updated_at,
        closed_at=feedback.closed_at,
        rule=(
            FeedbackRuleRef(
                rule_id=feedback.rule_id,
                rule_version=feedback.rule_version,
                sha256=feedback.rule_sha256,
            )
            if feedback.rule_id
            else None
        ),
    )


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
        counts = {
            str(key): int(value)
            for key, value in raw.items()
            if isinstance(value, int) and not isinstance(value, bool)
        }
    else:
        items = store.item_counts(task.task_id)
        navigation = store.item_counts(task.task_id, "navigation")
        products = store.item_counts(task.task_id, "product")
        product_total = sum(products.values())
        pending = products.get("PENDING", 0) + products.get("IN_FLIGHT", 0)
        processed = (
            products.get("DONE", 0)
            + products.get("EXCLUDED", 0)
            + products.get("FAILED", 0)
        )
        if task.task_type == "discovery":
            counts = {
                "navigation_urls": sum(navigation.values()),
                "discovered_urls": sum(items.values()),
                "url_candidates": product_total,
                "pending_urls": pending,
                "valid_urls": products.get("DONE", 0),
                "excluded_urls": products.get("EXCLUDED", 0),
                "failed_urls": products.get("FAILED", 0),
            }
        else:
            counts = {
                "navigation_urls": sum(navigation.values()),
                "discovered_urls": sum(items.values()),
                "product_candidates": product_total,
                "pending_products": pending,
                "in_flight_products": products.get("IN_FLIGHT", 0),
                "processed_products": processed,
                "valid_products": products.get("DONE", 0),
                "excluded_products": products.get("EXCLUDED", 0),
                "failed_products": products.get("FAILED", 0),
                "partial_description_products": 0,
            }
    # The retired Vue console reads the short aliases; v2 reads canonical names.
    counts.setdefault("pending", counts.get("pending_products", 0))
    counts.setdefault("in_flight", counts.get("in_flight_products", 0))
    counts.setdefault("excluded", counts.get("excluded_products", 0))
    counts.setdefault("failed", counts.get("failed_products", 0))
    return counts


def _summary(store: TaskStore, task: Task, out_root: Path) -> dict[str, Any]:
    result = _load_result(out_root, task.task_id)
    site_rule = store.get_site_rule(task.site_key or task.plan_id)
    active_version = site_rule.rule_version if site_rule else None
    active_sha256 = site_rule.sha256 if site_rule else None
    if site_rule is None:
        stale: bool | None = None
    elif task.rule_sha256:
        stale = task.rule_sha256 != site_rule.sha256
    elif task.plan_version != site_rule.rule_version:
        stale = True
    else:
        stale = None
    feedback, _ = store.list_feedback(task_id=task.task_id, limit=50)
    open_feedback = [
        item
        for item in feedback
        if item.status not in {"RESOLVED", "WONTFIX"}
    ]
    latest_feedback = feedback[0] if feedback else None
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
        "content_audit": result.get("content_audit") or {},
        "rule": {
            "rule_id": task.plan_id,
            "rule_version": task.plan_version,
            "sha256": task.rule_sha256,
            "active_version": active_version,
            "active_sha256": active_sha256,
            "stale": stale,
        },
        "feedback": {
            "open": len(open_feedback),
            "latest_id": latest_feedback.feedback_id if latest_feedback else None,
            "latest_status": latest_feedback.status if latest_feedback else None,
        },
        "archived_at": task.archived_at,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
    }


def _task_sort_value(item: dict[str, Any], key: str) -> Any:
    if key == "task":
        return str(item.get("site_key") or item.get("plan_id") or "").lower()
    if key == "state":
        return str(item.get("state") or "")
    if key == "results":
        counts = item.get("counts") or {}
        return (
            int(counts.get("valid_products") or 0),
            int(counts.get("discovered_urls") or 0),
        )
    if key == "coverage":
        coverage = item.get("coverage") or {}
        return str(coverage.get("status") or "")
    if key == "quality":
        return len(item.get("quality_exceptions") or [])
    if key == "updated":
        return str(item.get("updated_at") or "")
    return ""


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


def _error(
    code: str,
    message: str,
    status_code: int,
    details: dict[str, Any] | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "details": details or {}},
    )


def _legacy_ui_enabled() -> bool:
    """Return True only when the retired UI is explicitly enabled."""

    return os.environ.get("ECOM_LEGACY_UI", "off").strip().lower() in {
        "1",
        "on",
        "true",
        "yes",
        "enabled",
    }


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


def _display_path(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        relative = path.resolve().relative_to(Path.home().resolve())
    except (OSError, ValueError):
        return str(path)
    return "~/" + relative.as_posix() if relative.parts else "~"


def _disk_target(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate if candidate.exists() else Path.cwd()


def _is_allowed_host(host_header: str, allowed_hosts: frozenset[str]) -> bool:
    name = normalize_host_name(host_header)
    return name in LOOPBACK_HOSTS or name in allowed_hosts


def _origin_matches_host(
    origin: str,
    host_header: str,
    allowed_hosts: frozenset[str],
) -> bool:
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    if parsed.scheme != "http" or not parsed.netloc:
        return False
    if not _is_allowed_host(parsed.netloc, allowed_hosts):
        return False
    return parsed.netloc.lower() == host_header.strip().lower()


def _basic_password(header: str | None) -> str | None:
    """Extract the password from an HTTP Basic header; the user name is ignored."""
    if not header:
        return None
    parts = header.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "basic":
        return None
    try:
        decoded = base64.b64decode(parts[1], validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    _user, separator, password = decoded.partition(":")
    return password if separator else None


def _unauthorized(message: str = "authentication required") -> JSONResponse:
    response = JSONResponse(
        status_code=401,
        content={
            "error": {
                "code": "UNAUTHORIZED",
                "message": message,
                "details": {},
            }
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _invalid_key(message: str = "访问密钥不正确") -> JSONResponse:
    response = JSONResponse(
        status_code=401,
        content={
            "error": {
                "code": "INVALID_KEY",
                "message": message,
                "details": {},
            }
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _too_many_requests(retry_after: int) -> JSONResponse:
    response = JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "TOO_MANY_ATTEMPTS",
                "message": f"尝试次数过多，请 {retry_after} 秒后重试",
                "details": {"retry_after": retry_after},
            }
        },
    )
    response.headers["Retry-After"] = str(retry_after)
    response.headers["Cache-Control"] = "no-store"
    return response


def _client_key(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _is_public_static(path: str, method: str) -> bool:
    if method not in {"GET", "HEAD"}:
        return False
    return (
        path == "/"
        or path == "/favicon.ico"
        or path == "/next"
        or path.startswith("/next/")
    )


def _is_auth_path(path: str) -> bool:
    return path in {"/api/auth/login", "/api/auth/logout"}


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
            "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
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
    build_extra_permissions: list[dict[str, Any]] | None = None,
    build_dependency_policy: DependencyPolicy | None = None,
    proxy: str | None = None,
    read_only: bool = False,
    access_token: str | None = None,
    allowed_hosts: Iterable[str] | None = None,
    serve_host: str = "127.0.0.1",
    serve_port: int = 8765,
    access_urls: Iterable[str] | None = None,
) -> FastAPI:
    if read_only and manage_worker:
        raise ValueError("read_only mode cannot manage a worker")
    if read_only and build_manager is not None:
        raise ValueError("read_only mode cannot accept a build manager")
    token = access_token if access_token is None else str(access_token)
    if token is not None:
        try:
            token = validate_access_token(token)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
    raw_hosts = (
        [allowed_hosts] if isinstance(allowed_hosts, str) else list(allowed_hosts or ())
    )
    allowed = frozenset(
        name for name in (normalize_host_name(item) for item in raw_hosts) if name
    )
    store = TaskStore(db_path, read_only=read_only)
    root = Path(out_root)
    if not read_only:
        root.mkdir(parents=True, exist_ok=True)
    rules = Path(rules_dir).resolve() if rules_dir is not None else None
    builds_disabled = os.environ.get("ECOM_BUILD_DISABLED") == "1"
    legacy_ui_enabled = _legacy_ui_enabled()

    stored_token = parse_token_setting(store.get_setting(SETTING_TOKEN))
    token_salt: str | None
    token_hash: str | None
    token_updated_at: str | None
    if token is not None:
        token_salt = secrets.token_hex(16)
        token_hash = hash_token(token, token_salt)
        token_updated_at = utc_now()
        if not read_only:
            store.set_setting(
                SETTING_TOKEN,
                token_setting(token_salt, token_hash, token_updated_at),
            )
    elif stored_token is not None:
        token_salt, token_hash, token_updated_at = stored_token
    else:
        token_salt = token_hash = token_updated_at = None
    if allowed and token_hash is None:
        raise ValueError("allowed_hosts requires access_token")
    lan_capable = not is_loopback_bind(serve_host)
    if lan_capable and token_hash is None:
        raise ValueError(
            "non-loopback serve_host requires an access token or a stored token"
        )
    stored_lan = store.get_setting(SETTING_LAN_ENABLED)
    lan_enabled = lan_capable and (stored_lan != "0" if stored_lan is not None else True)
    access_lock = threading.Lock()
    access_state: dict[str, Any] = {
        "lan_enabled": lan_enabled,
        "token_salt": token_salt,
        "token_hash": token_hash,
        "token_updated_at": token_updated_at,
    }
    login_limiter = LoginRateLimiter()
    urls = [str(url) for url in (access_urls or ()) if str(url).strip()]
    if not urls:
        display = f"[{serve_host}]" if ":" in serve_host else serve_host
        urls = [f"http://{display}:{serve_port}/next/"]
    started_at = utc_now()
    started_monotonic = time.monotonic()
    if build_manager is None and rules is not None:
        build_manager = BuildManager(
            store,
            root,
            rules,
            default_proxy=proxy,
            extra_permissions=build_extra_permissions,
            dependency_policy=build_dependency_policy,
            read_only=read_only,
        )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> Any:
        if build_manager is not None and not read_only:
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
            if build_manager is not None and not read_only:
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
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.store = store
    app.state.out_root = root
    app.state.rules_dir = rules
    app.state.worker_managed = manage_worker
    app.state.build_manager = build_manager
    app.state.proxy = proxy
    app.state.read_only = read_only
    app.state.auth_required = token_hash is not None
    app.state.token_configured = token_hash is not None
    app.state.lan_capable = lan_capable
    app.state.lan_enabled = lan_enabled
    app.state.serve_host = serve_host
    app.state.serve_port = serve_port
    app.state.access_urls = tuple(urls)
    app.state.allowed_hosts = tuple(sorted(allowed))
    app.state.session_ttl_seconds = SESSION_TTL_SECONDS

    def rule_error(exc: Exception) -> HTTPException:
        if isinstance(exc, RuleActivationConflictError):
            code = "ACTIVATION_CONFLICT"
        else:
            text = str(exc)
            if "hash mismatch" in text:
                code = "RULE_HASH_MISMATCH"
            elif "not a candidate" in text or "expected candidate" in text:
                code = "RULE_NOT_CANDIDATE"
            elif "not a superseded" in text or "expected superseded" in text:
                code = "RULE_NOT_ACTIVE"
            elif "already exists" in text:
                code = "RULE_VERSION_CONFLICT"
            elif "rule_id mismatch" in text:
                code = "RULE_ID_MISMATCH"
            else:
                code = "RULE_CONFLICT"
        return _error(code, str(exc), 409)

    def site_busy(site_key: str) -> dict[str, str] | None:
        tasks = [
            task
            for task in store.list_tasks()
            if (task.site_key or task.plan_id) == site_key
            and task.state in ACTIVE_TASK_STATES
        ]
        builds = store.list_builds(
            site_key=site_key, states=ACTIVE_BUILD_STATES, limit=1
        )
        if tasks:
            task = tasks[0]
            return {"task_id": task.task_id, "task_state": task.state}
        if builds:
            build = builds[0]
            return {"build_id": build.build_id, "build_state": build.state}
        return None

    def rule_version_payload(
        version: RuleVersion, build: BuildRecord | None = None
    ) -> RuleVersionRecord:
        return RuleVersionRecord(
            rule_id=version.rule_id,
            rule_version=version.rule_version,
            sha256=version.sha256,
            parent_version=version.parent_version,
            status=version.status,
            source_build_id=version.source_build_id,
            source_feedback_id=version.source_feedback_id,
            path=version.path,
            created_at=version.created_at,
            activated_at=version.activated_at,
            activated_by=version.activated_by,
            reviewed_by=version.reviewed_by,
            reviewed_at=version.reviewed_at,
            notes=version.notes,
            change_summary=(build.change_summary or None) if build else None,
            validation=(build.validation or None) if build else None,
        )

    def ensure_site_rule(site_key: str) -> SiteRule | None:
        if build_manager is not None:
            return build_manager.ensure_site_rule(site_key)
        current = store.get_site_rule(site_key)
        if current is not None:
            return current
        latest = store.latest_batch_site_rule(site_key)
        if (
            latest is None
            or rules is None
            or not latest.rule_id
            or not latest.rule_version
            or not latest.rule_path
        ):
            return None
        path = rules / latest.rule_path
        if not path.is_file():
            return None
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        store.create_rule_version(
            RuleVersion(
                rule_id=latest.rule_id,
                rule_version=latest.rule_version,
                sha256=digest,
                path=latest.rule_path,
                status="active",
                created_at=latest.updated_at,
                activated_at=latest.updated_at,
                activated_by="legacy-migration",
            )
        )
        return store.upsert_site_rule(
            SiteRule(
                site_key=site_key,
                rule_id=latest.rule_id,
                rule_version=latest.rule_version,
                sha256=digest,
                path=latest.rule_path,
                updated_at=latest.updated_at,
            )
        )

    def known_site(site_key: str) -> bool:
        return bool(
            store.get_site_rule(site_key)
            or store.latest_batch_site_rule(site_key)
            or store.list_builds(site_key=site_key, limit=1)
        )

    def site_rule_payload(site_key: str) -> SiteRuleResponse:
        if not known_site(site_key):
            raise _error("SITE_NOT_FOUND", f"unknown site: {site_key}", 404)
        active = ensure_site_rule(site_key)
        rule_id = active.rule_id if active else None
        if rule_id is None:
            latest = store.latest_batch_site_rule(site_key)
            rule_id = latest.rule_id if latest else None
        candidates: list[RuleVersion] = []
        if rule_id is None:
            builds = store.list_builds(site_key=site_key, limit=1)
            if builds and builds[0].rule_id:
                rule_id = builds[0].rule_id
        if rule_id:
            candidates = store.list_candidate_rules(rule_id)
        tasks = [
            task
            for task in store.list_tasks()
            if (task.site_key or task.plan_id) == site_key
        ]
        stale_tasks = 0
        if active is not None:
            for task in tasks:
                if task.plan_version != active.rule_version or (
                    task.rule_sha256 and task.rule_sha256 != active.sha256
                ):
                    stale_tasks += 1
        feedback, _ = store.list_feedback(site_key=site_key, limit=200)
        open_feedback = sum(
            1
            for item in feedback
            if item.status
            not in {"RESOLVED", "WONTFIX"}
        )
        active_record = (
            store.get_rule_version(active.rule_id, active.rule_version)
            if active
            else None
        )
        candidate_payloads: list[SiteRuleCandidate] = []
        for item in candidates:
            build = (
                store.get_build(item.source_build_id)
                if item.source_build_id
                else None
            )
            candidate_payloads.append(
                SiteRuleCandidate(
                    rule_version=item.rule_version,
                    sha256=item.sha256,
                    build_id=item.source_build_id,
                    validation_status=(
                        str((build.validation or {}).get("status") or "") or None
                        if build
                        else None
                    ),
                    change_summary=(build.change_summary or None) if build else None,
                    validation=(build.validation or None) if build else None,
                    created_at=item.created_at,
                )
            )
        return SiteRuleResponse(
            site_key=site_key,
            rule_id=rule_id,
            active=(
                SiteRuleActive(
                    rule_version=active.rule_version,
                    sha256=active.sha256,
                    path=active.path,
                    activated_at=active_record.activated_at if active_record else None,
                )
                if active
                else None
            ),
            candidates=candidate_payloads,
            stale_tasks=stale_tasks,
            open_feedback=open_feedback,
        )

    def require_file_hash(version: RuleVersion) -> None:
        if rules is None:
            raise _error("RULES_NOT_CONFIGURED", "rules directory is not set", 400)
        path = rules / version.path
        if not path.is_file():
            raise _error(
                "RULE_HASH_MISMATCH",
                f"rule file is missing: {version.path}",
                409,
            )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != version.sha256:
            raise _error(
                "RULE_HASH_MISMATCH",
                f"rule file hash does not match ledger: {version.path}",
                409,
            )

    def sample_key(value: Any) -> str:
        return str(value or "").strip().rstrip("/").casefold()

    def activation_validation_error(
        target: RuleVersion, feedback_id: str | None
    ) -> tuple[str, str] | None:
        """Return ``(code, message)`` when activation lacks valid evidence."""
        build = (
            store.get_build(target.source_build_id)
            if target.source_build_id
            else None
        )
        if build is None:
            return (
                "VALIDATION_REQUIRED",
                "候选没有关联的构建验证记录",
            )
        if (
            build.target_rule_version != target.rule_version
            or build.target_rule_sha256 != target.sha256
        ):
            return (
                "VALIDATION_REQUIRED",
                "候选版本或哈希与构建验证记录不一致",
            )
        validation = build.validation if isinstance(build.validation, dict) else {}
        evidence = str(validation.get("evidence_sha256") or "")
        if (
            not re.fullmatch(r"[0-9a-f]{64}", evidence)
            or evidence != str(build.evidence_sha256 or "")
        ):
            return (
                "VALIDATION_REQUIRED",
                "候选缺少可核对的验证证据哈希",
            )
        smoke = validation.get("candidate_smoke")
        if not isinstance(smoke, dict) or not smoke.get("executed"):
            return (
                "VALIDATION_REQUIRED",
                "候选缺少候选冒烟记录；请重新运行修复构建",
            )
        if int(smoke.get("valid_products") or 0) < 1:
            return (
                "VALIDATION_REQUIRED",
                "候选冒烟没有产生有效商品",
            )
        status = str(validation.get("status") or "").upper()
        if status == "INCOMPLETE":
            reasons = [
                str(reason)
                for reason in (validation.get("status_reasons") or [])
                if str(reason).strip()
            ]
            return (
                "VALIDATION_REQUIRED",
                "验证证据不完整" + (f"：{'；'.join(reasons)}" if reasons else ""),
            )
        if status != "PASSED":
            regression = validation.get("regression")
            regression = regression if isinstance(regression, dict) else {}
            regressions = regression.get("regressions") or []
            reasons = [
                str(reason)
                for reason in (validation.get("status_reasons") or [])
                if str(reason).strip()
            ]
            if regressions:
                return (
                    "VALIDATION_FAILED",
                    f"候选验证发现 {len(regressions)} 项回归，不能激活",
                )
            return (
                "VALIDATION_FAILED",
                "候选验证未通过" + (f"：{'；'.join(reasons)}" if reasons else ""),
            )
        regression = validation.get("regression")
        regression = regression if isinstance(regression, dict) else {}
        if regression.get("required"):
            if not regression.get("executed") or int(
                regression.get("checked") or 0
            ) < 1:
                return (
                    "VALIDATION_REQUIRED",
                    "修复候选缺少新旧规则同页回归；请重新运行修复构建",
                )
            expected_checked = int(regression.get("required_checked") or 0)
            if expected_checked < 1:
                samples = smoke.get("product_samples") or []
                expected_checked = min(3, len(samples)) if samples else 0
            checked = int(regression.get("checked") or 0)
            if expected_checked and checked < expected_checked:
                return (
                    "VALIDATION_REQUIRED",
                    (
                        "同页回归覆盖不足："
                        f"{checked} / {expected_checked} 条必需页面"
                    ),
                )
            if regression.get("regressions"):
                return (
                    "VALIDATION_FAILED",
                    "新旧规则回归发现字段退化，不能激活",
                )
        linked = feedback_id or target.source_feedback_id
        if linked:
            feedback = store.get_feedback(linked)
            samples = [
                str(sample).strip()
                for sample in (feedback.samples if feedback else [])
                if str(sample).strip()
            ]
            if samples:
                checks = {
                    sample_key(check.get("sample")): check
                    for check in (validation.get("issue_checks") or [])
                    if isinstance(check, dict)
                }
                for sample in samples:
                    check = checks.get(sample_key(sample))
                    if check is None:
                        return (
                            "VALIDATION_REQUIRED",
                            f"问题样本缺少主机检查：{sample}",
                        )
                    if not check.get("passed"):
                        return (
                            "VALIDATION_FAILED",
                            f"问题样本检查未通过：{sample}",
                        )
        return None

    @app.middleware("http")
    async def read_only_guard(request: Request, call_next: Any) -> Any:
        if (
            read_only
            and request.method.upper() in WRITE_METHODS
            and not _is_auth_path(request.url.path)
        ):
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "READ_ONLY",
                        "message": "read-only mode rejects write operations",
                        "details": {},
                    }
                },
            )
        return await call_next(request)

    @app.middleware("http")
    async def access_guard(request: Request, call_next: Any) -> Any:
        host = request.headers.get("host", "")
        if not _is_allowed_host(host, allowed):
            return _forbidden("request host is not allowed")
        path = request.url.path
        method = request.method.upper()
        auth_path = _is_auth_path(path)
        public_static = _is_public_static(path, method)
        with access_lock:
            lan_enabled_now = bool(access_state["lan_enabled"])
            token_salt_now = access_state["token_salt"]
            token_hash_now = access_state["token_hash"]
        if lan_capable and not lan_enabled_now and not is_loopback_host(host):
            return _forbidden("LAN access is disabled")
        if token_hash_now is not None and not auth_path and not public_static:
            session_value = request.cookies.get(SESSION_COOKIE_NAME)
            if not verify_session(session_value, token_hash_now):
                password = _basic_password(request.headers.get("authorization"))
                if password is None:
                    return _unauthorized()
                client = _client_key(request)
                retry_after = login_limiter.retry_after(client)
                if retry_after is not None:
                    return _too_many_requests(retry_after)
                if verify_token(password, token_salt_now, token_hash_now):
                    login_limiter.success(client)
                else:
                    login_limiter.failure(client)
                    return _unauthorized()
        if method in WRITE_METHODS:
            origin = request.headers.get("origin", "")
            if not _origin_matches_host(origin, host, allowed):
                return _forbidden("write requests require a same-origin Origin")
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
                    "details": detail.get("details", {}),
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {
                "loc": list(error.get("loc", [])),
                "msg": str(error.get("msg", "")),
                "type": str(error.get("type", "")),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "request validation failed",
                    "details": {"errors": errors},
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

    def normalize_market(value: Any) -> str:
        return str(value or "").strip().upper()

    def market_conflict(
        rule: dict[str, Any], batch_market: str | None
    ) -> str | None:
        rule_market = normalize_market(rule.get("market"))
        wanted = normalize_market(batch_market)
        if wanted and rule_market and wanted != rule_market:
            return f"市场不匹配：规则 {rule_market}，批次 {wanted}"
        return None

    def find_rule_entry(
        rule_id: str,
        rule_version: str,
        entries: list[dict[str, Any]],
        sha256: str | None = None,
    ) -> dict[str, Any] | None:
        matches = [
            entry
            for entry in entries
            if entry.get("valid")
            and entry.get("rule_id") == rule_id
            and entry.get("rule_version") == rule_version
            and (sha256 is None or entry.get("sha256") == sha256)
        ]
        return matches[0] if len(matches) == 1 else None

    def match_rule(
        site_key: str, entries: list[dict[str, Any]]
    ) -> tuple[dict[str, Any] | None, str]:
        """Resolve the rule a normal batch may run.

        The active rule ledger is authoritative.  The YAML ``status`` field is
        only a fallback for legacy rules that predate the ledger; candidates,
        rejected and superseded versions never enter a normal task through the
        directory scan.
        """
        active = store.get_site_rule(site_key)
        if active is not None:
            entry = find_rule_entry(
                active.rule_id, active.rule_version, entries, active.sha256
            )
            if entry is None:
                return (
                    None,
                    (
                        "生效规则 "
                        f"{active.rule_id}@{active.rule_version} 的文件不可用或哈希不一致"
                    ),
                )
            return entry, f"生效版本 {active.rule_id}@{active.rule_version}"
        stored = store.latest_batch_site_rule(site_key)
        if stored is not None and stored.rule_id and stored.rule_version:
            entry = find_rule_entry(stored.rule_id, stored.rule_version, entries)
            if entry is not None and entry.get("status") == "verified":
                return (
                    entry,
                    f"已复核版本 {entry['rule_id']}@{entry['rule_version']}",
                )
            if entry is not None:
                return (
                    None,
                    f"规则 {entry['rule_id']}@{entry['rule_version']} 未在生效账本中",
                )
        verified = [
            entry
            for entry in entries
            if entry.get("valid")
            and entry.get("status") == "verified"
            and site_key in entry.get("domains", [])
        ]
        if verified:
            verified.sort(
                key=lambda entry: (
                    str(entry.get("rule_version") or ""),
                    str(entry.get("path") or ""),
                )
            )
            entry = verified[-1]
            note = f"已复核版本 {entry['rule_id']}@{entry['rule_version']}"
            if len(verified) > 1:
                note += f"（{len(verified)} 个已复核版本，使用最高版本）"
            return entry, note
        unactivated = [
            entry
            for entry in entries
            if entry.get("valid") and site_key in entry.get("domains", [])
        ]
        if unactivated:
            unactivated.sort(
                key=lambda entry: (
                    str(entry.get("rule_version") or ""),
                    str(entry.get("path") or ""),
                )
            )
            entry = unactivated[-1]
            return (
                None,
                f"仅有未激活版本 {entry['rule_id']}@{entry['rule_version']}",
            )
        return None, "未匹配受管规则包"

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
        batch_market: str | None = None,
        scoped: bool = False,
    ) -> tuple[dict[str, Any], list[BatchSite]]:
        parsed = parse_sites(values, scoped=scoped, market=batch_market)
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
                rule, note = match_target(item.site_key or "", item.input_value, entries, scoped)
                if rule is None:
                    readiness = "needs_onboarding"
                else:
                    conflict = market_conflict(rule, batch_market)
                    if conflict:
                        readiness = "needs_onboarding"
                        note = f"{conflict}；请调整批次市场或换用匹配规则"
                    else:
                        readiness = "ready"
                stored = True
            if scoped and readiness in {"invalid", "duplicate"}:
                stored = False
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

    def match_target(
        site_key: str, value: str, entries: list[dict[str, Any]], scoped: bool
    ) -> tuple[dict[str, Any] | None, str]:
        rule, note = match_rule(site_key, entries)
        entry = target_entry(value) if scoped else None
        if entry is None:
            return rule, note
        if rule is None and store.get_site_rule(site_key) is None:
            domain = normalize_site(value).site_key
            rule, _ = match_rule(domain or site_key, entries)
        if rule is not None and rules is not None:
            try:
                package = load_rule(rules / str(rule["path"]))
                if rule_covers_entry(package, entry):
                    return rule, f"适用版本 {rule['rule_id']}@{rule['rule_version']}"
            except (OSError, RuleError):
                pass
        return None, "当前规则未验证此入口，需接入指定范围"

    def batch_status(
        batch: Batch,
        sites: list[BatchSite],
        summaries: dict[str, dict[str, Any]],
    ) -> str:
        if batch.archived_at:
            return "ARCHIVED"
        if batch.collection_mode and any(site.readiness == "building" for site in sites):
            return "RUNNING"
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
        approval_required = False
        if build_manager is not None and record.state in {"RUNNING", "PAUSED"}:
            details = build_manager.describe(build_id, event_limit=1)
            approval_required = bool(
                details.get("pending_permissions") or details.get("pending_dependencies")
            )
        return {
            "build_id": record.build_id,
            "state": record.state,
            "outcome": record.outcome,
            "approval_required": approval_required,
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
        tasks = {task.task_id: task for task in store.list_batch_tasks(batch.batch_id)}
        summaries = {task_id: _summary(store, task, root) for task_id, task in tasks.items()}
        return summarize_batch(batch, sites, tasks, summaries, detail=detail)

    def delivery_task(site: BatchSite, tasks: dict[str, Task]) -> Task | None:
        if site.delivery_task_id:
            return tasks.get(site.delivery_task_id)
        current = tasks.get(site.task_id or "")
        if current is not None and not current.input.get("feedback_id"):
            return current
        return None

    def summarize_batch(
        batch: Batch,
        sites: list[BatchSite],
        tasks: dict[str, Task],
        summaries: dict[str, dict[str, Any]],
        *,
        detail: bool = False,
    ) -> dict[str, Any]:
        current_task_ids = {site.task_id for site in sites if site.task_id}
        current_summaries = {
            task_id: summaries[task_id]
            for task_id in current_task_ids
            if task_id in summaries
        }
        result_summaries = [
            summaries[task.task_id]
            for site in sites
            if (task := delivery_task(site, tasks)) is not None
        ]
        readiness = Counter(site.readiness for site in sites)
        states = Counter(summary["state"] for summary in current_summaries.values())
        failed_tasks = sum(
            1
            for summary in current_summaries.values()
            if summary["state"] == "FINISHED"
            and summary["outcome"] == "FAILED"
        )
        partial_tasks = sum(
            1
            for summary in current_summaries.values()
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
            "tasks": len(current_summaries),
            "task_runs": len(summaries),
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
            "collection_mode": batch.collection_mode,
            "language": batch.language,
            "category": batch.category,
            "note": batch.note,
            "status": batch_status(batch, sites, current_summaries),
            "archived_at": batch.archived_at,
            "created_at": batch.created_at,
            "updated_at": batch.updated_at,
            "counts": counts,
            "valid_products": sum(
                int(summary["counts"].get("valid_products", 0))
                for summary in result_summaries
            ),
            "failed_products": sum(
                int(summary["counts"].get("failed_products", 0))
                for summary in result_summaries
            ),
        }
        if detail:
            payload["onboarding_available"] = build_manager is not None and not builds_disabled and not read_only
            actionable = {}
            for task_id, summary in summaries.items():
                if summary["feedback"]["latest_status"] in {
                    "AWAITING_ACTIVATION", "AWAITING_RERUN", "RERUN_PENDING",
                }:
                    actionable.setdefault(tasks[task_id].site_key, {
                        "task_id": task_id, "status": summary["feedback"]["latest_status"],
                        "feedback_id": summary["feedback"]["latest_id"],
                    })
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
                    "delivery_task_id": site.delivery_task_id,
                    "delivery_task": summaries.get(site.delivery_task_id) if site.delivery_task_id else None,
                    "feedback_action": actionable.get(site.site_key),
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
        if (V2_DIST_DIR / "index.html").is_file():
            return RedirectResponse(url="/next/", status_code=307)
        if legacy_ui_enabled and (BATCH_DIST_DIR / "index.html").is_file():
            return RedirectResponse(url="/batch/", status_code=307)
        if legacy_ui_enabled:
            return FileResponse(STATIC_DIR / "index.html")
        raise _error(
            "UI_NOT_BUILT",
            "v2 UI build not found; build app/frontend-v2/dist or set ECOM_LEGACY_UI=on",
            503,
        )

    @app.get("/legacy", include_in_schema=False)
    def legacy_index() -> Response:
        if not legacy_ui_enabled:
            if (V2_DIST_DIR / "index.html").is_file():
                return RedirectResponse(url="/next/", status_code=307)
            raise _error("NOT_FOUND", "legacy UI is disabled", 404)
        return FileResponse(STATIC_DIR / "index.html")

    if not legacy_ui_enabled:

        @app.get("/batch", include_in_schema=False)
        @app.get("/batch/{path:path}", include_in_schema=False)
        def retired_batch(path: str = "") -> Response:
            if (V2_DIST_DIR / "index.html").is_file():
                return RedirectResponse(url="/next/", status_code=307)
            raise _error("NOT_FOUND", "legacy UI is disabled", 404)

        @app.get("/static/index.html", include_in_schema=False)
        def retired_static_index() -> Response:
            if (V2_DIST_DIR / "index.html").is_file():
                return RedirectResponse(url="/next/", status_code=307)
            raise _error("NOT_FOUND", "legacy UI is disabled", 404)

    def _access_payload() -> dict[str, Any]:
        with access_lock:
            state = dict(access_state)
        token_configured = state["token_hash"] is not None
        return {
            "host": serve_host,
            "port": serve_port,
            "lan_capable": lan_capable,
            "lan_enabled": bool(state["lan_enabled"]),
            "auth_required": token_configured,
            "token_configured": token_configured,
            "token_updated_at": state["token_updated_at"],
            "session_ttl_seconds": SESSION_TTL_SECONDS,
            "allowed_hosts": sorted(allowed),
            "urls": list(urls),
        }

    def _system_payload() -> dict[str, Any]:
        tasks = store.list_tasks()
        task_counts = Counter(task.state for task in tasks)
        active_builds = store.list_builds(
            states=ACTIVE_BUILD_STATES,
            limit=1000,
        )
        build_counts = Counter(record.state for record in active_builds)
        db_path = Path(store.path)
        db_bytes = sum(
            path.stat().st_size
            for path in (
                db_path,
                Path(f"{db_path}-wal"),
                Path(f"{db_path}-shm"),
            )
            if path.is_file()
        )
        disk_target = _disk_target(root)
        disk = shutil.disk_usage(disk_target)
        worker = (
            "read-only"
            if read_only
            else ("managed" if manage_worker else "external")
        )
        builds_available = (
            build_manager is not None and not builds_disabled and not read_only
        )
        return {
            "status": "ok",
            "version": __version__,
            "started_at": started_at,
            "uptime_seconds": max(0, int(time.monotonic() - started_monotonic)),
            "server": _access_payload(),
            "runtime": {
                "worker": worker,
                "max_tasks": max_tasks if manage_worker else None,
                "max_browser_tasks": max_browser_tasks if manage_worker else None,
                "read_only": read_only,
                "builds_available": builds_available,
                "builds_disabled": builds_disabled,
                "legacy_ui": "enabled" if legacy_ui_enabled else "disabled",
                "rules_configured": rules is not None and rules.is_dir(),
                "python": platform.python_version(),
                "platform": platform.platform(),
                "threads": threading.active_count(),
            },
            "work": {
                "tasks_total": len(tasks),
                "tasks_active": sum(
                    task_counts.get(state, 0)
                    for state in ("RUNNING", "PAUSING", "CANCELLING")
                ),
                "tasks_queued": task_counts.get("QUEUED", 0),
                "tasks_paused": task_counts.get("PAUSED", 0),
                "tasks_by_state": dict(sorted(task_counts.items())),
                "builds_active": sum(
                    count for state, count in build_counts.items() if state != "QUEUED"
                ),
                "builds_queued": build_counts.get("QUEUED", 0),
            },
            "storage": {
                "db_bytes": db_bytes,
                "disk_total_bytes": disk.total,
                "disk_used_bytes": disk.used,
                "disk_free_bytes": disk.free,
                "disk_path": _display_path(disk_target),
            },
            "paths": {
                "db": _display_path(db_path),
                "out_root": _display_path(root),
                "rules_dir": _display_path(rules),
            },
        }

    @app.post("/api/auth/login")
    def login(payload: LoginRequest, request: Request, response: Response) -> Any:
        with access_lock:
            salt = access_state["token_salt"]
            digest = access_state["token_hash"]
        if digest is None:
            raise _error("TOKEN_NOT_CONFIGURED", "尚未配置访问密钥", 409)
        client = _client_key(request)
        retry_after = login_limiter.retry_after(client)
        if retry_after is not None:
            return _too_many_requests(retry_after)
        try:
            key = validate_access_token(payload.key)
        except ValueError as exc:
            login_limiter.failure(client)
            raise _error("INVALID_ACCESS_KEY", str(exc), 400) from exc
        if not verify_token(key, salt, digest):
            login_limiter.failure(client)
            return _invalid_key()
        login_limiter.success(client)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=create_session(digest),
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            samesite="lax",
            path="/",
        )
        response.headers["Cache-Control"] = "no-store"
        return {"ok": True, "expires_in": SESSION_TTL_SECONDS}

    @app.post("/api/auth/logout")
    def logout(response: Response) -> dict[str, Any]:
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")
        response.headers["Cache-Control"] = "no-store"
        return {"ok": True}

    @app.get("/api/system")
    def system_status() -> dict[str, Any]:
        return _system_payload()

    @app.put("/api/system/access")
    def update_system_access(payload: SystemAccessRequest) -> dict[str, Any]:
        if not lan_capable:
            raise _error(
                "LAN_NOT_CAPABLE",
                "服务以回环地址启动；修改 --host 后重启才能开放局域网",
                409,
            )
        with access_lock:
            token_configured = access_state["token_hash"] is not None
        if payload.lan_enabled and not token_configured:
            raise _error(
                "TOKEN_REQUIRED",
                "开启局域网前需要配置访问令牌",
                409,
            )
        if not read_only:
            store.set_setting(
                SETTING_LAN_ENABLED,
                "1" if payload.lan_enabled else "0",
            )
        with access_lock:
            access_state["lan_enabled"] = payload.lan_enabled
        app.state.lan_enabled = payload.lan_enabled
        return {"access": _access_payload()}

    @app.post("/api/system/access/token")
    def rotate_system_token(
        response: Response,
        payload: SystemTokenRequest | None = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        generated = payload is None or payload.token is None
        if generated:
            token_value, salt, digest = new_token()
        else:
            try:
                token_value = validate_access_token(payload.token)
            except ValueError as exc:
                raise _error("INVALID_ACCESS_KEY", str(exc), 400) from exc
            salt = secrets.token_hex(16)
            digest = hash_token(token_value, salt)
        updated_at = utc_now()
        if not read_only:
            store.set_setting(
                SETTING_TOKEN,
                token_setting(salt, digest, updated_at),
            )
        with access_lock:
            access_state["token_salt"] = salt
            access_state["token_hash"] = digest
            access_state["token_updated_at"] = updated_at
        app.state.auth_required = True
        app.state.token_configured = True
        return {
            "token": token_value if generated else None,
            "generated": generated,
            "access": _access_payload(),
        }

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "db": str(store.path),
            "tasks": len(store.list_tasks()),
            "worker": (
                "read-only"
                if read_only
                else ("managed" if manage_worker else "external")
            ),
            "read_only": read_only,
            "max_tasks": max_tasks if manage_worker else None,
            "max_browser_tasks": max_browser_tasks if manage_worker else None,
            "rules_configured": rules is not None and rules.is_dir(),
            "builds_readable": build_manager is not None,
            "builds_available": (
                build_manager is not None
                and not builds_disabled
                and not read_only
            ),
            "legacy_ui": "enabled" if legacy_ui_enabled else "disabled",
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
        batch_id: Annotated[str | None, Query(max_length=200)] = None,
        site_key: Annotated[str | None, Query(max_length=200)] = None,
        include_archived: Annotated[bool, Query()] = False,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        sort: Annotated[str | None, Query(max_length=40)] = None,
        order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    ) -> dict[str, Any]:
        tasks = store.list_tasks(set(state) if state else None)
        tasks = [
            task
            for task in tasks
            if include_archived or task.archived_at is None
        ]
        if task_type:
            tasks = [task for task in tasks if task.task_type == task_type]
        if batch_id:
            tasks = [task for task in tasks if task.batch_id == batch_id]
        if site_key:
            tasks = [
                task
                for task in tasks
                if (task.site_key or task.plan_id) == site_key
            ]
        total = len(tasks)
        sort_keys = {"task", "state", "results", "coverage", "quality", "updated"}
        if sort in sort_keys:
            # Sorting by a computed field needs the summary for every task in
            # the filtered set; the task list is a local, bounded workspace.
            items = [_summary(store, task, root) for task in tasks]
            items.sort(
                key=lambda item: _task_sort_value(item, sort),
                reverse=order == "desc",
            )
            return {"total": total, "items": items[offset : offset + limit]}
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

    @app.get("/api/tasks/{task_id}/csv")
    def preview_task_csv(
        task_id: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        task = require_task(task_id)
        task_dir = root / task_id
        columns: list[str] = list(CSV_COLUMNS)
        rows: list[dict[str, Any]] = []
        source: str | None = None
        terminal = task.state in {"FINISHED", "CANCELLED"}
        csv_path = task_dir / "products.csv"
        jsonl_path = task_dir / "products.jsonl"
        if terminal and csv_path.is_file():
            try:
                with csv_path.open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    if reader.fieldnames:
                        columns = list(reader.fieldnames)
                    rows = [dict(row) for row in reader]
                source = "products.csv"
            except OSError:
                rows = []
        if source is None and jsonl_path.is_file():
            try:
                for line in jsonl_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    rows.append(
                        {
                            column: record.get(column, "")
                            for column in columns
                        }
                    )
                source = "products.jsonl"
            except OSError:
                rows = []
        return {
            "task_id": task.task_id,
            "state": task.state,
            "live": not terminal,
            "columns": columns,
            "rows": rows[offset : offset + limit],
            "total": len(rows),
            "source": source,
        }

    @app.get("/api/tasks/{task_id}/items")
    def list_items(        task_id: str,
        kind: Annotated[str, Query(pattern="^(url|product)$")] = "product",
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        state: Annotated[str | None, Query(max_length=20)] = None,
        order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    ) -> dict[str, Any]:
        require_task(task_id)
        item_type = "navigation" if kind == "url" else "product"
        items = store.items(task_id, item_type)
        if state:
            wanted = state.strip().upper()
            items = [item for item in items if item.state == wanted]
        if order == "desc":
            items = list(reversed(items))
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

    @app.post(
        "/api/tasks/{task_id}/feedback",
        status_code=201,
        response_model=FeedbackCreateResponse,
        responses={200: {"model": FeedbackCreateResponse}},
    )
    def create_task_feedback(
        task_id: str, payload: FeedbackCreateRequest, response: Response
    ) -> FeedbackCreateResponse:
        task = require_task(task_id)
        if task.state not in {"FINISHED", "CANCELLED"}:
            raise _error(
                "INVALID_TASK_STATE",
                "feedback requires a finished or cancelled task",
                409,
            )
        samples = [sample.strip() for sample in payload.samples]
        if any(not sample or not _valid_http_url(sample) for sample in samples):
            raise _error(
                "VALIDATION_ERROR",
                "samples must be non-empty http or https URLs",
                400,
            )
        expectation = payload.expectation.strip()
        if not expectation:
            raise _error("VALIDATION_ERROR", "expectation must not be empty", 400)
        if not samples and payload.category not in {"BUSINESS_EXPECTATION", "OTHER"}:
            raise _error(
                "VALIDATION_ERROR",
                "this category requires at least one sample URL",
                400,
            )
        now = utc_now()
        request_json = json.dumps(
            {"task_id": task_id, **payload.model_dump()},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        feedback = QualityFeedback(
            feedback_id=f"fb-{uuid.uuid4().hex[:12]}",
            request_id=payload.request_id,
            task_id=task_id,
            category=payload.category,
            expectation=expectation,
            batch_id=task.batch_id,
            site_key=task.site_key,
            rule_id=task.plan_id,
            rule_version=task.plan_version,
            rule_sha256=_rule_sha256(rules, task.rule_path),
            samples=samples,
            note=payload.note,
            scope=payload.scope or "Task-scoped review.",
            created_by=payload.created_by or "local-user",
            created_at=now,
            updated_at=now,
            request_json=request_json,
        )
        try:
            record, created = store.create_feedback(feedback)
        except FeedbackRequestConflictError as exc:
            raise _error("CONFLICT", str(exc), 409) from exc
        response.status_code = 201 if created else 200
        return FeedbackCreateResponse(
            created=created,
            feedback=_feedback_payload(record),
        )

    @app.get(
        "/api/tasks/{task_id}/feedback",
        response_model=FeedbackListResponse,
    )
    def list_task_feedback(
        task_id: str,
        status: Annotated[str | None, Query(max_length=30)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> FeedbackListResponse:
        require_task(task_id)
        items, total = store.list_feedback(
            task_id=task_id,
            status=status.strip().upper() if status else None,
            limit=limit,
            offset=offset,
        )
        return FeedbackListResponse(
            total=total,
            items=[_feedback_payload(item) for item in items],
        )

    @app.get("/api/feedback", response_model=FeedbackListResponse)
    def list_feedback(
        task_id: Annotated[str | None, Query(max_length=200)] = None,
        batch_id: Annotated[str | None, Query(max_length=200)] = None,
        site_key: Annotated[str | None, Query(max_length=200)] = None,
        status: Annotated[str | None, Query(max_length=30)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> FeedbackListResponse:
        items, total = store.list_feedback(
            task_id=task_id,
            batch_id=batch_id,
            site_key=site_key,
            status=status.strip().upper() if status else None,
            limit=limit,
            offset=offset,
        )
        return FeedbackListResponse(
            total=total,
            items=[_feedback_payload(item) for item in items],
        )

    @app.get("/api/feedback/{feedback_id}", response_model=FeedbackRecord)
    def get_feedback(feedback_id: str) -> FeedbackRecord:
        feedback = store.get_feedback(feedback_id)
        if feedback is None:
            raise _error("FEEDBACK_NOT_FOUND", f"unknown feedback: {feedback_id}", 404)
        return _feedback_payload(feedback)

    @app.post(
        "/api/feedback/{feedback_id}/triage",
        response_model=FeedbackTriageResponse,
    )
    def triage_feedback(
        feedback_id: str, payload: FeedbackTriageRequest
    ) -> FeedbackTriageResponse:
        if payload.triage == "DUPLICATE":
            if not payload.duplicate_of:
                raise _error(
                    "VALIDATION_ERROR",
                    "duplicate_of is required for DUPLICATE triage",
                    400,
                )
            if payload.duplicate_of == feedback_id:
                raise _error(
                    "VALIDATION_ERROR",
                    "feedback cannot duplicate itself",
                    400,
                )
            if store.get_feedback(payload.duplicate_of) is None:
                raise _error(
                    "VALIDATION_ERROR",
                    f"unknown duplicate_of feedback: {payload.duplicate_of}",
                    400,
                )
        elif payload.duplicate_of:
            raise _error(
                "VALIDATION_ERROR",
                "duplicate_of is only allowed with DUPLICATE triage",
                400,
            )
        try:
            feedback = store.triage_feedback(
                feedback_id,
                triage=payload.triage,
                note=payload.note,
                duplicate_of=payload.duplicate_of,
                actor=payload.actor or "local-user",
            )
        except FeedbackNotFoundError as exc:
            raise _error("FEEDBACK_NOT_FOUND", str(exc), 404) from exc
        except FeedbackTransitionError as exc:
            raise _error("INVALID_FEEDBACK_STATE", str(exc), 409) from exc
        return FeedbackTriageResponse(feedback=_feedback_payload(feedback))

    @app.post("/api/feedback/{feedback_id}/repair", status_code=202)
    def repair_feedback(
        feedback_id: str, payload: FeedbackRepairRequest
    ) -> dict[str, Any]:
        if build_manager is None:
            raise _error(
                "BUILD_UNAVAILABLE",
                "build agent is not configured; start serve with --rules-dir",
                409,
            )
        if builds_disabled:
            raise _error(
                "BUILD_UNAVAILABLE",
                "build agent is disabled in read-only preview",
                409,
            )
        feedback = store.get_feedback(feedback_id)
        if feedback is None:
            raise _error("FEEDBACK_NOT_FOUND", f"unknown feedback: {feedback_id}", 404)
        existing_build = store.get_build_by_request_id(payload.request_id)
        if existing_build is not None:
            if existing_build.feedback_id != feedback_id:
                raise _error(
                    "CONFLICT", "request_id belongs to another feedback", 409
                )
            return {
                "accepted": True,
                "build": build_manager.describe(existing_build.build_id),
                "feedback": _feedback_payload(
                    store.get_feedback(feedback_id) or feedback
                ),
            }
        if feedback.status not in {"OPEN", "TRIAGED"}:
            raise _error(
                "INVALID_FEEDBACK_STATE",
                f"feedback is {feedback.status}, expected OPEN or TRIAGED",
                409,
            )
        if feedback.triage not in {None, "RULE_REPAIR"}:
            raise _error(
                "INVALID_FEEDBACK_STATE",
                f"feedback triage is {feedback.triage}, expected RULE_REPAIR",
                409,
            )
        if feedback.category in {"ACCESS_RUNTIME", "BUSINESS_EXPECTATION"}:
            raise _error(
                "INVALID_FEEDBACK_STATE",
                "runtime/business feedback must be triaged and handled outside rule repair",
                409,
            )
        if not feedback.batch_id or not feedback.site_key:
            raise _error(
                "INVALID_STATE",
                "feedback has no batch/site; use the site build entry instead",
                409,
            )
        task = store.get_task(feedback.task_id)
        if task is None or task.state not in {"FINISHED", "CANCELLED"}:
            raise _error(
                "INVALID_TASK_STATE",
                "feedback task must be terminal before repair",
                409,
            )
        busy = site_busy(feedback.site_key)
        if busy:
            raise _error("SITE_BUSY", "site has active work", 409, busy)
        active = build_manager.ensure_site_rule(feedback.site_key)
        if active is None:
            raise _error(
                "RULE_NOT_ACTIVE",
                "site has no active rule; use the site build entry",
                409,
            )
        batch = store.get_batch(feedback.batch_id)
        site = store.get_batch_site(feedback.batch_id, feedback.site_key)
        if batch is None or site is None:
            raise _error("INVALID_STATE", "feedback batch/site no longer exists", 409)
        store.update_feedback(
            feedback_id,
            status="REPAIRING",
            triage=feedback.triage or "RULE_REPAIR",
            triage_source=feedback.triage_source or "repair",
        )
        try:
            record = build_manager.repair(
                batch,
                site,
                reason=payload.reason or feedback.expectation,
                max_products=payload.max_products,
                max_seconds=payload.max_seconds,
                max_total_seconds=payload.max_total_seconds,
                max_input_tokens=payload.max_input_tokens,
                max_output_tokens=payload.max_output_tokens,
                capture_reasoning=payload.capture_reasoning,
                repair_rounds=payload.repair_rounds,
                archive_mode=payload.archive_mode,
                archive_root=payload.archive_root,
                archive_sample_limit=payload.archive_sample_limit,
                archive_max_bytes=payload.archive_max_bytes,
                feedback_id=feedback_id,
                request_id=payload.request_id,
                model_ref=payload.model_ref,
            )
        except BuildError as exc:
            store.update_feedback(feedback_id, status="TRIAGED")
            raise _error("BUILD_CONFLICT", str(exc), 409) from exc
        store.update_feedback(feedback_id, repair_build_id=record.build_id)
        updated = store.get_feedback(feedback_id) or feedback
        return {
            "accepted": True,
            "build": build_manager.describe(record.build_id),
            "feedback": _feedback_payload(updated),
        }

    @app.post("/api/feedback/{feedback_id}/rerun", status_code=202)
    def rerun_feedback(
        feedback_id: str, payload: FeedbackRerunRequest
    ) -> dict[str, Any]:
        if rules is None or not rules.is_dir():
            raise _error("RULES_NOT_CONFIGURED", "rules directory is not set", 400)
        feedback = store.get_feedback(feedback_id)
        if feedback is None:
            raise _error("FEEDBACK_NOT_FOUND", f"unknown feedback: {feedback_id}", 404)
        request_json = json.dumps(
            {"feedback_id": feedback_id, **payload.model_dump()},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        try:
            existing = store.get_task_request(payload.request_id, request_json)
        except RequestConflictError as exc:
            raise _error("CONFLICT", str(exc), 409) from exc
        if existing is not None:
            return {
                "accepted": True, "created": False,
                "task": _summary(store, existing, root),
                "feedback": _feedback_payload(feedback),
            }
        if feedback.status != "AWAITING_RERUN":
            raise _error(
                "INVALID_FEEDBACK_STATE",
                f"feedback is {feedback.status}, expected AWAITING_RERUN",
                409,
            )
        if not feedback.batch_id or not feedback.site_key:
            raise _error(
                "INVALID_STATE", "feedback has no batch/site; create a task manually", 409
            )
        batch = store.get_batch(feedback.batch_id)
        if batch is None or batch.archived_at:
            raise _error("INVALID_STATE", "feedback batch is missing or archived", 409)
        active = ensure_site_rule(feedback.site_key)
        if active is None:
            raise _error("RULE_NOT_ACTIVE", "site has no active rule", 409)
        busy = site_busy(feedback.site_key)
        if busy:
            raise _error("SITE_BUSY", "site has active work", 409, busy)
        rule_path = rules / active.path
        if not rule_path.is_file():
            raise _error("RULE_HASH_MISMATCH", "active rule file is missing", 409)
        task_id = f"web-{uuid.uuid4().hex[:12]}"
        source = store.get_task(feedback.task_id)
        limits = payload.limits.model_dump()
        if batch.collection_mode and source is not None:
            limits = {key: source.limits.get(key, value) for key, value in limits.items()}
            site = store.get_batch_site(feedback.batch_id, feedback.site_key)
            if site is None or not rule_covers_entry(load_rule(rule_path), target_entry(site.input_value)):
                raise _error("INVALID_STATE", "active rule does not cover the requested entry", 409)
        task = build_task(
            rule_path=rule_path,
            task_id=task_id,
            task_type="product",
            max_urls=limits["max_urls"],
            max_products=limits["max_products"],
            max_seconds=limits["max_seconds"],
            max_attempts=limits["max_attempts"],
            proxy=source.input.get("proxy") if source is not None else None,
            archive_mode=payload.archive_mode,
            archive_root=root / "archive",
        )
        task.batch_id = feedback.batch_id
        task.site_key = feedback.site_key
        task.rule_sha256 = active.sha256
        task.input["feedback_id"] = feedback_id
        task.state = "QUEUED"
        if source is not None:
            task.domain_key = source.domain_key
            task.market = source.market or task.market
            if mode := source.input.get("collection_mode"):
                task.input["collection_mode"] = mode
            if entry := source.input.get("target_entry"):
                task.input["target_entry"] = entry
        try:
            task, created = store.create_task_idempotent(
                task, payload.request_id, request_json, feedback_id=feedback_id
            )
        except RequestConflictError as exc:
            raise _error("CONFLICT", str(exc), 409) from exc
        except FeedbackTransitionError as exc:
            raise _error("INVALID_FEEDBACK_STATE", str(exc), 409) from exc
        updated = store.get_feedback(feedback_id) or feedback
        return {
            "accepted": True,
            "created": created,
            "task": _summary(store, store.get_task(task.task_id) or task, root),
            "feedback": _feedback_payload(updated),
        }

    @app.post("/api/feedback/{feedback_id}/resolve")
    def resolve_feedback(
        feedback_id: str, payload: FeedbackResolveRequest
    ) -> dict[str, Any]:
        feedback = store.get_feedback(feedback_id)
        if feedback is None:
            raise _error("FEEDBACK_NOT_FOUND", f"unknown feedback: {feedback_id}", 404)
        if payload.resolution == "RESOLVED":
            if feedback.status == "RERUN_PENDING":
                if not feedback.rerun_task_id:
                    raise _error(
                        "INVALID_FEEDBACK_STATE", "rerun task is missing", 409
                    )
                try:
                    updated = store.adopt_feedback_result(
                        feedback, note=payload.note, actor=payload.actor or "local-user"
                    )
                except FeedbackTransitionError as exc:
                    raise _error("INVALID_FEEDBACK_STATE", str(exc), 409) from exc
                return {"feedback": _feedback_payload(updated)}
            elif feedback.status == "TRIAGED" and feedback.triage in {
                "RUNTIME",
                "BUSINESS",
            }:
                pass
            else:
                raise _error(
                    "INVALID_FEEDBACK_STATE",
                    f"feedback is {feedback.status}; cannot resolve as RESOLVED",
                    409,
                )
            resolution = "RESOLVED"
        else:
            if feedback.status in {"RESOLVED", "WONTFIX"}:
                raise _error(
                    "INVALID_FEEDBACK_STATE", "feedback is already closed", 409
                )
            if feedback.status == "REPAIRING":
                raise _error(
                    "SITE_BUSY",
                    "repair build is still active; wait or cancel it first",
                    409,
                )
            resolution = "WONTFIX"
        updated = store.update_feedback(
            feedback_id,
            status=resolution,
            resolution=resolution,
            resolution_note=payload.note,
            resolved_by=payload.actor or "local-user",
            closed_at=utc_now(),
        )
        return {"feedback": _feedback_payload(updated)}

    @app.get(
        "/api/rules/{rule_id}/versions",
        response_model=RuleVersionListResponse,
    )
    def list_rule_versions(
        rule_id: str,
        status: Annotated[str | None, Query(max_length=30)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> RuleVersionListResponse:
        items, total = store.list_rule_versions(
            rule_id,
            status=status.strip().lower() if status else None,
            limit=limit,
            offset=offset,
        )
        return RuleVersionListResponse(
            total=total, items=[rule_version_payload(item) for item in items]
        )

    @app.get(
        "/api/rules/{rule_id}/versions/{rule_version}",
        response_model=RuleVersionRecord,
    )
    def get_rule_version(rule_id: str, rule_version: str) -> RuleVersionRecord:
        version = store.get_rule_version(rule_id, rule_version)
        if version is None:
            raise _error(
                "RULE_NOT_FOUND",
                f"unknown rule version: {rule_id}@{rule_version}",
                404,
            )
        build = (
            store.get_build(version.source_build_id)
            if version.source_build_id
            else None
        )
        return rule_version_payload(version, build)

    @app.post(
        "/api/rules/{rule_id}/versions/{rule_version}/reject",
        response_model=RuleVersionRecord,
    )
    def reject_rule_version(
        rule_id: str,
        rule_version: str,
        payload: RuleRejectRequest,
    ) -> RuleVersionRecord:
        try:
            version = store.reject_rule_version(
                rule_id,
                rule_version,
                reason=payload.reason,
                feedback_id=payload.feedback_id,
                retry=payload.retry,
                actor=payload.actor or "local-user",
            )
        except RuleVersionError as exc:
            raise rule_error(exc) from exc
        return rule_version_payload(version)

    @app.get("/api/sites/{site_key}/rule", response_model=SiteRuleResponse)
    def read_site_rule(site_key: str) -> SiteRuleResponse:
        return site_rule_payload(site_key)

    @app.post("/api/sites/{site_key}/rule/activate")
    def activate_site_rule(
        site_key: str, payload: RuleActivateRequest
    ) -> dict[str, Any]:
        existing = store.get_activation_by_request(payload.request_id)
        if existing is not None:
            return {
                "activated": True,
                "site": site_rule_payload(site_key).model_dump(),
                "previous": {
                    "rule_version": existing.from_version,
                    "sha256": existing.from_sha256,
                },
            }
        busy = site_busy(site_key)
        if busy:
            raise _error("SITE_BUSY", "site has active work", 409, busy)
        active = store.get_site_rule(site_key)
        target = store.get_rule_version(
            payload.rule_id or (active.rule_id if active else ""),
            payload.rule_version,
        )
        if target is None:
            raise _error("RULE_NOT_FOUND", "candidate rule version not found", 404)
        if payload.rule_id and payload.rule_id != target.rule_id:
            raise _error(
                "RULE_ID_MISMATCH",
                f"rule_id does not match candidate: {target.rule_id}",
                409,
            )
        gate_error = activation_validation_error(
            target, payload.feedback_id or target.source_feedback_id
        )
        if gate_error is not None:
            code, message = gate_error
            raise _error(
                code,
                message,
                409,
                {
                    "rule_version": target.rule_version,
                    "build_id": target.source_build_id,
                },
            )
        require_file_hash(target)
        try:
            site_rule, activation = store.activate_rule(
                site_key=site_key,
                rule_id=target.rule_id,
                rule_version=target.rule_version,
                sha256=target.sha256,
                expected_active_version=payload.expected_active_version,
                expected_active_sha256=payload.expected_active_sha256,
                feedback_id=payload.feedback_id,
                request_id=payload.request_id,
                reason=payload.reason,
                actor=payload.actor or "local-user",
                action="activate",
            )
        except RuleVersionError as exc:
            raise rule_error(exc) from exc
        feedback = None
        linked = payload.feedback_id or target.source_feedback_id
        if linked:
            record = store.get_feedback(linked)
            feedback = _feedback_payload(record) if record else None
        return {
            "activated": True,
            "site": {
                "site_key": site_rule.site_key,
                "active": {
                    "rule_version": site_rule.rule_version,
                    "sha256": site_rule.sha256,
                    "path": site_rule.path,
                },
            },
            "previous": {
                "rule_version": activation.from_version,
                "sha256": activation.from_sha256,
            },
            "feedback": feedback,
        }

    @app.post("/api/sites/{site_key}/rule/rollback")
    def rollback_site_rule(
        site_key: str, payload: RuleRollbackRequest
    ) -> dict[str, Any]:
        existing = store.get_activation_by_request(payload.request_id)
        if existing is not None:
            return {
                "rolled_back": True,
                "site": site_rule_payload(site_key).model_dump(),
                "previous": {
                    "rule_version": existing.from_version,
                    "sha256": existing.from_sha256,
                },
                "target": {
                    "rule_version": existing.to_version,
                    "sha256": existing.to_sha256,
                },
            }
        busy = site_busy(site_key)
        if busy:
            raise _error("SITE_BUSY", "site has active work", 409, busy)
        active = ensure_site_rule(site_key)
        if active is None:
            raise _error("RULE_NOT_ACTIVE", "site has no active rule", 409)
        target = None
        if payload.to_version:
            target = store.get_rule_version(active.rule_id, payload.to_version)
        else:
            target = store.latest_superseded_rule(active.rule_id)
        if target is None:
            raise _error("RULE_NOT_ACTIVE", "no rollback target found", 409)
        require_file_hash(target)
        try:
            site_rule, activation = store.activate_rule(
                site_key=site_key,
                rule_id=target.rule_id,
                rule_version=target.rule_version,
                sha256=target.sha256,
                expected_active_version=(
                    payload.expected_active_version or active.rule_version
                ),
                feedback_id=None,
                request_id=payload.request_id,
                reason=payload.reason,
                actor=payload.actor or "local-user",
                action="rollback",
            )
        except RuleVersionError as exc:
            raise rule_error(exc) from exc
        return {
            "rolled_back": True,
            "site": {
                "site_key": site_rule.site_key,
                "active": {
                    "rule_version": site_rule.rule_version,
                    "sha256": site_rule.sha256,
                    "path": site_rule.path,
                },
            },
            "previous": {
                "rule_version": activation.from_version,
                "sha256": activation.from_sha256,
            },
            "target": {
                "rule_version": target.rule_version,
                "sha256": target.sha256,
            },
        }

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
            report, _ = import_sites(
                "",
                values,
                [],
                entries,
                persist=False,
                batch_market=payload.market,
                scoped=payload.collection_mode is not None,
            )
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
            collection_mode=payload.collection_mode,
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
            batch_market=batch.market,
            scoped=batch.collection_mode is not None,
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
            batch_market=batch.market,
            scoped=batch.collection_mode is not None,
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
        if payload is not None and payload.offline and payload.archive_mode != "full":
            raise _error(
                "INVALID_ARCHIVE",
                "offline replay requires archive_mode=full",
                422,
            )
        entries = _rule_entries(rules)
        sites = store.list_batch_sites(batch_id)
        wanted = set(payload.site_keys) if payload is not None else set()
        if wanted:
            known = {site.site_key for site in sites}
            missing = sorted(wanted - known)
            if missing:
                raise _error(
                    "NOT_FOUND",
                    f"unknown batch site: {missing[0]}",
                    404,
                )
        accepted: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        onboarding: list[dict[str, Any]] = []
        if payload is not None and payload.onboard:
            if not batch.collection_mode or builds_disabled or build_manager is None:
                raise _error("BUILD_UNAVAILABLE", "构建服务不可用或批次未设置采集计划", 409)
            pending = [site for site in sites if (
                site.readiness == "needs_onboarding" and not site.task_id
                and (not wanted or site.site_key in wanted)
            )]
            if len(pending) > 10:
                raise _error("VALIDATION_ERROR", "一次最多接入 10 个目标，请先选择要接入的站点", 422)
        promote = bool(payload and payload.promote_trial)
        if promote:
            if wanted:
                raise _error("VALIDATION_ERROR", "转为正式采集适用于整个批次", 422)
            try:
                batch = store.promote_batch_collection(batch_id)
            except BatchTransitionError as exc:
                raise _error("INVALID_STATE", "请先完成或取消当前试采和接入任务", 409) from exc
        if batch.collection_mode in BATCH_COLLECTION_LIMITS:
            limits = Limits(**BATCH_COLLECTION_LIMITS[batch.collection_mode])
        for site in sites:
            if wanted and site.site_key not in wanted:
                continue
            item = {
                "site_key": site.site_key,
                "domain": site.domain,
                "task_id": site.task_id,
            }
            rerun = promote or bool(payload is not None and payload.rerun_finished)
            if site.task_id:
                existing = store.get_task(site.task_id)
                if not rerun:
                    skipped.append({**item, "reason": "站点已开始"})
                    continue
                if existing is not None and existing.state in ACTIVE_TASK_STATES:
                    skipped.append({**item, "reason": "站点任务仍在运行"})
                    continue
                if existing is not None and existing.state not in {
                    "FINISHED",
                    "CANCELLED",
                }:
                    skipped.append(
                        {**item, "reason": f"站点任务状态为 {existing.state}"}
                    )
                    continue
            if rules is None or not rules.is_dir():
                skipped.append({**item, "reason": "服务未配置规则目录"})
                continue
            if site.readiness in {"invalid", "duplicate"}:
                skipped.append(
                    {
                        **item,
                        "reason": READINESS_SKIP.get(
                            site.readiness, f"站点状态为 {site.readiness}"
                        ),
                    }
                )
                continue
            rule, rule_note = match_target(
                site.site_key, site.input_value, entries, batch.collection_mode is not None
            )
            conflict = market_conflict(rule, batch.market) if rule else None
            if site.readiness != "ready":
                if (payload is not None and payload.onboard and build_manager is not None
                    and site.readiness == "needs_onboarding" and not site.task_id and not conflict):
                    try:
                        build = build_manager.start(
                            batch, site, max_products=6, max_seconds=600, max_total_seconds=600,
                            max_input_tokens=200000, max_output_tokens=30000, repair_rounds=1,
                            proxy=proxy_override or site.proxy, auto_collect=True,
                        )
                    except BuildError as exc:
                        skipped.append({**item, "reason": str(exc)})
                    else:
                        onboarding.append({**item, "build_id": build.build_id})
                    continue
                if conflict:
                    reason = conflict
                elif site.readiness == "needs_onboarding" and rule is None:
                    reason = rule_note
                else:
                    reason = READINESS_SKIP.get(
                        site.readiness, f"站点状态为 {site.readiness}"
                    )
                skipped.append({**item, "reason": reason})
                continue
            if rule is None:
                skipped.append({**item, "reason": rule_note})
                continue
            if conflict:
                skipped.append({**item, "reason": conflict})
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
                    archive_mode=payload.archive_mode if payload is not None else "off",
                    archive_root=payload.archive_root if payload is not None else None,
                    archive_sample_limit=(
                        payload.archive_sample_limit if payload is not None else 20
                    ),
                    archive_max_bytes=(
                        payload.archive_max_bytes if payload is not None else None
                    ),
                    archive_reuse=payload.archive_reuse if payload is not None else False,
                    offline=payload.offline if payload is not None else False,
                )
            except (RuleError, ContractError) as exc:
                skipped.append({**item, "reason": f"规则包无法构建任务：{exc}"})
                continue
            task.batch_id = batch_id
            task.site_key = site.site_key
            if batch.collection_mode:
                task.input["collection_mode"] = batch.collection_mode
                if entry := target_entry(site.input_value):
                    task.input["target_entry"] = entry
            task.state = "QUEUED"
            task.domain_key = normalize_site(site.input_value).site_key or site.domain
            task.market = (
                normalize_market(batch.market)
                or normalize_market(rule.get("market"))
                or None
            )
            if rule.get("sha256"):
                task.rule_sha256 = str(rule["sha256"])
            try:
                created = store.create_task_for_site(
                    task, site_key=site.site_key, replace_existing=rerun
                )
            except BatchNotFoundError:
                skipped.append({**item, "reason": "站点在批次中不存在"})
                continue
            if not created:
                skipped.append({**item, "reason": "站点已开始"})
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
            "onboarding": onboarding,
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
        try:
            batch, sites, runs = store.read_batch_snapshot(batch_id)
        except BatchNotFoundError as exc:
            raise _error("NOT_FOUND", str(exc), 404) from exc
        tasks = {task.task_id: task for task in runs}
        if not partial and any(
            not site.delivery_task_id and site.task_id in tasks
            and tasks[site.task_id].state in ACTIVE_TASK_STATES | {"DRAFT"}
            for site in sites
        ):
            raise _error(
                "EXPORT_NOT_READY",
                "batch has active tasks; use partial=true",
                409,
            )
        manifest_sites: list[dict[str, Any]] = []
        summaries = {task_id: _summary(store, task, root) for task_id, task in tasks.items()}
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for site in sites:
                current = tasks.get(site.task_id or "")
                task = delivery_task(site, tasks)
                summary = summaries[task.task_id] if task else None
                files: list[str] = []
                if task is not None and task.state in {"FINISHED", "CANCELLED"}:
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
                    export_status = "awaiting_review" if current and current.input.get("feedback_id") else "missing"
                elif summary["state"] == "CANCELLED":
                    export_status = "partial" if files else "cancelled"
                elif summary["state"] in ACTIVE_TASK_STATES or summary["state"] == "DRAFT":
                    export_status = "running"
                elif summary["outcome"] == "COMPLETED":
                    if not {"products.csv", "task-result.json"}.issubset(files):
                        export_status = "missing"
                    else:
                        export_status = "sample" if task and task.input.get("collection_mode") == "sample" else "complete"
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
                        "task_id": task.task_id if task else None,
                        "current_task_id": site.task_id,
                        "current_task_state": current.state if current else None,
                        "collection_mode": (task.input.get("collection_mode") if task else None),
                        "task_state": summary["state"] if summary else None,
                        "outcome": summary["outcome"] if summary else None,
                        "stop_reason": summary["stop_reason"] if summary else None,
                        "export_status": export_status,
                        "files": files,
                        "counts": summary["counts"] if summary and export_status != "running" else None,
                        "coverage": summary["coverage"] if summary and export_status != "running" else None,
                        "quality_exceptions": (
                            summary["quality_exceptions"] if summary else []
                        ),
                    }
                )
            batch_summary = summarize_batch(batch, sites, tasks, summaries)
            for key in ("valid_products", "failed_products"):
                batch_summary[key] = sum(
                    (item["counts"] or {}).get(key, 0)
                    for item in manifest_sites
                    if "task-result.json" in item["files"]
                )
            manifest = {
                "generated_at": utc_now(),
                "batch": batch_summary,
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
        site_key: str | None = None,
        feedback_id: str | None = None,
        state: str | None = None,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        if build_manager is None:
            raise _error("BUILD_UNAVAILABLE", "build agent is not configured", 409)
        records = store.list_builds(
            batch_id=batch_id,
            site_key=site_key,
            feedback_id=feedback_id,
            states={state} if state else None,
            limit=limit,
        )
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
        if builds_disabled:
            raise _error(
                "BUILD_UNAVAILABLE",
                "build agent is disabled in read-only preview",
                409,
            )
        batch = require_batch(batch_id)
        site = store.get_batch_site(batch_id, site_key)
        if site is None:
            raise _error("NOT_FOUND", f"unknown batch site: {site_key}", 404)
        request = payload or BuildStartRequest()
        feedback = None
        if request.feedback_id:
            if request.mode != "repair":
                raise _error(
                    "INVALID_STATE",
                    "feedback_id is only valid for mode=repair",
                    409,
                )
            feedback = store.get_feedback(request.feedback_id)
            if feedback is None:
                raise _error(
                    "FEEDBACK_NOT_FOUND",
                    f"unknown feedback: {request.feedback_id}",
                    404,
                )
            if (
                feedback.site_key != site.site_key
                or feedback.batch_id != batch.batch_id
            ):
                raise _error(
                    "INVALID_STATE",
                    "feedback does not belong to this batch site",
                    409,
                )
        if request.mode == "repair" and request.feedback_id:
            triage_value = (feedback.triage if feedback else None) or "RULE_REPAIR"
            triage_source = (
                feedback.triage_source if feedback else None
            ) or "repair"
            store.update_feedback(
                request.feedback_id,
                status="REPAIRING",
                triage=triage_value,
                triage_source=triage_source,
            )
        try:
            if request.mode == "repair":
                record = build_manager.repair(
                    batch,
                    site,
                    reason=request.reason,
                    max_products=request.max_products,
                    max_seconds=request.max_seconds,
                    max_total_seconds=request.max_total_seconds,
                    max_input_tokens=request.max_input_tokens,
                    max_output_tokens=request.max_output_tokens,
                    proxy=request.proxy,
                    capture_reasoning=request.capture_reasoning,
                    repair_rounds=request.repair_rounds,
                    archive_mode=request.archive_mode,
                    archive_root=request.archive_root,
                    archive_sample_limit=request.archive_sample_limit,
                    archive_max_bytes=request.archive_max_bytes,
                    feedback_id=request.feedback_id,
                    request_id=request.request_id,
                    model_ref=request.model_ref,
                )
                if request.feedback_id:
                    store.update_feedback(
                        request.feedback_id,
                        repair_build_id=record.build_id,
                    )
            else:
                record = build_manager.start(
                    batch,
                    site,
                    max_products=request.max_products,
                    max_seconds=request.max_seconds,
                    max_total_seconds=request.max_total_seconds,
                    max_input_tokens=request.max_input_tokens,
                    max_output_tokens=request.max_output_tokens,
                    proxy=request.proxy,
                    capture_reasoning=request.capture_reasoning,
                    repair_rounds=request.repair_rounds,
                    archive_mode=request.archive_mode,
                    archive_root=request.archive_root,
                    archive_sample_limit=request.archive_sample_limit,
                    archive_max_bytes=request.archive_max_bytes,
                    catalog_scope=request.catalog_scope,
                    catalog_products=request.catalog_products,
                    model_ref=request.model_ref,
                )
        except BuildError as exc:
            raise _error("BUILD_CONFLICT", str(exc), 409) from exc
        return {
            "accepted": True,
            "build": build_manager.describe(record.build_id),
        }

    def build_config_payload() -> dict[str, Any]:
        if build_manager is None:
            return {
                "available": False,
                "unavailable_reason": "unconfigured",
                "reasoning_capture_enabled": False,
                "max_repair_rounds": 0,
                "models": [],
                "default_model": None,
                "model_pool_source": "none",
                "model_pool_editable": False,
                "model_pool_override": False,
                "model_catalog": known_models(),
            }
        unavailable_reason = (
            "read_only" if read_only else ("disabled" if builds_disabled else None)
        )
        return {
            "available": not builds_disabled and not read_only,
            "unavailable_reason": unavailable_reason,
            "reasoning_capture_enabled": build_manager.reasoning_capture_enabled,
            "max_repair_rounds": build_manager.max_repair_rounds,
            "models": build_manager.model_pool.describe(),
            "default_model": build_manager.model_pool.default_ref,
            "model_pool_source": build_manager.model_pool_source,
            "model_pool_editable": not builds_disabled and not read_only,
            "model_pool_override": build_manager.model_pool_override,
            "model_catalog": known_models(),
        }

    @app.get("/api/builds/config")
    def get_build_config() -> dict[str, Any]:
        return build_config_payload()

    @app.put("/api/builds/config/models")
    def update_build_models(payload: BuildModelPoolRequest) -> dict[str, Any]:
        if build_manager is None or builds_disabled:
            raise _error("BUILD_UNAVAILABLE", "build service unavailable", 409)
        try:
            build_manager.update_model_pool(payload.refs, payload.default_ref)
        except ModelPoolError as exc:
            raise _error("MODEL_POOL_INVALID", str(exc), 400) from exc
        except BuildError as exc:
            raise _error("MODEL_POOL_UNAVAILABLE", str(exc), 409) from exc
        return build_config_payload()

    @app.delete("/api/builds/config/models")
    def reset_build_models() -> dict[str, Any]:
        if build_manager is None or builds_disabled:
            raise _error("BUILD_UNAVAILABLE", "build service unavailable", 409)
        try:
            build_manager.reset_model_pool()
        except ModelPoolError as exc:
            raise _error("MODEL_POOL_UNAVAILABLE", str(exc), 409) from exc
        except BuildError as exc:
            raise _error("MODEL_POOL_UNAVAILABLE", str(exc), 409) from exc
        return build_config_payload()

    @app.get("/api/builds/models/available")
    def list_available_build_models(refresh: bool = False) -> dict[str, Any]:
        try:
            models = discover_models(
                inherit_env=not (build_manager and build_manager.isolate_env),
                refresh=refresh,
            )
        except ModelPoolError as exc:
            return {"models": [], "error": str(exc)}
        return {"models": models, "error": None}

    @app.post("/api/builds/models/check")
    def check_build_model(payload: BuildModelCheckRequest) -> dict[str, Any]:
        if build_manager is None or builds_disabled:
            raise _error("BUILD_UNAVAILABLE", "build service unavailable", 409)
        try:
            return build_manager.model_pool.check(payload.model_ref)
        except ModelPoolError as exc:
            raise _error("MODEL_CHECK_UNAVAILABLE", str(exc), 409) from exc

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

    @app.get("/api/builds/{build_id}/events")
    async def build_events(build_id: str, request: Request) -> StreamingResponse:
        """Stream the visible build timeline as it grows.

        The payload is the same shape as ``/messages``; the first frame is a
        ``snapshot`` and later changes are ``timeline`` frames.  This keeps the
        build view live without making the browser poll a large timeline every
        few seconds.
        """
        require_build(build_id)

        async def stream() -> Any:
            last_fingerprint = ""
            last_heartbeat = time.monotonic()
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.to_thread(
                        build_manager.messages, build_id
                    )
                except KeyError:
                    yield _sse("error", {"message": "build disappeared"})
                    break
                fingerprint = hashlib.sha256(
                    json.dumps(
                        payload, ensure_ascii=False, sort_keys=True
                    ).encode("utf-8")
                ).hexdigest()
                if fingerprint != last_fingerprint:
                    event = "snapshot" if not last_fingerprint else "timeline"
                    last_fingerprint = fingerprint
                    yield _sse(event, payload)
                record = store.get_build(build_id)
                if record is None:
                    break
                if record.state in {"FINISHED", "CANCELLED"}:
                    yield _sse("end", {"state": record.state})
                    break
                if time.monotonic() - last_heartbeat >= 15:
                    yield ": keep-alive\n\n"
                    last_heartbeat = time.monotonic()
                await asyncio.sleep(0.3)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

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

    @app.post("/api/builds/{build_id}/continue", status_code=202)
    def continue_build(
        build_id: str, payload: BuildContinueRequest
    ) -> dict[str, Any]:
        if build_manager is None:
            raise _error("BUILD_UNAVAILABLE", "build agent is not configured", 409)
        if builds_disabled:
            raise _error(
                "BUILD_UNAVAILABLE",
                "build agent is disabled in read-only preview",
                409,
            )
        require_build(build_id)
        record = store.get_build(build_id)
        if record is None:
            raise _error("NOT_FOUND", f"unknown build: {build_id}", 404)
        digest = hashlib.sha256(payload.message.encode("utf-8")).hexdigest()
        existing = store.get_build_continuation(payload.request_id)
        if existing is not None:
            if (
                existing.build_id != build_id
                or existing.message_sha256 != digest
            ):
                raise _error(
                    "CONFLICT",
                    "request_id belongs to another build continuation",
                    409,
                )
            if existing.state == "FAILED":
                raise _error(
                    "BUILD_SESSION_UNAVAILABLE",
                    existing.error or "build continuation failed",
                    409,
                )
            return {"accepted": True, "build": build_manager.describe(build_id)}
        if record.state != "FINISHED":
            raise _error(
                "BUILD_NOT_CONTINUABLE",
                f"build {build_id} is {record.state}; only finished builds can continue",
                409,
            )
        if record.outcome not in {"failed", "interrupted"}:
            raise _error(
                "BUILD_NOT_CONTINUABLE",
                f"build {build_id} is {record.outcome or 'unfinished'}; "
                "only failed or interrupted builds can continue",
                409,
            )
        try:
            store.create_build_continuation(
                BuildContinuation(
                    request_id=payload.request_id,
                    build_id=build_id,
                    message_sha256=digest,
                    message_chars=len(payload.message),
                )
            )
        except BuildContinuationConflictError as exc:
            raise _error("CONFLICT", str(exc), 409) from exc
        try:
            described = build_manager.continue_session(build_id, payload.message)
        except (BuildError, HarnessStateError, KeyError) as exc:
            store.update_build_continuation(
                payload.request_id,
                state="FAILED",
                error=str(exc)[:2000],
            )
            code = (
                "BUILD_SESSION_UNAVAILABLE"
                if "session is no longer available" in str(exc)
                else "BUILD_CONFLICT"
                if "another build is still active" in str(exc)
                else "BUILD_NOT_CONTINUABLE"
            )
            raise _error(code, str(exc), 409) from exc
        return {"accepted": True, "build": described}

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
    if (V2_DIST_DIR / "index.html").is_file():
        app.mount(
            "/next",
            StaticFiles(directory=V2_DIST_DIR, html=True),
            name="next",
        )
    if legacy_ui_enabled and (BATCH_DIST_DIR / "index.html").is_file():
        app.mount(
            "/batch",
            StaticFiles(directory=BATCH_DIST_DIR, html=True),
            name="batch",
        )
    return app
