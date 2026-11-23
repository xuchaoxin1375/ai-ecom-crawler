"""Batch-site build workflow around the OpenCode harness.

The workflow is deliberately narrow:

1. a batch site without a rule becomes ``building``;
2. the build agent receives a workspace brief and writes ``out/plan/rule.yaml``;
3. the host validates the rule in a bounded run and installs it as a candidate;
4. the site becomes ``ready`` and can be started from the normal batch flow.

The harness session itself remains an internal object; the API exposes only a
small build record, events and pending approvals.  This is the first vertical
slice of the user workflow, not a full build-session UI.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import yaml

from .execution import run_task
from .executor.preflight import check_rule_selectors, format_selector_errors
from .harness import BuildService, BuildTask, OpenCodeHttpAdapter
from .harness.adapter import BuildSession
from .harness.dependencies import DependencyPolicy
from .harness.trace import build_trace, render_trace_markdown
from .robots import extract_sitemaps, robots_url_for
from .runtime.archive import prefetch_rule_samples
from .runtime.batch import normalize_site, rule_domains
from .runtime.models import Batch, BatchSite, BuildRecord, utc_now
from .runtime.rule import load_rule
from .runtime.store import TaskStore

ACTIVE_BUILD_STATES = {
    "CREATED",
    "RUNNING",
    "PAUSING",
    "PAUSED",
    "CANCELLING",
    "VALIDATING",
}
TERMINAL_BUILD_STATES = {"CANCELLED", "FINISHED"}
SAFE_PERMISSIONS = {
    "bash",
    "browser",
    "edit",
    "read",
    "shell",
    "webfetch",
    "websearch",
    "write",
}
MARKET_CURRENCY = {
    "US": "USD",
    "GB": "GBP",
    "FR": "EUR",
    "DE": "EUR",
    "ES": "EUR",
    "IT": "EUR",
    "NL": "EUR",
    "BE": "EUR",
    "AT": "EUR",
    "JP": "JPY",
    "CA": "CAD",
    "AU": "AUD",
    "CN": "CNY",
}
RULE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
TIMELINE_LIMIT = 200
ROBOTS_USER_AGENT = "ecom-crawler-build/0.1"
ROBOTS_TIMEOUT_SECONDS = 10.0
logger = logging.getLogger(__name__)


def _probe_robots(
    entry_url: str, proxy: str | None = None
) -> tuple[str, list[str]]:
    """Fetch robots.txt opportunistically and retain only Sitemap declarations.

    Build-time exploration uses shell/curl tools, so the host performs this
    probe once and passes the Sitemap URLs to the agent. A missing or unreadable
    robots.txt never blocks the build; ``Disallow``/``Crawl-delay`` are not
    parsed or enforced.
    """
    try:
        robots_url = robots_url_for(entry_url)
    except ValueError as exc:
        return f"robots.txt skipped: {exc}", []
    handlers: list[Any] = []
    if proxy:
        handlers.append(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(
        robots_url,
        headers={"User-Agent": ROBOTS_USER_AGENT, "Accept": "text/plain,*/*"},
    )
    try:
        with opener.open(request, timeout=ROBOTS_TIMEOUT_SECONDS) as response:
            status = int(getattr(response, "status", 200))
            body = response.read(1_000_000)
    except urllib.error.HTTPError as exc:
        return f"robots.txt HTTP {exc.code}", []
    except Exception as exc:  # noqa: BLE001 - opportunistic network boundary
        return f"robots.txt fetch failed: {type(exc).__name__}: {exc}", []
    if not 200 <= status < 300:
        return f"robots.txt HTTP {status}", []
    sitemaps = extract_sitemaps(body, base_url=entry_url)
    if sitemaps:
        return f"robots.txt sitemap lines: {len(sitemaps)}", sitemaps
    return "robots.txt has no Sitemap lines", []


class BuildError(ValueError):
    """Raised when a build cannot start or is invalid for the site."""


Validator = Callable[..., dict[str, Any]]


def default_model() -> dict[str, Any] | None:
    provider = os.environ.get("ECOM_BUILD_MODEL_PROVIDER", "opencode-go").strip()
    model_id = os.environ.get("ECOM_BUILD_MODEL_ID", "deepseek-v4.1-flash").strip()
    variant = os.environ.get("ECOM_BUILD_MODEL_VARIANT", "high").strip()
    if not provider or not model_id or provider.lower() in {"none", "off"}:
        return None
    model: dict[str, Any] = {"providerID": provider, "id": model_id}
    if variant:
        model["variant"] = variant
    return model


def default_permissions(
    workspace: str | Path | None = None,
    *,
    skill_roots: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build-session permissions.

    Host skills and the local page/browser MCP tools are shared deliberately.
    The workspace keeps ``input/`` read-only and limits host writes to ``out/``
    and ``work/``; ``shell`` keeps the host user's authority, so this is a
    guardrail rather than an OS sandbox.
    """
    rules: list[dict[str, Any]] = [
        {"action": "question", "resource": "*", "effect": "deny"},
        {"action": "skill", "resource": "*", "effect": "allow"},
        {"action": "subagent", "resource": "*", "effect": "deny"},
        {"action": "read", "resource": "*", "effect": "allow"},
        {"action": "edit", "resource": "*", "effect": "allow"},
        {"action": "write", "resource": "*", "effect": "allow"},
        {"action": "bash", "resource": "*", "effect": "allow"},
        {"action": "shell", "resource": "*", "effect": "allow"},
        {"action": "webfetch", "resource": "*", "effect": "allow"},
        {"action": "websearch", "resource": "*", "effect": "allow"},
        {"action": "browser", "resource": "*", "effect": "allow"},
        {"action": "shell", "resource": "git push *", "effect": "deny"},
        {"action": "shell", "resource": "sudo *", "effect": "deny"},
        {"action": "bash", "resource": "git push *", "effect": "deny"},
        {"action": "bash", "resource": "sudo *", "effect": "deny"},
    ]
    if workspace is None:
        return rules
    root = Path(workspace).resolve().as_posix().rstrip("/")
    rules.extend(
        [
            # Unknown MCP tools/resources stay denied; the known page tools are
            # re-allowed below. External-directory rules also contain an
            # underscore, so they are re-allowed separately.
            {"action": "*_*", "resource": "*", "effect": "deny"},
            {"action": "browse_*", "resource": "*", "effect": "allow"},
            {"action": "htmlmini_*", "resource": "*", "effect": "allow"},
            {"action": "external_directory", "resource": "*", "effect": "deny"},
            {
                "action": "external_directory",
                "resource": "../input*",
                "effect": "allow",
            },
            {
                "action": "external_directory",
                "resource": "../out*",
                "effect": "allow",
            },
            {
                "action": "external_directory",
                "resource": f"{root}/input",
                "effect": "allow",
            },
            {
                "action": "external_directory",
                "resource": f"{root}/input/*",
                "effect": "allow",
            },
            {
                "action": "external_directory",
                "resource": f"{root}/out",
                "effect": "allow",
            },
            {
                "action": "external_directory",
                "resource": f"{root}/out/*",
                "effect": "allow",
            },
            {"action": "read", "resource": f"{root}/control", "effect": "deny"},
            {"action": "read", "resource": f"{root}/control/*", "effect": "deny"},
            {"action": "read", "resource": f"{root}/logs", "effect": "deny"},
            {"action": "read", "resource": f"{root}/logs/*", "effect": "deny"},
            {"action": "read", "resource": "../control*", "effect": "deny"},
            {"action": "read", "resource": "../logs*", "effect": "deny"},
            {"action": "edit", "resource": f"{root}/input", "effect": "deny"},
            {"action": "edit", "resource": f"{root}/input/*", "effect": "deny"},
            {"action": "edit", "resource": f"{root}/control", "effect": "deny"},
            {"action": "edit", "resource": f"{root}/control/*", "effect": "deny"},
            {"action": "edit", "resource": f"{root}/logs", "effect": "deny"},
            {"action": "edit", "resource": f"{root}/logs/*", "effect": "deny"},
            {"action": "edit", "resource": "../input*", "effect": "deny"},
            {"action": "edit", "resource": "../control*", "effect": "deny"},
            {"action": "edit", "resource": "../logs*", "effect": "deny"},
        ]
    )
    for skill_root in skill_roots or []:
        resolved = Path(skill_root).resolve().as_posix().rstrip("/")
        rules.extend(
            [
                {
                    "action": "external_directory",
                    "resource": resolved,
                    "effect": "allow",
                },
                {
                    "action": "external_directory",
                    "resource": f"{resolved}/*",
                    "effect": "allow",
                },
                {"action": "edit", "resource": resolved, "effect": "deny"},
                {"action": "edit", "resource": f"{resolved}/*", "effect": "deny"},
            ]
        )
    return rules


def default_validator(
    rule_path: Path,
    work_dir: Path,
    max_products: int,
    max_seconds: int,
    proxy: str | None = None,
    *,
    archive_mode: str = "off",
    archive_root: str | Path | None = None,
    archive_sample_limit: int = 20,
    archive_max_bytes: int | None = None,
    archive_reuse: bool = False,
) -> dict[str, Any]:
    """Run the bounded validation task in an isolated ledger/output tree."""
    work_dir.mkdir(parents=True, exist_ok=True)
    task_id = f"validate-{uuid.uuid4().hex[:10]}"
    result, task_dir = run_task(
        rule_path=rule_path,
        db_path=work_dir / "validation.db",
        out_root=work_dir / "out",
        task_id=task_id,
        task_type="product",
        max_urls=max(10, max_products * 3),
        max_products=max_products,
        max_seconds=max_seconds,
        max_attempts=1,
        per_domain_rps=1.0,
        proxy=proxy,
        archive_mode=archive_mode,
        archive_root=archive_root,
        archive_sample_limit=archive_sample_limit,
        archive_max_bytes=archive_max_bytes,
        archive_reuse=archive_reuse,
    )
    result["failure_samples"] = _validation_failure_samples(work_dir, task_id)
    currencies: dict[str, int] = {}
    products_path = task_dir / "export" / "products.csv"
    if products_path.is_file():
        with products_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                currency = str(row.get("price_currency") or "").strip().upper()
                if currency:
                    currencies[currency] = currencies.get(currency, 0) + 1
    result["currencies"] = currencies
    return result


