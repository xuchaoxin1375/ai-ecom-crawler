"""Local FastAPI surface for the D08 read-only and control slices."""

from __future__ import annotations

import asyncio
import base64
import binascii
import csv
import hashlib
import io
import ipaddress
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
from dataclasses import replace
from functools import lru_cache
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
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError

from .. import __version__
from ..build_models import ModelPoolError, discover_models, known_models
from ..builds import ACTIVE_BUILD_STATES, BuildError, BuildManager
from ..collection_policy import (
    COLLECTION_POLICY_SETTING,
    CollectionPolicyError,
    default_rate_overrides,
    dump_collection_policy,
    formal_collection_limits,
    load_collection_policy,
    validate_collection_policy,
)
from ..execution import build_task
from ..executor.runner import CSV_COLUMNS
from ..harness.adapter import HarnessStateError
from ..harness.dependencies import DependencyPolicy
from ..image_proxy import (
    IMAGE_PROXY_SETTING,
    ImageProxyConfigError,
    ImageProxyError,
    ImageProxyUrlError,
    dump_image_proxy,
    fetch_image_with_attempts,
    image_proxy_attempts,
    load_image_proxy,
    validate_image_proxy,
)
from ..model import ContractError
from ..preview_settings import (
    PREVIEW_SETTINGS_SETTING,
    PreviewSettingsError,
    dump_preview_settings,
    load_preview_settings,
    validate_preview_settings,
)
from ..rate_policy import (
    RATE_LIMIT_MAX_CONCURRENCY,
    RATE_LIMIT_MAX_DELAY_MS,
    RATE_LIMIT_MAX_RPS,
    RATE_LIMIT_MIN_RPS,
    SITE_RATE_POLICIES_SETTING,
    RatePolicyError,
    dump_policies,
    effective_policy,
    load_policies,
    normalize_domain,
    validate_policy,
)
from ..runtime.analysis import (
    analysis_etag,
    analysis_fingerprint,
    build_analysis_cached,
)
from ..runtime.batch import (
    BATCH_COLLECTION_LIMITS,
    normalize_site,
    parse_site_text,
    parse_sites,
    rule_domains,
    rule_has_catalog_discovery,
    site_identity,
    target_entry,
    target_entry_mode,
    target_key,
)
from ..runtime.identity import code_fingerprint, frontend_info, git_info
from ..runtime.models import (
    TERMINAL_TASK_STATES,
    Batch,
    BatchFolder,
    BatchSite,
    BuildContinuation,
    BuildRecord,
    QualityFeedback,
    RuleVersion,
    SiteRule,
    Task,
    WorkbenchNode,
    WorkbenchTaskDef,
    WorkItem,
    utc_now,
)
from ..runtime.rule import RuleError, load_rule
from ..runtime.store import (
    BatchFolderConflictError,
    BatchFolderError,
    BatchFolderNameError,
    BatchFolderNotFoundError,
    BatchNotFoundError,
    BatchTransitionError,
    BuildContinuationConflictError,
    CleanupError,
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
from ..runtime.system_metrics import SystemMetricsSampler
from ..runtime.worker import Worker
from .access import (
    LOOPBACK_HOSTS,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    SETTING_DEV_NO_AUTH,
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

FRONTEND_DIST_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"
DEV_IDENTITY_PATH = "/api/dev/identity"
EXPORT_FILES = (
    "products.csv",
    "task-result.json",
    "records.jsonl",
    "diagnostics/excluded.jsonl",
    "diagnostics/failed.jsonl",
)


class Limits(BaseModel):
    max_urls: int | None = Field(default=100, ge=1, le=100000)
    max_products: int | None = Field(default=20, ge=1, le=100000)
    max_seconds: int | None = Field(default=180, ge=1, le=86400)
    max_attempts: int = Field(default=2, ge=1, le=10)
    max_navigation: int | None = Field(default=None, ge=1, le=10000)
    max_sitemaps: int | None = Field(default=None, ge=1, le=1000)
    concurrency: int | None = Field(
        default=None, ge=1, le=RATE_LIMIT_MAX_CONCURRENCY
    )
    per_domain_rps: float | None = Field(
        default=None, ge=RATE_LIMIT_MIN_RPS, le=RATE_LIMIT_MAX_RPS
    )
    delay_ms: int | None = Field(
        default=None, ge=0, le=RATE_LIMIT_MAX_DELAY_MS
    )


class CreateTaskRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    rule_id: str
    rule_version: str
    task_type: Literal["product", "discovery"] = "product"
    limits: Limits = Field(default_factory=Limits)
    proxy: str | None = Field(default=None, max_length=500)


class WorkbenchGroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    parent_id: str | None = Field(default=None, max_length=40)
    after_node_id: str | None = Field(default=None, max_length=40)


class WorkbenchNodeRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class WorkbenchNodeMoveRequest(BaseModel):
    parent_id: str | None = Field(default=None, max_length=40)
    after_node_id: str | None = Field(default=None, max_length=40)
    before_node_id: str | None = Field(default=None, max_length=40)


class WorkbenchTaskCreateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    input_url: str = Field(min_length=1, max_length=1000)
    parent_id: str | None = Field(default=None, max_length=40)
    rule_id: str = Field(min_length=1, max_length=200)
    rule_version: str = Field(min_length=1, max_length=120)
    task_type: Literal["product", "discovery"] = "product"
    collection_mode: Literal["sample", "formal"] = "sample"
    country: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=80)
    market: str | None = Field(default=None, max_length=80)
    category: str | None = Field(default=None, max_length=120)
    limits: Limits = Field(default_factory=Limits)
    proxy: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=2000)


class WorkbenchTaskUpdateRequest(BaseModel):
    rule_id: str | None = Field(default=None, min_length=1, max_length=200)
    rule_version: str | None = Field(default=None, min_length=1, max_length=120)
    task_type: Literal["product", "discovery"] | None = None
    collection_mode: Literal["sample", "formal"] | None = None
    country: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=80)
    market: str | None = Field(default=None, max_length=80)
    category: str | None = Field(default=None, max_length=120)
    limits: Limits | None = None
    proxy: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=2000)


class WorkbenchTaskCloneRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    parent_id: str | None = Field(default=None, max_length=40)
    copy_rule: bool = False
    copy_data: bool = False
    copy_run_id: str | None = Field(default=None, max_length=100)


class WorkbenchBatchImportRequest(BaseModel):
    batch_id: str = Field(min_length=1, max_length=40)
    parent_id: str | None = Field(default=None, max_length=40)


class WorkbenchRunAttachRequest(BaseModel):
    parent_id: str | None = Field(default=None, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=80)


class WorkbenchStartRequest(BaseModel):
    request_id: str | None = Field(default=None, max_length=200)


class WorkbenchRunLimitsUpdate(BaseModel):
    max_urls: int | None = Field(default=None, ge=1, le=100000)
    max_products: int | None = Field(default=None, ge=1, le=100000)
    max_seconds: int | None = Field(default=None, ge=1, le=86400)
    max_attempts: int | None = Field(default=None, ge=1, le=10)
    max_navigation: int | None = Field(default=None, ge=1, le=10000)
    max_sitemaps: int | None = Field(default=None, ge=1, le=1000)


class WorkbenchRunRateUpdate(BaseModel):
    concurrency: int | None = Field(
        default=None, ge=1, le=RATE_LIMIT_MAX_CONCURRENCY
    )
    per_domain_rps: float | None = Field(
        default=None, ge=RATE_LIMIT_MIN_RPS, le=RATE_LIMIT_MAX_RPS
    )
    delay_ms: int | None = Field(
        default=None, ge=0, le=RATE_LIMIT_MAX_DELAY_MS
    )


class WorkbenchRunConfigUpdate(BaseModel):
    limits: WorkbenchRunLimitsUpdate | None = None
    rate: WorkbenchRunRateUpdate | None = None
    sync_definition: bool = True
    action: Literal["save", "continue"] = "save"
    reset_discovery: bool = False


class WorkbenchRecentDismissRequest(BaseModel):
    task_ids: list[str] = Field(min_length=1, max_length=200)


class WorkbenchCleanupRequest(BaseModel):
    purge_runs: bool = False
    purge_feedback: bool = False


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
    applies_to: Literal["CURRENT_RUN", "NEXT_RUN"] = "CURRENT_RUN"
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
    active_repair_build_id: str | None = None


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
    feedback_ids: list[str] = Field(default_factory=list, max_length=50)
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


class FeedbackBundleRequest(BaseModel):
    feedback_ids: list[str] = Field(min_length=1, max_length=50)


class FeedbackBundleBlocker(BaseModel):
    feedback_id: str
    reason: str


class FeedbackBundleResponse(BaseModel):
    can_repair: bool
    site_key: str | None = None
    batch_id: str | None = None
    rule: FeedbackRuleRef | None = None
    items: list[FeedbackRecord]
    blockers: list[FeedbackBundleBlocker]


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
    retired_at: str | None = None
    retired_by: str | None = None


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


class RuleRetireRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    expected_active_version: str | None = Field(default=None, max_length=120)
    expected_active_sha256: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=2000)
    actor: str | None = Field(default=None, max_length=120)


class RuleCleanupRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=2000)
    actor: str | None = Field(default=None, max_length=120)


class RuleCleanupReferences(BaseModel):
    tasks: int = 0
    builds: int = 0
    builds_active: int = 0
    feedback: int = 0
    site_rules: int = 0
    batch_sites: int = 0
    workbench_defs: int = 0
    activations: int = 0
    child_versions: int = 0
    samples: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class RuleVersionCleanupPreview(BaseModel):
    rule_id: str
    rule_version: str
    sha256: str
    status: str
    path: str
    file_exists: bool
    bytes: int
    references: RuleCleanupReferences
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    can_purge: bool


class RuleCleanupResult(BaseModel):
    purged: bool
    cleanup_id: str
    rule_id: str
    rule_version: str
    sha256: str
    path: str
    bytes: int
    file_removed: bool
    residual_path: str | None = None
    references: RuleCleanupReferences


class BatchCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    collection_mode: Literal["sample", "formal"] | None = None
    country: str | None = Field(default=None, max_length=80)
    market: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=80)
    category: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=2000)
    folder_id: str | None = Field(default=None, max_length=40)
    workbench_parent_id: str | None = Field(default=None, max_length=40)
    sites: list[str] = Field(default_factory=list, max_length=5000)
    sites_text: str = Field(default="", max_length=500000)
    preview: bool = False


class BatchUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=2000)
    folder_id: str | None = Field(default=None, max_length=40)


class BatchMoveRequest(BaseModel):
    batch_ids: list[str] = Field(min_length=1, max_length=500)
    folder_id: str | None = Field(default=None, max_length=40)


class BatchFolderCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    parent_id: str | None = Field(default=None, max_length=40)


class BatchFolderUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    parent_id: str | None = Field(default=None, max_length=40)


class BatchImportRequest(BaseModel):
    sites: list[str] = Field(default_factory=list, max_length=5000)
    sites_text: str = Field(default="", max_length=500000)


class CollectionPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    formal_unlimited: bool = True
    formal_max_products: int | None = Field(default=None, ge=1, le=100000)
    formal_max_seconds: int | None = Field(default=None, ge=60, le=86400)
    default_per_domain_rps: float | None = Field(default=None, ge=0.1, le=10)
    default_concurrency: int | None = Field(default=None, ge=1, le=8)


class ImageProxyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["auto", "specified", "direct"] = "auto"
    proxy: str | None = Field(default=None, max_length=500)


class PreviewSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thumbnails_enabled: StrictBool = True
    realtime_limit: StrictInt = 5
    realtime_batch_size: StrictInt = 50


class SiteRatePolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    per_domain_rps: float | None = Field(default=None, ge=0.1, le=10)
    concurrency: int | None = Field(default=None, ge=1, le=8)
    delay_ms: int | None = Field(default=None, ge=0, le=10000)
    max_attempts: int | None = Field(default=None, ge=1, le=5)
    backoff_ms: int | None = Field(default=None, ge=0, le=60000)


class BatchStartRequest(BaseModel):
    limits: Limits | None = None
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


class OnboardingBudgetRequest(BaseModel):
    max_seconds: int = Field(ge=60, le=7200, strict=True)
    max_input_tokens: int = Field(ge=1000, le=100_000_000, strict=True)
    max_output_tokens: int = Field(ge=1000, le=10_000_000, strict=True)


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


class SystemDevNoAuthRequest(BaseModel):
    enabled: bool


class SystemCollectionSlotsRequest(BaseModel):
    # The settings page must be able to round-trip every saved integer.
    max_tasks: int | None = Field(ge=1, le=2**53 - 1, strict=True)


COLLECTION_SLOTS_SETTING = "worker_max_tasks"
DEFAULT_COLLECTION_SLOTS = 1


BUILD_SLOTS_SETTING = "max_concurrent_builds"


def _saved_slots(store: TaskStore, setting: str) -> int | None:
    raw = store.get_setting(setting)
    if raw is None:
        return None
    try:
        return SystemCollectionSlotsRequest.model_validate_json(raw).max_tasks
    except ValidationError:
        logger.warning("Invalid saved value for %s, using application default", setting)
        return None


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


def _feedback_payload(
    feedback: QualityFeedback, *, active_repair_build_id: str | None = None
) -> FeedbackRecord:
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
        applies_to=feedback.applies_to,
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
        active_repair_build_id=active_repair_build_id,
    )


def _feedback_payloads(
    store: TaskStore, items: list[QualityFeedback]
) -> list[FeedbackRecord]:
    active_by_site: dict[str | None, str | None] = {}
    payloads = []
    for item in items:
        if item.site_key not in active_by_site:
            active_by_site[item.site_key] = store.find_active_repair_build(item.site_key)
        payloads.append(
            _feedback_payload(
                item,
                active_repair_build_id=active_by_site[item.site_key],
            )
        )
    return payloads


def _feedback_bundle(
    store: TaskStore, feedback_ids: list[str]
) -> dict[str, Any]:
    """Validate a merge request and return eligible records plus blockers."""
    items: list[QualityFeedback] = []
    blockers: list[dict[str, str]] = []
    seen: set[str] = set()
    reference: QualityFeedback | None = None
    for feedback_id in feedback_ids:
        if feedback_id in seen:
            continue
        seen.add(feedback_id)
        feedback = store.get_feedback(feedback_id)
        if feedback is None:
            blockers.append({"feedback_id": feedback_id, "reason": "反馈不存在"})
            continue
        if feedback.status not in {"OPEN", "TRIAGED"}:
            blockers.append(
                {
                    "feedback_id": feedback_id,
                    "reason": f"状态为 {feedback.status}，只有未启动的反馈可以合并修复",
                }
            )
            continue
        if feedback.triage not in {None, "RULE_REPAIR"}:
            blockers.append(
                {
                    "feedback_id": feedback_id,
                    "reason": f"分诊结论为 {feedback.triage}，不能进入规则修复",
                }
            )
            continue
        if feedback.category in {"ACCESS_RUNTIME", "BUSINESS_EXPECTATION"}:
            blockers.append(
                {
                    "feedback_id": feedback_id,
                    "reason": "访问运行或业务预期类反馈不走规则修复",
                }
            )
            continue
        if not feedback.batch_id or not feedback.site_key:
            blockers.append(
                {
                    "feedback_id": feedback_id,
                    "reason": "反馈没有批次或站点，无法发起修复构建",
                }
            )
            continue
        if reference is None:
            reference = feedback
        else:
            if feedback.site_key != reference.site_key:
                blockers.append(
                    {
                        "feedback_id": feedback_id,
                        "reason": f"属于其他站点：{feedback.site_key}",
                    }
                )
                continue
            if (feedback.rule_id, feedback.rule_version) != (
                reference.rule_id,
                reference.rule_version,
            ):
                blockers.append(
                    {
                        "feedback_id": feedback_id,
                        "reason": "规则版本与本次合并的基准反馈不同",
                    }
                )
                continue
        items.append(feedback)
    site_key = reference.site_key if reference else None
    batch_id = reference.batch_id if reference else None
    rule = (
        FeedbackRuleRef(
            rule_id=reference.rule_id,
            rule_version=reference.rule_version,
            sha256=reference.rule_sha256,
        )
        if reference and reference.rule_id
        else None
    )
    return {
        "can_repair": bool(items) and not blockers,
        "site_key": site_key,
        "batch_id": batch_id,
        "rule": rule,
        "items": items,
        "blockers": blockers,
    }


_RESULT_VIEW_KEYS = (
    "counts",
    "coverage",
    "quality_exceptions",
    "content_audit",
    "recovery",
    "stop_detail",
    "stop_detail_code",
    "stop_evidence",
    "language_check",
)


@lru_cache(maxsize=256)
def _cached_task_result(
    path_text: str, _mtime_ns: int, _size: int
) -> dict[str, Any]:
    """Cache only the result fields the web layer reads.

    ``task-result.json`` can be large (pricing rows are much bigger than the
    list counters), so keeping the whole parsed payload would retain hundreds
    of MB. The cache key carries mtime and size, matching the product index
    pattern, so a replaced result file is re-read on the next request.
    """

    path = Path(path_text)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {key: payload[key] for key in _RESULT_VIEW_KEYS if key in payload}


def _load_result(out_root: Path, task_id: str) -> dict[str, Any]:
    path = out_root / task_id / "task-result.json"
    try:
        stat = path.stat()
    except OSError:
        return {}
    if not path.is_file():
        return {}
    return _cached_task_result(str(path), stat.st_mtime_ns, stat.st_size)


def _task_output_dir(out_root: Path, task_id: str) -> Path:
    root = out_root.resolve()
    candidate = (root / task_id).resolve()
    if candidate.parent != root or candidate.name != task_id:
        raise ValueError(f"invalid task output directory: {task_id}")
    return candidate


def _directory_stats(path: Path) -> dict[str, int]:
    if not path.exists():
        return {"bytes": 0, "files": 0}
    total_bytes = 0
    file_count = 0
    for directory, _, filenames in os.walk(path):
        for filename in filenames:
            try:
                total_bytes += (Path(directory) / filename).stat().st_size
                file_count += 1
            except OSError:
                continue
    return {"bytes": total_bytes, "files": file_count}


def _with_cleanup_stats(out_root: Path, preview: dict[str, Any]) -> dict[str, Any]:
    total_bytes = 0
    total_files = 0
    if "runs" in preview:
        for run in preview["runs"]:
            try:
                stats = _directory_stats(_task_output_dir(out_root, run["task_id"]))
            except ValueError:
                stats = {"bytes": 0, "files": 0}
            run.update(stats)
            total_bytes += stats["bytes"]
            total_files += stats["files"]
    else:
        stats = _directory_stats(_task_output_dir(out_root, preview["task_id"]))
        total_bytes = stats["bytes"]
        total_files = stats["files"]
    preview["bytes"] = total_bytes
    preview["files"] = total_files
    return preview


def _workbench_terminal_runs(store: TaskStore, node_id: str) -> list[tuple[Any, Task]]:
    pairs: list[tuple[Any, Task]] = []
    for run in store.list_workbench_task_runs():
        if run.node_id != node_id:
            continue
        task = store.get_task(run.task_id)
        if task is not None and task.state in TERMINAL_TASK_STATES:
            pairs.append((run, task))
    pairs.sort(key=lambda item: item[0].created_at, reverse=True)
    return pairs


def _clone_default_name(source_name: str, siblings: list[WorkbenchNode]) -> str:
    base = f"{source_name.strip() or '任务'} 副本"[:80]
    names = {node.name for node in siblings}
    if base not in names:
        return base
    index = 2
    while index < 1000:
        suffix = f" ({index})"
        candidate = base[: max(1, 80 - len(suffix))] + suffix
        if candidate not in names:
            return candidate
        index += 1
    return f"{base[:73]}-{uuid.uuid4().hex[:6]}"


def _clone_rule_source(
    rules_dir: Path | None, definition: WorkbenchTaskDef
) -> tuple[Any | None, str | None]:
    if rules_dir is None or not rules_dir.is_dir():
        return None, "未配置规则目录"
    if not definition.rule_path:
        return None, "任务定义没有规则文件"
    root = rules_dir.resolve()
    try:
        path = (root / definition.rule_path).resolve()
    except OSError as exc:
        return None, f"规则路径无法解析：{exc}"
    if not path.is_relative_to(root):
        return None, "规则文件不在规则目录内"
    if not path.is_file():
        return None, "规则文件不存在"
    try:
        rule = load_rule(path)
    except Exception as exc:  # noqa: BLE001 - rule files are user data
        return None, f"规则文件无法加载：{exc}"
    if rule.rule_id != definition.rule_id:
        return None, "规则文件与任务定义的 rule_id 不一致"
    if rule.rule_version != definition.rule_version:
        return None, "规则文件与任务定义的 rule_version 不一致"
    if not rule.capabilities.get(definition.task_type):
        return None, f"规则不支持任务类型 {definition.task_type}"
    return rule, None


def _yaml_scalar(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value):
        return value
    return "'" + value.replace("'", "''") + "'"


def _clone_rule_text(text: str, version: str, now: str) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()

    def replace_top_level(key: str, value: str) -> int:
        pattern = re.compile(rf"^{re.escape(key)}\s*:")
        for index, line in enumerate(lines):
            if pattern.match(line):
                lines[index] = f"{key}: {value}"
                return index
        return -1

    version_index = replace_top_level("rule_version", _yaml_scalar(version))
    if version_index < 0:
        raise ValueError("规则文件缺少 rule_version")
    status_index = replace_top_level("status", "candidate")
    if status_index < 0:
        status_index = version_index + 1
        lines.insert(status_index, "status: candidate")
    updated_index = replace_top_level("updated_at", f"'{now}'")
    if updated_index < 0:
        lines.insert(status_index + 1, f"updated_at: '{now}'")
    return newline.join(lines) + newline


def _clone_rule_names(source: Path, source_version: str) -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:6]
    base_version = (source_version.strip() or "clone")[:64].rstrip("-._") or "clone"
    version = f"{base_version}-exp-{suffix}"
    stem = source.stem
    maximum = 120 - len("-exp-") - len(suffix) - len(source.suffix)
    if len(stem) > maximum:
        stem = stem[:maximum].rstrip("-._") or "rule"
    return version, f"{stem}-exp-{suffix}{source.suffix}"