def _safe_filename(value: str) -> str:
    cleaned = RULE_NAME_RE.sub("-", value).strip("-")
    return cleaned or "rule"


def _seconds_since(value: str | None, *, end: str | None = None) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if end:
        try:
            finished = datetime.fromisoformat(end)
        except ValueError:
            finished = datetime.now(UTC)
    else:
        finished = datetime.now(UTC)
    return max(0.0, (finished - parsed).total_seconds())


def _validate_proxy(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https", "socks5"} or not parsed.netloc:
        raise BuildError("proxy must be an http(s) or socks5 URL")
    if parsed.username or parsed.password:
        raise BuildError("proxy URL must not contain credentials")


def _mask_proxy(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.username or parsed.password:
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://***@{host}{port}"
    return value


def _entry_url(site: BatchSite) -> str:
    parsed = normalize_site(site.input_value)
    if parsed.error or not parsed.site_key:
        raise BuildError(f"site URL is not usable: {parsed.error or site.input_value}")
    value = site.input_value.strip()
    if "://" not in value:
        value = f"https://{value}"
    parts = urlsplit(value)
    return urlunsplit((parts.scheme or "https", parts.netloc, parts.path or "/", parts.query, ""))


def _origin(entry_url: str) -> str:
    parts = urlsplit(entry_url)
    return f"{parts.scheme}://{parts.netloc}"


def _validation_failure_samples(
    work_dir: Path, task_id: str, *, limit: int = 5
) -> list[dict[str, str]]:
    """Read failed product items from the bounded validation ledger."""
    db_path = work_dir / "validation.db"
    if not db_path.is_file():
        return []
    try:
        store = TaskStore(db_path)
        items = store.items(task_id, "product")
    except Exception:
        logger.debug("validation failure samples unavailable", exc_info=True)
        return []
    samples: list[dict[str, str]] = []
    for item in items:
        if item.state != "FAILED":
            continue
        reason = str(item.result.get("reason") or item.failure_class or "failed")
        detail = str(item.result.get("detail") or "")
        samples.append({"url": item.url, "reason": reason, "detail": detail})
        if len(samples) >= limit:
            break
    return samples


def _validation_error_message(
    task_result: dict[str, Any], *, valid: int, failed: int
) -> str:
    parts = [
        f"host validation produced no valid products: valid={valid}, failed={failed}",
        f"stop_reason={task_result.get('stop_reason')}",
    ]
    detail = str(task_result.get("stop_detail") or "").strip()
    if detail:
        parts.append(f"detail: {detail}")
    samples = task_result.get("failure_samples") or []
    if isinstance(samples, list) and samples:
        sample_text = "; ".join(
            f"{sample.get('url')} -> {sample.get('reason')}"
            for sample in samples[:3]
            if isinstance(sample, dict)
        )
        if sample_text:
            parts.append(f"samples: {sample_text}")
    return ", ".join(parts)


def _trace_timeline(
    trace: dict[str, Any], *, limit: int = TIMELINE_LIMIT
) -> tuple[list[dict[str, Any]], bool]:
    """Merge visible messages, reasoning and tools into chronological entries."""
    entries: list[dict[str, Any]] = []
    for item in trace.get("messages") or []:
        if not isinstance(item, dict) or not item.get("text"):
            continue
        entries.append(
            {
                "kind": "text",
                "role": str(item.get("role") or "assistant"),
                "created_at": item.get("created_at"),
                "text": str(item.get("text") or ""),
            }
        )
    for item in trace.get("reasoning") or []:
        if not isinstance(item, dict) or not item.get("text"):
            continue
        entries.append(
            {
                "kind": "reasoning",
                "created_at": item.get("created_at"),
                "text": str(item.get("text") or ""),
            }
        )
    for item in trace.get("tools") or []:
        if not isinstance(item, dict):
            continue
        entries.append(
            {
                "kind": "tool",
                "created_at": item.get("created_at"),
                "name": str(item.get("name") or "unknown"),
                "status": str(item.get("status") or ""),
                "input": item.get("input"),
                "output": item.get("output"),
                "duration_ms": item.get("duration_ms"),
            }
        )
    entries.sort(
        key=lambda item: (
            item.get("created_at") is None,
            item.get("created_at") or "",
        )
    )
    truncated = len(entries) > limit
    return entries[-limit:], truncated


def _merge_reasoning_timeline(
    trace_timeline: list[dict[str, Any]],
    live_timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep live reasoning visible after a build falls back to its trace.

    Reasoning is not persisted by default, so the trace timeline has no
    reasoning entries.  While the build session is still in memory we can merge
    the captured reasoning back into the trace timeline for display without
    writing it to ``trace.json``.
    """
    reasoning = [
        item
        for item in live_timeline
        if item.get("kind") == "reasoning" and item.get("text")
    ]
    if not reasoning:
        return trace_timeline
    seen = {
        (item.get("created_at"), item.get("text"))
        for item in trace_timeline
        if item.get("kind") == "reasoning"
    }
    merged = list(trace_timeline)
    for item in reasoning:
        key = (item.get("created_at"), item.get("text"))
        if key in seen:
            continue
        seen.add(key)
        timestamp = item.get("created_at") or ""
        inserted = False
        for index, existing in enumerate(merged):
            existing_timestamp = existing.get("created_at") or ""
            if timestamp and existing_timestamp and existing_timestamp > timestamp:
                merged.insert(index, item)
                inserted = True
                break
        if not inserted:
            merged.append(item)
    return merged


def _live_timeline(
    events: list[Any], *, limit: int = TIMELINE_LIMIT
) -> tuple[list[dict[str, Any]], bool]:
    """Build the same timeline shape from the in-memory event stream."""
    entries: list[dict[str, Any]] = []
    text_buffer: list[str] = []
    reasoning_buffer: list[str] = []
    text_started: str | None = None
    reasoning_started: str | None = None

    def flush_text() -> None:
        nonlocal text_started
        if text_buffer:
            entries.append(
                {
                    "kind": "text",
                    "role": "assistant",
                    "created_at": text_started,
                    "text": "".join(text_buffer),
                }
            )
            text_buffer.clear()
        text_started = None

    def flush_reasoning() -> None:
        nonlocal reasoning_started
        if reasoning_buffer:
            entries.append(
                {
                    "kind": "reasoning",
                    "created_at": reasoning_started,
                    "text": "".join(reasoning_buffer),
                }
            )
            reasoning_buffer.clear()
        reasoning_started = None

    def append_bounded(buffer: list[str], value: str, *, cap: int = 8000) -> None:
        current = sum(len(part) for part in buffer)
        if current >= cap:
            return
        buffer.append(value[: cap - current])

    for event in events:
        event_type = getattr(event, "type", "")
        data = getattr(event, "data", {}) or {}
        if event_type == "message_delta":
            flush_reasoning()
            if text_started is None:
                text_started = getattr(event, "created_at", None)
            append_bounded(text_buffer, str(data.get("delta") or ""))
        elif event_type == "reasoning":
            flush_text()
            if reasoning_started is None:
                reasoning_started = getattr(event, "created_at", None)
            append_bounded(reasoning_buffer, str(data.get("delta") or ""))
        elif event_type == "tool_started":
            flush_text()
            flush_reasoning()
            entries.append(
                {
                    "kind": "tool",
                    "created_at": getattr(event, "created_at", None),
                    "name": str(data.get("tool") or "unknown"),
                    "status": "running",
                    "call_id": data.get("call_id"),
                }
            )
        elif event_type == "tool_finished":
            flush_text()
            flush_reasoning()
            call_id = data.get("call_id")
            target = None
            for entry in reversed(entries):
                if entry.get("kind") != "tool" or entry.get("status") != "running":
                    continue
                if call_id and entry.get("call_id") not in {None, call_id}:
                    continue
                target = entry
                break
            if target is None:
                target = {
                    "kind": "tool",
                    "created_at": getattr(event, "created_at", None),
                    "name": str(data.get("tool") or "unknown"),
                }
                entries.append(target)
            target["status"] = str(data.get("status") or "finished")
    flush_text()
    flush_reasoning()
    truncated = len(entries) > limit
    return entries[-limit:], truncated



class BuildManager:
    """Own build records, harness sessions and host-side rule installation."""

    def __init__(
        self,
        store: TaskStore,
        out_root: str | Path,
        rules_dir: str | Path,
        *,
        adapter: Any | None = None,
        model: dict[str, Any] | None = None,
        validator: Validator | None = None,
        max_seconds: int | None = None,
        validation_seconds: int | None = None,
        max_products: int | None = None,
        event_timeout: float | None = None,
        default_proxy: str | None = None,
        capture_reasoning: bool | None = None,
        persist_reasoning: bool | None = None,
        robots_probe: Callable[[str, str | None], tuple[str, list[str]]] | None = None,
        max_repair_rounds: int | None = None,
        repair_seconds: int | None = None,
        archive_mode: str | None = None,
        archive_root: str | Path | None = None,
        archive_sample_limit: int | None = None,
        skills_dir: str | Path | None = None,
    ) -> None:
        self.store = store
        self.out_root = Path(out_root)
        self.rules_dir = Path(rules_dir)
        self.workspace_root = self.out_root / "builds"
        self.skills_dir = Path(skills_dir) if skills_dir is not None else None
        self.model = model if model is not None else default_model()
        self.default_proxy = (
            default_proxy
            or os.environ.get("ECOM_BUILD_PROXY")
            or os.environ.get("ECOM_FETCH_PROXY")
            or None
        )
        self.reasoning_capture_enabled = (
            capture_reasoning
            if capture_reasoning is not None
            else os.environ.get("ECOM_BUILD_CAPTURE_REASONING") == "1"
        )
        # Live reasoning is useful for the build timeline; persisting it into
        # trace.json is a separate, explicit decision because the trace is kept
        # as local evidence and may contain page or prompt content.
        self.persist_reasoning_enabled = (
            persist_reasoning
            if persist_reasoning is not None
            else os.environ.get("ECOM_BUILD_PERSIST_REASONING") == "1"
        )
        self.robots_probe = robots_probe or _probe_robots
        self._trace_reasoning: dict[str, bool] = {}
        self.max_repair_rounds = max(
            0,
            int(
                max_repair_rounds
                if max_repair_rounds is not None
                else os.environ.get("ECOM_BUILD_MAX_REPAIR_ROUNDS", "1")
            ),
        )
        self.repair_seconds = max(
            0,
            int(
                repair_seconds
                if repair_seconds is not None
                else os.environ.get("ECOM_BUILD_REPAIR_SECONDS", "240")
            ),
        )
        self._repair_limits: dict[str, int] = {}
        self._repairs: dict[str, list[dict[str, Any]]] = {}
        self._trace_meta_cache: dict[str, dict[str, Any]] = {}
        self._archive_configs: dict[str, dict[str, Any]] = {}
        self._catalog_configs: dict[str, dict[str, Any]] = {}
        self._archive_stats: dict[str, dict[str, Any]] = {}
        self.default_archive_mode = (
            archive_mode
            or os.environ.get("ECOM_BUILD_ARCHIVE_MODE")
            or "off"
        ).strip().lower()
        if self.default_archive_mode not in {"off", "sample", "full"}:
            raise BuildError(
                f"unsupported archive mode: {self.default_archive_mode}"
            )
        self.default_archive_root = (
            Path(archive_root) if archive_root else self.out_root / "archive"
        )
        self.default_archive_sample_limit = max(
            1,
            int(
                archive_sample_limit
                if archive_sample_limit is not None
                else os.environ.get("ECOM_BUILD_ARCHIVE_SAMPLE_LIMIT", "20")
            ),
        )
        self.validator = validator or default_validator
        self.max_seconds = int(
            max_seconds
            if max_seconds is not None
            else os.environ.get("ECOM_BUILD_MAX_SECONDS", "600")
        )
        self.validation_seconds = int(
            validation_seconds
            if validation_seconds is not None
            else os.environ.get("ECOM_BUILD_VALIDATION_SECONDS", "120")
        )
        self.max_products = int(
            max_products
            if max_products is not None
            else os.environ.get("ECOM_BUILD_MAX_PRODUCTS", "6")
        )
        if adapter is None:
            adapter = OpenCodeHttpAdapter(
                self.workspace_root,
                model=self.model,
                permissions=default_permissions(),
                dependency_policy=DependencyPolicy.empty(),
                event_timeout=event_timeout,
                capture_reasoning=self.reasoning_capture_enabled,
            )
        self.adapter = adapter
        self.service = BuildService(adapter)
        self._lock = threading.RLock()
        self._watchers: dict[str, threading.Thread] = {}
        self._finalizing: set[str] = set()
        self._handled_permissions: dict[str, set[str]] = {}
        self._stopping = threading.Event()

    # ------------------------------------------------------------------ start
    def start(
        self,
        batch: Batch,
        site: BatchSite,
        *,
        max_products: int | None = None,
        max_seconds: int | None = None,
        proxy: str | None = None,
        capture_reasoning: bool | None = None,
        repair_rounds: int | None = None,
        archive_mode: str | None = None,
        archive_root: str | Path | None = None,
        archive_sample_limit: int | None = None,
        archive_max_bytes: int | None = None,
        catalog_scope: str = "sample",
        catalog_products: int | None = None,
        repair: bool = False,
        repair_reason: str | None = None,
    ) -> BuildRecord:
        if site.readiness in {"invalid", "duplicate"}:
            raise BuildError("invalid or duplicate sites cannot be built")
        if not repair and site.task_id:
            raise BuildError("site already has a task")
        if repair:
            if site.readiness != "ready" or not site.rule_path:
                raise BuildError("only a ready site with an installed rule can be repaired")
            if not (self.rules_dir / site.rule_path).is_file():
                raise BuildError(f"installed rule file not found: {site.rule_path}")
        if not self.rules_dir.is_dir():
            raise BuildError("rules directory is not configured")
        entry_url = _entry_url(site)
        product_budget = max(1, int(max_products or self.max_products))
        second_budget = max(60, int(max_seconds or self.max_seconds))
        resolved_proxy = (proxy or site.proxy or self.default_proxy or "").strip() or None
        if resolved_proxy:
            _validate_proxy(resolved_proxy)
        try:
            robots_note, robots_sitemaps = self.robots_probe(
                entry_url, resolved_proxy
            )
        except Exception as exc:  # noqa: BLE001 - opportunistic probe boundary
            robots_note = f"robots.txt probe failed: {type(exc).__name__}: {exc}"
            robots_sitemaps = []
        with self._lock:
            active = self.service.active_build_id
            if active is not None:
                raise BuildError(f"another build is still active: {active}")
            latest = self.store.latest_build_for_site(batch.batch_id, site.site_key)
            if latest is not None and latest.state in ACTIVE_BUILD_STATES:
                raise BuildError(f"site already has an active build: {latest.build_id}")

            build_id = f"build-{uuid.uuid4().hex[:12]}"
            workspace_path = self.workspace_root / build_id
            skill_roots = self._skill_roots()
            skill_manifest = self._skill_manifest(skill_roots)
            self._trace_reasoning[build_id] = bool(
                capture_reasoning and self.reasoning_capture_enabled
            )
            requested_repairs = (
                self.max_repair_rounds
                if repair_rounds is None
                else max(0, min(int(repair_rounds), self.max_repair_rounds))
            )
            self._repair_limits[build_id] = requested_repairs
            self._repairs[build_id] = []
            resolved_archive_mode = (
                archive_mode or self.default_archive_mode
            ).strip().lower()
            if resolved_archive_mode not in {"off", "sample", "full"}:
                raise BuildError(f"unsupported archive mode: {resolved_archive_mode}")
            resolved_catalog_scope = (
                "full" if str(catalog_scope).strip().lower() == "full" else "sample"
            )
            self._archive_configs[build_id] = {
                "mode": resolved_archive_mode,
                "root": str(
                    Path(archive_root)
                    if archive_root
                    else self.default_archive_root
                ),
                "sample_limit": max(
                    1,
                    int(
                        archive_sample_limit
                        if archive_sample_limit is not None
                        else self.default_archive_sample_limit
                    ),
                ),
                "max_bytes": archive_max_bytes,
                "reuse": True,
            }
            self._catalog_configs[build_id] = {
                "catalog_scope": resolved_catalog_scope,
                "catalog_products": max(
                    1,
                    int(
                        catalog_products
                        if catalog_products is not None
                        else os.environ.get("ECOM_BUILD_CATALOG_PRODUCTS", "2000")
                    ),
                ),
            }
            task = BuildTask(
                build_id=build_id,
                site={
                    "name": site.site_key,
                    "entry_urls": [entry_url],
                    "allowed_origins": [_origin(entry_url)],
                    "allowed_path_prefixes": ["/"],
                    "market": batch.market or "UNKNOWN",
                    "locale": batch.language or "en-US",
                    "currency": "USD",
                },
                scope={
                    "max_products": product_budget,
                    "max_seconds": second_budget,
                },
                market=batch.market,
                locale=batch.language,
                limits={
                    "max_products": product_budget,
                    "max_seconds": second_budget,
                    "max_requests": max(30, product_budget * 6),
                },
                tools=["shell", "read", "write", "edit", "webfetch", "websearch"],
                model=self.model,
                workspace=str(workspace_path),
                output_dir=str(workspace_path / "out" / "plan"),
                notes=(
                    "Build a declarative product rule from the batch site entry "
                    "and install it only after host validation."
                ),
                extra={
                    **({"proxy": resolved_proxy} if resolved_proxy else {}),
                    "permissions": default_permissions(
                        workspace_path,
                        skill_roots=[str(root) for root in skill_roots],
                    ),
                    "skills": skill_manifest,
                    "robots_note": robots_note,
                    "robots_sitemaps": robots_sitemaps,
                    **self._catalog_configs[build_id],
                    **self._archive_configs[build_id],
                },
            )
            record = BuildRecord(
                build_id=build_id,
                batch_id=batch.batch_id,
                site_key=site.site_key,
                state="CREATED",
                model=self.model,
                proxy=resolved_proxy,
                workspace=str(self.workspace_root / build_id),
                mode="repair" if repair else "build",
            )
            self.store.create_build(record)
            self.store.update_batch_site(
                batch.batch_id,
                site.site_key,
                readiness="building",
                build_id=build_id,
                proxy=resolved_proxy,
                note=(
                    f"规则修复中：{build_id}"
                    if repair
                    else f"构建中：{build_id}"
                ),
            )
            session: BuildSession | None = None
            try:
                session = self.service.start_build(task)
                self._write_inputs(session, batch, site, task)
                if repair:
                    self._write_repair_inputs(
                        session, batch, site, task, repair_reason or ""
                    )
                self.store.update_build(
                    build_id,
                    workspace=str(session.workspace.root),
                    session_id=session.session_id,
                    state=session.state,
                )
                prompt = (
                    self._repair_run_prompt(site, task)
                    if repair
                    else self._prompt(site, batch, task)
                )
                self.service.send_prompt(build_id, prompt)
                self.store.update_build(
                    build_id,
                    state="RUNNING",
                    started_at=utc_now(),
                )
                self._start_watcher(build_id)
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                self._release_site(site.batch_id, site.site_key, build_id, message)
                self._record_failure(build_id, message)
                if session is not None:
                    try:
                        self.service.close(build_id)
                    except Exception:
                        logger.debug("build start cleanup failed", exc_info=True)
                raise BuildError(message) from exc
            return self.store.get_build(build_id) or record

    def repair(
        self,
        batch: Batch,
        site: BatchSite,
        *,
        reason: str | None = None,
        max_products: int | None = None,
        max_seconds: int | None = None,
        proxy: str | None = None,
        capture_reasoning: bool | None = None,
        repair_rounds: int | None = None,
        archive_mode: str | None = None,
        archive_root: str | Path | None = None,
        archive_sample_limit: int | None = None,
        archive_max_bytes: int | None = None,
    ) -> BuildRecord:
        """Revalidate and repair an installed rule without clearing task data."""
        return self.start(
            batch,
            site,
            max_products=max_products,
            max_seconds=max_seconds,
            proxy=proxy,
            capture_reasoning=capture_reasoning,
            repair_rounds=repair_rounds,
            archive_mode=archive_mode,
            archive_root=archive_root,
            archive_sample_limit=archive_sample_limit,
            archive_max_bytes=archive_max_bytes,
            catalog_scope="sample",
            repair=True,
            repair_reason=reason,
        )

    def _skill_roots(self) -> list[Path]:
        candidates: list[Path] = []
        if self.skills_dir is not None:
            candidates.append(self.skills_dir)
        configured = os.environ.get("ECOM_BUILD_SKILLS_DIR", "").strip()
        if configured:
            candidates.append(Path(configured))
        candidates.extend(
            [
                Path.home() / ".config" / "opencode" / "skills",
                Path.home() / ".claude" / "skills",
                Path.home() / ".agents" / "skills",
            ]
        )
        roots: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            resolved = candidate.expanduser().resolve()
            key = str(resolved).lower() if os.name == "nt" else str(resolved)
            if key in seen:
                continue
            seen.add(key)
            roots.append(resolved)
        return roots

    def _skill_manifest(self, roots: list[Path]) -> dict[str, Any]:
        items: list[dict[str, str]] = []
        for root in roots:
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("SKILL.md")):
                relative = path.relative_to(root)
                if any(
                    part.startswith(".") or part == "node_modules"
                    for part in relative.parts[:-1]
                ):
                    continue
                try:
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                except OSError:
                    continue
                items.append(
                    {
                        "id": path.parent.name,
                        "root": str(root),
                        "sha256": digest,
                    }
                )
            for path in sorted(root.glob("*.md")):
                if path.name == "SKILL.md" or path.name.startswith("."):
                    continue
                try:
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                except OSError:
                    continue
                items.append(
                    {
                        "id": path.stem,
                        "root": str(root),
                        "sha256": digest,
                    }
                )
        return {"roots": [str(root) for root in roots], "items": items}

    def _write_inputs(
        self,
        session: BuildSession,
        batch: Batch,
        site: BatchSite,
        task: BuildTask,
    ) -> None:
        input_dir = session.workspace.input_dir
        input_dir.mkdir(parents=True, exist_ok=True)
        reference = Path(__file__).with_name("harness") / "resources" / "reference-rule.yaml"
        if reference.is_file():
            target = input_dir / "reference-rule.yaml"
            target.write_text(reference.read_text(encoding="utf-8"), encoding="utf-8")
        (input_dir / "build-brief.md").write_text(
            self._brief(batch, site, task),
            encoding="utf-8",
        )
        (session.workspace.work_dir / "AGENTS.md").write_text(
            self._agent_rules(),
            encoding="utf-8",
        )

    def _write_repair_inputs(
        self,
        session: BuildSession,
        batch: Batch,
        site: BatchSite,
        task: BuildTask,
        reason: str,
    ) -> None:
        existing = self.rules_dir / str(site.rule_path)
        input_dir = session.workspace.input_dir
        input_rule = input_dir / "existing-rule.yaml"
        shutil.copyfile(existing, input_rule)
        plan_dir = session.workspace.out_dir / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(existing, plan_dir / "rule.yaml")
        context = {
            "previous_readiness": site.readiness,
            "previous_rule_id": site.rule_id,
            "previous_rule_version": site.rule_version,
            "previous_rule_path": site.rule_path,
            "reason": reason,
        }
        (input_dir / "repair-context.json").write_text(
            json.dumps(context, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (input_dir / "repair-brief.md").write_text(
            self._repair_brief(batch, site, task, reason),
            encoding="utf-8",
        )
        (session.workspace.work_dir / "AGENTS.md").write_text(
            self._agent_rules(),
            encoding="utf-8",
        )

    def _repair_brief(
        self,
        batch: Batch,
        site: BatchSite,
        task: BuildTask,
        reason: str,
    ) -> str:
        try:
            payload = yaml.safe_load(
                (self.rules_dir / str(site.rule_path)).read_text(encoding="utf-8")
            )
        except (OSError, yaml.YAMLError):
            payload = {}
        evidence = payload.get("evidence") if isinstance(payload, dict) else {}
        samples = evidence.get("sample_urls") if isinstance(evidence, dict) else []
        sample_lines = "\n".join(f"- {url}" for url in (samples or [])[:8])
        reason_text = reason.strip() or "Host content audit found description or field gaps."
        robots_note = str(task.extra.get("robots_note") or "robots.txt not probed")
        robots_sitemaps = [
            str(url) for url in (task.extra.get("robots_sitemaps") or [])
        ][:20]
        robots_lines = (
            "\n".join(f"- {url}" for url in robots_sitemaps)
            or "- No Sitemap lines found."
        )
        return f"""# Rule repair brief: {site.site_key}

You are repairing an **installed declarative rule**, not building a new site
from scratch. The previous rule is available at
`../input/existing-rule.yaml`; a working copy is already at
`../out/plan/rule.yaml`.

## Target

- Site key: `{site.site_key}`
- Entry URL: `{task.site["entry_urls"][0]}`
- Market / locale: `{batch.market or "unknown"}` / `{batch.language or "unknown"}`
- Previous rule: `{site.rule_id or "?"}@{site.rule_version or "?"}`
- Host validation sample: `{task.limits.get("max_products")}` products
- Repair reason: {reason_text}

## Scope of this repair

- Keep the existing discovery sources, scope, market, locale, currency and
  five core fields unless the evidence shows a clear bug.
- Do not enumerate the whole catalog again.
- Read local files from `../input`, `../out`, `work/` and the host skills
  directories; do not scan other repositories, user directories or prior run
  output.
- Host skills are available read-only, including `product-crawl-workflow`,
  `resilient-browser-fetch`, `browser-automation`, `network-access`, `htmlmini`
  and `scrapling-official`; use the relevant ones. The `browse` and `htmlmini`
  MCP tools are available. Do not read project site records or probes.
- Inspect 3–5 representative product pages, including at least one page whose
  description is split into a narrative block and a specification/feature list.
- If descriptions are split, use a `compose` fallback to merge the real blocks
  in DOM order and `exclude_selectors` for promo badges. `compose` uses
  `parts:` (a list of `{{type: css_html, selector: ...}}`); `audit` uses
  `blocks:`. Do not confuse the two. Declare every merged block under
  `extract.fields.description_html.audit.blocks`; the host fails validation
  when a present block is missing from the final HTML.
- Keep specification tables in `description_html`; `options`/`attributes` are
  only for purchasable options.
- Bump `rule_version` to a new unique value.
- Write `../out/evidence/build-notes.md` with what changed and the sample URLs
  you checked.

## Known sample URLs

{sample_lines or "- No sample URLs recorded in the previous rule."}

## Output

- `../out/plan/rule.yaml`
- `../out/evidence/build-notes.md`

Do not write outside the workspace. Do not install packages. Respect the
request budget.

## Site access and robots

The host already probed `/robots.txt`; result: {robots_note}.

Sitemap URLs from robots.txt:

{robots_lines}

Use these Sitemap URLs if they help discovery. Do not fetch or read robots.txt
yourself, and do not analyze `Disallow`, `Allow`, `Crawl-delay` or user-agent
groups. robots.txt is not a stop signal. Keep the fixed conservative request
rate. Do not use archive.org or caches as a substitute for the live target.
"""

    def _repair_run_prompt(self, site: BatchSite, task: BuildTask) -> str:
        return (
            "Read AGENTS.md, ../input/repair-brief.md and "
            "../input/existing-rule.yaml, then "
            f"repair the existing rule for {site.site_key}. "
            f"Entry: {task.site['entry_urls'][0]}. "
            "Use the available host skills as needed; do not read project site "
            "records or prior probes. "
            "Focus on the reported content gap and merge any description blocks "
            "that are currently missing. Keep discovery and scope unchanged. "
            "Write ../out/plan/rule.yaml and ../out/evidence/build-notes.md, "
            "then reply briefly."
        )

    def _agent_rules(self) -> str:
        return """# Build agent operating rules

Read first, in this order:

1. the brief named in the prompt (`../input/build-brief.md` or
   `../input/repair-brief.md`);
2. `../input/reference-rule.yaml` or `../input/existing-rule.yaml`;
3. `../input/build-task.json` when present (machine-readable target and budget).

## Local files, network and tools

- Read local files from `../input`, `../out`, `work/` and the host skills
  directories. Do not read project site records, other repositories, user
  directories, prior run output or credentials.
- Host skills are available read-only: `product-crawl-workflow`,
  `resilient-browser-fetch`, `browser-automation`, `network-access`, `htmlmini`,
  `scrapling-official` and other installed user skills. Use the relevant ones;
  read their references or scripts as needed, but do not write into the skills
  directories.
- The `browse` and `htmlmini` MCP tools are available. Other MCP servers are
  disabled.
- Prefer the target origin and path prefixes in the brief; network and search
  tools may use their normal endpoints within the request budget. Do not use an
  archive or cache as a substitute for the live target.
- This workspace is headless. If a global instruction asks for interactive
  confirmation or host file access outside the skills and workspace roots,
  follow this file and the brief instead.

## Site access and robots

- The host probes `<entry origin>/robots.txt` before the build and passes only
  its `Sitemap:` URLs in the brief. Do not fetch, print or read robots.txt
  yourself.
- Do not analyze `Disallow`, `Allow`, `Crawl-delay`, user-agent groups or any
  other robots content. robots.txt is not a stop signal and must not be used to
  exclude paths or change the request rate.
- Use the brief's Sitemap URLs when they help discovery; otherwise discover
  from the entry page.
- Never fetch a URL outside the allowed origin or path prefix. Keep the fixed
  conservative rate from the brief; do not raise concurrency because robots.txt
  looks permissive.
- Do not use archive.org, caches, search snippets, or a different origin as a
  substitute for the live target.
- Logins, payments and personal-data submission are outside this build unless
  the operator explicitly includes them.
- Stay within the brief's request and time budget; do not crawl the whole site.

## Outputs

Write only the files named in the brief. The rule must remain a declarative
candidate; the host validates and installs it.
"""

    def _brief(self, batch: Batch, site: BatchSite, task: BuildTask) -> str:
        entry = task.site["entry_urls"][0]
        origin = task.site["allowed_origins"][0]
        proxy = str(task.extra.get("proxy") or "").strip()
        proxy_line = (
            f"- Egress proxy: `{proxy}`. Use `curl --proxy {proxy}` (or the "
            "equivalent fetch option) for every static price/currency check; "
            "the host validation uses the same proxy. Do not put the proxy URL "
            "into the rule package.\n"
            if proxy
            else "- Egress proxy: direct; no proxy is configured for this build.\n"
        )
        catalog_scope = str(task.extra.get("catalog_scope") or "sample").strip().lower()
        catalog_products = int(
            task.extra.get("catalog_products") or task.limits.get("max_products") or 1
        )
        if catalog_scope == "full":
            catalog_lines = (
                f"- Catalog scope: **full site** (target at least {catalog_products} products)\n"
                f"- Host validation sample: {task.limits.get('max_products')} products\n"
                "- The rule's `scope.max_products` must be at least the catalog target; "
                "the host validates only a small sample.\n"
            )
            discovery_instruction = (
                "This build targets the **full catalog**, not a single entry-page sample. "
                "Inspect the homepage navigation and, when available, the site map page "
                "(for PrestaShop, `/plan-site`). Enumerate the top-level product "
                "categories, then use `discovery.sources` entries of type `listing` "
                "with `product_link_selector` and `advance: {type: page_param, param: "
                "\"p\"}` (or `next_link` when the category exposes rel=next). When "
                "`discovery.sources` is present, `discovery.strategies` must be "
                "`['entry_links']` (schema constraint), even though the actual sources "
                "are listings. Set `max_pages` from the category pagination you actually "
                "observe; do not guess a huge number. Deduplicate product URLs by "
                "canonical URL. You do not need to fetch every product page during the "
                "build: inspect at least one product page per distinct "
                "template/category and put 3+ representative product URLs in "
                "`evidence.sample_urls` so the host can archive them.\n"
            )
        else:
            catalog_lines = (
                f"- Product budget: `{task.limits.get('max_products')}`\n"
                f"- Wall-clock budget: `{task.limits.get('max_seconds')}` seconds\n"
                f"- Request budget: `{task.limits.get('max_requests')}`\n"
            )
            discovery_instruction = (
                "Use the entry page first. If it has product links, a bounded "
                "`entry_links` sample is enough; do not crawl the whole site. If it has "
                "no product links, inspect one category or sitemap and use `listing`, "
                "`html_index` or `sitemap`.\n"
            )
        robots_note = str(task.extra.get("robots_note") or "robots.txt not probed")
        robots_sitemaps = [
            str(url) for url in (task.extra.get("robots_sitemaps") or [])
        ][:20]
        robots_lines = (
            "\n".join(f"- {url}" for url in robots_sitemaps)
            or "- No Sitemap lines found."
        )
        return f"""# Build brief: {site.site_key}

You are building a **declarative** rule package for one public e-commerce site.
The host will validate your rule and install it only if it produces at least one
valid product. You cannot mark a rule `verified`; the host stores it as
`candidate` until a human signs it off.

## Target

- Site key: `{site.site_key}`
- Entry URL: `{entry}`
- Allowed origin: `{origin}`
- Batch market: `{batch.market or "unknown"}`
- Batch language: `{batch.language or "unknown"}`
{catalog_lines}{proxy_line}
{discovery_instruction}
## Required output

Write these files from the workspace (`work/` is your current directory):

- `../out/plan/rule.yaml` — the complete rule manifest.
- `../out/evidence/build-notes.md` — what you inspected, sample URLs, selectors,
  limitations and anything you could not verify.

Read local files from `../input`, `../out`, `work/` and the host skills
directories; do not read project site records, other repositories, user
directories or prior run output.
Do not write outside the workspace. Do not install packages. Respect the
request budget. Logins, payments and personal-data submission are outside this
build unless the operator explicitly includes them.

## Site access and robots

The host already probed `/robots.txt`; result: {robots_note}.

Sitemap URLs from robots.txt:

{robots_lines}

Use these Sitemap URLs if they help discovery. Do not fetch or read robots.txt
yourself, and do not analyze `Disallow`, `Allow`, `Crawl-delay` or user-agent
groups. robots.txt is not a stop signal. Keep the fixed conservative request
rate in this brief. Do not use archive.org or caches as a substitute for the
live target.

A generic reference rule is at `../input/reference-rule.yaml`; adapt it, do not
copy its site or selectors blindly.

## Rule contract (schema_version 1.1)

Required top-level keys: `schema_version`, `rule_id`, `rule_version`, `kind`,
`site`, `scope`, `capabilities`, `discovery`, `fetch`, `extract`, `normalize`,
`validate`, `output`.

- `kind: declarative`; `status: candidate`.
- `rule_id`: lowercase letters, digits and hyphens, e.g. `{site.site_key.replace(".", "-")}-build`.
- `rule_version`: `YYYY.MM.DD-1`.
- `site`: `name`, `entry_urls`, `allowed_origins`, `allowed_path_prefixes`,
  `market`, `locale`, `currency`. Determine the currency from the site; it must
  be a 3-letter code. Use `{batch.market or "the batch market"}` as the market
  hint and `{batch.language or "the page language"}` as the locale hint.
- `scope`: `include`, `exclude` (Python regex on URL path/full URL),
  `max_products`, `max_seconds`, `notes`.
- `capabilities`: `discovery: true`, `product: true`.
- `discovery`: prefer `strategies: ["entry_links"]` with `link_selector`,
  `product_url_patterns` and `url_identity: canonical`. A `listing` source with
  `product_link_selector` is also supported.
- `fetch`: `default_engine` is `static` unless the page truly needs JavaScript;
  `concurrency: 1`, `delay_ms` at least `1000`, `retry: {{max_attempts: 2,
  backoff_ms: 1000}}`, `timeout_ms: 45000`, `browser: false` for static pages.
  If browser is required, set `default_engine: browser` and `browser:
  {{headless: true, wait_selector: "..."}}`; `schema_version: "1.2"` is only
  needed for `load_more`/`infinite_scroll`.
- `extract.fields` must cover `name`, `price.amount`, `price.currency`,
  `primary_image_url`, `source_url`; add `description_html`, `category`,
  `brand`, `options` when available. Every field needs an ordered `fallbacks`
  list with explicit `type` and `label`; put `json_ld` first when the page has
  Product JSON-LD, then CSS/attribute/title fallbacks.
- Product descriptions are often split across a narrative block and a
  specification list/table. Do not accept a short microdata summary as the
  complete description when the page also shows specs. Use a `compose` fallback
  to merge the real blocks in DOM order, with `exclude_selectors` for promo
  badges or share controls. `compose` uses `parts:` (a list of
  `{{type: css_html, selector: ...}}`); the description audit uses `blocks:`.
  Add `extract.fields.description_html.audit.blocks` for every block used
  (narrative, feature list, specification tab); the host fails validation when
  a present block is not represented in the final `description_html`.
- `normalize.price`: `tax_basis: "exclusive_or_inclusive"`, `choose:
  "smaller_public_pair"`, `positive_only: true`.
- `validate.required_fields`: the five core fields above; assertions for
  positive price and 3-letter currency.
- `output`: `url_list.enabled: true`, `product_csv.enabled: true`,
  `product_csv.columns: 9`, `task_result: true`.

A single product page must be inspected to confirm selectors; include at least
three sample product URLs in `evidence.sample_urls` when possible. Record
`limitations` for anything sampled or unavailable.

## Market and currency check

The host fetches with the static engine declared in `fetch`; it does not reuse
your browser cookies or locale. A browser sample can be geo-localized. Before
finishing, fetch at least one product page with the same static path and check
the price currency in the response. The rule's `site.market` must match the
batch market (`{batch.market or "unknown"}`), and `site.currency` must match the
currency the host validation actually sees. Common market expectations are
US→USD, GB→GBP, FR/DE/ES/IT/NL/BE/AT→EUR, JP→JPY, CA→CAD, AU→AUD and CN→CNY.
If they differ, use a market-localized URL (country/locale path or query) or
correct the rule; a currency or market mismatch fails host validation.

When you are done, write the two files and reply with a short summary. The host
will run the bounded validation and may reject the rule if it is missing,
domain-mismatched, or produces no valid product.
"""

    def _prompt(self, site: BatchSite, batch: Batch, task: BuildTask) -> str:
        catalog = str(task.extra.get("catalog_scope") or "sample").lower()
        scope_note = (
            " This is a full-catalog build: enumerate the top-level product "
            "categories and their pagination, and set scope.max_products to the "
            "catalog target. The host validation uses only a small sample."
            if catalog == "full"
            else ""
        )
        return (
            "Read AGENTS.md, ../input/build-brief.md and "
            "../input/reference-rule.yaml, "
            f"then build the rule package for {site.site_key}. "
            f"Entry: {task.site['entry_urls'][0]}.{scope_note} "
            "Use the available host skills (for example "
            "`product-crawl-workflow`, `resilient-browser-fetch`, "
            "`browser-automation`, `network-access`) as needed; do not read "
            "project site records or prior probes. "
            "Write ../out/plan/rule.yaml and ../out/evidence/build-notes.md, "
            "inspect at least one real product page, and keep within the brief's "
            "request and time budget. Reply briefly when the files are written."
        )

    # ------------------------------------------------------------------ watch
    def _start_watcher(self, build_id: str) -> None:
        thread = threading.Thread(
            target=self._watch,
            args=(build_id,),
            name=f"build-watch-{build_id}",
            daemon=True,
        )
        with self._lock:
            self._watchers[build_id] = thread
        thread.start()

    def _watch(self, build_id: str) -> None:
        deadline = time.monotonic() + self.max_seconds
        record = self.store.get_build(build_id)
        if record is None:
            return
        try:
            while not self._stopping.is_set():
                record = self.store.get_build(build_id)
                if record is None:
                    return
                session = self._session(build_id)
                if session is None:
                    self._finalize(build_id, error="build session is no longer available")
                    return
                if session.state in TERMINAL_BUILD_STATES:
                    if session.state == "FINISHED" and record.state not in TERMINAL_BUILD_STATES:
                        self.store.update_build(build_id, state="VALIDATING")
                    result = self._finalize(build_id)
                    if result == "repairing":
                        deadline = time.monotonic() + self.repair_seconds
                        time.sleep(0.5)
                        continue
                    return
                if time.monotonic() >= deadline:
                    try:
                        self.service.cancel(build_id)
                    except Exception as exc:  # noqa: BLE001 - timeout boundary
                        self._finalize(
                            build_id,
                            error=f"build timed out and cancel failed: {exc}",
                        )
                        return
                    self._finalize(build_id, error="build exceeded the wall-clock budget")
                    return
                self._auto_approve(build_id, session)
                if session.state != record.state:
                    self.store.update_build(build_id, state=session.state)
                time.sleep(0.5)
        except Exception:
            logger.exception("build watcher failed for %s", build_id)
        finally:
            with self._lock:
                self._watchers.pop(build_id, None)

    def _session(self, build_id: str) -> BuildSession | None:
        try:
            return self.service.status(build_id)
        except KeyError:
            return None

    def _auto_approve(self, build_id: str, session: BuildSession) -> None:
        if session.state in {"PAUSING", "PAUSED", "CANCELLING", "CANCELLED"}:
            return
        try:
            permissions = self.service.list_permissions(build_id)
        except Exception:
            logger.debug("permission probe failed", exc_info=True)
            return
        handled = self._handled_permissions.setdefault(build_id, set())
        for item in permissions:
            request_id = str(item.get("id") or "")
            action = str(item.get("action") or "").lower()
            if not request_id or request_id in handled or action not in SAFE_PERMISSIONS:
                continue
            try:
                self.service.reply_permission(build_id, request_id, "once")
                handled.add(request_id)
            except Exception:
                logger.debug("permission reply failed", exc_info=True)
                continue

    # --------------------------------------------------------------- finalize
    def _finalize(
        self, build_id: str, *, error: str | None = None
    ) -> str | None:
        """Validate and install one finished agent run.

        Returns ``"repairing"`` when a failed validation was handed back to the
        same harness session; the watcher must keep waiting in that case.
        """
        with self._lock:
            if build_id in self._finalizing:
                return None
            self._finalizing.add(build_id)
        try:
            record = self.store.get_build(build_id)
            if record is None:
                return None
            session = self._session(build_id)
            if session is None:
                message = error or "build session disappeared"
                self._mark_repair_finished(build_id, resolved=False)
                self._release_site(
                    record.batch_id,
                    record.site_key,
                    build_id,
                    f"构建失败：{message}",
                )
                self._record_failure(build_id, message)
                return None
            try:
                self.service.adapter.collect_artifacts(build_id)
            except Exception:
                logger.debug("artifact collection failed", exc_info=True)
            if error is None and session.state == "CANCELLED":
                error = "build was cancelled"
            if error is None and (
                session.state != "FINISHED" or session.outcome != "succeeded"
            ):
                error = session.error or f"build ended with {session.state}/{session.outcome}"

            if error is not None:
                self._mark_repair_finished(build_id, resolved=False)
                self._write_trace(build_id, session, error=error)
                self._release_site(
                    record.batch_id,
                    record.site_key,
                    build_id,
                    f"构建失败：{error}",
                )
                self._record_failure(build_id, error)
                self._close_session(build_id)
                return None

            validation: dict[str, Any] | None = None
            archive_stats: dict[str, Any] | None = None
            try:
                rule_path = self._find_rule(session)
                rule = load_rule(rule_path)
                catalog = self._catalog_configs.get(build_id, {})
                if str(catalog.get("catalog_scope")) == "full":
                    target = int(catalog.get("catalog_products") or 2000)
                    payload = yaml.safe_load(rule_path.read_text(encoding="utf-8"))
                    scope = payload.setdefault("scope", {}) if isinstance(payload, dict) else {}
                    if isinstance(scope, dict):
                        changed = False
                        if int(scope.get("max_products") or 0) < target:
                            scope["max_products"] = target
                            changed = True
                        if int(scope.get("max_seconds") or 0) < 3600:
                            scope["max_seconds"] = 3600
                            changed = True
                        if changed:
                            rule_path.write_text(
                                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                                encoding="utf-8",
                            )
                            rule = load_rule(rule_path)
                selector_errors = check_rule_selectors(rule.raw)
                if selector_errors:
                    raise BuildError(format_selector_errors(selector_errors))
                self._assert_catalog_rule(build_id, rule)
                archive = self._archive_configs.get(build_id, {})
                if str(archive.get("mode") or "off") != "off":
                    archive_stats = prefetch_rule_samples(
                        rule,
                        archive.get("root") or self.out_root / "archive",
                        proxy=record.proxy,
                        limit=int(archive.get("sample_limit") or 20),
                    )
                    self._archive_stats[build_id] = archive_stats
                domains = rule_domains(rule.site)
                if record.site_key not in domains:
                    raise BuildError(
                        "rule domains do not include the target site: "
                        f"{sorted(domains)}"
                    )
                self.store.update_build(build_id, state="VALIDATING")
                work_dir = Path(session.workspace.root) / "validation"
                task_result = self.validator(
                    rule_path,
                    work_dir,
                    self.max_products,
                    self.validation_seconds,
                    record.proxy,
                    archive_mode=str(archive.get("mode") or "off"),
                    archive_root=archive.get("root"),
                    archive_sample_limit=int(archive.get("sample_limit") or 20),
                    archive_max_bytes=archive.get("max_bytes"),
                    archive_reuse=True,
                )
                counts = task_result.get("counts") if isinstance(task_result, dict) else {}
                counts = counts if isinstance(counts, dict) else {}
                valid = int(counts.get("valid_products") or 0)
                failed = int(counts.get("failed_products") or 0)
                validation = {
                    "valid_products": valid,
                    "failed_products": failed,
                    "stop_reason": task_result.get("stop_reason")
                    if isinstance(task_result, dict)
                    else None,
                    "stop_detail": task_result.get("stop_detail")
                    if isinstance(task_result, dict)
                    else None,
                    "failure_samples": task_result.get("failure_samples") or [],
                    "currencies": task_result.get("currencies") or {},
                    "content_audit": task_result.get("content_audit") or {},
                    "archive": {
                        **(
                            {"prefetch": archive_stats}
                            if archive_stats
                            else {}
                        ),
                        **(
                            {
                                "validation": (
                                    task_result.get("runtime") or {}
                                ).get("archive")
                            }
                            if isinstance(task_result, dict)
                            and isinstance(task_result.get("runtime"), dict)
                            and (task_result.get("runtime") or {}).get("archive")
                            else {}
                        ),
                    }
                    or None,
                }
                if valid < 1:
                    raise BuildError(
                        _validation_error_message(
                            task_result if isinstance(task_result, dict) else {},
                            valid=valid,
                            failed=failed,
                        )
                    )
                audit = validation.get("content_audit") or {}
                audit_gaps = int(audit.get("description_gaps") or 0)
                if audit_gaps > 0:
                    samples = audit.get("samples") or []
                    sample_text = "; ".join(
                        f"{item.get('source_url')}: {','.join(item.get('missing_blocks') or [])}"
                        for item in samples[:3]
                        if isinstance(item, dict)
                    )
                    raise BuildError(
                        "description content audit found "
                        f"{audit_gaps} of {audit.get('products_checked') or 0} "
                        "validated product(s) with page blocks missing from "
                        f"description_html; merge the declared blocks with compose "
                        f"or adjust audit.blocks. {sample_text}"
                    )
                batch = self.store.get_batch(record.batch_id)
                batch_market = (batch.market or "").strip().upper() if batch else ""
                rule_market = str(rule.site.get("market") or "").strip().upper()
                if batch_market and rule_market and batch_market != rule_market:
                    raise BuildError(
                        f"rule market {rule_market} does not match batch market "
                        f"{batch_market}; fix the rule or the batch before retrying"
                    )
                rule_currency = str(rule.site.get("currency") or "").strip().upper()
                expected_currency = MARKET_CURRENCY.get(batch_market)
                if expected_currency and rule_currency != expected_currency:
                    raise BuildError(
                        f"rule currency {rule_currency or 'missing'} does not match "
                        f"batch market {batch_market} (expected {expected_currency})"
                    )
                currencies = task_result.get("currencies") or {}
                currencies = {
                    str(key).upper(): int(value)
                    for key, value in currencies.items()
                    if key and int(value) > 0
                }
                validation["currencies"] = currencies
                if rule_currency and currencies and rule_currency not in currencies:
                    raise BuildError(
                        f"currency mismatch: rule declares {rule_currency}, "
                        f"host validation produced {sorted(currencies)}; "
                        "use a market-localized URL or fix the rule currency"
                    )
                rule_id, rule_version, rule_name = self._install_rule(
                    rule_path,
                    record,
                    counts,
                    task_result,
                )
            except Exception as exc:  # noqa: BLE001 - rule/validation boundary
                message = f"{type(exc).__name__}: {exc}"
                if self._start_repair(build_id, message, validation):
                    return "repairing"
                self._mark_repair_finished(build_id, resolved=False)
                self._write_trace(
                    build_id, session, validation=validation, error=message
                )
                self._release_site(
                    record.batch_id,
                    record.site_key,
                    build_id,
                    f"构建失败：{message}",
                )
                self._record_failure(build_id, message)
                self._close_session(build_id)
                return None

            validation.update(
                {
                    "rule_id": rule_id,
                    "rule_version": rule_version,
                    "rule_path": rule_name,
                    "batch_market": batch_market or None,
                }
            )
            note = (
                f"候选方案：{rule_id}@{rule_version}，"
                f"有界验证 {valid} 条有效、{failed} 失败；待人工签字"
            )
            site = self.store.get_batch_site(record.batch_id, record.site_key)
            if site is not None and site.build_id == build_id:
                self.store.update_batch_site(
                    record.batch_id,
                    record.site_key,
                    readiness="ready",
                    rule_id=rule_id,
                    rule_version=rule_version,
                    rule_path=rule_name,
                    proxy=record.proxy,
                    note=note,
                )
            self._mark_repair_finished(build_id, resolved=True)
            self._write_trace(
                build_id,
                session,
                validation=validation,
            )
            self.store.update_build(
                build_id,
                state="FINISHED",
                outcome="succeeded",
                rule_id=rule_id,
                rule_version=rule_version,
                rule_path=rule_name,
                finished_at=utc_now(),
                error=None,
            )
            self._close_session(build_id)
            return None
        finally:
            with self._lock:
                self._finalizing.discard(build_id)
                self._handled_permissions.pop(build_id, None)

    def _assert_catalog_rule(self, build_id: str, rule: Any) -> None:
        catalog = self._catalog_configs.get(build_id, {})
        if str(catalog.get("catalog_scope")) != "full":
            return
        sources = rule.discovery.get("sources")
        source_types = {
            str(source.get("type"))
            for source in sources or []
            if isinstance(source, dict)
        }
        if not source_types & {"listing", "sitemap", "html_index", "public_json"}:
            raise BuildError(
                "full catalog build requires discovery.sources with a listing, "
                "sitemap, html_index or public_json source; entry_links alone is "
                "not a full-catalog discovery path"
            )

    def _start_repair(
        self,
        build_id: str,
        message: str,
        validation: dict[str, Any] | None,
    ) -> bool:
        """Hand one validation failure back to the same harness session."""
        rounds = self._repairs.setdefault(build_id, [])
        limit = self._repair_limits.get(build_id, 0)
        if len(rounds) >= limit:
            return False
        if rounds:
            rounds[-1].setdefault("finished_at", utc_now())
            rounds[-1].setdefault("resolved", False)
        round_number = len(rounds) + 1
        entry: dict[str, Any] = {
            "round": round_number,
            "error": message,
            "validation": validation,
            "started_at": utc_now(),
        }
        rounds.append(entry)
        prompt = self._repair_prompt(round_number, limit, message, validation)
        try:
            self.service.continue_after_finish(build_id, prompt)
        except Exception as exc:  # noqa: BLE001 - continuation boundary
            entry.update(
                {
                    "finished_at": utc_now(),
                    "resolved": False,
                    "start_error": f"{type(exc).__name__}: {exc}",
                }
            )
            return False
        self.store.update_build(build_id, state="RUNNING", error=None)
        return True

    def _repair_prompt(
        self,
        round_number: int,
        limit: int,
        message: str,
        validation: dict[str, Any] | None,
    ) -> str:
        lines = [
            (
                "Host validation rejected the rule. Repair the existing rule instead "
                "of repeating the whole site investigation."
            ),
            f"This is automatic repair round {round_number} of {limit}.",
            "",
            "Exact failure:",
            message,
        ]
        if validation:
            detail = str(validation.get("stop_detail") or "").strip()
            if detail and detail not in message:
                lines.extend(["", f"Validation detail: {detail}"])
            samples = validation.get("failure_samples") or []
            if isinstance(samples, list) and samples:
                lines.extend(["", "Failed sample URLs:"])
                for sample in samples[:5]:
                    if not isinstance(sample, dict):
                        continue
                    lines.append(
                        f"- {sample.get('url')}: {sample.get('reason')}"
                        + (
                            f" ({sample.get('detail')})"
                            if sample.get("detail")
                            else ""
                        )
                    )
        lines.extend(
            [
                "",
                "Required work:",
                "- Edit ../out/plan/rule.yaml only, plus evidence notes if needed.",
                "- Keep the same site, market, currency, scope and five core fields.",
                (
                    "- Every CSS selector must compile under lxml/cssselect. In particular, "
                    "`:not(:first-of-type)` fails in lxml with `*:first-of-type is not "
                    "implemented`; use `:nth-of-type(n+2)`, a class, or an attribute "
                    "selector instead."
                ),
                (
                    "- Inspect at most one product page for the fix; do not expand the "
                    "request budget. Reply briefly when the rule is updated."
                ),
            ]
        )
        return "\n".join(lines)

    def _mark_repair_finished(self, build_id: str, *, resolved: bool) -> None:
        rounds = self._repairs.get(build_id) or []
        if not rounds:
            return
        last = rounds[-1]
        last.setdefault("finished_at", utc_now())
        last["resolved"] = resolved


    def _trace_meta(self, build_id: str, workspace: str | None) -> dict[str, Any]:
        cached = self._trace_meta_cache.get(build_id)
        if cached is not None:
            return cached
        meta: dict[str, Any] = {}
        if workspace:
            path = Path(workspace) / "out" / "trace.json"
            if path.is_file():
                try:
                    trace = json.loads(path.read_text(encoding="utf-8"))
                    meta = {
                        "repairs": trace.get("repairs") or [],
                        "repair_limit": int(trace.get("repair_limit") or 0),
                        "reasoning_retained": bool(
                            trace.get("reasoning_retained")
                        ),
                    }
                except (OSError, json.JSONDecodeError):
                    meta = {}
        self._trace_meta_cache[build_id] = meta
        return meta

    def _write_trace(
        self,
        build_id: str,
        session: BuildSession,
        *,
        validation: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self._trace_meta_cache.pop(build_id, None)
        export: dict[str, Any] | None = None
        client = getattr(self.service.adapter, "client", None)
        if client is not None and session.session_id:
            try:
                export = client.export_session(session.session_id, sanitize=False)
            except Exception:
                logger.debug("session export failed", exc_info=True)
        events: list[dict[str, Any]] = []
        try:
            events = [event.to_dict() for event in self.service.event_log(build_id)]
        except KeyError:
            events = []
        trace = build_trace(
            export,
            build_id=build_id,
            model=session.model,
            events=events,
            validation=validation,
            repairs=list(self._repairs.get(build_id, [])),
            repair_limit=self._repair_limits.get(build_id, 0),
            error=error,
            capture_reasoning=(
                self._trace_reasoning.get(build_id, False)
                and self.persist_reasoning_enabled
            ),
        )
        out_dir = session.workspace.out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "trace.json").write_text(
            json.dumps(trace, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (out_dir / "trace.md").write_text(
            render_trace_markdown(trace),
            encoding="utf-8",
        )

    def _find_rule(self, session: BuildSession) -> Path:
        plan_dir = session.workspace.out_dir / "plan"
        preferred = plan_dir / "rule.yaml"
        if preferred.is_file():
            return preferred
        candidates = sorted(plan_dir.glob("*.yaml")) + sorted(plan_dir.glob("*.yml"))
        if not candidates:
            raise BuildError("agent did not write out/plan/rule.yaml")
        return candidates[0]

    def _install_rule(
        self,
        rule_path: Path,
        record: BuildRecord,
        counts: dict[str, Any],
        task_result: dict[str, Any],
    ) -> tuple[str, str, str]:
        payload = yaml.safe_load(rule_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise BuildError("rule manifest is not a mapping")
        payload["status"] = "candidate"
        payload["updated_at"] = utc_now()
        evidence = payload.get("evidence")
        if not isinstance(evidence, dict):
            evidence = {}
        evidence["host_validation"] = {
            "validated_at": utc_now(),
            "build_id": record.build_id,
            "valid_products": int(counts.get("valid_products") or 0),
            "failed_products": int(counts.get("failed_products") or 0),
            "stop_reason": task_result.get("stop_reason"),
            "outcome": task_result.get("outcome"),
            "currencies": task_result.get("currencies") or {},
            "proxy_configured": bool(record.proxy),
        }
        limitations = evidence.get("limitations")
        if not isinstance(limitations, list):
            limitations = []
        limitations.append(
            "Host validation is a bounded sample, not full-site or long-term coverage."
        )
        evidence["limitations"] = limitations
        payload["evidence"] = evidence

        rule_id = str(payload.get("rule_id") or "").strip()
        rule_version = str(payload.get("rule_version") or "").strip()
        if not rule_id or not rule_version:
            raise BuildError("rule_id and rule_version are required")
        self.rules_dir.mkdir(parents=True, exist_ok=True)
        base = f"{_safe_filename(rule_id)}-{_safe_filename(rule_version)}"
        target = self.rules_dir / f"{base}.yaml"
        if target.exists():
            target = self.rules_dir / f"{base}-{record.build_id}.yaml"
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        os.replace(temporary, target)
        return rule_id, rule_version, target.name

    def _record_failure(self, build_id: str, message: str) -> None:
        record = self.store.get_build(build_id)
        if record is None or record.state in TERMINAL_BUILD_STATES:
            return
        self.store.update_build(
            build_id,
            state="FINISHED",
            outcome="failed",
            error=message,
            finished_at=utc_now(),
        )

    def _release_site(
        self,
        batch_id: str,
        site_key: str,
        build_id: str,
        note: str,
    ) -> None:
        site = self.store.get_batch_site(batch_id, site_key)
        if site is None or site.build_id != build_id:
            return
        if site.readiness != "building":
            return
        context = self._repair_context(build_id)
        if context and context.get("previous_readiness") == "ready":
            self.store.update_batch_site(
                batch_id,
                site_key,
                readiness="ready",
                rule_id=context.get("previous_rule_id"),
                rule_version=context.get("previous_rule_version"),
                rule_path=context.get("previous_rule_path"),
                note=f"规则修复失败，保留原规则：{note}",
            )
            return
        record = self.store.get_build(build_id)
        if record is not None and record.mode == "repair":
            self.store.update_batch_site(
                batch_id,
                site_key,
                readiness="ready",
                note=f"规则修复失败，保留原规则：{note}",
            )
            return
        self.store.update_batch_site(
            batch_id,
            site_key,
            readiness="needs_onboarding",
            note=note,
        )

    def _repair_context(self, build_id: str) -> dict[str, Any] | None:
        record = self.store.get_build(build_id)
        if record is None or not record.workspace:
            return None
        path = Path(record.workspace) / "input" / "repair-context.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _close_session(self, build_id: str) -> None:
        try:
            self.service.close(build_id)
        except Exception:
            logger.debug("build session close failed", exc_info=True)

    # ------------------------------------------------------------------ reads
    def describe(self, build_id: str, *, event_limit: int = 30) -> dict[str, Any]:
        record = self.store.get_build(build_id)
        if record is None:
            raise KeyError(f"unknown build: {build_id}")
        session = self._session(build_id)
        state = session.state if session is not None else record.state
        outcome = session.outcome if session is not None else record.outcome
        if record.state in TERMINAL_BUILD_STATES:
            state = record.state
            if record.outcome:
                outcome = record.outcome
        elif session is not None and session.state in TERMINAL_BUILD_STATES:
            # The agent finished but the host may still be validating and
            # installing the rule.  Do not report a terminal build too early.
            state = "VALIDATING" if session.state == "FINISHED" else session.state
            outcome = None
        events: list[dict[str, Any]] = []
        pending_permissions: list[dict[str, Any]] = []
        pending_dependencies: list[str] = []
        if session is not None:
            try:
                events = [
                    event.to_dict()
                    for event in self.service.event_log(build_id)
                    if event.type != "reasoning_event"
                ][-max(1, event_limit) :]
            except KeyError:
                events = []
            try:
                pending_permissions = self.service.list_permissions(build_id)
            except Exception:
                logger.debug("permission read failed", exc_info=True)
                pending_permissions = []
            try:
                pending_dependencies = self.service.pending_dependency_ids(build_id)
            except Exception:
                logger.debug("dependency read failed", exc_info=True)
                pending_dependencies = []
        else:
            events = self._read_events(record.workspace, limit=max(1, event_limit))
        repair_limit = self._repair_limits.get(build_id)
        repairs = list(self._repairs.get(build_id, []))
        trace_meta: dict[str, Any] = {}
        if repair_limit is None:
            trace_meta = self._trace_meta(build_id, record.workspace)
            repair_limit = int(trace_meta.get("repair_limit") or 0)
        if not repairs:
            repairs = list(trace_meta.get("repairs") or [])
        return {
            "build_id": record.build_id,
            "batch_id": record.batch_id,
            "site_key": record.site_key,
            "state": state,
            "outcome": outcome,
            "mode": record.mode,
            "workspace": record.workspace,
            "session_id": record.session_id,
            "model": record.model,
            "proxy": _mask_proxy(record.proxy),
            "proxy_configured": bool(record.proxy),
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
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
            "elapsed_seconds": _seconds_since(
                record.started_at,
                end=record.finished_at if record.state in TERMINAL_BUILD_STATES else None,
            ),
            "events": events,
            "pending_permissions": pending_permissions,
            "pending_dependencies": pending_dependencies,
            "trace_available": (
                bool(record.workspace)
                and (Path(record.workspace) / "out" / "trace.json").is_file()
            ),
            "reasoning_capture_enabled": self.reasoning_capture_enabled,
            "reasoning_live": bool(self._trace_reasoning.get(build_id, False)),
            "reasoning_retained": bool(trace_meta.get("reasoning_retained")),
            "repair_limit": repair_limit,
            "repair_round": len(repairs),
            "repairs": repairs,
            "archive": self._archive_configs.get(build_id),
            "archive_stats": self._archive_stats.get(build_id),
            "catalog": self._catalog_configs.get(build_id),
        }

    def messages(self, build_id: str, *, limit: int = 80) -> dict[str, Any]:
        """Return visible staged output, and reasoning only if retained.

        A finished build reads the sanitized trace so the UI gets complete
        assistant messages rather than token deltas.  A live build falls back to
        the in-memory event log and labels the result as stream fragments.
        """
        record = self.store.get_build(build_id)
        if record is None:
            raise KeyError(f"unknown build: {build_id}")
        trace_path = (
            Path(record.workspace) / "out" / "trace.json"
            if record.workspace
            else None
        )
        if trace_path is not None and trace_path.is_file():
            try:
                trace = json.loads(trace_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                trace = {}
            timeline, timeline_truncated = _trace_timeline(trace)
            if not trace.get("reasoning_retained"):
                try:
                    live_events = self.service.event_log(build_id)
                except KeyError:
                    live_events = []
                if live_events:
                    live_timeline, _ = _live_timeline(live_events)
                    merged = _merge_reasoning_timeline(timeline, live_timeline)
                    if merged is not timeline:
                        timeline_truncated = (
                            timeline_truncated
                            or len(merged) > TIMELINE_LIMIT
                        )
                        timeline = merged[-TIMELINE_LIMIT:]
            return {
                "build_id": build_id,
                "state": record.state,
                "live": False,
                "messages": (trace.get("messages") or [])[-limit:],
                "reasoning": (trace.get("reasoning") or [])[-limit:],
                "reasoning_retained": bool(trace.get("reasoning_retained")),
                "timeline": timeline,
                "timeline_truncated": timeline_truncated,
                "truncated": False,
            }
        events: list[Any] = []
        try:
            events = self.service.event_log(build_id)
        except KeyError:
            events = []
        messages: list[dict[str, Any]] = []
        reasoning: list[dict[str, Any]] = []
        for event in events:
            if event.type == "message_delta":
                text = str(event.data.get("delta") or "")
                if text:
                    messages.append({"created_at": event.created_at, "text": text})
            elif event.type == "reasoning":
                text = str(event.data.get("delta") or "")
                if text:
                    reasoning.append({"created_at": event.created_at, "text": text})
        timeline, timeline_truncated = _live_timeline(events)
        return {
            "build_id": build_id,
            "state": record.state,
            "live": True,
            "messages": messages[-limit:],
            "reasoning": reasoning[-limit:],
            "reasoning_retained": bool(reasoning),
            "timeline": timeline,
            "timeline_truncated": timeline_truncated,
            "truncated": any(
                bool((event.data or {}).get("truncated")) for event in events
            ),
        }

    def _read_events(self, workspace: str | None, *, limit: int) -> list[dict[str, Any]]:
        if not workspace:
            return []
        path = Path(workspace) / "out" / "session.ndjson"
        if not path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict) and item.get("type") != "reasoning_event":
                    rows.append(item)
        except OSError:
            return []
        return rows[-limit:]

    # ---------------------------------------------------------------- control
    def pause(self, build_id: str) -> dict[str, Any]:
        session = self.service.pause(build_id)
        self.store.update_build(build_id, state=session.state)
        return self.describe(build_id)

    def resume(self, build_id: str) -> dict[str, Any]:
        session = self.service.resume(build_id)
        self.store.update_build(build_id, state=session.state)
        return self.describe(build_id)

    def cancel(self, build_id: str) -> dict[str, Any]:
        record = self.store.get_build(build_id)
        if record is None:
            raise KeyError(f"unknown build: {build_id}")
        session = self.service.cancel(build_id)
        self._write_trace(build_id, session, error="build was cancelled")
        self._release_site(
            record.batch_id,
            record.site_key,
            build_id,
            "构建已取消：可重新开始",
        )
        self.store.update_build(
            build_id,
            state=session.state,
            outcome="cancelled",
            finished_at=utc_now(),
        )
        self._close_session(build_id)
        return self.describe(build_id)

    def reply_permission(
        self,
        build_id: str,
        request_id: str,
        decision: str,
        *,
        message: str | None = None,
    ) -> dict[str, Any]:
        self.service.reply_permission(
            build_id,
            request_id,
            decision,
            message=message,
        )
        return self.describe(build_id)

    def reply_dependency(
        self,
        build_id: str,
        request_id: str,
        decision: str,
        *,
        message: str | None = None,
    ) -> dict[str, Any]:
        self.service.reply_dependency(
            build_id,
            request_id,
            decision,
            message=message,
        )
        return self.describe(build_id)

    # -------------------------------------------------------------- lifecycle
    def reconcile(self) -> list[str]:
        """Close builds left active by a previous service process.

        Harness sessions live in memory, so a restarted service cannot resume
        them.  Mark them interrupted and return the site to ``needs_onboarding``
        instead of leaving a permanently "building" row.
        """
        interrupted: list[str] = []
        for record in self.store.list_builds(states=ACTIVE_BUILD_STATES, limit=500):
            message = "服务重启，构建会话已中断"
            self.store.update_build(
                record.build_id,
                state="FINISHED",
                outcome="failed",
                error=message,
                finished_at=utc_now(),
            )
            self._release_site(
                record.batch_id,
                record.site_key,
                record.build_id,
                message,
            )
            interrupted.append(record.build_id)
        for batch in self.store.list_batches(include_archived=True):
            for site in self.store.list_batch_sites(batch.batch_id):
                if site.readiness != "building":
                    continue
                if site.build_id:
                    build = self.store.get_build(site.build_id)
                    if build is not None and build.state in ACTIVE_BUILD_STATES:
                        continue
                self.store.update_batch_site(
                    batch.batch_id,
                    site.site_key,
                    readiness="needs_onboarding",
                    note="构建状态已失效：可重新开始",
                )
        return interrupted

    def shutdown(self) -> None:
        self._stopping.set()
        records = {
            record.build_id: record
            for record in self.store.list_builds(
                states=ACTIVE_BUILD_STATES, limit=500
            )
        }
        for build_id, record in sorted(records.items()):
            try:
                self.service.cancel(build_id)
            except Exception:
                logger.debug("build cancel on shutdown failed", exc_info=True)
            self._release_site(
                record.batch_id,
                record.site_key,
                build_id,
                "服务停止，构建会话已中断",
            )
            self.store.update_build(
                build_id,
                state="FINISHED",
                outcome="failed",
                error="服务停止，构建会话已中断",
                finished_at=utc_now(),
            )
            self._close_session(build_id)
        with self._lock:
            threads = list(self._watchers.values())
        for thread in threads:
            thread.join(timeout=2)