def _write_clone_rule(
    source: Path, rules_root: Path, *, version: str, filename: str, now: str
) -> Path:
    target = rules_root / filename
    if target.exists():
        raise ValueError(f"规则副本已存在：{filename}")
    text = source.read_bytes().decode("utf-8-sig")
    new_text = _clone_rule_text(text, version, now)
    with target.open("x", encoding="utf-8", newline="") as handle:
        handle.write(new_text)
    try:
        rule = load_rule(target)
        if rule.rule_version != version:
            raise ValueError("规则副本元数据与原规则不一致")
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


def _clone_task_snapshot(
    source: Task, *, task_id: str, node_id: str, now: str
) -> Task:
    task_input = dict(source.input or {})
    task_input["cloned_from"] = source.task_id
    task_input["source_workbench_node_id"] = task_input.get("workbench_node_id")
    task_input["workbench_node_id"] = node_id
    return replace(
        source,
        task_id=task_id,
        input=task_input,
        limits=dict(source.limits or {}),
        output=dict(source.output or {}),
        counters=dict(source.counters or {}),
        created_at=now,
        updated_at=now,
        started_at=now,
        finished_at=now,
        archived_at=None,
        batch_id=None,
        lease_owner=None,
        lease_token=0,
        lease_expires_at=None,
        lease_heartbeat_at=None,
    )


def _copy_clone_output(
    source_dir: Path, target_dir: Path, *, source: Task, clone: Task
) -> None:
    shutil.copytree(source_dir, target_dir)
    result_path = target_dir / "task-result.json"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("运行结果文件不是对象")
    payload["task_id"] = clone.task_id
    payload["cloned_from"] = source.task_id
    payload["source_started_at"] = source.started_at
    payload["source_finished_at"] = source.finished_at
    payload["started_at"] = clone.started_at
    payload["finished_at"] = clone.finished_at
    result_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _workbench_clone_preview(
    store: TaskStore, root: Path, rules_dir: Path | None, node_id: str
) -> dict[str, Any]:
    node = store.get_workbench_node(node_id)
    definition = store.get_workbench_task_def(node_id)
    if node is None or node.node_type != "task" or definition is None:
        raise KeyError(f"unknown workbench task: {node_id}")

    rule, rule_error = _clone_rule_source(rules_dir, definition)
    terminal_runs = _workbench_terminal_runs(store, node_id)
    source_run = terminal_runs[0] if terminal_runs else None
    run_stats = {"bytes": 0, "files": 0}
    data_error: str | None = None
    if source_run is None:
        data_error = "还没有已结束的运行可复制"
    else:
        try:
            source_dir = _task_output_dir(root, source_run[1].task_id)
        except ValueError:
            source_dir = None
        if source_dir is None or not source_dir.is_dir():
            data_error = "运行输出目录不存在"
        else:
            run_stats = _directory_stats(source_dir)
            if not run_stats["files"]:
                data_error = "运行输出目录为空"
            else:
                result_path = source_dir / "task-result.json"
                if not result_path.is_file():
                    data_error = "运行结果文件缺失"
                else:
                    try:
                        payload = json.loads(result_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        data_error = "运行结果文件损坏"
                    else:
                        if not isinstance(payload, dict):
                            data_error = "运行结果文件不是对象"

    siblings = [
        item
        for item in store.list_workbench_nodes()
        if item.parent_id == node.parent_id and item.node_id != node.node_id
    ]
    source_rule = None
    if rule is not None:
        source_rule = {
            "rule_id": rule.rule_id,
            "rule_version": rule.rule_version,
            "path": rule.path.resolve().relative_to(rules_dir.resolve()).as_posix()
            if rules_dir is not None
            else rule.path.name,
            "status": rule.raw.get("status", "candidate"),
            "sha256": hashlib.sha256(rule.path.read_bytes()).hexdigest(),
        }
    source_run_payload = None
    if source_run is not None:
        source_run_payload = {
            "task_id": source_run[1].task_id,
            "state": source_run[1].state,
            "outcome": source_run[1].outcome,
            "started_at": source_run[1].started_at,
            "finished_at": source_run[1].finished_at,
            "bytes": run_stats["bytes"],
            "files": run_stats["files"],
        }
    return {
        "node_id": node.node_id,
        "name": node.name,
        "parent_id": node.parent_id,
        "definition": _workbench_definition_payload(definition),
        "source_rule": source_rule,
        "source_run": source_run_payload,
        "default_name": _clone_default_name(node.name, siblings),
        "can_copy_rule": rule is not None,
        "can_copy_data": data_error is None,
        "rule_blockers": [rule_error] if rule_error else [],
        "data_blockers": [data_error] if data_error else [],
    }


def _retired_site_rule(
    store: TaskStore, *, site_key: str | None = None, rule_id: str | None = None
) -> SiteRule | None:
    for site_rule in store.list_site_rules():
        if not site_rule.retired_at:
            continue
        if site_key and site_rule.site_key == site_key:
            return site_rule
        if rule_id and site_rule.rule_id == rule_id:
            return site_rule
    return None


def _rule_cleanup_blockers(references: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if references.get("tasks"):
        blockers.append(f"仍有 {references['tasks']} 个任务引用")
    if references.get("builds_active"):
        blockers.append(f"有 {references['builds_active']} 个进行中的构建引用")
    if references.get("feedback"):
        blockers.append(f"仍有 {references['feedback']} 条反馈引用")
    if references.get("site_rules"):
        blockers.append(f"仍是 {references['site_rules']} 个站点的当前规则")
    if references.get("batch_sites"):
        blockers.append(f"仍有 {references['batch_sites']} 个批次站点指向")
    if references.get("workbench_defs"):
        blockers.append(f"仍有 {references['workbench_defs']} 个任务定义指向")
    if references.get("activations"):
        blockers.append(f"激活审计引用 {references['activations']} 条")
    if references.get("child_versions"):
        blockers.append(f"有 {references['child_versions']} 个新版本以它为父版本")
    return blockers


def _rule_cleanup_preview(
    store: TaskStore,
    rules_dir: Path | None,
    rule_id: str,
    rule_version: str,
) -> dict[str, Any]:
    version = store.get_rule_version(rule_id, rule_version)
    if version is None:
        raise KeyError(f"unknown rule version: {rule_id}@{rule_version}")
    references = store.rule_version_references(
        rule_id, rule_version, version.sha256
    )
    blockers: list[str] = []
    warnings: list[str] = []
    if version.status not in {"candidate", "rejected"}:
        blockers.append(
            f"当前状态为 {version.status}，只允许清理 candidate/rejected 版本"
        )
    blockers.extend(_rule_cleanup_blockers(references))
    file_exists = False
    file_bytes = 0
    if rules_dir is None or not rules_dir.is_dir():
        blockers.append("未配置规则目录")
    else:
        root = rules_dir.resolve()
        try:
            path = (root / version.path).resolve()
        except OSError:
            path = None
        if path is None or not path.is_relative_to(root):
            blockers.append("规则文件不在规则目录内")
        else:
            file_exists = path.is_file()
            if file_exists:
                try:
                    file_bytes = path.stat().st_size
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                except OSError:
                    digest = None
                if digest is None:
                    blockers.append("规则文件无法读取")
                elif digest != version.sha256:
                    blockers.append("规则文件哈希与账本不一致")
            else:
                warnings.append("规则文件已缺失，清理只移除账本记录")
    if references.get("builds") and not references.get("builds_active"):
        warnings.append(
            f"{references['builds']} 个已结束构建保留版本号和哈希；"
            "构建详情会显示规则版本已清理"
        )
    return {
        "rule_id": version.rule_id,
        "rule_version": version.rule_version,
        "sha256": version.sha256,
        "status": version.status,
        "path": version.path,
        "file_exists": file_exists,
        "bytes": file_bytes,
        "references": references,
        "blockers": blockers,
        "warnings": warnings,
        "can_purge": not blockers,
    }


def _resolve_rule_path(
    rules_dir: Path | None, relative: str
) -> Path | None:
    if rules_dir is None or not rules_dir.is_dir():
        return None
    root = rules_dir.resolve()
    try:
        path = (root / relative).resolve()
    except OSError:
        return None
    return path if path.is_relative_to(root) else None


def _finish_rule_cleanup(
    store: TaskStore, cleanup: dict[str, Any], rules_dir: Path | None
) -> dict[str, Any]:
    path = _resolve_rule_path(rules_dir, str(cleanup["path"]))
    residual_path = None
    file_removed = path is None
    if path is not None:
        if not path.exists():
            file_removed = True
        else:
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                digest = None
            if digest != cleanup["sha256"]:
                residual_path = str(path)
                file_removed = False
            else:
                try:
                    path.unlink()
                    file_removed = True
                except OSError:
                    residual_path = str(path)
                    file_removed = False
    updated = store.update_rule_cleanup_file(
        cleanup["cleanup_id"],
        file_removed=file_removed,
        residual_path=residual_path,
    )
    return _rule_cleanup_payload(updated)


def _rule_cleanup_payload(cleanup: dict[str, Any]) -> dict[str, Any]:
    return {
        "purged": True,
        "cleanup_id": cleanup["cleanup_id"],
        "rule_id": cleanup["rule_id"],
        "rule_version": cleanup["rule_version"],
        "sha256": cleanup["sha256"],
        "path": cleanup["path"],
        "bytes": cleanup["bytes"],
        "file_removed": cleanup["file_removed"],
        "residual_path": cleanup["residual_path"],
        "references": cleanup["references"],
    }


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


def _summary(
    store: TaskStore,
    task: Task,
    out_root: Path,
    *,
    site_rules: dict[str, SiteRule] | None = None,
    feedback_summaries: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result = _current_task_result(task, out_root)
    site_key = task.site_key or task.plan_id
    site_rule = (
        site_rules.get(site_key)
        if site_rules is not None
        else store.get_site_rule(site_key)
    )
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
    if feedback_summaries is None:
        feedback, _ = store.list_feedback(task_id=task.task_id, limit=50)
        open_feedback = [
            item
            for item in feedback
            if item.status not in {"RESOLVED", "WONTFIX"}
        ]
        latest_feedback = feedback[0] if feedback else None
        feedback_payload = {
            "open": len(open_feedback),
            "latest_id": latest_feedback.feedback_id if latest_feedback else None,
            "latest_status": latest_feedback.status if latest_feedback else None,
        }
    else:
        feedback_payload = feedback_summaries.get(task.task_id) or {
            "open": 0,
            "latest_id": None,
            "latest_status": None,
        }
    counts = _counts(store, task, result)
    continuation = _workbench_run_can_continue(store, task, result)
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
        "stop_detail": _workbench_stop_detail(task, counts, result),
        "stop_detail_code": result.get("stop_detail_code"),
        "stop_evidence": result.get("stop_evidence") or None,
        "language_check": result.get("language_check") or None,
        "can_continue": continuation["can_continue"],
        "continue_hint": continuation["continue_hint"],
        **_task_recovery_payload(task, result),
        "limits": dict(task.limits),
        "counts": counts,
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
        "feedback": feedback_payload,
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


def _workbench_host_key(value: str) -> str:
    return normalize_domain(value).removeprefix("www.")


def _workbench_definition_payload(definition: WorkbenchTaskDef | None) -> dict[str, Any] | None:
    if definition is None:
        return None
    return {
        "input_url": definition.input_url,
        "domain": definition.domain,
        "site_key": definition.site_key,
        "batch_id": definition.batch_id,
        "country": definition.country,
        "language": definition.language,
        "market": definition.market,
        "category": definition.category,
        "task_type": definition.task_type,
        "collection_mode": definition.collection_mode,
        "rule_id": definition.rule_id,
        "rule_version": definition.rule_version,
        "limits": definition.limits,
        "proxy": definition.proxy,
        "note": definition.note,
    }


_RUN_DISCOVERY_DETAIL_MARKERS = (
    "max_sitemaps",
    "max_navigation",
    "max_pages",
    "max_depth",
    "max_batches",
    "max_requests",
    "max_products",
    "max_urls",
)

LIMIT_KEYS = (
    "max_urls",
    "max_products",
    "max_seconds",
    "max_attempts",
    "max_navigation",
    "max_sitemaps",
)


def _workbench_stop_detail(
    task: Task, counts: dict[str, int], result: dict[str, Any]
) -> str | None:
    detail = result.get("stop_detail")
    if task.state not in {"FINISHED", "CANCELLED"}:
        return None
    if task.stop_reason != "BUDGET_EXHAUSTED":
        return str(detail) if detail else None
    generic = {
        "task budget exhausted",
        "formal collection reached its product limit",
    }
    if detail and detail not in generic:
        return str(detail)
    if task.task_type == "discovery":
        limit = task.limits.get("max_urls")
        processed = (
            int(counts.get("valid_urls") or 0)
            + int(counts.get("excluded_urls") or 0)
            + int(counts.get("failed_urls") or 0)
        )
        label = "URL 数"
    else:
        limit = task.limits.get("max_products")
        processed = int(counts.get("processed_products") or 0)
        label = "商品数"
    if limit is not None and processed >= int(limit):
        return f"{label}达到入队时的上限 {int(limit)}"
    max_seconds = task.limits.get("max_seconds")
    if max_seconds is not None:
        seconds = int(max_seconds)
        hours = seconds / 3600
        suffix = f"（{hours:g} 小时）" if hours >= 1 else ""
        return f"任务时长达到入队时的上限 {seconds} 秒{suffix}"
    return str(detail) if detail else None


def _current_task_result(task: Task, root: Path) -> dict[str, Any]:
    if task.state not in TERMINAL_TASK_STATES or task.output.get("recovery_export_pending"):
        return {}
    return _load_result(root, task.task_id)


def _task_recovery_payload(task: Task, result: dict[str, Any]) -> dict[str, Any]:
    if task.state in {"RUNNING", "PAUSING", "CANCELLING"} and (
        task.lease_expires_at is None or task.lease_expires_at <= time.time()
    ):
        recovery = "WAITING_FOR_WORKER"
    elif task.output.get("recovery_export_pending"):
        recovery = "EXPORT_PENDING"
    elif (result.get("recovery") or {}).get("missing_product_records"):
        recovery = "RESULT_INCOMPLETE"
    elif task.output.get("recovered_at"):
        recovery = "RECOVERED"
    else:
        recovery = None
    return {"recovery_state": recovery, "recovered_at": task.output.get("recovered_at")}


def _workbench_run_can_continue(
    store: TaskStore, task: Task, result: dict[str, Any]
) -> dict[str, Any]:
    eligible = (
        task.state == "FINISHED"
        and task.stop_reason == "BUDGET_EXHAUSTED"
        and task.archived_at is None
        and not task.input.get("cloned_from")
    )
    stop_detail = str(result.get("stop_detail") or "")
    discovery_limit = str(task.counters.get("discovery_limit") or "")
    discovery_truncated = bool(discovery_limit) or any(
        marker in stop_detail for marker in _RUN_DISCOVERY_DETAIL_MARKERS
    )
    cloned_snapshot = bool(task.input.get("cloned_from"))
    if not eligible:
        # Most recent runs are not eligible. Avoid two per-task item-count
        # queries just to prove that a completed or active run cannot continue.
        return {
            "can_continue": False,
            "continue_hint": (
                "这是克隆的数据快照，不能续采；请从克隆任务定义启动新运行。"
                if cloned_snapshot
                else None
            ),
            "reset_discovery": discovery_truncated,
            "pending_products": 0,
            "pending_navigation": 0,
            "discovery_truncated": discovery_truncated,
        }
    products = store.item_counts(task.task_id, "product")
    navigation = store.item_counts(task.task_id, "navigation")
    pending_products = products.get("PENDING", 0) + products.get("IN_FLIGHT", 0)
    pending_navigation = navigation.get("PENDING", 0) + navigation.get(
        "IN_FLIGHT", 0
    )
    can_continue = pending_products + pending_navigation > 0 or discovery_truncated
    hints: list[str] = []
    if pending_products:
        valid = int((result.get("counts") or {}).get("valid_products") or 0)
        if not valid:
            valid = products.get("DONE", 0)
        hints.append(
            f"剩余 {pending_products} 个待采商品；续采会保留已采 {valid} 条结果。"
        )
    if pending_navigation:
        hints.append(f"剩余 {pending_navigation} 个导航／发现项。")
    if discovery_truncated:
        detail = stop_detail or discovery_limit or "发现上限"
        hints.append(
            f"发现被「{detail}」截断；续采会重置发现项并重新请求入口、分类或 sitemap。"
        )
    return {
        "can_continue": can_continue,
        "continue_hint": " ".join(hints) or None,
        "reset_discovery": discovery_truncated,
        "pending_products": pending_products,
        "pending_navigation": pending_navigation,
        "discovery_truncated": discovery_truncated,
    }


def _workbench_run_rule_limits(
    task: Task,
) -> dict[str, int]:
    if not task.rule_path:
        return {}
    try:
        rule = load_rule(task.rule_path)
    except (OSError, RuleError):
        return {}
    discovery_limits = rule.discovery.get("limits", {}) or {}
    sitemap_limits = [
        int(source.get("max_sitemaps", discovery_limits.get("max_sitemaps", 50)))
        for source in rule.sources
        if source.get("type") == "sitemap"
    ]
    return {
        "max_navigation": int(
            discovery_limits.get("max_navigation", 100) or 100
        ),
        "max_sitemaps": int(
            min(sitemap_limits)
            if sitemap_limits
            else discovery_limits.get("max_sitemaps", 50) or 50
        ),
    }


def _workbench_run_config_payload(
    store: TaskStore, root: Path, task: Task
) -> dict[str, Any]:
    result = _load_result(root, task.task_id)
    counts = _counts(store, task, result)
    raw_limits = dict(task.limits)
    raw_concurrency = raw_limits.get("concurrency")
    if isinstance(raw_concurrency, dict):
        product_concurrency = raw_concurrency.get(
            "product", raw_concurrency.get("navigation")
        )
    else:
        product_concurrency = raw_concurrency
    rate_policy = dict(task.input.get("rate_policy") or {})
    rule_limits = _workbench_run_rule_limits(task)
    raw_max_navigation = raw_limits.get("max_navigation")
    raw_max_sitemaps = raw_limits.get("max_sitemaps")
    raw_delay = raw_limits.get("fetch_delay_ms")
    if raw_delay is None:
        raw_delay = rate_policy.get("delay_ms")
    limits = {
        "max_urls": raw_limits.get("max_urls"),
        "max_products": raw_limits.get("max_products"),
        "max_seconds": raw_limits.get("max_seconds"),
        "max_attempts": int(raw_limits.get("max_attempts", 2) or 2),
        "max_navigation": (
            int(raw_max_navigation)
            if raw_max_navigation is not None
            else rule_limits.get("max_navigation")
        ),
        "max_sitemaps": (
            int(raw_max_sitemaps)
            if raw_max_sitemaps is not None
            else rule_limits.get("max_sitemaps")
        ),
        "concurrency": (
            int(product_concurrency)
            if product_concurrency is not None
            else rate_policy.get("concurrency")
        ),
        "per_domain_rps": rate_policy.get("per_domain_rps"),
        "delay_ms": int(raw_delay or 0),
    }
    run = next(
        (
            item
            for item in store.list_workbench_task_runs()
            if item.task_id == task.task_id
        ),
        None,
    )
    definition = store.get_workbench_task_def(run.node_id) if run else None
    node = store.get_workbench_node(run.node_id) if run else None
    site_policy = load_policies(store).get(
        normalize_domain(task.domain_key or task.site_key or ""), {}
    )
    can_continue = _workbench_run_can_continue(store, task, result)
    return {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "collection_mode": (
            task.input.get("collection_mode")
            or (definition.collection_mode if definition is not None else None)
        ),
        "state": task.state,
        "outcome": task.outcome,
        "stop_reason": task.stop_reason,
        "stop_detail": _workbench_stop_detail(task, counts, result),
        "stop_detail_code": result.get("stop_detail_code"),
        "stop_evidence": result.get("stop_evidence") or None,
        "language_check": result.get("language_check") or None,
        "counts": counts,
        "limits": limits,
        "definition": (
            {
                "node_id": definition.node_id,
                "name": node.name if node else definition.site_key,
                "collection_mode": definition.collection_mode,
                "limits": definition.limits,
            }
            if definition is not None
            else None
        ),
        "rule_limits": rule_limits,
        "site_rate_policy": site_policy or None,
        **can_continue,
    }


def _workbench_task_brief(store: TaskStore, task: Task | None, root: Path) -> dict[str, Any] | None:
    if task is None:
        return None
    result = _current_task_result(task, root)
    continuation = _workbench_run_can_continue(store, task, result)
    return {
        "task_id": task.task_id,
        "state": task.state,
        "outcome": task.outcome,
        "stop_reason": task.stop_reason,
        "stop_detail_code": result.get("stop_detail_code"),
        "can_continue": continuation["can_continue"],
        **_task_recovery_payload(task, result),
        "counts": task.counters,
        "started_at": task.started_at,
        "updated_at": task.updated_at,
    }


def _workbench_path(
    node: WorkbenchNode | None, nodes_by_id: dict[str, WorkbenchNode]
) -> str | None:
    if node is None:
        return None
    parts: list[str] = []
    parent_id = node.parent_id
    seen: set[str] = set()
    while parent_id and parent_id not in seen:
        seen.add(parent_id)
        parent = nodes_by_id.get(parent_id)
        if parent is None:
            break
        parts.append(parent.name)
        parent_id = parent.parent_id
    return " / ".join(reversed(parts)) if parts else None


def _workbench_tree_payload(store: TaskStore, root: Path) -> dict[str, Any]:
    nodes = store.list_workbench_nodes()
    nodes_by_id = {node.node_id: node for node in nodes}
    definitions = {item.node_id: item for item in store.list_workbench_task_defs()}
    site_by_node: dict[str, Any] = {}
    build_by_node: dict[str, Any] = {}
    for node_id, definition in definitions.items():
        if not definition.batch_id:
            continue
        site = store.get_batch_site(definition.batch_id, definition.site_key)
        if site is None:
            continue
        site_by_node[node_id] = site
        builds = store.list_builds(
            batch_id=definition.batch_id,
            site_key=definition.site_key,
            limit=1,
        )
        if builds:
            build_by_node[node_id] = builds[0]
    runs = sorted(store.list_workbench_task_runs(), key=lambda item: item.created_at)
    current_by_node: dict[str, Task] = {}
    for run in runs:
        task = store.get_task(run.task_id)
        if task is not None:
            current_by_node[run.node_id] = task

    task_counts = {node.node_id: 0 for node in nodes if node.node_type == "group"}
    running_counts = {node.node_id: 0 for node in nodes if node.node_type == "group"}
    for node in nodes:
        if node.node_type != "task":
            continue
        task = current_by_node.get(node.node_id)
        parent_id = node.parent_id
        seen: set[str] = set()
        while parent_id and parent_id not in seen:
            seen.add(parent_id)
            if parent_id in task_counts:
                task_counts[parent_id] += 1
                if task is not None and task.state == "RUNNING":
                    running_counts[parent_id] += 1
            parent = nodes_by_id.get(parent_id)
            parent_id = parent.parent_id if parent else None

    items: list[dict[str, Any]] = []
    for node in nodes:
        payload: dict[str, Any] = {
            "node_id": node.node_id,
            "node_type": node.node_type,
            "parent_id": node.parent_id,
            "name": node.name,
            "sort_order": node.sort_order,
            "created_at": node.created_at,
            "updated_at": node.updated_at,
        }
        if node.node_type == "group":
            payload["task_count"] = task_counts.get(node.node_id, 0)
            payload["running_count"] = running_counts.get(node.node_id, 0)
        else:
            payload["definition"] = _workbench_definition_payload(definitions.get(node.node_id))
            site = site_by_node.get(node.node_id)
            build = build_by_node.get(node.node_id)
            payload["site_readiness"] = site.readiness if site is not None else None
            payload["build"] = (
                {
                    "build_id": build.build_id,
                    "state": build.state,
                    "outcome": build.outcome,
                }
                if build is not None
                else None
            )
            payload["current_run"] = _workbench_task_brief(
                store, current_by_node.get(node.node_id), root,
            )
            payload["path"] = _workbench_path(node, nodes_by_id)
        items.append(payload)
    return {"nodes": items}


def _workbench_recent_payload(
    store: TaskStore,
    root: Path,
    *,
    scope: str,
    query: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    tasks = [task for task in store.list_tasks() if task.archived_at is None]
    runs = store.list_workbench_task_runs()
    nodes = store.list_workbench_nodes()
    nodes_by_id = {node.node_id: node for node in nodes}
    definitions = {item.node_id: item for item in store.list_workbench_task_defs()}
    node_by_task = {run.task_id: run.node_id for run in runs}
    dismissals = store.list_workbench_dismissals()
    batches = {
        batch.batch_id: batch for batch in store.list_batches(include_archived=True)
    }
    needle = query.strip().casefold()

    rows: list[tuple[str, Task]] = []
    counts = {"recent": 0, "running": 0, "queued": 0, "removed": 0}
    for task in tasks:
        dismissed = task.task_id in dismissals
        if dismissed:
            counts["removed"] += 1
        else:
            counts["recent"] += 1
            if task.state == "RUNNING":
                counts["running"] += 1
            elif task.state == "QUEUED":
                counts["queued"] += 1
        if scope == "recent" and dismissed:
            continue
        if scope == "running" and (dismissed or task.state != "RUNNING"):
            continue
        if scope == "removed" and not dismissed:
            continue
        node = nodes_by_id.get(node_by_task.get(task.task_id, ""))
        definition = definitions.get(node.node_id) if node else None
        batch = batches.get(task.batch_id or "")
        path = _workbench_path(node, nodes_by_id)
        haystack = " ".join(
            filter(
                None,
                (
                    task.task_id,
                    task.site_key,
                    task.domain_key,
                    node.name if node else "",
                    definition.domain if definition else "",
                    path or "",
                    batch.name if batch else "",
                ),
            )
        ).casefold()
        if needle and needle not in haystack:
            continue
        rows.append((task.started_at or task.created_at, task))
    rows.sort(key=lambda item: item[0], reverse=True)
    total = len(rows)
    page = rows[offset : offset + limit]

    page_task_ids = [task.task_id for _, task in page]
    site_rules = {rule.site_key: rule for rule in store.list_site_rules()}
    feedback_by_task = store.feedback_summaries(page_task_ids)
    items: list[dict[str, Any]] = []
    for _, task in page:
        node_id = node_by_task.get(task.task_id)
        node = nodes_by_id.get(node_id or "")
        definition = definitions.get(node_id or "")
        batch = batches.get(task.batch_id or "")
        summary = _summary(
            store,
            task,
            root,
            site_rules=site_rules,
            feedback_summaries=feedback_by_task,
        )
        summary.update(
            {
                "node_id": node_id,
                "path": _workbench_path(node, nodes_by_id),
                "definition_name": node.name if node else None,
                "definition": _workbench_definition_payload(definition),
                "batch_name": batch.name if batch else None,
                "dismissed": task.task_id in dismissals,
                "can_dismiss": task.state in TERMINAL_TASK_STATES,
            }
        )
        items.append(summary)
    unassigned_total = sum(
        1
        for task in tasks
        if task.task_id not in dismissals and task.task_id not in node_by_task
    )
    return {
        "total": total,
        "items": items,
        "counts": counts,
        "unassigned_total": unassigned_total,
    }


PRODUCT_INDEX_MAX_BYTES = 128 * 1024 * 1024


@lru_cache(maxsize=8)
def _cached_product_index(
    path_text: str,
    mtime_ns: int,
    size: int,
) -> dict[str, dict[str, str]]:
    """Index exported product rows by source URL for on-demand list enrichment.

    The cache key carries the file timestamp and size so a live products.jsonl
    is re-read after each append without persisting descriptions in the ledger.
    """

    path = Path(path_text)
    index: dict[str, dict[str, str]] = {}
    try:
        if path.suffix.lower() == ".csv":
            with path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    if not row:
                        continue
                    source_url = str(row.get("source_url") or "").strip()
                    if not source_url:
                        continue
                    normalized = {key: str(row.get(key) or "") for key in CSV_COLUMNS}
                    index[source_url] = normalized
                    index.setdefault(source_url.rstrip("/"), normalized)
        else:
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(record, dict):
                        continue
                    source_url = str(record.get("source_url") or "").strip()
                    if not source_url:
                        continue
                    normalized = {
                        key: str(record.get(key) or "") for key in CSV_COLUMNS
                    }
                    index[source_url] = normalized
                    index.setdefault(source_url.rstrip("/"), normalized)
    except (OSError, csv.Error, UnicodeDecodeError):
        return {}
    return index


def _product_row_index(task: Task, root: Path) -> dict[str, dict[str, str]]:
    task_dir = root / task.task_id
    terminal = task.state in {"FINISHED", "CANCELLED"}
    csv_path = task_dir / "products.csv"
    jsonl_path = task_dir / "products.jsonl"
    path = csv_path if terminal and csv_path.is_file() else jsonl_path
    if not path.is_file():
        return {}
    try:
        stat = path.stat()
    except OSError:
        return {}
    if stat.st_size > PRODUCT_INDEX_MAX_BYTES:
        return {}
    return _cached_product_index(str(path), stat.st_mtime_ns, stat.st_size)


def _item_payload(
    item: WorkItem,
    product_index: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    result = {
        key: value for key, value in item.result.items() if key != "product_record"
    }
    if product_index and item.item_type == "product" and item.state == "DONE":
        row = product_index.get(item.url) or product_index.get(item.url.rstrip("/"))
        if row:
            preview = dict(result.get("product_preview") or {})
            for key in ("description_html", "attributes"):
                value = row.get(key)
                if value:
                    preview[key] = value
            if preview:
                result["product_preview"] = preview
    return {
        "item_id": item.item_id,
        "item_type": item.item_type,
        "url": item.url,
        "state": item.state,
        "occurred_at": item.updated_at,
        "attempts": item.attempts,
        "failure_class": item.failure_class,
        "result": result,
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


def _client_is_loopback(request: Request) -> bool:
    client = request.client
    if client is None:
        return False
    try:
        address = ipaddress.ip_address(client.host)
    except ValueError:
        return False
    if address.version == 6 and address.ipv4_mapped is not None:
        return address.ipv4_mapped.is_loopback
    return address.is_loopback


def _is_dev_loopback_request(request: Request) -> bool:
    """Return True only for a loopback peer using a loopback Host header."""
    return _client_is_loopback(request) and is_loopback_host(
        request.headers.get("host", "")
    )


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
    # 旧入口只做兼容重定向，未认证时也应能加载。
    return path in {"/", "/favicon.ico", "/favicon.svg", "/next"} or path.startswith(
        ("/assets/", "/next/")
    )


def _is_auth_path(path: str) -> bool:
    return path in {"/api/auth/login", "/api/auth/logout"}


def _sse(event: str, data: Any, event_id: int | None = None) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.extend((f"event: {event}", f"data: {payload}"))
    return "\n".join(lines) + "\n\n"


class _EventLogIndex:
    """Byte offsets of non-empty lines in an append-only events.ndjson."""

    __slots__ = ("ends", "size", "starts")

    def __init__(self) -> None:
        self.size = 0
        self.starts: list[int] = []
        self.ends: list[int] = []


_EVENT_LOG_INDEXES: dict[str, _EventLogIndex] = {}
_EVENT_LOG_INDEX_LOCK = threading.Lock()


def _event_log_index(path: Path) -> _EventLogIndex:
    key = str(path)
    with _EVENT_LOG_INDEX_LOCK:
        index = _EVENT_LOG_INDEXES.get(key)
        if index is None:
            index = _EventLogIndex()
            _EVENT_LOG_INDEXES[key] = index
        if not path.is_file():
            index.size = 0
            index.starts.clear()
            index.ends.clear()
            return index
        stat = path.stat()
        if stat.st_size < index.size:
            index.size = 0
            index.starts.clear()
            index.ends.clear()
        if stat.st_size == index.size:
            return index
        with path.open("rb") as handle:
            handle.seek(index.size)
            data = handle.read()
        complete = data.rfind(b"\n") + 1
        if complete <= 0:
            return index
        chunk = data[:complete]
        cursor = index.size
        parts = chunk.split(b"\n")
        if parts and parts[-1] == b"":
            parts.pop()
        for raw in parts:
            if raw.strip():
                index.starts.append(cursor)
                index.ends.append(cursor + len(raw))
            cursor += len(raw) + 1
        index.size += complete
        return index


def _event_log_page(
    path: Path,
    *,
    limit: int,
    tail: int | None = None,
    before: int | None = None,
    after: int | None = None,
) -> dict[str, Any]:
    index = _event_log_index(path)
    total = len(index.starts)
    window = tail if tail is not None else limit
    if before is not None:
        end = min(max(0, before - 1), total)
        start = max(0, end - window)
        has_more = start > 0
    elif after is not None:
        start = min(max(0, after), total)
        end = min(total, start + window)
        has_more = end < total
    else:
        end = total
        start = max(0, total - window)
        has_more = start > 0

    items: list[dict[str, Any]] = []
    if end > start:
        with path.open("rb") as handle:
            for seq in range(start + 1, end + 1):
                handle.seek(index.starts[seq - 1])
                raw = handle.read(index.ends[seq - 1] - index.starts[seq - 1])
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(payload, dict):
                    items.append({**payload, "seq": seq})
    return {
        "items": items,
        "total": total,
        "has_more": has_more,
        "oldest_seq": start + 1 if end > start else None,
        "newest_seq": end if end > start else None,
    }


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
    max_tasks: int | None = None,
    max_builds: int | None = None,
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
    dev_no_auth: bool = False,
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
    slots_override = max_tasks is not None
    if slots_override:
        max_tasks = max(1, max_tasks or 1)
    else:
        max_tasks = _saved_slots(store, COLLECTION_SLOTS_SETTING) or DEFAULT_COLLECTION_SLOTS
    build_slots_override = max_builds is not None or build_manager is not None
    max_builds = (
        build_manager.max_concurrent if build_manager is not None
        else max(1, max_builds) if max_builds is not None
        else _saved_slots(store, BUILD_SLOTS_SETTING) or 1
    )
    root = Path(out_root)
    if not read_only:
        root.mkdir(parents=True, exist_ok=True)
    rules = Path(rules_dir).resolve() if rules_dir is not None else None
    builds_disabled = os.environ.get("ECOM_BUILD_DISABLED") == "1"

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
    stored_dev_no_auth = store.get_setting(SETTING_DEV_NO_AUTH)
    dev_no_auth_setting = stored_dev_no_auth == "1"
    dev_no_auth_forced = bool(dev_no_auth)
    dev_no_auth_active = dev_no_auth_forced or dev_no_auth_setting
    access_lock = threading.Lock()
    access_state: dict[str, Any] = {
        "lan_enabled": lan_enabled,
        "token_salt": token_salt,
        "token_hash": token_hash,
        "token_updated_at": token_updated_at,
        "dev_no_auth_setting": dev_no_auth_setting,
        "dev_no_auth_active": dev_no_auth_active,
        "dev_no_auth_forced": dev_no_auth_forced,
    }
    login_limiter = LoginRateLimiter()
    rate_policy_lock = threading.Lock()
    collection_policy_lock = threading.Lock()
    image_proxy_lock = threading.Lock()
    preview_settings_lock = threading.Lock()

    def _image_proxy_payload() -> dict[str, Any]:
        setting = load_image_proxy(store)
        return {
            **setting,
            "service_proxy_configured": bool(proxy),
        }

    def _collection_policy_payload() -> dict[str, Any]:
        policy = load_collection_policy(store)
        return {
            "policy": policy,
            "formal_limits": formal_collection_limits(policy),
            "default_rate": default_rate_overrides(policy),
            "site_policies": [
                {"domain": domain, **fields}
                for domain, fields in sorted(load_policies(store).items())
            ],
        }

    def _site_rate_policy_payload(site: BatchSite) -> dict[str, Any]:
        domain = normalize_domain(site.domain)
        policy = load_policies(store).get(domain, {})
        rule_fetch: dict[str, Any] = {}
        rule_path = getattr(site, "rule_path", None)
        if rules is not None and rule_path:
            try:
                rule_fetch = dict(load_rule(rules / str(rule_path)).fetch)
            except (OSError, ValueError):
                rule_fetch = {}
        defaults = effective_policy(
            None,
            default_rps=per_domain_rps,
            rule_fetch=rule_fetch,
        )
        return {
            "domain": domain,
            "policy": policy,
            "defaults": defaults,
            "effective": effective_policy(
                policy,
                default_rps=per_domain_rps,
                rule_fetch=rule_fetch,
            ),
        }

    def _save_site_rate_policy(
        site: BatchSite, payload: SiteRatePolicyRequest
    ) -> dict[str, Any]:
        domain = normalize_domain(site.domain)
        try:
            policy = validate_policy(payload.model_dump(exclude_none=True))
        except RatePolicyError as exc:
            raise _error("VALIDATION_ERROR", str(exc), 422) from exc
        with rate_policy_lock:
            policies = load_policies(store)
            if policy:
                policies[domain] = policy
            else:
                policies.pop(domain, None)
            if policies:
                store.set_setting(
                    SITE_RATE_POLICIES_SETTING,
                    dump_policies(policies),
                )
            else:
                store.delete_setting(SITE_RATE_POLICIES_SETTING)
        return _site_rate_policy_payload(site)

    urls = [str(url) for url in (access_urls or ()) if str(url).strip()]
    if not urls:
        display = f"[{serve_host}]" if ":" in serve_host else serve_host
        urls = [f"http://{display}:{serve_port}/"]
    started_at = utc_now()
    frontend_mounted = (FRONTEND_DIST_DIR / "index.html").is_file()
    frontend_kind = "react" if frontend_mounted else "none"
    startup_code_fingerprint = code_fingerprint(Path(__file__).resolve().parents[1])
    startup_frontend = frontend_info(FRONTEND_DIST_DIR)
    startup_git = git_info(Path(__file__).resolve().parents[4])
    instance_id = uuid.uuid4().hex[:12]
    worker_label = "read-only" if read_only else ("managed" if manage_worker else "external")

    def identity_fields() -> dict[str, Any]:
        return {
            "pid": os.getpid(),
            "host": serve_host,
            "port": serve_port,
            "started_at": started_at,
            "instance_id": instance_id,
            "code_fingerprint": startup_code_fingerprint,
            "git": startup_git,
            "frontend": {
                "kind": frontend_kind,
                "mounted": frontend_mounted,
                "index_sha256": startup_frontend["sha256"],
                "built_at": startup_frontend["built_at"],
            },
            "db": str(store.path),
            "worker": worker_label,
            "read_only": read_only,
        }

    started_monotonic = time.monotonic()
    system_metrics = SystemMetricsSampler()
    if build_manager is None and rules is not None:
        build_manager = BuildManager(
            store,
            root,
            rules,
            default_proxy=proxy,
            extra_permissions=build_extra_permissions,
            dependency_policy=build_dependency_policy,
            read_only=read_only,
            max_concurrent=max_builds,
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
    app.state.dev_no_auth_setting = dev_no_auth_setting
    app.state.dev_no_auth_active = dev_no_auth_active
    app.state.dev_no_auth_forced = dev_no_auth_forced
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
            elif "already retired" in text:
                code = "RULE_RETIRED"
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
        if current is not None or read_only:
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
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if (
                store.get_rule_version(latest.rule_id, latest.rule_version) is None
                and load_rule(path).raw.get("status") != "verified"
            ):
                return None
        except (OSError, RuleError):
            return None
        return store.bind_verified_site_rule(
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
            candidates = store.list_candidate_rules(rule_id, site_key)
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
            retired_at=active.retired_at if active else None,
            retired_by=active.retired_by if active else None,
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
        linked_ids = list(
            dict.fromkeys(
                [
                    *([feedback_id] if feedback_id else []),
                    *([target.source_feedback_id] if target.source_feedback_id else []),
                    *(build.feedback_ids or []),
                ]
            )
        )
        for linked in linked_ids:
            feedback = store.get_feedback(linked)
            samples = [
                str(sample).strip()
                for sample in (feedback.samples if feedback else [])
                if str(sample).strip()
            ]
            if not samples:
                continue
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
        dev_identity = path == DEV_IDENTITY_PATH
        with access_lock:
            lan_enabled_now = bool(access_state["lan_enabled"])
            token_salt_now = access_state["token_salt"]
            token_hash_now = access_state["token_hash"]
            dev_no_auth_now = bool(access_state["dev_no_auth_active"])
        if lan_capable and not lan_enabled_now and not is_loopback_host(host):
            return _forbidden("LAN access is disabled")
        protected = not auth_path and not public_static and not dev_identity
        dev_bypass = (
            protected and dev_no_auth_now and _is_dev_loopback_request(request)
        )
        if token_hash_now is not None and protected and not dev_bypass:
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

    def require_workbench_parent(parent_id: str | None) -> WorkbenchNode | None:
        if not parent_id:
            return None
        parent = store.get_workbench_node(parent_id)
        if parent is None:
            raise _error("TARGET_NOT_FOUND", f"unknown workbench parent: {parent_id}", 404)
        if parent.node_type != "group":
            raise _error("INVALID_PARENT", "parent must be a workbench group", 409)
        return parent

    def resolve_workbench_target_rule(
        site: BatchSite, batch: Batch, entries: list[dict[str, Any]]
    ) -> tuple[dict[str, Any] | None, str]:
        """Resolve the rule a workbench import may use for one batch site."""
        domain = normalize_site(site.input_value).site_key or site.domain
        entry = target_entry(site.input_value)
        keys = list(
            dict.fromkeys(
                (
                    site.site_key,
                    target_key(domain, entry, batch.market),
                    domain,
                )
            )
        )
        rule: dict[str, Any] | None = None
        note = "未匹配受管规则包"
        for key in keys:
            candidate, candidate_note = match_rule(key, entries)
            if candidate is not None:
                rule, note = candidate, candidate_note
                break
            note = candidate_note or note
        if rule is None:
            rule, note = match_target(
                target_key(domain, entry, batch.market),
                site.input_value,
                entries,
                True,
                batch.market,
            )
        if (
            rule is None
            and site.readiness == "ready"
            and site.rule_id
            and site.rule_version
            and not note.startswith(("站点规则已停用", "市场不匹配"))
        ):
            stored = [
                entry
                for entry in entries
                if entry.get("valid")
                and entry.get("rule_id") == site.rule_id
                and entry.get("rule_version") == site.rule_version
            ]
            if len(stored) == 1:
                rule = stored[0]
                note = f"批次已复核规则 {site.rule_id}@{site.rule_version}"
        if rule is None:
            if site.note and site.note.startswith(("市场不匹配", "站点规则已停用")):
                note = site.note
            domain_candidates = [
                entry
                for entry in entries
                if entry.get("valid")
                and _workbench_host_key(domain)
                in {
                    _workbench_host_key(str(item))
                    for item in entry.get("domains", [])
                }
            ]
            conflicts = [
                conflict
                for entry in domain_candidates
                if (conflict := market_conflict(entry, batch.market))
            ]
            if domain_candidates and len(conflicts) == len(domain_candidates):
                note = conflicts[0]
            return None, note
        rule_hosts = {
            _workbench_host_key(str(item)) for item in rule.get("domains", [])
        }
        if rule_hosts and _workbench_host_key(domain) not in rule_hosts:
            return None, "规则与站点不匹配"
        conflict = market_conflict(rule, batch.market)
        if conflict:
            return None, conflict
        if not covers_target(rule, entry):
            return None, "当前规则未验证此入口，需接入指定范围"
        return rule, note

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

    def verified_catalog_rule(entry: dict[str, Any]) -> bool:
        if entry.get("status") != "verified":
            return False
        known = store.get_rule_version(entry["rule_id"], entry["rule_version"])
        return known is None or (known.status == "active" and known.sha256 == entry["sha256"])

    def covers_target(rule: dict[str, Any], entry: str | None) -> bool:
        if entry is None:
            return True
        if rules is None:
            return False
        try:
            return target_entry_mode(load_rule(rules / str(rule["path"])), entry) is not None
        except (OSError, RuleError):
            return False

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
            if active.retired_at:
                return (
                    None,
                    f"站点规则已停用：{active.rule_id}@{active.rule_version}",
                )
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
            if entry is not None and verified_catalog_rule(entry):
                return (
                    entry,
                    f"已复核版本 {entry['rule_id']}@{entry['rule_version']}",
                )
            if entry is not None:
                return (
                    None,
                    f"规则 {entry['rule_id']}@{entry['rule_version']} 未在生效账本中",
                )
        return match_catalog(site_key, entries)

    def match_catalog(
        domain: str, entries: list[dict[str, Any]], *,
        market: str | None = None, entry: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        matching = [
            rule for rule in entries
            if rule.get("valid") and domain in rule.get("domains", [])
        ]
        verified = [
            rule for rule in matching
            if not market_conflict(rule, market)
            and covers_target(rule, entry)
            and verified_catalog_rule(rule)
        ]
        if verified:
            wanted = normalize_market(market)
            verified.sort(
                key=lambda rule: (
                    bool(wanted and normalize_market(rule.get("market")) == wanted),
                    str(rule.get("rule_version") or ""),
                    str(rule.get("path") or ""),
                )
            )
            entry = verified[-1]
            note = f"已复核版本 {entry['rule_id']}@{entry['rule_version']}"
            if len(verified) > 1:
                note += f"（{len(verified)} 个已复核版本，使用最高版本）"
            return entry, note
        unactivated = [rule for rule in matching if not market_conflict(rule, market)]
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
        if scoped:
            for site in existing_keys.copy().values():
                if domain := normalize_site(site.input_value).site_key:
                    existing_keys.setdefault(
                        target_key(domain, target_entry(site.input_value), batch_market), site
                    )
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
                rule, note = match_target(
                    item.site_key or "", item.input_value, entries, scoped, batch_market,
                )
                if rule is None:
                    readiness = "needs_onboarding"
                else:
                    conflict = market_conflict(rule, batch_market)
                    if conflict:
                        readiness = "needs_onboarding"
                        note = f"{conflict}；请调整批次市场或换用匹配规则"
                    else:
                        readiness = "ready"
                        if scoped and persist and item.site_key:
                            binding = store.bind_verified_site_rule(SiteRule(
                                site_key=item.site_key,
                                rule_id=rule["rule_id"],
                                rule_version=rule["rule_version"],
                                sha256=rule["sha256"],
                                path=rule["path"],
                            ))
                            if binding is None:
                                rule = None
                                readiness = "needs_onboarding"
                                note = "规则已变更，请重新匹配目标"
                            elif (binding.rule_id, binding.rule_version, binding.sha256) != (
                                rule["rule_id"], rule["rule_version"], rule["sha256"],
                            ):
                                rule, note = match_target(
                                    item.site_key, item.input_value, entries, scoped, batch_market,
                                )
                                if rule is None or market_conflict(rule, batch_market):
                                    readiness = "needs_onboarding"
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
        site_key: str, value: str, entries: list[dict[str, Any]], scoped: bool,
        market: str | None,
    ) -> tuple[dict[str, Any] | None, str]:
        rule, note = match_rule(site_key, entries)
        if not scoped:
            return rule, note
        domain = normalize_site(value).site_key or site_key
        entry = target_entry(value)
        if site_key == domain:
            return rule, note
        if rule is not None and covers_target(rule, entry):
            return rule, note
        if store.get_site_rule(site_key) is not None:
            return None, note if rule is None else "当前规则未验证此入口，需接入指定范围"
        market_note = None
        for default_key in dict.fromkeys((target_key(domain, None, market), domain)):
            if default_key == site_key:
                continue
            default_rule, default_note = match_rule(default_key, entries)
            if default_rule is None or not covers_target(default_rule, entry):
                continue
            conflict = market_conflict(default_rule, market)
            if not conflict:
                return default_rule, default_note
            market_note = conflict
        rule, note = match_catalog(domain, entries, market=market, entry=entry)
        if rule is not None:
            return rule, note
        if market_note:
            return None, f"{market_note}；需接入所选市场"
        return None, "当前规则未验证此入口，需接入指定范围" if entry else note

    def batch_status(
        batch: Batch,
        sites: list[BatchSite],
        summaries: dict[str, dict[str, Any]],
        startable: int,
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
        complete = (
            len(summaries) == len(started)
            and all(
                summary["state"] == "FINISHED"
                and summary["outcome"] == "COMPLETED"
                for summary in summaries.values()
            )
            and not startable
            and not needs
        )
        return "FINISHED" if complete else "PARTIAL"

    def awaits_formal_collection(mode: str | None, task: Task | None) -> bool:
        return (
            mode == "formal" and task is not None
            and task.state in {"FINISHED", "CANCELLED"}
            and task.input.get("collection_mode") == "sample"
        )

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
            "cancellable_onboarding": bool(
                record.state in ACTIVE_BUILD_STATES
                and record.request.get("auto_collect")
                and not record.request.get("batch_cancel_requested")
            ),
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

    def folder_payload(folder: BatchFolder) -> dict[str, Any]:
        return {
            "folder_id": folder.folder_id,
            "parent_id": folder.parent_id,
            "name": folder.name,
            "sort_order": folder.sort_order,
            "created_at": folder.created_at,
            "updated_at": folder.updated_at,
        }

    def folder_error(exc: BatchFolderError) -> None:
        if isinstance(exc, BatchFolderNotFoundError):
            raise _error("NOT_FOUND", str(exc), 404) from exc
        if isinstance(exc, BatchFolderConflictError):
            raise _error("CONFLICT", str(exc), 409) from exc
        if isinstance(exc, BatchFolderNameError):
            raise _error("INVALID_NAME", str(exc), 400) from exc
        raise _error("INVALID_FOLDER", str(exc), 400) from exc

    def require_folder(folder_id: str) -> BatchFolder:
        folder = store.get_batch_folder(folder_id)
        if folder is None:
            raise _error("NOT_FOUND", f"unknown batch folder: {folder_id}", 404)
        return folder

    def folder_scope_ids(folder_id: str, *, include_descendants: bool) -> set[str]:
        folders = store.list_batch_folders()
        known = {folder.folder_id for folder in folders}
        if folder_id not in known:
            raise _error("NOT_FOUND", f"unknown batch folder: {folder_id}", 404)
        if not include_descendants:
            return {folder_id}
        children: dict[str | None, list[str]] = {}
        for folder in folders:
            children.setdefault(folder.parent_id, []).append(folder.folder_id)
        result: set[str] = set()
        stack = [folder_id]
        while stack:
            current = stack.pop()
            if current in result:
                continue
            result.add(current)
            stack.extend(children.get(current, []))
        return result

    def batch_tree_payload() -> dict[str, Any]:
        folders = store.list_batch_folders()
        batches = store.list_batches(include_archived=False)
        archived = store.list_batches(include_archived=True)
        signals = store.batch_tree_signals()
        children: dict[str | None, list[BatchFolder]] = {}
        for folder in folders:
            children.setdefault(folder.parent_id, []).append(folder)
        direct_counts = Counter(batch.folder_id for batch in batches)

        def descendant_count(folder_id: str) -> int:
            total = direct_counts.get(folder_id, 0)
            for child in children.get(folder_id, []):
                total += descendant_count(child.folder_id)
            return total

        zero_signal = {"running": 0, "failed": 0, "needs_onboarding": 0}
        return {
            "folders": [
                {
                    **folder_payload(folder),
                    "batch_count": direct_counts.get(folder.folder_id, 0),
                    "descendant_batch_count": descendant_count(folder.folder_id),
                }
                for folder in folders
            ],
            "batches": [
                {
                    "batch_id": batch.batch_id,
                    "name": batch.name,
                    "folder_id": batch.folder_id,
                    "updated_at": batch.updated_at,
                    "signals": signals.get(batch.batch_id, zero_signal),
                }
                for batch in batches
            ],
            "unfiled": {"batch_count": direct_counts.get(None, 0)},
            "archived": {"batch_count": len(archived) - len(batches)},
        }

    def delivery_task(site: BatchSite, tasks: dict[str, Task]) -> Task | None:
        if site.delivery_task_id:
            return tasks.get(site.delivery_task_id)
        current = tasks.get(site.task_id or "")
        if current is not None and not current.input.get("feedback_id"):
            return current
        return None

    def task_export_files(task_id: str) -> list[tuple[str, Path]]:
        run_dir = (root / task_id).resolve()
        files = []
        for name in EXPORT_FILES:
            path = (run_dir / name).resolve()
            if path.is_relative_to(run_dir) and path.is_file():
                files.append((name, path))
        return files

    def exportable_delivery(task: Task | None) -> bool:
        return task is not None and task.state in {"FINISHED", "CANCELLED"}

    def site_export_task_id(site: BatchSite, tasks: dict[str, Task]) -> str | None:
        task = delivery_task(site, tasks)
        if task and exportable_delivery(task) and task_export_files(task.task_id):
            return task.task_id
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
        pending_formal = {
            site.site_key for site in sites
            if site.readiness == "ready"
            and awaits_formal_collection(batch.collection_mode, tasks.get(site.task_id or ""))
        }
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
                if site.readiness == "ready" and (
                    not site.task_id or site.site_key in pending_formal
                )
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
            "folder_id": batch.folder_id,
            "status": batch_status(
                batch, sites, current_summaries, counts["startable"]
            ),
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
                    "target_entry": target_entry(site.input_value) if batch.collection_mode else None,
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
                    "formal_pending": site.site_key in pending_formal,
                    "delivery_task_id": site.delivery_task_id,
                    "delivery_task": summaries.get(site.delivery_task_id) if site.delivery_task_id else None,
                    "export_task_id": site_export_task_id(site, tasks),
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
        cancelled_onboarding = (
            store.request_cancel_batch_onboarding(batch_id) if action == "cancel" else []
        )
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
            if action == "pause":
                if task.state == "DRAFT":
                    skipped.append(
                        {**item, "reason": "草稿任务尚未启动，不能暂停；可取消"}
                    )
                    continue
                if task.state in {"FINISHED", "CANCELLED"}:
                    skipped.append(
                        {**item, "reason": f"任务已结束（{task.state}）"}
                    )
                    continue
                if task.state == "CANCELLING":
                    skipped.append(
                        {**item, "reason": "任务正在取消，不能暂停"}
                    )
                    continue
            elif action == "resume":
                if task.state in {"FINISHED", "CANCELLED"}:
                    skipped.append(
                        {**item, "reason": f"任务已结束（{task.state}）"}
                    )
                    continue
                if task.state == "PAUSING":
                    skipped.append(
                        {**item, "reason": "任务正在暂停，请稍后重试"}
                    )
                    continue
                if task.state != "PAUSED":
                    skipped.append(
                        {**item, "reason": f"任务未暂停（{task.state}）"}
                    )
                    continue
            elif task.state in {"FINISHED", "CANCELLED"}:
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
            "cancelled_onboarding": cancelled_onboarding,
            "batch": batch_payload(batch, detail=True),
        }

    @app.get("/", include_in_schema=False)
    def index() -> Response:
        if (FRONTEND_DIST_DIR / "index.html").is_file():
            return FileResponse(FRONTEND_DIST_DIR / "index.html")
        raise _error(
            "UI_NOT_BUILT",
            "frontend build not found; build app/frontend/dist",
            503,
        )

    @app.get("/favicon.svg", include_in_schema=False)
    def frontend_favicon() -> Response:
        favicon = FRONTEND_DIST_DIR / "favicon.svg"
        if favicon.is_file():
            return FileResponse(favicon)
        raise _error("NOT_FOUND", "frontend favicon not found", 404)

    @app.get("/next", include_in_schema=False)
    @app.get("/next/{path:path}", include_in_schema=False)
    def next_alias(path: str = "") -> Response:
        if path.startswith("assets/") or path in {"favicon.svg", "favicon.ico"}:
            return RedirectResponse(url=f"/{path}", status_code=308)
        return RedirectResponse(url="/", status_code=308)

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
            "dev_no_auth_setting": bool(state["dev_no_auth_setting"]),
            "dev_no_auth_active": bool(state["dev_no_auth_active"]),
            "dev_no_auth_forced": bool(state["dev_no_auth_forced"]),
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
                "per_domain_rps": per_domain_rps if manage_worker else None,
                "collection_slots": _collection_slots_payload() if manage_worker else None,
                "max_builds": max_builds if builds_available else None,
                "build_slots": _slots_payload(BUILD_SLOTS_SETTING, max_builds, build_slots_override) if builds_available else None,
                "read_only": read_only,
                "builds_available": builds_available,
                "builds_disabled": builds_disabled,
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
            "resources": system_metrics.snapshot(),
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

    @app.get("/api/system/collection-policy")
    def get_collection_policy() -> dict[str, Any]:
        return _collection_policy_payload()

    @app.put("/api/system/collection-policy")
    def put_collection_policy(payload: CollectionPolicyRequest) -> dict[str, Any]:
        try:
            policy = validate_collection_policy(payload.model_dump())
        except CollectionPolicyError as exc:
            raise _error("VALIDATION_ERROR", str(exc), 422) from exc
        with collection_policy_lock:
            store.set_setting(
                COLLECTION_POLICY_SETTING,
                dump_collection_policy(policy),
            )
        return _collection_policy_payload()

    @app.get("/api/system/image-proxy")
    def get_image_proxy() -> dict[str, Any]:
        return _image_proxy_payload()

    @app.put("/api/system/image-proxy")
    def put_image_proxy(payload: ImageProxyRequest) -> dict[str, Any]:
        try:
            setting = validate_image_proxy(payload.model_dump())
        except ImageProxyConfigError as exc:
            raise _error("VALIDATION_ERROR", str(exc), 422) from exc
        with image_proxy_lock:
            store.set_setting(IMAGE_PROXY_SETTING, dump_image_proxy(setting))
        return _image_proxy_payload()

    @app.get("/api/system/preview-settings")
    def get_preview_settings() -> dict[str, Any]:
        return load_preview_settings(store)

    @app.put("/api/system/preview-settings")
    def put_preview_settings(payload: PreviewSettingsRequest) -> dict[str, Any]:
        try:
            setting = validate_preview_settings(payload.model_dump())
        except PreviewSettingsError as exc:
            raise _error("VALIDATION_ERROR", str(exc), 422) from exc
        with preview_settings_lock:
            store.set_setting(
                PREVIEW_SETTINGS_SETTING,
                dump_preview_settings(setting),
            )
        return load_preview_settings(store)

    def _slots_payload(setting: str, current: int, override: bool) -> dict[str, Any]:
        if override:
            return {"next_start": current, "source": "cli"}
        saved = _saved_slots(store, setting)
        return {
            "next_start": saved if saved is not None else DEFAULT_COLLECTION_SLOTS,
            "source": "settings" if saved is not None else "default",
        }

    def _collection_slots_payload() -> dict[str, Any]:
        return _slots_payload(COLLECTION_SLOTS_SETTING, max_tasks, slots_override)

    def _save_slots(setting: str, payload: SystemCollectionSlotsRequest) -> None:
        if payload.max_tasks is None:
            store.delete_setting(setting)
        else:
            store.set_setting(setting, payload.model_dump_json())

    @app.put("/api/system/collection-slots")
    def update_collection_slots(payload: SystemCollectionSlotsRequest) -> dict[str, Any]:
        if not manage_worker:
            raise _error("WORKER_NOT_MANAGED", "当前服务未托管采集 worker", 409)
        if slots_override:
            raise _error("WORKER_SLOTS_OVERRIDDEN", "任务数由启动参数 --max-tasks 决定", 409)
        _save_slots(COLLECTION_SLOTS_SETTING, payload)
        return _collection_slots_payload()

    @app.put("/api/system/build-slots")
    def update_build_slots(payload: SystemCollectionSlotsRequest) -> dict[str, Any]:
        if build_manager is None or builds_disabled:
            raise _error("BUILDS_UNAVAILABLE", "当前服务未启用规则分析", 409)
        if build_slots_override:
            raise _error("BUILD_SLOTS_OVERRIDDEN", "分析并发由服务启动配置决定", 409)
        _save_slots(BUILD_SLOTS_SETTING, payload)
        return _slots_payload(BUILD_SLOTS_SETTING, max_builds, build_slots_override)

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

    @app.put("/api/system/access/dev-no-auth")
    def update_dev_no_auth(
        request: Request, payload: SystemDevNoAuthRequest
    ) -> dict[str, Any]:
        if not _is_dev_loopback_request(request):
            raise _error(
                "DEV_MODE_LOOPBACK_ONLY",
                "开发者模式只能从本机回环入口修改",
                403,
            )
        if read_only:
            raise _error("READ_ONLY", "read-only mode rejects write operations", 403)
        with access_lock:
            forced = bool(access_state["dev_no_auth_forced"])
        if forced:
            raise _error(
                "DEV_MODE_FORCED",
                "开发者模式由启动参数 --dev-no-auth 强制开启",
                409,
            )
        store.set_setting(
            SETTING_DEV_NO_AUTH,
            "1" if payload.enabled else "0",
        )
        with access_lock:
            access_state["dev_no_auth_setting"] = payload.enabled
            access_state["dev_no_auth_active"] = payload.enabled
        app.state.dev_no_auth_setting = payload.enabled
        app.state.dev_no_auth_active = payload.enabled
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
            **identity_fields(),
            "tasks": len(store.list_tasks()),
            "max_tasks": max_tasks if manage_worker else None,
            "max_browser_tasks": max_browser_tasks if manage_worker else None,
            "rules_configured": rules is not None and rules.is_dir(),
            "builds_readable": build_manager is not None,
            "builds_available": (
                build_manager is not None
                and not builds_disabled
                and not read_only
            ),
        }

    @app.get(DEV_IDENTITY_PATH, include_in_schema=False)
    def dev_identity(request: Request) -> dict[str, Any]:
        if not _client_is_loopback(request):
            raise _error("NOT_FOUND", "not found", 404)
        return {"status": "ok", "version": __version__, **identity_fields()}

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
            rule = load_rule(rules / str(entry["path"]))
            collection_policy = load_collection_policy(store)
            rate_policy = {
                **default_rate_overrides(collection_policy),
                **load_policies(store).get(
                    normalize_domain(rule.entry_url),
                    {},
                ),
            }
            task = build_task(
                rule_path=rules / str(entry["path"]),
                task_id=f"web-{uuid.uuid4().hex[:12]}",
                task_type=payload.task_type,
                max_urls=payload.limits.max_urls,
                max_products=payload.limits.max_products,
                max_seconds=payload.limits.max_seconds,
                max_attempts=(
                    rate_policy["max_attempts"]
                    if rate_policy.get("max_attempts") is not None
                    else payload.limits.max_attempts
                ),
                proxy=payload.proxy,
                concurrency=rate_policy.get("concurrency"),
                delay_ms=rate_policy.get("delay_ms"),
                retry_backoff_ms=rate_policy.get("backoff_ms"),
                rate_policy=rate_policy,
            )
        except (RuleError, ContractError) as exc:
            raise _error("INVALID_RULE", str(exc), 400) from exc
        retired = _retired_site_rule(
            store, site_key=task.site_key, rule_id=task.plan_id
        )
        if retired is not None:
            raise _error(
                "SITE_RULE_RETIRED",
                f"站点规则已停用：{retired.rule_id}@{retired.rule_version}",
                409,
            )
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

    @app.get("/api/tasks/{task_id}/analysis")
    def get_task_analysis(
        task_id: str,
        request: Request,
        window_seconds: Annotated[int | None, Query(ge=60, le=30 * 24 * 3600)] = None,
        bucket_seconds: Annotated[int | None, Query(ge=60, le=3600)] = None,
    ) -> Response:
        task = require_task(task_id)
        result = _current_task_result(task, root)
        counts = _counts(store, task, result)
        task_dir = root / task.task_id
        fingerprint = analysis_fingerprint(
            task,
            task_dir,
            counts=counts,
            window_seconds=window_seconds,
            bucket_seconds=bucket_seconds,
        )
        etag = analysis_etag(fingerprint)
        terminal = task.state in {"FINISHED", "CANCELLED"}
        headers = {
            "ETag": etag,
            "Cache-Control": "private, max-age=15" if terminal else "no-store",
        }
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        payload = build_analysis_cached(
            task,
            task_dir,
            counts=counts,
            result=result,
            window_seconds=window_seconds,
            bucket_seconds=bucket_seconds,
        )
        return JSONResponse(content=payload, headers=headers)

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
    def list_items(
        task_id: str,
        kind: Annotated[str, Query(pattern="^(url|product)$")] = "product",
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        state: Annotated[str | None, Query(max_length=20)] = None,
        order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
        include_description: bool = False,
    ) -> dict[str, Any]:
        task = require_task(task_id)
        item_type = "navigation" if kind == "url" else "product"
        items = store.items(task_id, item_type)
        if state:
            wanted = state.strip().upper()
            items = [item for item in items if item.state == wanted]
        if order == "desc":
            items = list(reversed(items))
        product_index = (
            _product_row_index(task, root)
            if include_description and item_type == "product"
            else None
        )
        return {
            "total": len(items),
            "items": [
                _item_payload(item, product_index)
                for item in items[offset : offset + limit]
            ],
        }

    @app.get("/api/media/image")
    def media_image(
        url: Annotated[str, Query(min_length=1, max_length=2048)],
        task_id: Annotated[str | None, Query(max_length=100)] = None,
    ) -> Response:
        task_proxy: str | None = None
        if task_id:
            task = require_task(task_id)
            task_proxy = str(task.input.get("proxy") or "").strip() or None
        setting = load_image_proxy(store)
        attempts = image_proxy_attempts(
            mode=str(setting["mode"]),
            task_proxy=task_proxy,
            service_proxy=proxy,
            system_proxy=setting.get("proxy"),
        )
        try:
            content, content_type = fetch_image_with_attempts(url, attempts)
        except ImageProxyUrlError as exc:
            raise _error("INVALID_IMAGE_URL", str(exc), 400) from exc
        except ImageProxyError as exc:
            logger.warning(
                "image proxy failed: task=%s host=%s attempts=%s",
                task_id or "none",
                urlsplit(url).hostname or "unknown",
                exc.attempts,
            )
            raise _error("IMAGE_FETCH_FAILED", str(exc), 502) from exc
        return Response(
            content=content,
            media_type=content_type,
            headers={
                "Cache-Control": "public, max-age=3600",
                "X-Content-Type-Options": "nosniff",
            },
        )

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
    async def task_events(
        task_id: str,
        request: Request,
        after: Annotated[int | None, Query(ge=0)] = None,
    ) -> StreamingResponse:
        require_task(task_id)
        header_value = request.headers.get("last-event-id", "")
        try:
            header_after = int(header_value) if header_value.strip() else None
        except ValueError:
            header_after = None
        cursor = max(
            (value for value in (after, header_after) if value is not None),
            default=None,
        )

        async def stream() -> Any:
            yield _sse("snapshot", _summary(store, require_task(task_id), root))
            path = root / task_id / "events.ndjson"
            if cursor is None:
                cursor_seq = _event_log_page(path, limit=1)["total"]
            else:
                cursor_seq = cursor
            last_heartbeat = time.monotonic()
            while True:
                page = _event_log_page(path, after=cursor_seq, limit=500)
                if page["total"] < cursor_seq:
                    cursor_seq = 0
                    yield _sse("reset", {"reason": "events_reset"})
                    continue
                for item in page["items"]:
                    yield _sse(
                        "update",
                        {key: value for key, value in item.items() if key != "seq"},
                        item["seq"],
                    )
                if page["newest_seq"] is not None:
                    cursor_seq = max(cursor_seq, int(page["newest_seq"]))
                current = store.get_task(task_id)
                if current is None:
                    break
                if current.state in {"FINISHED", "CANCELLED"}:
                    final = _event_log_page(path, after=cursor_seq, limit=500)
                    for item in final["items"]:
                        yield _sse(
                            "update",
                            {key: value for key, value in item.items() if key != "seq"},
                            item["seq"],
                        )
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

    @app.get("/api/tasks/{task_id}/events/history")
    def task_events_history(
        task_id: str,
        tail: Annotated[int | None, Query(ge=1, le=500)] = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 500,
        before: Annotated[int | None, Query(ge=1)] = None,
        after: Annotated[int | None, Query(ge=0)] = None,
    ) -> dict[str, Any]:
        require_task(task_id)
        if before is not None and after is not None:
            raise _error(
                "BAD_REQUEST", "before and after cannot be used together", 400
            )
        page = _event_log_page(
            root / task_id / "events.ndjson",
            limit=limit,
            tail=tail,
            before=before,
            after=after,
        )
        return page

    @app.get("/api/tasks/{task_id}/export")
    def export_task(task_id: str, partial: bool = False) -> Response:
        task = require_task(task_id)
        if task.output.get("recovery_export_pending"):
            raise _error("EXPORT_NOT_READY", "正在恢复已采数据，恢复完成后可导出", 409)
        if task.state not in {"FINISHED", "CANCELLED"} and not partial:
            raise _error("EXPORT_NOT_READY", "task is not finished; use partial=true", 409)
        run_dir = (root / task_id).resolve()
        if not run_dir.is_dir():
            raise _error("NOT_FOUND", f"no output directory for task: {task_id}", 404)
        buffer = io.BytesIO()
        written = 0
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, path in task_export_files(task_id):
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
        if task.state not in {
            "QUEUED",
            "RUNNING",
            "PAUSING",
            "PAUSED",
            "FINISHED",
            "CANCELLED",
        }:
            raise _error(
                "INVALID_TASK_STATE",
                "feedback requires a queued, running, paused, finished or cancelled task",
                409,
            )
        terminal = task.state in {"FINISHED", "CANCELLED"}
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
            applies_to="CURRENT_RUN" if terminal else "NEXT_RUN",
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
            feedback=_feedback_payload(
                record,
                active_repair_build_id=store.find_active_repair_build(record.site_key),
            ),
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
            items=_feedback_payloads(store, items),
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
            items=_feedback_payloads(store, items),
        )

    @app.get("/api/feedback/{feedback_id}", response_model=FeedbackRecord)
    def get_feedback(feedback_id: str) -> FeedbackRecord:
        feedback = store.get_feedback(feedback_id)
        if feedback is None:
            raise _error("FEEDBACK_NOT_FOUND", f"unknown feedback: {feedback_id}", 404)
        return _feedback_payloads(store, [feedback])[0]

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

    @app.post("/api/feedback/bundle", response_model=FeedbackBundleResponse)
    def bundle_feedback(payload: FeedbackBundleRequest) -> FeedbackBundleResponse:
        result = _feedback_bundle(store, payload.feedback_ids)
        return FeedbackBundleResponse(
            can_repair=result["can_repair"],
            site_key=result["site_key"],
            batch_id=result["batch_id"],
            rule=result["rule"],
            items=_feedback_payloads(store, result["items"]),
            blockers=result["blockers"],
        )

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
            if (
                existing_build.feedback_id != feedback_id
                and feedback_id not in (existing_build.feedback_ids or [])
            ):
                raise _error(
                    "CONFLICT", "request_id belongs to another feedback", 409
                )
            return {
                "accepted": True,
                "build": build_manager.describe(existing_build.build_id),
                "feedback": _feedback_payloads(
                    store, [store.get_feedback(feedback_id) or feedback]
                )[0],
            }
        feedback_ids = list(
            dict.fromkeys([feedback_id, *payload.feedback_ids])
        )
        bundle = _feedback_bundle(store, feedback_ids)
        if not bundle["can_repair"]:
            raise _error(
                "FEEDBACK_BUNDLE_BLOCKED",
                "这些反馈不能合并到一次规则修复",
                409,
                {"blockers": bundle["blockers"]},
            )
        items: list[QualityFeedback] = bundle["items"]
        reference: QualityFeedback = items[0]
        busy = site_busy(reference.site_key)  # type: ignore[arg-type]
        if busy:
            raise _error("SITE_BUSY", "site has active work", 409, busy)
        active = build_manager.ensure_site_rule(reference.site_key)  # type: ignore[arg-type]
        if active is None:
            raise _error(
                "RULE_NOT_ACTIVE",
                "site has no active rule; use the site build entry",
                409,
            )
        batch = store.get_batch(reference.batch_id)  # type: ignore[arg-type]
        site = store.get_batch_site(
            reference.batch_id, reference.site_key  # type: ignore[arg-type]
        )
        if batch is None or site is None:
            raise _error("INVALID_STATE", "feedback batch/site no longer exists", 409)
        reason = (payload.reason or "").strip()
        if not reason:
            reason = "；".join(
                f"{item.feedback_id}: {item.expectation}" for item in items
            )[:2000]
        for item in items:
            store.update_feedback(
                item.feedback_id,
                status="REPAIRING",
                triage=item.triage or "RULE_REPAIR",
                triage_source=item.triage_source or "repair",
            )
        try:
            record = build_manager.repair(
                batch,
                site,
                reason=reason,
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
                feedback_id=items[0].feedback_id,
                feedback_ids=[item.feedback_id for item in items],
                request_id=payload.request_id,
                model_ref=payload.model_ref,
            )
        except BuildError as exc:
            for item in items:
                store.update_feedback(item.feedback_id, status="TRIAGED")
            raise _error("BUILD_CONFLICT", str(exc), 409) from exc
        for item in items:
            store.update_feedback(
                item.feedback_id, repair_build_id=record.build_id
            )
        updated = store.get_feedback(items[0].feedback_id) or items[0]
        return {
            "accepted": True,
            "build": build_manager.describe(record.build_id),
            "feedback": _feedback_payloads(store, [updated])[0],
            "feedbacks": _feedback_payloads(
                store,
                [
                    store.get_feedback(item.feedback_id) or item
                    for item in items
                ],
            ),
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
        linked_ids = [feedback_id]
        if feedback.repair_build_id:
            repair_build = store.get_build(feedback.repair_build_id)
            if repair_build is not None:
                for candidate in [
                    repair_build.feedback_id,
                    *(repair_build.feedback_ids or []),
                ]:
                    if candidate and candidate not in linked_ids:
                        linked_ids.append(candidate)
        linked_feedbacks = [
            item
            for linked_id in linked_ids
            if (item := store.get_feedback(linked_id)) is not None
            and item.site_key == feedback.site_key
            and item.batch_id == feedback.batch_id
        ]
        request_json = json.dumps(
            {
                "feedback_id": feedback_id,
                "feedback_ids": [item.feedback_id for item in linked_feedbacks],
                **payload.model_dump(),
            },
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
                "feedbacks": _feedback_payloads(store, linked_feedbacks),
            }
        if feedback.status != "AWAITING_RERUN":
            raise _error(
                "INVALID_FEEDBACK_STATE",
                f"feedback is {feedback.status}, expected AWAITING_RERUN",
                409,
            )
        rerun_feedbacks = [
            item for item in linked_feedbacks if item.status == "AWAITING_RERUN"
        ]
        if feedback.feedback_id not in {
            item.feedback_id for item in rerun_feedbacks
        }:
            rerun_feedbacks.insert(0, feedback)
        rerun_ids = [item.feedback_id for item in rerun_feedbacks]
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
        if active.retired_at:
            raise _error(
                "SITE_RULE_RETIRED",
                f"站点规则已停用：{active.rule_id}@{active.rule_version}",
                409,
            )
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
            if site is None or target_entry_mode(load_rule(rule_path), target_entry(site.input_value)) is None:
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
        task.input["feedback_ids"] = rerun_ids
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
                task,
                payload.request_id,
                request_json,
                feedback_id=feedback_id,
                feedback_ids=rerun_ids,
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
            "feedbacks": _feedback_payloads(
                store,
                [
                    store.get_feedback(item.feedback_id) or item
                    for item in rerun_feedbacks
                ],
            ),
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

    @app.get(
        "/api/rules/{rule_id}/versions/{rule_version}/cleanup-preview",
        response_model=RuleVersionCleanupPreview,
    )
    def get_rule_cleanup_preview(
        rule_id: str, rule_version: str
    ) -> RuleVersionCleanupPreview:
        try:
            return RuleVersionCleanupPreview.model_validate(
                _rule_cleanup_preview(store, rules, rule_id, rule_version)
            )
        except KeyError as exc:
            raise _error("RULE_NOT_FOUND", str(exc), 404) from exc

    @app.post(
        "/api/rules/{rule_id}/versions/{rule_version}/purge",
        response_model=RuleCleanupResult,
    )
    def purge_rule_version(
        rule_id: str,
        rule_version: str,
        payload: RuleCleanupRequest,
    ) -> RuleCleanupResult:
        existing = store.get_rule_cleanup_by_request(payload.request_id)
        if existing is not None:
            if (
                existing["rule_id"] != rule_id
                or existing["rule_version"] != rule_version
            ):
                raise _error(
                    "RULE_CLEANUP_CONFLICT",
                    "request ID belongs to another rule cleanup",
                    409,
                )
            return RuleCleanupResult.model_validate(
                _finish_rule_cleanup(store, existing, rules)
            )
        try:
            preview = _rule_cleanup_preview(store, rules, rule_id, rule_version)
        except KeyError as exc:
            raise _error("RULE_NOT_FOUND", str(exc), 404) from exc
        if not preview["can_purge"]:
            raise _error(
                "RULE_CLEANUP_BLOCKED",
                "规则版本仍被引用，不能清理",
                409,
                {"blockers": preview["blockers"]},
            )
        version = store.get_rule_version(rule_id, rule_version)
        if version is None:
            raise _error("RULE_NOT_FOUND", "rule version disappeared", 404)
        try:
            cleanup = store.purge_rule_version(
                rule_id,
                rule_version,
                request_id=payload.request_id,
                sha256=version.sha256,
                path=version.path,
                bytes_count=int(preview["bytes"]),
                references=preview["references"],
                actor=payload.actor or "local-user",
                reason=payload.reason,
            )
        except RuleVersionError as exc:
            raise rule_error(exc) from exc
        return RuleCleanupResult.model_validate(
            _finish_rule_cleanup(store, cleanup, rules)
        )

    @app.get("/api/sites/{site_key}/rule", response_model=SiteRuleResponse)
    def read_site_rule(site_key: str) -> SiteRuleResponse:
        return site_rule_payload(site_key)

    @app.post("/api/sites/{site_key}/rule/activate")
    def activate_site_rule(
        site_key: str, payload: RuleActivateRequest
    ) -> dict[str, Any]:
        existing = store.get_activation_by_request(payload.request_id)
        if existing is not None:
            if (
                existing.site_key != site_key
                or existing.action != "activate"
                or existing.to_version != payload.rule_version
                or (payload.rule_id is not None and existing.rule_id != payload.rule_id)
                or (payload.expected_active_version is not None and existing.from_version != payload.expected_active_version)
                or (payload.expected_active_sha256 is not None and existing.from_sha256 != payload.expected_active_sha256)
            ):
                raise _error("ACTIVATION_CONFLICT", "request ID belongs to another rule activation", 409)
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
        active = ensure_site_rule(site_key)
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
        linked_build = (
            store.get_build(target.source_build_id)
            if target.source_build_id
            else None
        )
        activation_feedback_ids = list(
            dict.fromkeys(
                [
                    *([payload.feedback_id] if payload.feedback_id else []),
                    *([target.source_feedback_id] if target.source_feedback_id else []),
                    *((linked_build.feedback_ids if linked_build else None) or []),
                ]
            )
        )
        try:
            site_rule, activation = store.activate_rule(
                site_key=site_key,
                rule_id=target.rule_id,
                rule_version=target.rule_version,
                sha256=target.sha256,
                expected_active_version=payload.expected_active_version,
                expected_active_sha256=payload.expected_active_sha256,
                feedback_id=payload.feedback_id,
                feedback_ids=activation_feedback_ids,
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
            if (
                existing.site_key != site_key
                or existing.action != "rollback"
                or (payload.to_version is not None and existing.to_version != payload.to_version)
            ):
                raise _error("ACTIVATION_CONFLICT", "request ID belongs to another rule activation", 409)
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
        target = store.find_rollback_rule(active, payload.to_version)
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
                expected_active_sha256=active.sha256,
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

    @app.post("/api/sites/{site_key}/rule/retire")
    def retire_site_rule(
        site_key: str, payload: RuleRetireRequest
    ) -> dict[str, Any]:
        existing = store.get_activation_by_request(payload.request_id)
        if existing is not None:
            if (
                existing.site_key != site_key
                or existing.action != "retire"
                or (
                    payload.expected_active_version is not None
                    and existing.to_version != payload.expected_active_version
                )
            ):
                raise _error(
                    "ACTIVATION_CONFLICT",
                    "request ID belongs to another rule retirement",
                    409,
                )
            return {
                "retired": True,
                "site": site_rule_payload(site_key).model_dump(),
                "previous": {
                    "rule_version": existing.from_version,
                    "sha256": existing.from_sha256,
                },
            }
        builds = store.list_builds(
            site_key=site_key, states=ACTIVE_BUILD_STATES, limit=1
        )
        if builds:
            raise _error(
                "SITE_BUSY",
                "site has an active build; wait or cancel it before retiring the rule",
                409,
                {"build_id": builds[0].build_id, "build_state": builds[0].state},
            )
        active = store.get_site_rule(site_key)
        if active is None:
            raise _error("RULE_NOT_ACTIVE", "site has no active rule", 409)
        try:
            _site_rule, activation = store.retire_site_rule(
                site_key=site_key,
                request_id=payload.request_id,
                expected_active_version=payload.expected_active_version,
                expected_active_sha256=payload.expected_active_sha256,
                reason=payload.reason,
                actor=payload.actor or "local-user",
            )
        except RuleVersionError as exc:
            raise rule_error(exc) from exc
        return {
            "retired": True,
            "site": site_rule_payload(site_key).model_dump(),
            "previous": {
                "rule_version": activation.from_version,
                "sha256": activation.from_sha256,
            },
        }

    @app.get("/api/workbench/tree")
    def get_workbench_tree() -> dict[str, Any]:
        return _workbench_tree_payload(store, root)

    @app.post("/api/workbench/groups", status_code=201)
    def create_workbench_group(payload: WorkbenchGroupCreateRequest) -> dict[str, Any]:
        name = payload.name.strip()
        if not name:
            raise _error("VALIDATION_ERROR", "name must not be blank", 422)
        if payload.parent_id:
            parent = store.get_workbench_node(payload.parent_id)
            if parent is None:
                raise _error("NOT_FOUND", f"unknown workbench parent: {payload.parent_id}", 404)
            if parent.node_type != "group":
                raise _error("INVALID_PARENT", "parent must be a workbench group", 409)
        siblings = [
            node
            for node in store.list_workbench_nodes()
            if node.parent_id == payload.parent_id
        ]
        node = WorkbenchNode(
            node_id=f"g-{uuid.uuid4().hex[:12]}",
            node_type="group",
            name=name,
            parent_id=payload.parent_id,
            sort_order=max((item.sort_order for item in siblings), default=-1) + 1,
        )
        try:
            created = store.create_workbench_group(node)
        except ValueError as exc:
            raise _error("CONFLICT", str(exc), 409) from exc
        return {
            "node": {
                "node_id": created.node_id,
                "node_type": created.node_type,
                "parent_id": created.parent_id,
                "name": created.name,
                "sort_order": created.sort_order,
            }
        }

    @app.patch("/api/workbench/nodes/{node_id}")
    def rename_workbench_node(
        node_id: str, payload: WorkbenchNodeRenameRequest
    ) -> dict[str, Any]:
        name = payload.name.strip()
        if not name or any(ord(char) < 32 for char in name):
            raise _error("VALIDATION_ERROR", "name is invalid", 422)
        try:
            node = store.rename_workbench_node(node_id, name, utc_now())
        except KeyError as exc:
            raise _error("NOT_FOUND", str(exc), 404) from exc
        return {
            "node": {
                "node_id": node.node_id,
                "node_type": node.node_type,
                "parent_id": node.parent_id,
                "name": node.name,
                "sort_order": node.sort_order,
            }
        }

    @app.post("/api/workbench/nodes/{node_id}/move")
    def move_workbench_node(
        node_id: str, payload: WorkbenchNodeMoveRequest
    ) -> dict[str, Any]:
        try:
            node = store.move_workbench_node(
                node_id,
                payload.parent_id,
                payload.after_node_id,
                utc_now(),
                before_node_id=payload.before_node_id,
            )
        except KeyError as exc:
            raise _error("NOT_FOUND", str(exc), 404) from exc
        except ValueError as exc:
            raise _error("INVALID_MOVE", str(exc), 409) from exc
        return {
            "node": {
                "node_id": node.node_id,
                "node_type": node.node_type,
                "parent_id": node.parent_id,
                "name": node.name,
                "sort_order": node.sort_order,
            }
        }

    @app.delete("/api/workbench/groups/{node_id}")
    def dissolve_workbench_group(node_id: str) -> dict[str, Any]:
        try:
            moved = store.dissolve_workbench_group(node_id, utc_now())
        except KeyError as exc:
            raise _error("NOT_FOUND", str(exc), 404) from exc
        except ValueError as exc:
            raise _error("INVALID_GROUP", str(exc), 409) from exc
        return {"node_id": node_id, "dissolved": True, "moved": moved}

    workbench_import_lock = threading.Lock()

    def _import_workbench_batch(
        payload: WorkbenchBatchImportRequest,
    ) -> dict[str, Any]:
        if rules is None or not rules.is_dir():
            raise _error("RULES_NOT_CONFIGURED", "serve --rules-dir is not set", 400)
        batch = store.get_batch(payload.batch_id)
        if batch is None:
            raise _error("NOT_FOUND", f"unknown batch: {payload.batch_id}", 404)
        if batch.archived_at is not None:
            raise _error("INVALID_STATE", "batch is archived", 409)
        intent = store.get_workbench_batch_import(batch.batch_id)
        parent_id = (
            payload.parent_id
            if payload.parent_id is not None
            else (intent.parent_id if intent else None)
        )
        parent = require_workbench_parent(parent_id)
        target = {
            "node_id": parent.node_id if parent else None,
            "name": parent.name if parent else "根目录",
            "missing": False,
        }
        store.upsert_workbench_batch_import(batch.batch_id, parent_id=parent_id)
        entries = _rule_entries(rules)
        definitions = store.list_workbench_task_defs()
        existing_by_key = {definition.site_key: definition for definition in definitions}
        existing_by_identity: dict[tuple[str, str | None, str], WorkbenchTaskDef] = {}
        for definition in definitions:
            identity = site_identity(
                definition.domain,
                definition.input_url,
                definition.market or batch.market,
            )
            existing_by_identity.setdefault(identity, definition)
        runs = store.list_workbench_task_runs()
        mapped_tasks = {run.task_id for run in runs}
        siblings = [
            node
            for node in store.list_workbench_nodes()
            if node.parent_id == parent_id
        ]
        next_order = max((item.sort_order for item in siblings), default=-1) + 1
        added: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        counts: Counter[str] = Counter()

        def skip(
            site: BatchSite,
            category: str,
            reason: str,
            *,
            existing_node_id: str | None = None,
        ) -> None:
            item: dict[str, Any] = {
                "site_key": site.site_key,
                "domain": site.domain,
                "reason": reason,
                "category": category,
            }
            if existing_node_id:
                item["existing_node_id"] = existing_node_id
            skipped.append(item)
            counts[category] += 1

        try:
            for site in store.list_batch_sites(batch.batch_id):
                counts["total"] += 1
                identity = site_identity(site.domain, site.input_value, batch.market)
                existing = existing_by_key.get(site.site_key) or existing_by_identity.get(
                    identity
                )
                rule, note = resolve_workbench_target_rule(site, batch, entries)
                if site.readiness == "duplicate":
                    skip(site, "duplicate", site.note or "批次内重复")
                    continue
                if site.readiness == "invalid":
                    skip(site, "invalid", site.note or "网址无效")
                    continue
                raw_input = (site.input_value or "").strip()
                input_url = (
                    raw_input
                    if re.match(r"^https?://", raw_input, re.IGNORECASE)
                    else f"https://{site.domain}/"
                )
                if existing is not None:
                    if not existing.rule_id and rule is not None:
                        task_types = list(rule.get("task_types", []))
                        task_type = (
                            "product"
                            if "product" in task_types
                            else (task_types[0] if task_types else "")
                        )
                        if not task_type:
                            skip(site, "pending", "规则不支持任务类型")
                            continue
                        updated = store.update_workbench_task(
                            existing.node_id,
                            utc_now(),
                            rule_id=rule["rule_id"],
                            rule_version=rule["rule_version"],
                            rule_path=str(rule["path"]),
                            task_type=task_type,
                            note=site.note or note or existing.note,
                        )
                        existing_by_key[site.site_key] = updated
                        existing_by_identity[identity] = updated
                        attached = False
                        if site.task_id and site.task_id not in mapped_tasks:
                            try:
                                attached = store.attach_workbench_run(
                                    existing.node_id, site.task_id, utc_now()
                                )
                            except (KeyError, ValueError):
                                attached = False
                            if attached:
                                mapped_tasks.add(site.task_id)
                        added.append(
                            {
                                "node_id": existing.node_id,
                                "name": existing.domain or existing.site_key,
                                "site_key": site.site_key,
                                "task_id": site.task_id,
                                "attached": attached,
                                "bound": True,
                            }
                        )
                        counts["added"] += 1
                        continue
                    skip(site, "existing", "已在任务树", existing_node_id=existing.node_id)
                    continue
                task_type = "product"
                if rule is not None:
                    task_types = list(rule.get("task_types", []))
                    task_type = (
                        "product"
                        if "product" in task_types
                        else (task_types[0] if task_types else "")
                    )
                    if not task_type:
                        skip(site, "pending", "规则不支持任务类型")
                        continue
                now = utc_now()
                node = WorkbenchNode(
                    node_id=f"n-{uuid.uuid4().hex[:12]}",
                    node_type="task",
                    name=site.domain or site.site_key,
                    parent_id=parent_id,
                    sort_order=next_order,
                    created_at=now,
                    updated_at=now,
                )
                definition = WorkbenchTaskDef(
                    node_id=node.node_id,
                    input_url=input_url,
                    domain=site.domain,
                    site_key=site.site_key,
                    batch_id=batch.batch_id,
                    country=batch.country,
                    language=batch.language,
                    market=batch.market,
                    category=batch.category,
                    task_type=task_type,
                    collection_mode=(
                        batch.collection_mode
                        if batch.collection_mode in {"sample", "formal"}
                        else "formal"
                    ),
                    rule_id=rule["rule_id"] if rule is not None else "",
                    rule_version=rule["rule_version"] if rule is not None else "",
                    rule_path=str(rule["path"]) if rule is not None else "",
                    limits={},
                    proxy=site.proxy,
                    note=site.note or (note if rule is None else None),
                    created_at=now,
                    updated_at=now,
                )
                try:
                    store.create_workbench_task(node, definition)
                except ValueError as exc:
                    skip(site, "failed", str(exc))
                    continue
                existing_by_key[site.site_key] = definition
                existing_by_identity[identity] = definition
                next_order += 1
                attached = False
                if site.task_id and site.task_id not in mapped_tasks:
                    try:
                        attached = store.attach_workbench_run(
                            node.node_id, site.task_id, utc_now()
                        )
                    except (KeyError, ValueError):
                        attached = False
                    if attached:
                        mapped_tasks.add(site.task_id)
                added.append(
                    {
                        "node_id": node.node_id,
                        "name": node.name,
                        "site_key": site.site_key,
                        "task_id": site.task_id,
                        "attached": attached,
                        "pending_rule": rule is None,
                    }
                )
                counts["added"] += 1
            store.mark_workbench_batch_import_attempt(batch.batch_id)
        except Exception as exc:
            detail = getattr(exc, "detail", None) or str(exc) or type(exc).__name__
            store.mark_workbench_batch_import_attempt(
                batch.batch_id, error=str(detail)[:500]
            )
            raise
        return {
            "batch_id": batch.batch_id,
            "target": target,
            "added": added,
            "skipped": skipped,
            "counts": {
                key: counts[key]
                for key in (
                    "total",
                    "added",
                    "pending",
                    "existing",
                    "duplicate",
                    "invalid",
                    "failed",
                )
            },
        }

    @app.post("/api/workbench/import-batch")
    def import_workbench_batch(payload: WorkbenchBatchImportRequest) -> dict[str, Any]:
        with workbench_import_lock:
            return _import_workbench_batch(payload)

    @app.get("/api/workbench/pending-targets")
    def workbench_pending_targets() -> dict[str, Any]:
        entries: list[dict[str, Any]] | None = None
        intents = store.list_workbench_batch_imports()
        definitions = store.list_workbench_task_defs() if intents else []
        scoped_identities: set[tuple[str, str | None, str]] = set()
        unscoped_identities: set[tuple[str, str | None]] = set()
        for definition in definitions:
            domain, entry, market = site_identity(
                definition.domain, definition.input_url, definition.market
            )
            if definition.market:
                scoped_identities.add((domain, entry, market))
            else:
                unscoped_identities.add((domain, entry))
        onboarding_available = (
            build_manager is not None and not builds_disabled and not read_only
        )
        onboarding_reason = None
        if not onboarding_available:
            onboarding_reason = (
                "只读模式不能启动构建"
                if read_only
                else "构建服务不可用；请配置规则目录后重启"
            )
        batches: list[dict[str, Any]] = []
        total_pending = 0
        for intent in intents:
            batch = store.get_batch(intent.batch_id)
            if batch is None or batch.archived_at is not None:
                continue
            parent = (
                store.get_workbench_node(intent.parent_id)
                if intent.parent_id
                else None
            )
            target = {
                "node_id": intent.parent_id,
                "name": parent.name if parent else None,
                "missing": bool(intent.parent_id and parent is None),
            }
            sites = store.list_batch_sites(batch.batch_id)
            counts: Counter[str] = Counter(sites=len(sites))
            pending_sites: list[dict[str, Any]] = []
            for site in sites:
                identity = site_identity(site.domain, site.input_value, batch.market)
                domain, entry, _ = identity
                if identity in scoped_identities or (domain, entry) in unscoped_identities:
                    counts["in_workbench"] += 1
                    continue
                if site.readiness in {"invalid", "duplicate"}:
                    counts[site.readiness] += 1
                    continue
                build = store.get_build(site.build_id) if site.build_id else None
                if build is None:
                    recent_builds = store.list_builds(
                        batch_id=batch.batch_id,
                        site_key=site.site_key,
                        limit=1,
                    )
                    build = recent_builds[0] if recent_builds else None
                if entries is None:
                    entries = _rule_entries(rules) if rules is not None and rules.is_dir() else []
                rule, note = resolve_workbench_target_rule(site, batch, entries)
                if build is not None and build.state in ACTIVE_BUILD_STATES:
                    category = "building"
                    action = "open_build"
                    reason = f"构建中（{build.state}）"
                elif build is not None and build.state == "FINISHED" and rule is None:
                    category = "needs_onboarding"
                    action = "open_build"
                    reason = "构建完成但规则尚未激活或不可用"
                elif rule is not None:
                    category = "ready"
                    action = "import"
                    reason = note or "可加入任务树"
                else:
                    category = "needs_onboarding"
                    reason = note or site.note or "未匹配受管规则包"
                    blocked = reason.startswith(
                        ("市场不匹配", "站点规则已停用")
                    )
                    action = (
                        "build"
                        if onboarding_available and not blocked
                        else "none"
                    )
                    if build is not None and build.state in {"FAILED", "CANCELLED"}:
                        reason = f"{reason}；最近构建 {build.build_id} {build.state}"
                if action == "build" and site.task_id:
                    action = "none"
                    reason = "该目标已有运行但规则不可用；请先检查运行或重新接入"
                counts[category] += 1
                pending_sites.append(
                    {
                        "site_key": site.site_key,
                        "domain": site.domain,
                        "input_value": site.input_value,
                        "identity": {
                            "domain": identity[0],
                            "entry": identity[1],
                            "market": identity[2],
                        },
                        "readiness": site.readiness,
                        "in_workbench": False,
                        "action": action,
                        "reason": reason,
                        "active_rule": (
                            {
                                "rule_id": rule["rule_id"],
                                "rule_version": rule["rule_version"],
                            }
                            if rule is not None
                            else None
                        ),
                        "build_id": build.build_id if build is not None else None,
                        "build_state": build.state if build is not None else None,
                        "build_outcome": build.outcome if build is not None else None,
                    }
                )
            if not pending_sites:
                continue
            total_pending += len(pending_sites)
            batches.append(
                {
                    "batch_id": batch.batch_id,
                    "name": batch.name,
                    "market": batch.market,
                    "created_at": batch.created_at,
                    "target": target,
                    "attempted_at": intent.attempted_at,
                    "last_error": intent.last_error,
                    "counts": {
                        key: counts[key]
                        for key in (
                            "sites",
                            "in_workbench",
                            "needs_onboarding",
                            "building",
                            "ready",
                            "invalid",
                            "duplicate",
                        )
                    },
                    "truncated": len(pending_sites) > 500,
                    "sites": pending_sites[:500],
                }
            )
        return {
            "total_batches": len(batches),
            "total_pending": total_pending,
            "onboarding_available": onboarding_available,
            "onboarding_unavailable_reason": onboarding_reason,
            "batches": batches,
        }

    @app.post("/api/workbench/pending-targets/{batch_id}/dismiss")
    def dismiss_workbench_pending_target(batch_id: str) -> dict[str, Any]:
        if not store.dismiss_workbench_batch_import(batch_id):
            raise _error("NOT_FOUND", f"unknown pending batch: {batch_id}", 404)
        return {"batch_id": batch_id, "dismissed": True}

    @app.post("/api/workbench/tasks", status_code=201)
    def create_workbench_task(payload: WorkbenchTaskCreateRequest) -> dict[str, Any]:
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
        if len(matches) != 1 or not matches[0].get("valid"):
            raise _error("INVALID_RULE", "rule package is invalid or duplicated", 400)
        entry = matches[0]
        if payload.task_type not in entry.get("task_types", []):
            raise _error(
                "INVALID_TASK_TYPE",
                f"rule does not support {payload.task_type}",
                400,
            )
        parsed = normalize_site(payload.input_url)
        if not parsed.valid or not (parsed.site_key or parsed.domain):
            raise _error(
                "INVALID_SITE",
                parsed.error or "站点 URL 无效",
                422,
            )
        rule_domains = [
            _workbench_host_key(str(domain)) for domain in entry.get("domains", [])
        ]
        if rule_domains and _workbench_host_key(parsed.domain) not in rule_domains:
            raise _error(
                "RULE_SITE_MISMATCH",
                "站点域名与所选规则包不匹配",
                422,
            )
        if payload.parent_id:
            parent = store.get_workbench_node(payload.parent_id)
            if parent is None:
                raise _error("NOT_FOUND", f"unknown workbench parent: {payload.parent_id}", 404)
            if parent.node_type != "group":
                raise _error("INVALID_PARENT", "parent must be a workbench group", 409)
        site_key = parsed.site_key or parsed.domain
        existing = next(
            (
                item
                for item in store.list_workbench_task_defs()
                if item.site_key == site_key
            ),
            None,
        )
        if existing is not None:
            raise _error(
                "WORKBENCH_TASK_EXISTS",
                f"task definition already exists for {site_key}",
                409,
            )
        siblings = [
            node
            for node in store.list_workbench_nodes()
            if node.parent_id == payload.parent_id
        ]
        now = utc_now()
        node = WorkbenchNode(
            node_id=f"n-{uuid.uuid4().hex[:12]}",
            node_type="task",
            name=(payload.name or parsed.domain or site_key).strip(),
            parent_id=payload.parent_id,
            sort_order=max((item.sort_order for item in siblings), default=-1) + 1,
            created_at=now,
            updated_at=now,
        )
        definition = WorkbenchTaskDef(
            node_id=node.node_id,
            input_url=payload.input_url.strip(),
            domain=parsed.domain,
            site_key=site_key,
            rule_id=payload.rule_id,
            rule_version=payload.rule_version,
            rule_path=str(entry["path"]),
            task_type=payload.task_type,
            collection_mode=payload.collection_mode,
            country=payload.country,
            language=payload.language,
            market=payload.market,
            category=payload.category,
            limits=payload.limits.model_dump(),
            proxy=payload.proxy,
            note=payload.note,
            created_at=now,
            updated_at=now,
        )
        try:
            store.create_workbench_task(node, definition)
        except ValueError as exc:
            raise _error("CONFLICT", str(exc), 409) from exc
        return {
            "node": {
                "node_id": node.node_id,
                "node_type": node.node_type,
                "parent_id": node.parent_id,
                "name": node.name,
                "sort_order": node.sort_order,
            },
            "definition": _workbench_definition_payload(definition),
        }

    @app.get("/api/workbench/tasks/{node_id}/clone-preview")
    def get_workbench_task_clone_preview(node_id: str) -> dict[str, Any]:
        try:
            return _workbench_clone_preview(store, root, rules, node_id)
        except KeyError as exc:
            raise _error("NOT_FOUND", str(exc), 404) from exc

    @app.post("/api/workbench/tasks/{node_id}/clone", status_code=201)
    def clone_workbench_task(
        node_id: str, payload: WorkbenchTaskCloneRequest
    ) -> dict[str, Any]:
        node = store.get_workbench_node(node_id)
        definition = store.get_workbench_task_def(node_id)
        if node is None or node.node_type != "task" or definition is None:
            raise _error("NOT_FOUND", f"unknown workbench task: {node_id}", 404)
        rule, rule_error = _clone_rule_source(rules, definition)
        if rule is None:
            raise _error(
                "CLONE_RULE_UNAVAILABLE",
                rule_error or "规则文件不可用",
                409,
            )

        terminal_runs = _workbench_terminal_runs(store, node_id)
        source_task: Task | None = None
        if payload.copy_data:
            if payload.copy_run_id:
                source_task = next(
                    (
                        task
                        for _, task in terminal_runs
                        if task.task_id == payload.copy_run_id
                    ),
                    None,
                )
                if source_task is None:
                    raise _error(
                        "CLONE_DATA_UNAVAILABLE",
                        "指定的运行不存在或未结束",
                        409,
                    )
            elif terminal_runs:
                source_task = terminal_runs[0][1]
            if source_task is None:
                raise _error(
                    "CLONE_DATA_UNAVAILABLE",
                    "还没有已结束的运行可复制",
                    409,
                )
            try:
                source_dir = _task_output_dir(root, source_task.task_id)
            except ValueError:
                source_dir = None
            if source_dir is None or not source_dir.is_dir():
                raise _error(
                    "CLONE_DATA_UNAVAILABLE",
                    "运行输出目录不存在",
                    409,
                )
            result_path = source_dir / "task-result.json"
            if not result_path.is_file():
                raise _error(
                    "CLONE_DATA_UNAVAILABLE",
                    "运行结果文件缺失",
                    409,
                )
            try:
                result_payload = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                result_payload = None
            if not isinstance(result_payload, dict):
                raise _error(
                    "CLONE_DATA_UNAVAILABLE",
                    "运行结果文件损坏",
                    409,
                )

        if "parent_id" in payload.model_fields_set:
            parent_id = payload.parent_id or None
        else:
            parent_id = node.parent_id
        if parent_id:
            parent = store.get_workbench_node(parent_id)
            if parent is None or parent.node_type != "group":
                raise _error(
                    "INVALID_PARENT",
                    "目标目录不存在或不是目录",
                    409,
                )
        siblings = [
            item
            for item in store.list_workbench_nodes()
            if item.parent_id == parent_id
        ]
        name = (payload.name or "").strip() or _clone_default_name(node.name, siblings)
        if len(name) > 80:
            raise _error("INVALID_NAME", "名称不能超过 80 个字符", 422)
        if any(ord(character) < 32 for character in name):
            raise _error("INVALID_NAME", "名称不能包含控制字符", 422)

        now = utc_now()
        existing_node_ids = {item.node_id for item in store.list_workbench_nodes()}
        new_node_id = f"n-{uuid.uuid4().hex[:12]}"
        while new_node_id in existing_node_ids:
            new_node_id = f"n-{uuid.uuid4().hex[:12]}"
        new_task_id = f"web-{uuid.uuid4().hex[:12]}"
        while (
            store.get_task(new_task_id) is not None
            or (root / new_task_id).exists()
        ):
            new_task_id = f"web-{uuid.uuid4().hex[:12]}"

        created_rule: Path | None = None
        created_data: Path | None = None
        cloned_task: Task | None = None
        rule_version_record: RuleVersion | None = None
        try:
            rules_root = rules.resolve()
            new_rule_path = rule.path.resolve().relative_to(rules_root).as_posix()
            new_rule_version = rule.rule_version
            rule_payload = None
            if payload.copy_rule:
                version, filename = _clone_rule_names(
                    rule.path, rule.rule_version
                )
                copied_rule = _write_clone_rule(
                    rule.path,
                    rules_root,
                    version=version,
                    filename=filename,
                    now=now,
                )
                created_rule = copied_rule
                new_rule_path = (
                    copied_rule.resolve().relative_to(rules_root).as_posix()
                )
                new_rule_version = version
                rule_digest = hashlib.sha256(copied_rule.read_bytes()).hexdigest()
                rule_version_record = RuleVersion(
                    rule_id=rule.rule_id,
                    rule_version=version,
                    sha256=rule_digest,
                    path=new_rule_path,
                    status="candidate",
                    parent_version=rule.rule_version,
                    notes=f"任务克隆实验版本，克隆自 {node.name}",
                )
                rule_payload = {
                    "rule_id": rule.rule_id,
                    "rule_version": version,
                    "path": new_rule_path,
                    "status": "candidate",
                    "sha256": rule_digest,
                }
            if source_task is not None:
                cloned_task = _clone_task_snapshot(
                    source_task,
                    task_id=new_task_id,
                    node_id=new_node_id,
                    now=now,
                )
                target_dir = _task_output_dir(root, cloned_task.task_id)
                source_dir = _task_output_dir(root, source_task.task_id)
                created_data = target_dir
                _copy_clone_output(
                    source_dir,
                    target_dir,
                    source=source_task,
                    clone=cloned_task,
                )

            provenance = f"克隆自「{node.name}」（{node.node_id}）"
            note = (definition.note or "").strip()
            if note:
                room = max(0, 2000 - len(provenance) - 1)
                note = f"{note[:room]}\n{provenance}"[:2000]
            else:
                note = provenance
            new_node = WorkbenchNode(
                node_id=new_node_id,
                node_type="task",
                name=name,
                parent_id=parent_id,
                sort_order=max(
                    (item.sort_order for item in siblings), default=-1
                )
                + 1,
                created_at=now,
                updated_at=now,
            )
            new_definition = WorkbenchTaskDef(
                node_id=new_node_id,
                input_url=definition.input_url,
                domain=definition.domain,
                site_key=definition.site_key,
                rule_id=definition.rule_id,
                rule_version=new_rule_version,
                rule_path=new_rule_path,
                task_type=definition.task_type,
                collection_mode=definition.collection_mode,
                batch_id=None,
                country=definition.country,
                language=definition.language,
                market=definition.market,
                category=definition.category,
                limits=dict(definition.limits or {}),
                proxy=definition.proxy,
                note=note,
                created_at=now,
                updated_at=now,
            )
            store.clone_workbench_task(
                new_node,
                new_definition,
                source_task=cloned_task,
                copy_items_from=(
                    source_task.task_id if source_task is not None else None
                ),
                rule_version=rule_version_record,
            )
        except ValueError as exc:
            if created_data is not None and created_data.exists():
                shutil.rmtree(created_data, ignore_errors=True)
            if created_rule is not None and created_rule.exists():
                created_rule.unlink(missing_ok=True)
            raise _error("CLONE_FAILED", str(exc), 409) from exc
        except Exception:
            if created_data is not None and created_data.exists():
                shutil.rmtree(created_data, ignore_errors=True)
            if created_rule is not None and created_rule.exists():
                created_rule.unlink(missing_ok=True)
            raise

        run_payload = None
        if cloned_task is not None and created_data is not None:
            stats = _directory_stats(created_data)
            run_payload = {
                "task_id": cloned_task.task_id,
                "source_task_id": cloned_task.input.get("cloned_from"),
                "state": cloned_task.state,
                "outcome": cloned_task.outcome,
                "bytes": stats["bytes"],
                "files": stats["files"],
            }
        return {
            "node": {
                "node_id": new_node.node_id,
                "node_type": new_node.node_type,
                "parent_id": new_node.parent_id,
                "name": new_node.name,
                "sort_order": new_node.sort_order,
            },
            "definition": _workbench_definition_payload(new_definition),
            "rule": rule_payload,
            "run": run_payload,
        }

    @app.patch("/api/workbench/tasks/{node_id}")
    def update_workbench_task(
        node_id: str, payload: WorkbenchTaskUpdateRequest
    ) -> dict[str, Any]:
        definition = store.get_workbench_task_def(node_id)
        if definition is None:
            raise _error("NOT_FOUND", f"unknown workbench task: {node_id}", 404)
        updates = payload.model_dump(exclude_unset=True)
        for key in ("country", "language", "market", "category", "proxy", "note"):
            if key in updates:
                value = updates[key]
                updates[key] = value.strip() or None if isinstance(value, str) else value
        if "rule_id" in updates or "rule_version" in updates or "task_type" in updates:
            if rules is None or not rules.is_dir():
                raise _error("RULES_NOT_CONFIGURED", "serve --rules-dir is not set", 400)
            rule_id = str(updates.get("rule_id") or definition.rule_id)
            rule_version = str(
                updates.get("rule_version") or definition.rule_version
            )
            task_type = str(updates.get("task_type") or definition.task_type)
            entries = _rule_entries(rules)
            matches = [
                entry
                for entry in entries
                if entry.get("rule_id") == rule_id
                and entry.get("rule_version") == rule_version
            ]
            if len(matches) != 1 or not matches[0].get("valid"):
                raise _error("INVALID_RULE", "rule package is invalid or duplicated", 400)
            entry = matches[0]
            if task_type not in entry.get("task_types", []):
                raise _error(
                    "INVALID_TASK_TYPE",
                    f"rule does not support {task_type}",
                    400,
                )
            rule_domains = [
                _workbench_host_key(str(domain)) for domain in entry.get("domains", [])
            ]
            if rule_domains and _workbench_host_key(definition.domain) not in rule_domains:
                raise _error(
                    "RULE_SITE_MISMATCH",
                    "站点域名与所选规则包不匹配",
                    422,
                )
            updates.update(
                {
                    "rule_id": rule_id,
                    "rule_version": rule_version,
                    "rule_path": str(entry["path"]),
                    "task_type": task_type,
                }
            )
        if "limits" in updates and updates["limits"] is None:
            updates.pop("limits")
        try:
            updated = store.update_workbench_task(node_id, utc_now(), **updates)
        except KeyError as exc:
            raise _error("NOT_FOUND", str(exc), 404) from exc
        except ValueError as exc:
            raise _error("INVALID_TASK", str(exc), 400) from exc
        return {"definition": _workbench_definition_payload(updated)}

    def _attach_run_to_workbench(
        task: Task,
        parent_id: str | None,
        name: str | None = None,
    ) -> dict[str, Any]:
        task_id = task.task_id
        existing_run = next(
            (run for run in store.list_workbench_task_runs() if run.task_id == task_id),
            None,
        )
        if existing_run is not None:
            return {
                "task_id": task_id,
                "node_id": existing_run.node_id,
                "created": False,
                "attached": False,
            }
        if parent_id:
            parent = store.get_workbench_node(parent_id)
            if parent is None:
                raise _error("NOT_FOUND", f"unknown workbench parent: {parent_id}", 404)
            if parent.node_type != "group":
                raise _error("INVALID_PARENT", "parent must be a workbench group", 409)
        site_key = task.site_key or task.domain_key or task.plan_id
        if "." not in site_key and task.domain_key:
            site_key = task.domain_key
        site_key = site_key.removeprefix("www.")
        definitions = store.list_workbench_task_defs()
        existing = next(
            (
                definition
                for definition in definitions
                if definition.site_key.removeprefix("www.") == site_key
                and task.batch_id
                and definition.batch_id == task.batch_id
            ),
            next(
                (
                    definition
                    for definition in definitions
                    if definition.site_key.removeprefix("www.") == site_key
                ),
                None,
            ),
        )
        if existing is not None:
            store.attach_workbench_run(existing.node_id, task_id, utc_now())
            return {
                "task_id": task_id,
                "node_id": existing.node_id,
                "created": False,
                "attached": True,
            }
        if rules is None or not rules.is_dir():
            raise _error("RULES_NOT_CONFIGURED", "serve --rules-dir is not set", 400)
        entries = _rule_entries(rules)
        matches = [
            entry
            for entry in entries
            if entry.get("rule_id") == task.plan_id
            and entry.get("rule_version") == task.plan_version
        ]
        if len(matches) != 1 or not matches[0].get("valid"):
            raise _error(
                "RULE_NOT_AVAILABLE",
                "任务使用的规则包当前不可用，无法加入任务树",
                409,
            )
        entry = matches[0]
        if task.task_type not in entry.get("task_types", []):
            raise _error(
                "INVALID_TASK_TYPE",
                f"rule does not support {task.task_type}",
                400,
            )
        domain = (task.domain_key or site_key).removeprefix("www.")
        rule_domains = [
            _workbench_host_key(str(item)) for item in entry.get("domains", [])
        ]
        if rule_domains and _workbench_host_key(domain) not in rule_domains:
            raise _error("RULE_SITE_MISMATCH", "站点域名与规则包不匹配", 422)
        batch = store.get_batch(task.batch_id) if task.batch_id else None
        batch_site = (
            store.get_batch_site(task.batch_id, site_key) if task.batch_id else None
        )
        raw_input = (batch_site.input_value or "").strip() if batch_site else ""
        input_url = (
            raw_input
            if re.match(r"^https?://", raw_input, re.IGNORECASE)
            else f"https://{domain}/"
        )
        limits = {
            key: task.limits[key]
            for key in ("max_urls", "max_products", "max_seconds", "max_attempts")
            if task.limits.get(key) is not None
        }
        mode = task.input.get("collection_mode")
        now = utc_now()
        siblings = [
            node for node in store.list_workbench_nodes() if node.parent_id == parent_id
        ]
        node = WorkbenchNode(
            node_id=f"n-{uuid.uuid4().hex[:12]}",
            node_type="task",
            name=(name or site_key).strip(),
            parent_id=parent_id,
            sort_order=max((item.sort_order for item in siblings), default=-1) + 1,
            created_at=now,
            updated_at=now,
        )
        definition = WorkbenchTaskDef(
            node_id=node.node_id,
            input_url=input_url,
            domain=domain,
            site_key=site_key,
            batch_id=task.batch_id,
            country=batch.country if batch else None,
            language=batch.language if batch else None,
            market=(batch.market if batch else None) or task.market,
            category=batch.category if batch else None,
            task_type=task.task_type,
            collection_mode=mode if mode in {"sample", "formal"} else "formal",
            rule_id=task.plan_id,
            rule_version=task.plan_version,
            rule_path=str(entry["path"]),
            limits=limits,
            proxy=batch_site.proxy if batch_site else None,
            note=batch_site.note if batch_site else None,
            created_at=now,
            updated_at=now,
        )
        try:
            store.create_workbench_task(node, definition)
            store.attach_workbench_run(node.node_id, task_id, now)
        except (ValueError, KeyError) as exc:
            raise _error("CONFLICT", str(exc), 409) from exc
        return {
            "task_id": task_id,
            "node_id": node.node_id,
            "created": True,
            "attached": True,
        }

    @app.post("/api/workbench/runs/{task_id}/attach")
    def attach_workbench_run(
        task_id: str, payload: WorkbenchRunAttachRequest
    ) -> dict[str, Any]:
        task = store.get_task(task_id)
        if task is None:
            raise _error("NOT_FOUND", f"unknown task: {task_id}", 404)
        return _attach_run_to_workbench(task, payload.parent_id, payload.name)

    @app.get("/api/workbench/runs/{task_id}/config")
    def get_workbench_run_config(task_id: str) -> dict[str, Any]:
        task = store.get_task(task_id)
        if task is None:
            raise _error("NOT_FOUND", f"unknown task: {task_id}", 404)
        return _workbench_run_config_payload(store, root, task)

    @app.patch("/api/workbench/runs/{task_id}/config")
    def update_workbench_run_config(
        task_id: str, payload: WorkbenchRunConfigUpdate
    ) -> dict[str, Any]:
        task = store.get_task(task_id)
        if task is None:
            raise _error("NOT_FOUND", f"unknown task: {task_id}", 404)
        limits_update = (
            payload.limits.model_dump(exclude_unset=True) if payload.limits else {}
        )
        rate_update = (
            payload.rate.model_dump(exclude_unset=True) if payload.rate else {}
        )
        for key in ("max_attempts",):
            if key in limits_update and limits_update[key] is None:
                raise _error(
                    "INVALID_LIMITS", f"{key} cannot be empty", 422
                )
        for key in ("concurrency", "per_domain_rps", "delay_ms"):
            if key in rate_update and rate_update[key] is None:
                raise _error(
                    "INVALID_LIMITS", f"{key} cannot be empty", 422
                )
        merged_limits = dict(task.limits)
        for key in (
            "max_urls",
            "max_products",
            "max_seconds",
            "max_navigation",
            "max_sitemaps",
        ):
            if key in limits_update:
                value = limits_update[key]
                merged_limits[key] = None if value is None else int(value)
        if "max_attempts" in limits_update:
            merged_limits["max_attempts"] = int(limits_update["max_attempts"])
        merged_input = dict(task.input)
        merged_rate = dict(task.input.get("rate_policy") or {})
        run_changed = any(
            key in limits_update
            for key in (
                "max_urls",
                "max_products",
                "max_seconds",
                "max_attempts",
                "max_navigation",
                "max_sitemaps",
            )
        )
        resume_required = False
        if "concurrency" in rate_update:
            value = int(rate_update["concurrency"])
            merged_limits["concurrency"] = {
                "navigation": value,
                "product": value,
            }
            merged_rate["concurrency"] = value
            run_changed = True
            resume_required = resume_required or task.state == "RUNNING"
        if "per_domain_rps" in rate_update:
            value = round(float(rate_update["per_domain_rps"]), 3)
            merged_rate["per_domain_rps"] = value
            run_changed = True
            resume_required = resume_required or task.state == "RUNNING"
        if "delay_ms" in rate_update:
            value = int(rate_update["delay_ms"])
            merged_limits["fetch_delay_ms"] = value
            merged_rate["delay_ms"] = value
            run_changed = True
            resume_required = resume_required or task.state == "RUNNING"
        if merged_rate:
            merged_input["rate_policy"] = merged_rate
        run = next(
            (
                item
                for item in store.list_workbench_task_runs()
                if item.task_id == task_id
            ),
            None,
        )
        definition = store.get_workbench_task_def(run.node_id) if run else None
        editable_states = {"QUEUED", "RUNNING", "PAUSED", "PAUSING"}
        continued = False
        applied_run = False
        warnings: list[str] = []
        if payload.action == "continue":
            result = _load_result(root, task_id)
            can_continue = _workbench_run_can_continue(store, task, result)
            if task.state != "FINISHED" or not can_continue["can_continue"]:
                raise _error(
                    "TASK_NOT_CONTINUABLE",
                    "该运行没有可续采的剩余工作，或当前状态不允许续采",
                    409,
                )
            try:
                updated = store.continue_task(
                    task_id,
                    limits=merged_limits,
                    input=merged_input,
                    reset_navigation=payload.reset_discovery,
                )
            except TaskTransitionError as exc:
                raise _error("TASK_NOT_CONTINUABLE", str(exc), 409) from exc
            continued = True
            applied_run = True
            if payload.reset_discovery:
                warnings.append(
                    "已重置发现项；续采会重新请求入口、分类或 sitemap。"
                )
            warnings.append("续采已排入队列，保留此前已采结果。")
        elif task.state in editable_states:
            if run_changed:
                store.update_task(
                    task_id,
                    limits=merged_limits,
                    input=merged_input,
                )
                applied_run = True
            updated = store.get_task(task_id) or task
            if resume_required:
                warnings.append(
                    "并发、每域 RPS 和请求间隔会在暂停并继续后生效。"
                )
            if task.state == "RUNNING" and any(
                key in limits_update
                for key in ("max_navigation", "max_sitemaps")
            ):
                warnings.append(
                    "发现上限已写入账本；已经结束的入口不会自动重跑，需要续采或下次运行重新发现。"
                )
        elif definition is not None:
            updated = task
            warnings.append("历史运行限额不变；新参数只用于之后的运行。")
        else:
            raise _error(
                "TASK_NOT_EDITABLE",
                "该运行已结束且未关联任务定义，不能修改运行配置",
                409,
            )
        definition_updated = False
        if payload.sync_definition and definition is not None:
            definition_limits = dict(definition.limits)
            for key in LIMIT_KEYS:
                if key in limits_update:
                    definition_limits[key] = merged_limits.get(key)
            if "concurrency" in rate_update:
                definition_limits["concurrency"] = int(rate_update["concurrency"])
            if "per_domain_rps" in rate_update:
                definition_limits["per_domain_rps"] = round(
                    float(rate_update["per_domain_rps"]), 3
                )
            if "delay_ms" in rate_update:
                definition_limits["delay_ms"] = int(rate_update["delay_ms"])
            try:
                store.update_workbench_task(
                    definition.node_id,
                    utc_now(),
                    limits=definition_limits,
                )
                definition_updated = True
            except (KeyError, ValueError) as exc:
                if applied_run:
                    warnings.append(f"运行已保存，但任务定义同步失败：{exc}")
                else:
                    raise _error("TASK_NOT_EDITABLE", str(exc), 409) from exc
        elif payload.sync_definition:
            warnings.append("该运行未加入任务树，未同步任务定义。")
        if (applied_run or definition_updated) and any(
            key in limits_update and limits_update[key] is None
            for key in ("max_products", "max_seconds", "max_urls")
        ):
            warnings.append("本次保存已取消对应预算上限。")
        summary = _summary(store, updated, root)
        return {
            "task": summary,
            "applied": {
                "run": applied_run,
                "definition": definition_updated,
                "continued": continued,
                "resume_required": resume_required,
            },
            "warnings": warnings,
        }

    def _ensure_default_workbench_group() -> tuple[WorkbenchNode, bool]:
        nodes = store.list_workbench_nodes()
        existing = next(
            (
                node
                for node in nodes
                if node.node_type == "group" and node.name == "Default"
            ),
            None,
        )
        if existing is not None:
            return existing, False
        siblings = [node for node in nodes if node.parent_id is None]
        now = utc_now()
        node = WorkbenchNode(
            node_id=f"g-{uuid.uuid4().hex[:12]}",
            node_type="group",
            name="Default",
            parent_id=None,
            sort_order=max((item.sort_order for item in siblings), default=-1) + 1,
            created_at=now,
            updated_at=now,
        )
        try:
            created = store.create_workbench_group(node)
        except ValueError as exc:
            raise _error("CONFLICT", str(exc), 409) from exc
        return created, True

    @app.post("/api/workbench/defaults/attach-unassigned")
    def attach_unassigned_workbench_runs() -> dict[str, Any]:
        mapped = {run.task_id for run in store.list_workbench_task_runs()}
        dismissed = store.list_workbench_dismissals()
        tasks = [
            task
            for task in store.list_tasks()
            if task.archived_at is None
            and task.task_id not in mapped
            and task.task_id not in dismissed
        ]
        existing_default = next(
            (
                node
                for node in store.list_workbench_nodes()
                if node.node_type == "group" and node.name == "Default"
            ),
            None,
        )
        if not tasks:
            return {
                "default_group": (
                    {
                        "node_id": existing_default.node_id,
                        "name": existing_default.name,
                        "created": False,
                    }
                    if existing_default is not None
                    else None
                ),
                "processed": 0,
                "attached": [],
                "skipped": [],
            }
        default_group, created_group = _ensure_default_workbench_group()
        attached: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for task in tasks:
            try:
                result = _attach_run_to_workbench(task, default_group.node_id, None)
                attached.append({**result, "site_key": task.site_key or task.domain_key})
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, dict) else {}
                skipped.append(
                    {
                        "task_id": task.task_id,
                        "site_key": task.site_key or task.domain_key,
                        "code": detail.get("code") or "ATTACH_FAILED",
                        "reason": detail.get("message") or str(exc.detail),
                    }
                )
        return {
            "default_group": {
                "node_id": default_group.node_id,
                "name": default_group.name,
                "created": created_group,
            },
            "processed": len(tasks),
            "attached": attached,
            "skipped": skipped,
        }

    @app.post("/api/workbench/tasks/{node_id}/start", status_code=202)
    def start_workbench_task(
        node_id: str, payload: WorkbenchStartRequest | None = None
    ) -> dict[str, Any]:
        if rules is None or not rules.is_dir():
            raise _error("RULES_NOT_CONFIGURED", "serve --rules-dir is not set", 400)
        definition = store.get_workbench_task_def(node_id)
        if definition is None:
            raise _error("NOT_FOUND", f"unknown workbench task: {node_id}", 404)
        if not definition.rule_id or not definition.rule_path:
            if build_manager is None or builds_disabled:
                raise _error(
                    "BUILD_UNAVAILABLE",
                    "构建服务不可用；请配置规则目录后重启",
                    409,
                )
            if not definition.batch_id:
                raise _error(
                    "RULE_NOT_READY",
                    "任务尚未绑定规则且没有批次来源，无法自动接入",
                    409,
                )
            batch = require_batch(definition.batch_id)
            site = store.get_batch_site(batch.batch_id, definition.site_key)
            if site is None:
                raise _error("NOT_FOUND", "批次站点不存在", 404)
            if site.readiness in {"invalid", "duplicate"}:
                raise _error(
                    "INVALID_SITE",
                    site.note or "站点无效或重复",
                    409,
                )
            active_builds = store.list_builds(
                site_key=definition.site_key,
                states=ACTIVE_BUILD_STATES,
                limit=1,
            )
            if active_builds:
                build = active_builds[0]
                return {
                    "accepted": [],
                    "task": None,
                    "onboarding": [
                        {
                            "site_key": definition.site_key,
                            "build_id": build.build_id,
                        }
                    ],
                    "build": build_summary(build.build_id),
                }
            budget, _ = build_manager.onboarding_budget()
            try:
                build = build_manager.start(
                    batch,
                    site,
                    max_products=6,
                    max_total_seconds=budget["max_seconds"],
                    repair_rounds=1,
                    proxy=definition.proxy or site.proxy,
                    auto_collect=True,
                    **budget,
                )
            except BatchTransitionError as exc:
                raise _error("INVALID_STATE", str(exc), 409) from exc
            except BuildError as exc:
                raise _error("BUILD_ERROR", str(exc), 409) from exc
            return {
                "accepted": [],
                "task": None,
                "onboarding": [
                    {
                        "site_key": definition.site_key,
                        "build_id": build.build_id,
                    }
                ],
                "build": build_summary(build.build_id),
            }
        retired = _retired_site_rule(
            store, site_key=definition.site_key, rule_id=definition.rule_id
        )
        if retired is not None:
            raise _error(
                "SITE_RULE_RETIRED",
                f"站点规则已停用：{retired.rule_id}@{retired.rule_version}",
                409,
            )
        runs = [
            run for run in store.list_workbench_task_runs() if run.node_id == node_id
        ]
        latest: Task | None = None
        for run in sorted(runs, key=lambda item: item.created_at):
            latest = store.get_task(run.task_id) or latest
        if latest is not None and latest.state not in TERMINAL_TASK_STATES:
            raise _error(
                "WORKBENCH_TASK_ACTIVE",
                f"task is already active: {latest.task_id}",
                409,
            )
        rule_path = (rules / definition.rule_path).resolve()
        if not rule_path.is_file():
            raise _error("INVALID_RULE", "rule package file is missing", 409)
        try:
            package = load_rule(rule_path)
        except (RuleError, ContractError) as exc:
            raise _error("INVALID_RULE", str(exc), 409) from exc
        if (
            package.rule_id != definition.rule_id
            or package.rule_version != definition.rule_version
        ):
            raise _error(
                "RULE_VERSION_MISMATCH",
                "规则文件为 "
                f"{package.rule_id}@{package.rule_version}，"
                f"任务定义绑定 {definition.rule_id}@{definition.rule_version}",
                409,
            )
        actual_sha256 = hashlib.sha256(rule_path.read_bytes()).hexdigest()
        version = store.get_rule_version(
            definition.rule_id, definition.rule_version
        )
        if version is not None and actual_sha256 != version.sha256:
            raise _error(
                "RULE_HASH_MISMATCH",
                f"规则文件哈希与账本不一致：{definition.rule_id}@"
                f"{definition.rule_version}",
                409,
            )
        rule_market = normalize_market(package.site.get("market"))
        task_market = normalize_market(definition.market)
        if rule_market and task_market and rule_market != task_market:
            raise _error(
                "SITE_MARKET_MISMATCH",
                f"市场不匹配：规则 {rule_market}，任务 {task_market}",
                409,
            )
        definition_limits = dict(definition.limits or {})
        policy = load_collection_policy(store)
        if definition.collection_mode == "formal":
            base_limits = formal_collection_limits(policy)
        else:
            base_limits = {
                "max_urls": 100,
                "max_products": 20,
                "max_seconds": 180,
            }
        effective_limits = {
            key: (
                definition_limits[key]
                if key in definition_limits
                else base_limits[key]
            )
            for key in ("max_urls", "max_products", "max_seconds")
        }
        rate_policy = {
            **default_rate_overrides(policy),
            **load_policies(store).get(
                normalize_domain(definition.domain), {}
            ),
        }
        raw_concurrency = definition_limits.get("concurrency")
        if isinstance(raw_concurrency, dict):
            raw_concurrency = raw_concurrency.get(
                "product", raw_concurrency.get("navigation")
            )
        if raw_concurrency is not None:
            rate_policy["concurrency"] = int(raw_concurrency)
        if definition_limits.get("per_domain_rps") is not None:
            rate_policy["per_domain_rps"] = float(
                definition_limits["per_domain_rps"]
            )
        if definition_limits.get("delay_ms") is not None:
            rate_policy["delay_ms"] = int(definition_limits["delay_ms"])
        max_attempts = definition_limits.get("max_attempts")
        if max_attempts is None:
            max_attempts = rate_policy.get("max_attempts", 2)
        try:
            task = build_task(
                rule_path=rule_path,
                task_id=f"web-{uuid.uuid4().hex[:12]}",
                task_type=definition.task_type,
                max_urls=effective_limits["max_urls"],
                max_products=effective_limits["max_products"],
                max_seconds=effective_limits["max_seconds"],
                max_attempts=int(max_attempts),
                proxy=definition.proxy,
                target_entry=target_entry(definition.input_url),
                concurrency=rate_policy.get("concurrency"),
                delay_ms=rate_policy.get("delay_ms"),
                retry_backoff_ms=rate_policy.get("backoff_ms"),
                rate_policy=rate_policy,
                max_navigation=definition_limits.get("max_navigation"),
                max_sitemaps=definition_limits.get("max_sitemaps"),
            )
        except (RuleError, ContractError) as exc:
            raise _error("INVALID_RULE", str(exc), 400) from exc
        task.batch_id = definition.batch_id
        task.site_key = definition.site_key
        task.domain_key = definition.domain
        task.market = definition.market or task.market
        task.input["collection_mode"] = definition.collection_mode
        task.input["workbench_node_id"] = node_id
        task.state = "QUEUED"
        request_id = (
            payload.request_id
            if payload is not None and payload.request_id
            else f"wb-{uuid.uuid4().hex[:16]}"
        )
        request_json = json.dumps(
            {
                "node_id": node_id,
                "rule_id": definition.rule_id,
                "rule_version": definition.rule_version,
                "limits": effective_limits,
                "rate_policy": rate_policy,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            created_task, created = store.create_workbench_run(
                task,
                node_id=node_id,
                request_id=request_id,
                request_json=request_json,
            )
        except (ValueError, RequestConflictError, BatchTransitionError) as exc:
            raise _error("CONFLICT", str(exc), 409) from exc
        return {
            "created": created,
            "task": _summary(store, created_task, root),
            "node_id": node_id,
        }

    @app.get("/api/workbench/recent")
    def list_workbench_recent(
        scope: Literal["recent", "running", "removed"] = "recent",
        q: Annotated[str, Query(max_length=200)] = "",
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        return _workbench_recent_payload(
            store,
            root,
            scope=scope,
            query=q,
            limit=limit,
            offset=offset,
        )

    @app.post("/api/workbench/recent/dismiss")
    def dismiss_workbench_recent_batch(
        request: WorkbenchRecentDismissRequest,
    ) -> dict[str, Any]:
        task_ids = list(dict.fromkeys(request.task_ids))
        tasks = {task_id: store.get_task(task_id) for task_id in task_ids}
        missing = [task_id for task_id, task in tasks.items() if task is None]
        if missing:
            raise _error("NOT_FOUND", f"unknown task: {', '.join(missing)}", 404)
        non_terminal = [
            task_id
            for task_id, task in tasks.items()
            if task is not None and task.state not in TERMINAL_TASK_STATES
        ]
        if non_terminal:
            raise _error(
                "NON_TERMINAL_TASK",
                "只有已结束的任务可以从最近列表移除: " + ", ".join(non_terminal),
                409,
            )
        store.dismiss_workbench_runs(task_ids)
        return {"task_ids": task_ids, "dismissed": True}

    @app.post("/api/workbench/recent/{task_id}/dismiss")
    def dismiss_workbench_recent(task_id: str) -> dict[str, Any]:
        task = require_task(task_id)
        if task.state not in TERMINAL_TASK_STATES:
            raise _error(
                "NON_TERMINAL_TASK",
                "只有已结束的任务可以从最近列表移除",
                409,
            )
        store.dismiss_workbench_runs([task_id])
        return {"task_id": task_id, "dismissed": True}

    @app.post("/api/workbench/recent/{task_id}/restore")
    def restore_workbench_recent(task_id: str) -> dict[str, Any]:
        require_task(task_id)
        store.restore_workbench_runs([task_id])
        return {"task_id": task_id, "dismissed": False}

    @app.get("/api/workbench/nodes/{node_id}")
    def get_workbench_node(node_id: str) -> dict[str, Any]:
        node = store.get_workbench_node(node_id)
        if node is None:
            raise _error("NOT_FOUND", f"unknown workbench node: {node_id}", 404)
        definition = store.get_workbench_task_def(node_id)
        return {
            "node": {
                "node_id": node.node_id,
                "node_type": node.node_type,
                "parent_id": node.parent_id,
                "name": node.name,
                "sort_order": node.sort_order,
            },
            "definition": _workbench_definition_payload(definition),
            "path": _workbench_path(
                node,
                {item.node_id: item for item in store.list_workbench_nodes()},
            ),
        }

    @app.get("/api/workbench/nodes/{node_id}/cleanup-preview")
    def get_workbench_node_cleanup_preview(node_id: str) -> dict[str, Any]:
        try:
            preview = store.cleanup_definition_preview(node_id)
        except KeyError as exc:
            raise _error("NOT_FOUND", str(exc), 404) from exc
        except ValueError as exc:
            raise _error("INVALID_CLEANUP_TARGET", str(exc), 409) from exc
        return _with_cleanup_stats(root, preview)

    @app.post("/api/workbench/nodes/{node_id}/delete")
    def delete_workbench_node(
        node_id: str, payload: WorkbenchCleanupRequest | None = None
    ) -> dict[str, Any]:
        request = payload or WorkbenchCleanupRequest()
        try:
            preview = store.cleanup_definition_preview(node_id)
        except KeyError as exc:
            raise _error("NOT_FOUND", str(exc), 404) from exc
        except ValueError as exc:
            raise _error("INVALID_CLEANUP_TARGET", str(exc), 409) from exc
        _with_cleanup_stats(root, preview)
        if not preview["can_delete"]:
            raise _error(
                "CLEANUP_BLOCKED",
                "任务定义仍有未结束运行，不能删除",
                409,
                {"blockers": preview["blockers"]},
            )
        if (
            request.purge_runs
            and preview["feedback_count"]
            and not request.purge_feedback
        ):
            raise _error(
                "CLEANUP_REFERENCED",
                "任务定义下的运行仍有关联反馈；请确认同时删除反馈，或先关闭后再清理",
                409,
                {"feedback_count": preview["feedback_count"]},
            )
        deleted_dirs = 0
        if request.purge_runs:
            for run in preview["runs"]:
                path = _task_output_dir(root, run["task_id"])
                if not path.exists():
                    continue
                try:
                    shutil.rmtree(path)
                    deleted_dirs += 1
                except OSError as exc:
                    raise _error(
                        "CLEANUP_FILES",
                        f"删除任务产物失败：{run['task_id']}：{exc}",
                        409,
                        {"task_id": run["task_id"]},
                    ) from exc
        try:
            result = store.delete_workbench_task_definition(
                node_id,
                purge_runs=request.purge_runs,
                purge_feedback=request.purge_feedback,
            )
        except KeyError as exc:
            raise _error("NOT_FOUND", str(exc), 404) from exc
        except CleanupError as exc:
            raise _error("CLEANUP_BLOCKED", str(exc), 409) from exc
        except ValueError as exc:
            raise _error("INVALID_CLEANUP_TARGET", str(exc), 409) from exc
        return {
            "deleted": True,
            **result,
            "deleted_directories": deleted_dirs,
            "bytes": preview["bytes"],
            "files": preview["files"],
        }

    @app.get("/api/tasks/{task_id}/cleanup-preview")
    def get_task_cleanup_preview(task_id: str) -> dict[str, Any]:
        require_task(task_id)
        try:
            preview = store.cleanup_run_preview(task_id)
        except TaskNotFoundError as exc:
            raise _error("NOT_FOUND", str(exc), 404) from exc
        return _with_cleanup_stats(root, preview)

    @app.post("/api/tasks/{task_id}/purge")
    def purge_task(
        task_id: str, payload: WorkbenchCleanupRequest | None = None
    ) -> dict[str, Any]:
        request = payload or WorkbenchCleanupRequest()
        require_task(task_id)
        try:
            preview = store.cleanup_run_preview(task_id)
        except TaskNotFoundError as exc:
            raise _error("NOT_FOUND", str(exc), 404) from exc
        _with_cleanup_stats(root, preview)
        if not preview["can_purge"]:
            raise _error(
                "CLEANUP_BLOCKED",
                "只有已结束的任务可以永久移除",
                409,
                {"blockers": preview["blockers"]},
            )
        if preview["feedback_count"] and not request.purge_feedback:
            raise _error(
                "CLEANUP_REFERENCED",
                "任务仍有关联反馈；请确认同时删除反馈，或先关闭后再清理",
                409,
                {"feedback_count": preview["feedback_count"]},
            )
        path = _task_output_dir(root, task_id)
        if path.exists():
            try:
                shutil.rmtree(path)
            except OSError as exc:
                raise _error(
                    "CLEANUP_FILES",
                    f"删除任务产物失败：{exc}",
                    409,
                    {"task_id": task_id},
                ) from exc
        try:
            result = store.purge_run(
                task_id, purge_feedback=request.purge_feedback
            )
        except TaskNotFoundError as exc:
            raise _error("NOT_FOUND", str(exc), 404) from exc
        except CleanupError as exc:
            raise _error("CLEANUP_BLOCKED", str(exc), 409) from exc
        return {
            "purged": True,
            **result,
            "bytes": preview["bytes"],
            "files": preview["files"],
        }

    @app.get("/api/batches")
    def list_batches(
        status: Annotated[str | None, Query()] = None,
        country: Annotated[str | None, Query()] = None,
        category: Annotated[str | None, Query()] = None,
        folder_id: Annotated[str | None, Query(max_length=40)] = None,
        include_descendants: Annotated[bool, Query()] = True,
        unfiled: Annotated[bool, Query()] = False,
        archived_only: Annotated[bool, Query()] = False,
        include_archived: Annotated[bool, Query()] = False,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        if folder_id and unfiled:
            raise _error(
                "INVALID_FILTER", "folder_id and unfiled cannot be combined", 400
            )
        batches = store.list_batches(
            include_archived=include_archived or archived_only
        )
        if archived_only:
            batches = [batch for batch in batches if batch.archived_at is not None]
        if unfiled:
            batches = [batch for batch in batches if batch.folder_id is None]
        elif folder_id:
            scope = folder_scope_ids(
                folder_id, include_descendants=include_descendants
            )
            batches = [batch for batch in batches if batch.folder_id in scope]
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

    @app.get("/api/batch-tree")
    def get_batch_tree() -> dict[str, Any]:
        return batch_tree_payload()

    @app.post("/api/batch-folders", status_code=201)
    def create_batch_folder(payload: BatchFolderCreateRequest) -> dict[str, Any]:
        try:
            folder = store.create_batch_folder(
                BatchFolder(
                    folder_id=f"f-{uuid.uuid4().hex[:12]}",
                    name=payload.name,
                    parent_id=payload.parent_id,
                )
            )
        except BatchFolderError as exc:
            folder_error(exc)
        return {"folder": folder_payload(folder)}

    @app.patch("/api/batch-folders/{folder_id}")
    def update_batch_folder(
        folder_id: str, payload: BatchFolderUpdateRequest
    ) -> dict[str, Any]:
        updates = payload.model_dump(exclude_unset=True)
        try:
            if not updates:
                folder = require_folder(folder_id)
            else:
                values: dict[str, Any] = {}
                if "name" in updates:
                    values["name"] = updates["name"]
                if "parent_id" in updates:
                    values["parent_id"] = updates["parent_id"]
                folder = store.update_batch_folder(folder_id, **values)
        except BatchFolderError as exc:
            folder_error(exc)
        return {"folder": folder_payload(folder)}

    @app.delete("/api/batch-folders/{folder_id}")
    def delete_batch_folder(folder_id: str) -> dict[str, Any]:
        try:
            result = store.delete_batch_folder(folder_id)
        except BatchFolderError as exc:
            folder_error(exc)
        return {"removed": result}

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
                        "folder_id": payload.folder_id,
                        "import": report,
                    },
                },
            )
        if payload.folder_id is not None:
            require_folder(payload.folder_id)
        require_workbench_parent(payload.workbench_parent_id)
        batch = Batch(
            batch_id=f"b-{uuid.uuid4().hex[:12]}",
            name=payload.name.strip(),
            country=payload.country,
            market=payload.market,
            language=payload.language,
            category=payload.category,
            note=payload.note,
            collection_mode=payload.collection_mode,
            folder_id=payload.folder_id,
        )
        try:
            if "workbench_parent_id" in payload.model_fields_set:
                store.create_batch_with_workbench_import(
                    batch, parent_id=payload.workbench_parent_id
                )
            else:
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

    @app.post("/api/batches/move")
    def move_batches(payload: BatchMoveRequest) -> dict[str, Any]:
        if payload.folder_id is not None:
            require_folder(payload.folder_id)
        try:
            moved = store.move_batches(payload.batch_ids, payload.folder_id)
        except BatchNotFoundError as exc:
            raise _error("NOT_FOUND", str(exc), 404) from exc
        except BatchFolderNotFoundError as exc:
            raise _error("NOT_FOUND", str(exc), 404) from exc
        return {
            "accepted": True,
            "moved": moved,
            "folder_id": payload.folder_id,
        }

    @app.patch("/api/batches/{batch_id}")
    def update_batch(batch_id: str, payload: BatchUpdateRequest) -> dict[str, Any]:
        require_batch(batch_id)
        updates = payload.model_dump(exclude_unset=True)
        if "name" in updates:
            name = updates["name"]
            if name is None or not str(name).strip():
                raise _error("INVALID_NAME", "批次名称不能为空", 400)
            updates["name"] = str(name).strip()
        if "folder_id" in updates and updates["folder_id"] is not None:
            require_folder(str(updates["folder_id"]))
        try:
            store.update_batch(batch_id, **updates)
        except BatchNotFoundError as exc:
            raise _error("NOT_FOUND", str(exc), 404) from exc
        except ValueError as exc:
            raise _error("INVALID_BATCH", str(exc), 400) from exc
        return {
            "accepted": True,
            "batch": batch_payload(require_batch(batch_id), detail=True),
        }

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

    @app.get("/api/batches/{batch_id}/sites/{site_key}/rate-policy")
    def get_site_rate_policy(batch_id: str, site_key: str) -> dict[str, Any]:
        require_batch(batch_id)
        site = store.get_batch_site(batch_id, site_key)
        if site is None:
            raise _error("NOT_FOUND", f"unknown batch site: {site_key}", 404)
        return _site_rate_policy_payload(site)

    @app.put("/api/batches/{batch_id}/sites/{site_key}/rate-policy")
    def put_site_rate_policy(
        batch_id: str, site_key: str, payload: SiteRatePolicyRequest
    ) -> dict[str, Any]:
        require_batch(batch_id)
        site = store.get_batch_site(batch_id, site_key)
        if site is None:
            raise _error("NOT_FOUND", f"unknown batch site: {site_key}", 404)
        return _save_site_rate_policy(site, payload)

    @app.post("/api/batches/{batch_id}/start", status_code=202)
    def start_batch(
        batch_id: str, payload: BatchStartRequest | None = None
    ) -> dict[str, Any]:
        batch = require_batch(batch_id)
        if batch.archived_at is not None:
            raise _error("INVALID_STATE", "batch is archived", 409)
        explicit_limits = payload.limits if payload is not None else None
        limits = explicit_limits or Limits()
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
        promote = bool(payload and payload.promote_trial)
        if promote and wanted:
            raise _error("VALIDATION_ERROR", "转为正式采集适用于整个批次", 422)

        def promotion_result(current: Batch) -> dict[str, Any]:
            return {
                "accepted": [],
                "onboarding": [],
                "skipped": [],
                "batch": batch_payload(current, detail=True),
            }

        if promote and batch.collection_mode == "formal":
            return promotion_result(batch)
        if promote and batch.collection_mode != "sample":
            raise _error("INVALID_STATE", "只有试采批次可以转为正式采集", 409)
        onboarding_budget = None
        if payload is not None and payload.onboard:
            if not batch.collection_mode or builds_disabled or build_manager is None:
                raise _error("BUILD_UNAVAILABLE", "构建服务不可用或批次未设置采集计划", 409)
            pending = [site for site in sites if (
                site.readiness == "needs_onboarding" and not site.task_id
                and (not wanted or site.site_key in wanted)
            )]
            if len(pending) > 10:
                raise _error("VALIDATION_ERROR", "一次最多接入 10 个目标，请先选择要接入的站点", 422)
            onboarding_budget, _ = build_manager.onboarding_budget()
        promotion_pending = promote
        collection_mode = "formal" if promote else batch.collection_mode
        collection_policy = load_collection_policy(store)
        if collection_mode == "sample":
            limits = Limits(**BATCH_COLLECTION_LIMITS["sample"])
        elif explicit_limits is not None:
            limits = explicit_limits
        elif collection_mode == "formal":
            limits = Limits(**formal_collection_limits(collection_policy))
        rate_policies = load_policies(store)
        default_rate = default_rate_overrides(collection_policy)
        for site in sites:
            if wanted and site.site_key not in wanted:
                continue
            rate_policy = {
                **default_rate,
                **rate_policies.get(normalize_domain(site.domain), {}),
            }
            item = {
                "site_key": site.site_key,
                "domain": site.domain,
                "task_id": site.task_id,
            }
            rerun = promote or bool(payload is not None and payload.rerun_finished)
            if site.task_id:
                existing = store.get_task(site.task_id)
                if not rerun and not awaits_formal_collection(collection_mode, existing):
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
            retired = _retired_site_rule(
                store, site_key=site.site_key, rule_id=site.rule_id
            )
            if retired is not None:
                skipped.append(
                    {
                        **item,
                        "reason": (
                            "站点规则已停用："
                            f"{retired.rule_id}@{retired.rule_version}"
                        ),
                    }
                )
                continue
            rule, rule_note = match_target(
                site.site_key, site.input_value, entries, batch.collection_mode is not None, batch.market,
            )
            conflict = market_conflict(rule, batch.market) if rule else None
            if site.readiness != "ready":
                if (onboarding_budget is not None and build_manager is not None
                    and site.readiness == "needs_onboarding" and not site.task_id and not conflict):
                    try:
                        build = build_manager.start(
                            batch, site, max_products=6,
                            max_total_seconds=onboarding_budget["max_seconds"],
                            repair_rounds=1,
                            proxy=proxy_override or site.proxy, auto_collect=True,
                            promote_trial=promotion_pending,
                            **onboarding_budget,
                        )
                    except BatchTransitionError as exc:
                        current = require_batch(batch_id)
                        if current.collection_mode == "formal":
                            return promotion_result(current)
                        raise _error("INVALID_STATE", "请先完成或取消当前试采和接入任务", 409) from exc
                    except BuildError as exc:
                        skipped.append({**item, "reason": str(exc)})
                    else:
                        onboarding.append({**item, "build_id": build.build_id})
                        promotion_pending = False
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
                if collection_mode == "formal":
                    version = store.get_rule_version(rule["rule_id"], rule["rule_version"])
                    build = store.get_build(version.source_build_id) if version and version.source_build_id else None
                    if (
                        build is not None
                        and build.request.get("auto_collect")
                        and (build.request.get("catalog") or {}).get("catalog_scope") == "sample"
                    ):
                        package = load_rule(rules / str(rule["path"]))
                        if (
                            target_entry_mode(package, target_entry(site.input_value)) != "product"
                            and not rule_has_catalog_discovery(package)
                        ):
                            skipped.append({**item, "reason": "旧规则只验证了入口试采，请先补齐目录发现范围"})
                            continue
                task = build_task(
                    rule_path=rules / str(rule["path"]),
                    task_id=f"web-{uuid.uuid4().hex[:12]}",
                    task_type="product",
                    max_urls=limits.max_urls,
                    max_products=limits.max_products,
                    max_seconds=limits.max_seconds,
                    max_attempts=(
                        rate_policy["max_attempts"]
                        if rate_policy.get("max_attempts") is not None
                        else limits.max_attempts
                    ),
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
                    concurrency=rate_policy.get("concurrency"),
                    delay_ms=rate_policy.get("delay_ms"),
                    retry_backoff_ms=rate_policy.get("backoff_ms"),
                    rate_policy=rate_policy,
                )
            except (RuleError, ContractError) as exc:
                skipped.append({**item, "reason": f"规则包无法构建任务：{exc}"})
                continue
            task.batch_id = batch_id
            task.site_key = site.site_key
            if collection_mode:
                task.input["collection_mode"] = collection_mode
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
                    task,
                    site_key=site.site_key,
                    expected_task_id=site.task_id,
                    promote_trial=promotion_pending,
                )
            except BatchTransitionError as exc:
                current = require_batch(batch_id)
                if current.collection_mode == "formal":
                    return promotion_result(current)
                raise _error("INVALID_STATE", "请先完成或取消当前试采和接入任务", 409) from exc
            except BatchNotFoundError:
                skipped.append({**item, "reason": "站点在批次中不存在"})
                continue
            if not created:
                skipped.append({**item, "reason": "站点已开始"})
                continue
            promotion_pending = False
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

    @app.post("/api/batches/{batch_id}/resume", status_code=202)
    def resume_batch(batch_id: str) -> dict[str, Any]:
        return control_batch(batch_id, "resume")

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
                if task and exportable_delivery(task):
                    safe_site = re.sub(r"[^A-Za-z0-9_.-]+", "-", site.site_key)
                    for name, path in task_export_files(task.task_id):
                        archive.write(path, arcname=f"sites/{safe_site}/{name}")
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
                    elif task and task.input.get("collection_mode") == "formal" and not summary["counts"].get("valid_products"):
                        export_status = "empty"
                    else:
                        export_status = "sample" if task and task.input.get("collection_mode") == "sample" else "complete"
                elif summary["outcome"] == "PARTIAL":
                    export_status = "partial"
                else:
                    export_status = "failed"
                delivery_source = None
                if task is not None:
                    delivery_source = (
                        "adopted"
                        if task.input.get("feedback_id") or task.input.get("feedback_ids")
                        else "current"
                    )
                manifest_sites.append(
                    {
                        "site_key": site.site_key,
                        "domain": site.domain,
                        "input_value": site.input_value,
                        "readiness": site.readiness,
                        "note": site.note,
                        "task_id": task.task_id if task else None,
                        "delivery_task_id": site.delivery_task_id,
                        "delivery_source": delivery_source,
                        "rule_id": task.plan_id if task else None,
                        "rule_version": task.plan_version if task else None,
                        "rule_sha256": task.rule_sha256 if task else None,
                        "finished_at": task.finished_at if task else None,
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
                    "delivery_source",
                    "rule_id",
                    "rule_version",
                    "finished_at",
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
                        item["delivery_source"] or "",
                        item["rule_id"] or "",
                        item["rule_version"] or "",
                        item["finished_at"] or "",
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
        onboarding_budget, budget_override = build_manager.onboarding_budget()
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
            "onboarding_budget": onboarding_budget,
            "onboarding_budget_override": budget_override,
        }

    @app.get("/api/builds/config")
    def get_build_config() -> dict[str, Any]:
        return build_config_payload()

    @app.put("/api/builds/config/onboarding-budget")
    def update_onboarding_budget(payload: OnboardingBudgetRequest) -> dict[str, Any]:
        if build_manager is None or builds_disabled:
            raise _error("BUILD_UNAVAILABLE", "build service unavailable", 409)
        build_manager.set_onboarding_budget(payload.model_dump())
        return build_config_payload()

    @app.delete("/api/builds/config/onboarding-budget")
    def reset_onboarding_budget() -> dict[str, Any]:
        if build_manager is None or builds_disabled:
            raise _error("BUILD_UNAVAILABLE", "build service unavailable", 409)
        build_manager.set_onboarding_budget(None)
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

    if build_manager is not None and not read_only:

        def _auto_import_ready_batch(batch_id: str, site_key: str) -> None:
            if store.get_workbench_batch_import(batch_id) is None:
                return
            with workbench_import_lock:
                try:
                    _import_workbench_batch(
                        WorkbenchBatchImportRequest(batch_id=batch_id)
                    )
                except Exception:
                    logger.exception(
                        "auto-import after build failed for %s/%s",
                        batch_id,
                        site_key,
                    )

        build_manager.on_site_ready = _auto_import_ready_batch

    if frontend_mounted:
        assets_dir = FRONTEND_DIST_DIR / "assets"
        if assets_dir.is_dir():
            app.mount(
                "/assets",
                StaticFiles(directory=assets_dir),
                name="assets",
            )
    return app
