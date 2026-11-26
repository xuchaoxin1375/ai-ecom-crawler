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

import copy
import csv
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import yaml

from .build_models import BuildModelPool, ModelPoolError
from .execution import build_task, run_task
from .executor.preflight import check_rule_selectors, format_selector_errors
from .harness import (
    BuildService,
    BuildTask,
    BuildWorkspace,
    HarnessEvent,
    OpenCodeHttpAdapter,
    OpenCodeServer,
)
from .harness.adapter import BuildSession
from .harness.dependencies import (
    DependencyPolicy,
    install_with_pip,
    install_with_uv,
    verify_with_python,
)
from .harness.trace import build_trace, render_trace_markdown
from .robots import extract_sitemaps, robots_url_for
from .rule_diff import (
    build_change_summary,
    compare_product_samples,
    feedback_issue_checks,
    normalize_validation,
)
from .runtime.archive import prefetch_rule_samples
from .runtime.batch import (
    BATCH_COLLECTION_LIMITS,
    normalize_site,
    rule_covers_entry,
    rule_domains,
    target_entry,
)
from .runtime.models import (
    Batch,
    BatchSite,
    BuildRecord,
    RuleVersion,
    SiteRule,
    utc_now,
)
from .runtime.rule import load_rule
from .runtime.store import BatchNotFoundError, TaskStore

ACTIVE_TASK_STATES = {"DRAFT", "QUEUED", "RUNNING", "PAUSING", "PAUSED"}

ACTIVE_BUILD_STATES = {
    "QUEUED",
    "CREATED",
    "RUNNING",
    "PAUSING",
    "PAUSED",
    "CANCELLING",
    "VALIDATING",
}
# States that hold the single build slot. QUEUED waits for it instead of
# occupying it, so restart and shutdown must leave queued rows alone.
RUNNING_BUILD_STATES = ACTIVE_BUILD_STATES - {"QUEUED"}
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
MODEL_POOL_SETTING = "build_model_pool"
MODEL_DEFAULT_SETTING = "build_model_default"
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
            # Unknown MCP tools/resources stay denied; the known page tools and
            # the host-owned dependency bridge are re-allowed below.
            # External-directory rules also contain an underscore, so they are
            # re-allowed separately.
            {"action": "*_*", "resource": "*", "effect": "deny"},
            {
                "action": "request_dependency",
                "resource": "*",
                "effect": "allow",
            },
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


def normalize_permission_rules(
    rules: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    """Validate extra session rules.

    Extra rules are appended after :func:`default_permissions`; OpenCode uses
    the last matching rule, so callers can use them to turn a default ``allow``
    into ``ask`` without rebuilding the workspace-specific rules.
    """

    normalized: list[dict[str, str]] = []
    for rule in rules or []:
        if not isinstance(rule, dict):
            raise BuildError("permission rules must be objects")
        action = str(rule.get("action") or "").strip()
        resource = str(rule.get("resource") or "*").strip()
        effect = str(rule.get("effect") or "").strip().lower()
        if not action:
            raise BuildError("permission rule action is required")
        if effect not in {"allow", "deny", "ask"}:
            raise BuildError(f"unsupported permission effect: {effect}")
        normalized.append(
            {"action": action, "resource": resource, "effect": effect}
        )
    return normalized


def dependency_policy_from_env() -> DependencyPolicy:
    """Build an opt-in dependency policy from explicit environment settings.

    Production defaults to an empty policy: a build may request a package, but
    the host will not install anything until an operator wires a dedicated build
    interpreter and allowlist.  ``ECOM_BUILD_PYTHON`` selects that interpreter;
    ``ECOM_BUILD_DEPENDENCY_ALLOWLIST`` is a comma-separated ``name==version``
    list.  Without the interpreter, the policy stays empty even if an allowlist
    is present.
    """

    python = os.environ.get("ECOM_BUILD_PYTHON", "").strip()
    if not python:
        return DependencyPolicy.empty()
    path = Path(python).expanduser()
    if not path.is_file():
        raise BuildError(f"ECOM_BUILD_PYTHON is not a file: {path}")
    allowlist: dict[str, dict[str, str]] = {}
    raw = os.environ.get("ECOM_BUILD_DEPENDENCY_ALLOWLIST", "")
    for item in raw.split(","):
        entry = item.strip()
        if not entry:
            continue
        if "==" not in entry:
            raise BuildError(
                "ECOM_BUILD_DEPENDENCY_ALLOWLIST entries must be name==version"
            )
        name, version = (part.strip() for part in entry.split("==", 1))
        if not name or not version:
            raise BuildError(
                "ECOM_BUILD_DEPENDENCY_ALLOWLIST entries must be name==version"
            )
        allowlist[name] = {"version": version}
    return DependencyPolicy(
        allowlist=allowlist,
        build_python=path,
        installers={"pip": install_with_pip, "uv": install_with_uv},
        verifier=verify_with_python,
    )


def _rule_needs_browser(rule: Any) -> bool:
    """Return whether any declared URL type needs a browser engine."""
    if str(getattr(rule, "kind", "")) == "hybrid":
        return True
    fetch = getattr(rule, "fetch", {}) or {}
    browser_engines = {"browser", "stealth"}
    if str(fetch.get("default_engine", "")).lower() in browser_engines:
        return True
    per_type = fetch.get("per_url_type")
    if isinstance(per_type, dict):
        for settings in per_type.values():
            if isinstance(settings, dict) and str(
                settings.get("engine", "")
            ).lower() in browser_engines:
                return True
    return False


def validation_seconds_for_rule(
    rule_path: Path,
    *,
    default: int,
    browser_default: int,
) -> int:
    """Raise the host-validation budget for rules that use a browser.

    Browser product pages are much slower than static HTML; the pilot's
    120-second budget validated only one of six products.  A rule that loads
    fails validation before this helper is called, so the fallback is only a
    defensive default.
    """
    base = max(1, int(default))
    try:
        rule = load_rule(rule_path)
    except Exception:  # noqa: BLE001 - validation reports the rule error later
        return base
    if _rule_needs_browser(rule):
        return max(base, max(1, int(browser_default)))
    return base


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
    seed_urls: list[str] | None = None,
    discover: bool = True,
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
        seed_urls=seed_urls,
        discover=discover,
    )
    result["failure_samples"] = _validation_failure_samples(work_dir, task_id)
    currencies: dict[str, int] = {}
    products_path = task_dir / "products.csv"
    if not products_path.is_file():
        products_path = task_dir / "export" / "products.csv"
    if products_path.is_file():
        with products_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                currency = str(row.get("price_currency") or "").strip().upper()
                if currency:
                    currencies[currency] = currencies.get(currency, 0) + 1
    result["currencies"] = currencies
    result["product_samples"] = _product_samples(products_path)
    return result


def _product_samples(products_path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    """Read the bounded validation CSV into comparable product records."""
    if not products_path.is_file():
        return []
    samples: list[dict[str, Any]] = []
    with products_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            samples.append(
                {
                    "source_url": str(row.get("source_url") or "").strip(),
                    "name": str(row.get("name") or "").strip(),
                    "price_amount": str(row.get("price_amount") or "").strip(),
                    "price_currency": str(
                        row.get("price_currency") or ""
                    ).strip().upper(),
                    "primary_image_url": str(
                        row.get("primary_image_url") or ""
                    ).strip(),
                    "description_html": str(
                        row.get("description_html") or ""
                    ).strip(),
                }
            )
            if len(samples) >= limit:
                break
    return [sample for sample in samples if sample["source_url"]]


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
    if parsed.tzinfo is None:
        # Older rows or external tooling may store naive timestamps; the
        # application writes UTC, so treat naive values as UTC instead of
        # failing the build detail response.
        parsed = parsed.replace(tzinfo=UTC)
    if end:
        try:
            finished = datetime.fromisoformat(end)
        except ValueError:
            finished = datetime.now(UTC)
    else:
        finished = datetime.now(UTC)
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=UTC)
    return max(0.0, (finished - parsed).total_seconds())


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip() == "1"


def _budget_value(explicit: int | None, env_name: str) -> int | None:
    """Resolve an optional per-build budget from an argument or environment.

    ``None`` keeps the budget unset so existing callers remain unlimited.
    A non-positive environment value is treated as unset; malformed values
    fail at startup instead of silently disabling the guard.
    """
    if explicit is not None:
        value = int(explicit)
        return value if value > 0 else None
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise BuildError(f"{env_name} must be an integer") from exc
    return value if value > 0 else None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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


def _workspace_events(workspace: BuildWorkspace) -> list[HarnessEvent]:
    """Load normalized events written before a service restart."""
    try:
        lines = workspace.session_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events: list[HarnessEvent] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        event_type = str(payload.get("type") or "")
        if not event_type:
            continue
        data = payload.get("data")
        events.append(
            HarnessEvent(
                type=event_type,
                source_type=str(payload.get("source_type") or ""),
                session_id=(
                    str(payload["session_id"])
                    if payload.get("session_id")
                    else None
                ),
                data=dict(data) if isinstance(data, dict) else {},
                created_at=str(payload.get("created_at") or utc_now()),
            )
        )
    return events


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


def _runtime_task_lines(runtime: dict[str, Any]) -> str:
    if not runtime:
        return "- No finished task result is recorded for this site yet."
    counts = runtime.get("counts") if isinstance(runtime.get("counts"), dict) else {}
    coverage = (
        runtime.get("coverage") if isinstance(runtime.get("coverage"), dict) else {}
    )
    audit = (
        runtime.get("content_audit")
        if isinstance(runtime.get("content_audit"), dict)
        else {}
    )
    quality = (
        runtime.get("quality_exceptions")
        if isinstance(runtime.get("quality_exceptions"), list)
        else []
    )
    lines = [
        (
            f"- Task: `{runtime.get('task_id')}` ({runtime.get('state') or '?'} / "
            f"{runtime.get('outcome') or '?'})"
        ),
        f"- Stop reason: `{runtime.get('stop_reason') or 'unknown'}`",
        "- Counts: "
        + ", ".join(
            f"{key} {counts.get(key)}"
            for key in (
                "discovered_urls",
                "valid_products",
                "excluded_products",
                "failed_products",
            )
            if counts.get(key) is not None
        ),
    ]
    if coverage:
        lines.append(
            "- Coverage: "
            f"{coverage.get('status') or 'UNKNOWN'} "
            f"({coverage.get('covered')}/{coverage.get('denominator')})"
        )
    if audit:
        lines.append(
            "- Content audit: "
            f"{audit.get('products_checked')} products checked, "
            f"{audit.get('description_gaps')} description gaps"
        )
    if quality:
        lines.append(
            f"- Quality exceptions: {runtime.get('quality_exception_count') or len(quality)}"
        )
        for item in quality[:3]:
            if not isinstance(item, dict):
                continue
            label = item.get("source_url") or item.get("field") or "item"
            reason = (
                item.get("reason")
                or item.get("partial_reason")
                or item.get("description_status")
                or item.get("missing_reasons")
                or "not acceptable"
            )
            lines.append(f"  - `{label}`: {str(reason)[:240]}")
    return "\n".join(lines)


def _duplicate_product_sample_error(
    samples: list[dict[str, Any]],
) -> str | None:
    """Reject a validation sample that is obviously one repeated product.

    A review widget or organisation JSON-LD block can make every product sample
    share the shop name or avatar.  Field-presence checks alone would accept
    that, so require at least three samples and fail only when every non-empty
    name or image is identical.
    """

    if len(samples) < 3:
        return None
    names = {
        str(item.get("name") or "").strip().casefold()
        for item in samples
        if isinstance(item, dict)
    }
    names.discard("")
    if len(names) == 1:
        value = next(iter(names))
        return f"all {len(samples)} product samples share name {value[:120]!r}"
    images = {
        str(item.get("primary_image_url") or "").strip()
        for item in samples
        if isinstance(item, dict)
    }
    images.discard("")
    if len(images) == 1:
        value = next(iter(images))
        return (
            f"all {len(samples)} product samples share primary image "
            f"{value[:160]!r}"
        )
    return None


_VISUAL_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _visual_evidence_status(workspace_root: Path) -> dict[str, Any]:
    """Inspect the build's visual evidence without failing the build.

    Visual evidence is a soft requirement in the current pilot.  The host only
    reports missing or unreadable files so the operator can see the gap; the
    agent's ``PASSED`` result is not rewritten into a visual review.
    """

    root = Path(workspace_root) / "out" / "evidence" / "visual"
    missing: list[str] = []
    screenshot = ""
    product_image = ""
    review_status = ""
    baseline = root / "baseline.json"
    compare = root / "compare.md"
    if not baseline.is_file():
        missing.append("baseline.json")
    if not compare.is_file():
        missing.append("compare.md")
    if baseline.is_file():
        try:
            payload = json.loads(baseline.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            missing.append("baseline.json (unreadable)")
            payload = {}
        if isinstance(payload, dict):
            capture = payload.get("capture")
            capture = capture if isinstance(capture, dict) else {}
            screenshot = str(capture.get("screenshot") or "").strip()
            product_image = str(capture.get("product_image") or "").strip()
            review = payload.get("review")
            review = review if isinstance(review, dict) else {}
            review_status = str(review.get("status") or "").strip()
    for label, value in (
        ("capture.screenshot", screenshot),
        ("capture.product_image", product_image),
    ):
        if not value:
            missing.append(f"{label} (missing field)")
            continue
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            missing.append(f"{label} (must be relative)")
            continue
        path = root / candidate
        if not path.is_file():
            missing.append(f"{label} ({value})")
            continue
        if path.suffix.casefold() not in _VISUAL_IMAGE_SUFFIXES:
            missing.append(f"{label} (unsupported image type)")
    if not screenshot and not product_image:
        images = [
            path
            for path in root.glob("*")
            if path.is_file() and path.suffix.casefold() in _VISUAL_IMAGE_SUFFIXES
        ]
        if not images:
            missing.append("screenshot/image file")
    return {
        "status": "complete" if not missing else "missing",
        "root": str(root),
        "missing": missing,
        "screenshot": screenshot,
        "product_image": product_image,
        "review_status": review_status,
    }


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
            value = str(data.get("delta") or "")
            if value:
                current = "".join(reasoning_buffer)
                # Some harnesses emit both delta chunks and a final full-text
                # reasoning event.  Keep the longer text instead of appending
                # the same thought twice.
                if value == current or current.startswith(value):
                    continue
                if current and value.startswith(current):
                    reasoning_buffer[:] = [value]
                else:
                    append_bounded(reasoning_buffer, value)
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



def _stable_rule_payload(payload: Any) -> Any:
    """Return rule content without volatile install timestamps.

    A revalidation of the same build may recompute ``updated_at`` and the host
    validation timestamp.  Those fields must not make an already installed
    version look like different content.
    """
    if not isinstance(payload, dict):
        return payload
    stable = copy.deepcopy(payload)
    stable.pop("updated_at", None)
    evidence = stable.get("evidence")
    if isinstance(evidence, dict):
        # Host-validation counts and timestamps are build evidence, not rule
        # behavior; revalidation may legitimately recompute them.
        evidence.pop("host_validation", None)
    return stable


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
        browser_validation_seconds: int | None = None,
        max_total_seconds: int | None = None,
        max_input_tokens: int | None = None,
        max_output_tokens: int | None = None,
        max_products: int | None = None,
        event_timeout: float | None = None,
        default_proxy: str | None = None,
        capture_reasoning: bool | None = None,
        persist_reasoning: bool | None = None,
        robots_probe: Callable[[str, str | None], tuple[str, list[str]]] | None = None,
        max_repair_rounds: int | None = None,
        repair_seconds: int | None = None,
        activation_mode: str | None = None,
        archive_mode: str | None = None,
        archive_root: str | Path | None = None,
        archive_sample_limit: int | None = None,
        skills_dir: str | Path | None = None,
        extra_permissions: list[dict[str, Any]] | None = None,
        dependency_policy: DependencyPolicy | None = None,
        isolate_env: bool | None = None,
        read_only: bool = False,
    ) -> None:
        self.store = store
        self.out_root = Path(out_root)
        self.read_only = read_only
        self.rules_dir = Path(rules_dir)
        self.workspace_root = self.out_root / "builds"
        self.skills_dir = Path(skills_dir) if skills_dir is not None else None
        self.extra_permissions = normalize_permission_rules(extra_permissions)
        self.dependency_policy = dependency_policy or dependency_policy_from_env()
        self.isolate_env = (
            isolate_env
            if isolate_env is not None
            else os.environ.get("ECOM_BUILD_ISOLATE_ENV") == "1"
        )
        self.model = model if model is not None else default_model()
        self._env_model_pool = os.environ.get("ECOM_BUILD_MODEL_POOL", "").strip()
        stored_pool = self.store.get_setting(MODEL_POOL_SETTING)
        stored_default = self.store.get_setting(MODEL_DEFAULT_SETTING)
        using_stored_pool = stored_pool is not None
        self._model_pool_override = stored_pool is not None
        raw_pool = stored_pool if stored_pool is not None else self._env_model_pool
        self._model_pool_source = (
            "settings"
            if stored_pool is not None
            else ("env" if self._env_model_pool else "none")
        )
        try:
            self.model_pool = BuildModelPool(
                raw_pool, inherit_env=not self.isolate_env,
            )
        except ModelPoolError as exc:
            if stored_pool is None:
                raise
            logger.warning(
                "stored model pool is invalid; falling back to environment: %s", exc
            )
            using_stored_pool = False
            self._model_pool_source = (
                "env" if self._env_model_pool else "none"
            )
            self.model_pool = BuildModelPool(
                self._env_model_pool, inherit_env=not self.isolate_env,
            )
        if using_stored_pool and stored_default:
            try:
                self.model_pool.set_default(stored_default)
            except ModelPoolError as exc:
                logger.warning(
                    "stored default model is invalid; using rotation: %s", exc
                )
        self.default_proxy = (
            default_proxy
            or os.environ.get("ECOM_BUILD_PROXY")
            or os.environ.get("ECOM_FETCH_PROXY")
            or None
        )
        dev_trace = _env_flag("ECOM_BUILD_DEV_TRACE")
        self.reasoning_capture_enabled = (
            capture_reasoning
            if capture_reasoning is not None
            else _env_flag("ECOM_BUILD_CAPTURE_REASONING", dev_trace)
        )
        # Live reasoning is useful for the build timeline; persisting it into
        # trace.json is a separate, explicit decision because the trace is kept
        # as local evidence and may contain page or prompt content.  The
        # development switch turns both on by default; an explicit per-switch
        # environment value still wins.
        self.persist_reasoning_enabled = (
            persist_reasoning
            if persist_reasoning is not None
            else _env_flag("ECOM_BUILD_PERSIST_REASONING", dev_trace)
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
        self.activation_mode = (
            activation_mode
            or os.environ.get("ECOM_RULE_ACTIVATION_MODE")
            or "manual"
        ).strip().lower()
        if self.activation_mode not in {"legacy", "manual"}:
            raise BuildError(
                f"unsupported rule activation mode: {self.activation_mode}"
            )
        self._repair_limits: dict[str, int] = {}
        self._repairs: dict[str, list[dict[str, Any]]] = {}
        self._repair_pending: set[str] = set()
        # Builds whose agent run finished before the host crashed.  Recovered
        # validation must not silently start a new paid repair turn.
        self._recovered_finalize: set[str] = set()
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
        self.browser_validation_seconds = max(
            self.validation_seconds,
            int(
                browser_validation_seconds
                if browser_validation_seconds is not None
                else os.environ.get("ECOM_BUILD_BROWSER_VALIDATION_SECONDS", "600")
            ),
        )
        # Optional whole-build guards.  They include the initial model turn,
        # automatic repair and host validation, unlike ``max_seconds`` which
        # only bounds the first turn.  Unset means unlimited and preserves the
        # behavior of older deployments and tests.
        self.max_total_seconds = _budget_value(
            max_total_seconds, "ECOM_BUILD_MAX_TOTAL_SECONDS"
        )
        self.max_input_tokens = _budget_value(
            max_input_tokens, "ECOM_BUILD_MAX_INPUT_TOKENS"
        )
        self.max_output_tokens = _budget_value(
            max_output_tokens, "ECOM_BUILD_MAX_OUTPUT_TOKENS"
        )
        self.usage_poll_seconds = 2.0
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
                dependency_policy=self.dependency_policy,
                event_timeout=event_timeout,
                capture_reasoning=self.reasoning_capture_enabled,
                server=(
                    OpenCodeServer(
                        cwd=self.workspace_root,
                        inherit_env=False,
                    )
                    if self.isolate_env
                    else None
                ),
            )
        self.adapter = adapter
        self.service = BuildService(adapter)
        self._lock = threading.RLock()
        self._watchers: dict[str, threading.Thread] = {}
        self._finalizing: set[str] = set()
        self._slot_build_id: str | None = None
        self._dispatching: str | None = None
        self._handled_permissions: dict[str, set[str]] = {}
        self._stopping = threading.Event()

    @property
    def model_pool_source(self) -> str:
        return self._model_pool_source

    @property
    def model_pool_override(self) -> bool:
        return self._model_pool_override

    def update_model_pool(
        self, refs: list[str], default_ref: str | None = None,
    ) -> None:
        if self.read_only:
            raise BuildError("build manager is read-only")
        candidate = BuildModelPool(
            ",".join(refs), inherit_env=not self.isolate_env
        )
        candidate.set_default(default_ref)
        candidate.restore_health(self.model_pool.snapshot_health())
        raw = ",".join(candidate.refs())
        with self._lock:
            self.store.set_setting(MODEL_POOL_SETTING, raw)
            if candidate.default_ref:
                self.store.set_setting(MODEL_DEFAULT_SETTING, candidate.default_ref)
            else:
                self.store.delete_setting(MODEL_DEFAULT_SETTING)
            self.model_pool = candidate
            self._model_pool_source = "settings"
            self._model_pool_override = True

    def reset_model_pool(self) -> None:
        if self.read_only:
            raise BuildError("build manager is read-only")
        candidate = BuildModelPool(
            self._env_model_pool, inherit_env=not self.isolate_env
        )
        candidate.restore_health(self.model_pool.snapshot_health())
        with self._lock:
            self.store.delete_setting(MODEL_POOL_SETTING)
            self.store.delete_setting(MODEL_DEFAULT_SETTING)
            self.model_pool = candidate
            self._model_pool_source = "env" if self._env_model_pool else "none"
            self._model_pool_override = False

    # ------------------------------------------------------------------ start
    def _ensure_site_rule(self, site: BatchSite) -> SiteRule | None:
        """Seed the v2 site pointer from a legacy batch-site rule once."""
        current = self.store.get_site_rule(site.site_key)
        if current is not None:
            return current
        if not site.rule_id or not site.rule_version or not site.rule_path:
            return None
        path = self.rules_dir / site.rule_path
        if not path.is_file():
            return None
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.store.create_rule_version(
            RuleVersion(
                rule_id=site.rule_id,
                rule_version=site.rule_version,
                sha256=digest,
                path=site.rule_path,
                status="active",
                created_at=site.updated_at,
                activated_at=site.updated_at,
                activated_by="legacy-migration",
            )
        )
        return self.store.upsert_site_rule(
            SiteRule(
                site_key=site.site_key,
                rule_id=site.rule_id,
                rule_version=site.rule_version,
                sha256=digest,
                path=site.rule_path,
                updated_at=site.updated_at,
            )
        )

    def ensure_site_rule(self, site_key: str) -> SiteRule | None:
        current = self.store.get_site_rule(site_key)
        if current is not None or self.read_only:
            return current
        site = self.store.latest_batch_site_rule(site_key)
        if site is None:
            return None
        return self._ensure_site_rule(site)

    def start(
        self,
        batch: Batch,
        site: BatchSite,
        *,
        max_products: int | None = None,
        max_seconds: int | None = None,
        max_total_seconds: int | None = None,
        max_input_tokens: int | None = None,
        max_output_tokens: int | None = None,
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
        feedback_id: str | None = None,
        request_id: str | None = None,
        model_ref: str | None = None,
        auto_collect: bool = False,
    ) -> BuildRecord:
        if self.read_only:
            raise BuildError("build manager is read-only")
        if site.readiness in {"invalid", "duplicate"}:
            raise BuildError("invalid or duplicate sites cannot be built")
        if not repair and site.task_id:
            raise BuildError("site already has a task")
        if repair:
            if site.readiness != "ready" or not site.rule_path:
                raise BuildError("only a ready site with an installed rule can be repaired")
            if not (self.rules_dir / site.rule_path).is_file():
                raise BuildError(f"installed rule file not found: {site.rule_path}")
            if site.task_id:
                current = self.store.get_task(site.task_id)
                if current is not None and current.state in ACTIVE_TASK_STATES:
                    raise BuildError(
                        "site has an active task; pause, cancel or wait before repairing "
                        f"the rule: {current.task_id} ({current.state})"
                    )
        if not self.rules_dir.is_dir():
            raise BuildError("rules directory is not configured")
        self._ensure_site_rule(site)
        source_rule_sha256 = None
        if repair and site.rule_path:
            source_rule_path = self.rules_dir / site.rule_path
            if source_rule_path.is_file():
                source_rule_sha256 = hashlib.sha256(
                    source_rule_path.read_bytes()
                ).hexdigest()
        entry_url = _entry_url(site)
        product_budget = max(1, int(max_products or self.max_products))
        # Per-build budgets must be honored exactly; the web API already
        # enforces its own minimum, while tests and internal callers may need
        # a short budget to verify the deadline behavior.
        second_budget = max(1, int(max_seconds or self.max_seconds))
        total_budget = (
            self.max_total_seconds
            if max_total_seconds is None
            else max(1, int(max_total_seconds))
        )
        input_budget = (
            self.max_input_tokens
            if max_input_tokens is None
            else max(1, int(max_input_tokens))
        )
        output_budget = (
            self.max_output_tokens
            if max_output_tokens is None
            else max(1, int(max_output_tokens))
        )
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
            latest = self.store.latest_build_for_site(batch.batch_id, site.site_key)
            if latest is not None and latest.state in ACTIVE_BUILD_STATES:
                raise BuildError(f"site already has an active build: {latest.build_id}")

            selected_model = self.model
            selection = "default"
            try:
                if model_ref is not None:
                    selected_model = self.model_pool.manual(model_ref)
                    selection = "manual"
                elif self.model_pool.models:
                    if self.model_pool.default_ref:
                        selected_model = self.model_pool.manual(
                            self.model_pool.default_ref
                        )
                        selection = "pinned"
                    else:
                        selected_model = self.model_pool.balanced(
                            self.store.last_balanced_build_model()
                        )
                        selection = "balanced"
            except ModelPoolError as exc:
                raise BuildError(str(exc)) from exc

            build_id = f"build-{uuid.uuid4().hex[:12]}"
            trace_reasoning = (
                self.reasoning_capture_enabled
                if capture_reasoning is None
                else bool(capture_reasoning) and self.reasoning_capture_enabled
            )
            self._trace_reasoning[build_id] = trace_reasoning
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
            resolved_catalog_scope = str(catalog_scope or "sample").strip().lower()
            if resolved_catalog_scope not in {"sample", "target", "full"}:
                resolved_catalog_scope = "sample"
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
                        else os.environ.get(
                            "ECOM_BUILD_CATALOG_PRODUCTS",
                            str(
                                product_budget
                                if resolved_catalog_scope == "target"
                                else 2000
                            ),
                        )
                    ),
                ),
            }
            request = {
                "max_products": product_budget,
                "max_seconds": second_budget,
                "max_total_seconds": total_budget,
                "max_input_tokens": input_budget,
                "max_output_tokens": output_budget,
                "repair_rounds": requested_repairs,
                "capture_reasoning": bool(trace_reasoning),
                "repair_reason": repair_reason or "",
                "previous_readiness": site.readiness,
                "robots_note": robots_note,
                "robots_sitemaps": robots_sitemaps,
                "archive": dict(self._archive_configs[build_id]),
                "catalog": dict(self._catalog_configs[build_id]),
                "model_selection": selection,
                "auto_collect": auto_collect,
            }
            record = BuildRecord(
                build_id=build_id,
                batch_id=batch.batch_id,
                site_key=site.site_key,
                state="QUEUED",
                model=selected_model,
                proxy=resolved_proxy,
                workspace=str(self.workspace_root / build_id),
                mode="repair" if repair else "build",
                feedback_id=feedback_id,
                request_id=request_id,
                request=request,
                source_rule_version=site.rule_version if repair else None,
                source_rule_sha256=source_rule_sha256,
            )
            self.store.create_build(record)
            self.store.update_batch_site(
                batch.batch_id,
                site.site_key,
                readiness="building",
                build_id=build_id,
                proxy=resolved_proxy,
                note=(
                    f"规则修复排队中：{build_id}"
                    if repair
                    else f"构建排队中：{build_id}"
                ),
            )
        self._drain_queue()
        return self.store.get_build(build_id) or record

    def repair(
        self,
        batch: Batch,
        site: BatchSite,
        *,
        reason: str | None = None,
        max_products: int | None = None,
        max_seconds: int | None = None,
        max_total_seconds: int | None = None,
        max_input_tokens: int | None = None,
        max_output_tokens: int | None = None,
        proxy: str | None = None,
        capture_reasoning: bool | None = None,
        repair_rounds: int | None = None,
        archive_mode: str | None = None,
        archive_root: str | Path | None = None,
        archive_sample_limit: int | None = None,
        archive_max_bytes: int | None = None,
        feedback_id: str | None = None,
        request_id: str | None = None,
        model_ref: str | None = None,
    ) -> BuildRecord:
        """Revalidate and repair an installed rule without clearing task data."""
        return self.start(
            batch,
            site,
            max_products=max_products,
            max_seconds=max_seconds,
            max_total_seconds=max_total_seconds,
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
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
            feedback_id=feedback_id,
            request_id=request_id,
            model_ref=model_ref,
        )

    # ----------------------------------------------------------------- queue
    def _next_queued(self) -> BuildRecord | None:
        queued = self.store.list_builds(
            states={"QUEUED"}, limit=500, oldest_first=True
        )
        return queued[0] if queued else None

    def _hydrate_request(self, record: BuildRecord) -> dict[str, Any]:
        request = dict(record.request or {})
        self._trace_reasoning[record.build_id] = bool(
            request.get("capture_reasoning") and self.reasoning_capture_enabled
        )
        self._repair_limits[record.build_id] = int(request.get("repair_rounds") or 0)
        self._repairs.setdefault(record.build_id, [])
        archive = request.get("archive")
        if isinstance(archive, dict):
            self._archive_configs[record.build_id] = dict(archive)
        catalog = request.get("catalog")
        if isinstance(catalog, dict):
            self._catalog_configs[record.build_id] = dict(catalog)
        return request

    def _queue_precondition_error(
        self, record: BuildRecord, site: BatchSite
    ) -> str | None:
        if site.build_id and site.build_id != record.build_id:
            return f"站点已关联其他构建：{site.build_id}"
        if record.mode == "repair":
            if site.readiness not in {"building", "ready"} or not site.rule_path:
                return "站点已不再满足规则修复条件"
            if not (self.rules_dir / site.rule_path).is_file():
                return f"已安装规则文件不存在：{site.rule_path}"
            if record.source_rule_sha256:
                current_sha256 = hashlib.sha256(
                    (self.rules_dir / site.rule_path).read_bytes()
                ).hexdigest()
                if current_sha256 != record.source_rule_sha256:
                    return "源规则文件在排队期间发生变化；请重新发起修复"
            if site.task_id:
                current = self.store.get_task(site.task_id)
                if current is not None and current.state in ACTIVE_TASK_STATES:
                    return (
                        "site has an active task; pause, cancel or wait before "
                        f"repairing the rule: {current.task_id} ({current.state})"
                    )
        else:
            if site.readiness in {"invalid", "duplicate"}:
                return "无效或重复站点不能构建"
            if site.task_id:
                return f"站点已有任务：{site.task_id}"
        return None

    def _build_task(
        self,
        record: BuildRecord,
        batch: Batch,
        site: BatchSite,
        request: dict[str, Any],
    ) -> BuildTask:
        entry_url = _entry_url(site)
        workspace_path = self.workspace_root / record.build_id
        skill_roots = self._skill_roots()
        skill_manifest = self._skill_manifest(skill_roots)
        product_budget = max(
            1, int(request.get("max_products") or self.max_products)
        )
        second_budget = max(
            1, int(request.get("max_seconds") or self.max_seconds)
        )
        archive = dict(request.get("archive") or {})
        catalog = dict(request.get("catalog") or {})
        permissions = default_permissions(
            workspace_path,
            skill_roots=[str(root) for root in skill_roots],
        )
        permissions.extend(self.extra_permissions)
        return BuildTask(
            build_id=record.build_id,
            site={
                "name": site.site_key,
                "entry_urls": [entry_url],
                "allowed_origins": [_origin(entry_url)],
                "allowed_path_prefixes": ["/"],
                "market": batch.market or "UNKNOWN",
                "locale": batch.language or "en-US",
                "currency": MARKET_CURRENCY.get((batch.market or "").upper(), ""),
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
            model=record.model or self.model,
            workspace=str(workspace_path),
            output_dir=str(workspace_path / "out" / "plan"),
            notes=(
                "Build a declarative product rule from the batch site entry "
                "and install it only after host validation."
            ),
            extra={
                **({"proxy": record.proxy} if record.proxy else {}),
                "permissions": permissions,
                "skills": skill_manifest,
                "robots_note": str(request.get("robots_note") or ""),
                "robots_sitemaps": list(request.get("robots_sitemaps") or []),
                **catalog,
                **archive,
            },
        )

    def _launch_queued(self, build_id: str) -> bool:
        record = self.store.get_build(build_id)
        if record is None or record.state != "QUEUED":
            return False
        batch = self.store.get_batch(record.batch_id)
        site = self.store.get_batch_site(record.batch_id, record.site_key)
        if batch is None or site is None:
            message = "队列中的构建找不到批次或站点"
            self._release_site(record.batch_id, record.site_key, build_id, message)
            self._record_failure(build_id, message)
            return False
        request = self._hydrate_request(record)
        precondition = self._queue_precondition_error(record, site)
        if precondition:
            self._release_site(
                record.batch_id,
                record.site_key,
                build_id,
                f"构建启动失败：{precondition}",
            )
            self._record_failure(build_id, precondition)
            return False
        session: BuildSession | None = None
        try:
            task = self._build_task(record, batch, site, request)
            session = self.service.start_build(task)
            self._write_inputs(session, batch, site, task)
            if record.mode == "repair":
                self._write_repair_inputs(
                    session,
                    batch,
                    site,
                    task,
                    str(request.get("repair_reason") or ""),
                    previous_readiness=str(request.get("previous_readiness") or ""),
                )
            self.store.update_build(
                build_id,
                workspace=str(session.workspace.root),
                session_id=session.session_id,
                state=session.state,
                started_at=utc_now(),
            )
            self.store.update_batch_site(
                record.batch_id,
                record.site_key,
                readiness="building",
                build_id=build_id,
                note=(
                    f"规则修复中：{build_id}"
                    if record.mode == "repair"
                    else f"构建中：{build_id}"
                ),
            )
            prompt = (
                self._repair_run_prompt(site, task)
                if record.mode == "repair"
                else self._prompt(site, batch, task)
            )
            self.service.send_prompt(build_id, prompt)
            self.store.update_build(build_id, state="RUNNING")
            self._start_watcher(build_id)
            return True
        except Exception as exc:  # noqa: BLE001 - queued start boundary
            message = f"{type(exc).__name__}: {exc}"
            logger.warning("queued build %s failed to start: %s", build_id, message)
            self._release_site(
                record.batch_id,
                record.site_key,
                build_id,
                f"构建启动失败：{message}",
            )
            self._record_failure(build_id, message)
            if session is not None:
                try:
                    self.service.close(build_id)
                except Exception:
                    logger.debug(
                        "queued build start cleanup failed", exc_info=True
                    )
            return False

    def _drain_queue(self) -> None:
        """Start the oldest queued build when the single slot is free."""
        if self.read_only:
            return
        if os.environ.get("ECOM_BUILD_DISABLED") == "1":
            return
        while not self._stopping.is_set():
            with self._lock:
                if self._dispatching is not None:
                    return
                if self._slot_build_id is not None:
                    return
                if self.service.active_build_id is not None:
                    return
                record = self._next_queued()
                if record is None:
                    return
                self._dispatching = record.build_id
                self._slot_build_id = record.build_id
            launched = False
            try:
                launched = self._launch_queued(record.build_id)
            except Exception as exc:
                logger.exception("queue dispatch failed for %s", record.build_id)
                self._release_site(
                    record.batch_id,
                    record.site_key,
                    record.build_id,
                    "构建启动失败：队列调度异常",
                )
                self._record_failure(
                    record.build_id,
                    f"队列调度失败：{type(exc).__name__}: {exc}",
                )
            finally:
                with self._lock:
                    self._dispatching = None
                    if not launched and self._slot_build_id == record.build_id:
                        self._slot_build_id = None
            if launched:
                with self._lock:
                    if self._slot_build_id is not None:
                        return
                if self._stopping.is_set():
                    return
                # The launched build finished before the dispatch returned;
                # continue with the next queued item instead of waiting for
                # another API call or watcher to nudge the queue.
                continue

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
        *,
        previous_readiness: str | None = None,
    ) -> None:
        existing = self.rules_dir / str(site.rule_path)
        input_dir = session.workspace.input_dir
        input_rule = input_dir / "existing-rule.yaml"
        shutil.copyfile(existing, input_rule)
        plan_dir = session.workspace.out_dir / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(existing, plan_dir / "rule.yaml")
        runtime_task = self._runtime_task_evidence(site)
        existing_versions = self._existing_rule_versions(site.rule_id)
        context = {
            "previous_readiness": previous_readiness or site.readiness,
            "previous_rule_id": site.rule_id,
            "previous_rule_version": site.rule_version,
            "previous_rule_path": site.rule_path,
            "existing_rule_versions": existing_versions,
            "reason": reason,
            "runtime_task": runtime_task,
        }
        (input_dir / "repair-context.json").write_text(
            json.dumps(context, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (input_dir / "repair-brief.md").write_text(
            self._repair_brief(
                batch,
                site,
                task,
                reason,
                runtime_task,
                existing_versions=existing_versions,
            ),
            encoding="utf-8",
        )
        (session.workspace.work_dir / "AGENTS.md").write_text(
            self._agent_rules(),
            encoding="utf-8",
        )

    def _existing_rule_versions(self, rule_id: str | None) -> list[str]:
        """Return managed versions so the repair agent can avoid collisions."""
        if not rule_id:
            return []
        versions: set[str] = set()
        prefix = f"{_safe_filename(rule_id)}-"
        if self.rules_dir.is_dir():
            for path in self.rules_dir.glob(f"{prefix}*.yaml"):
                if path.stem.startswith(prefix):
                    versions.add(path.stem[len(prefix) :])
        try:
            items, _ = self.store.list_rule_versions(rule_id, limit=500)
        except Exception:  # evidence is best effort
            logger.debug("rule version list failed", exc_info=True)
        else:
            versions.update(item.rule_version for item in items)
        return sorted(versions, reverse=True)

    def _runtime_task_evidence(self, site: BatchSite) -> dict[str, Any]:
        """Summarize the site's current run so repair starts from real gaps."""
        if not site.task_id:
            return {}
        task = self.store.get_task(site.task_id)
        if task is None:
            return {}
        result: dict[str, Any] = {}
        result_path = self.out_root / task.task_id / "task-result.json"
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                result = payload
        except (OSError, json.JSONDecodeError):
            pass
        counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
        coverage = (
            result.get("coverage") if isinstance(result.get("coverage"), dict) else {}
        )
        audit = (
            result.get("content_audit")
            if isinstance(result.get("content_audit"), dict)
            else {}
        )
        quality = (
            result.get("quality_exceptions")
            if isinstance(result.get("quality_exceptions"), list)
            else []
        )
        sample_urls: list[str] = []
        for item in quality[:10]:
            if isinstance(item, dict) and item.get("source_url"):
                sample_urls.append(str(item["source_url"]))
        for item in result.get("failure_samples") or []:
            if isinstance(item, dict) and item.get("url"):
                sample_urls.append(str(item["url"]))
        sample_urls = list(dict.fromkeys(sample_urls))[:8]
        return {
            "task_id": task.task_id,
            "state": task.state,
            "outcome": task.outcome,
            "stop_reason": task.stop_reason,
            "counts": counts,
            "coverage": coverage,
            "content_audit": {
                "products_checked": audit.get("products_checked"),
                "description_gaps": audit.get("description_gaps"),
            },
            "quality_exceptions": quality[:10],
            "quality_exception_count": len(quality),
            "sample_urls": sample_urls,
        }

    def _repair_brief(
        self,
        batch: Batch,
        site: BatchSite,
        task: BuildTask,
        reason: str,
        runtime_task: dict[str, Any] | None = None,
        *,
        existing_versions: list[str] | None = None,
    ) -> str:
        try:
            payload = yaml.safe_load(
                (self.rules_dir / str(site.rule_path)).read_text(encoding="utf-8")
            )
        except (OSError, yaml.YAMLError):
            payload = {}
        evidence = payload.get("evidence") if isinstance(payload, dict) else {}
        rule_samples = evidence.get("sample_urls") if isinstance(evidence, dict) else []
        runtime = runtime_task or {}
        runtime_samples = runtime.get("sample_urls") if isinstance(runtime, dict) else []
        sample_urls = list(
            dict.fromkeys(
                [
                    *(str(url) for url in (runtime_samples or [])),
                    *(str(url) for url in (rule_samples or [])),
                ]
            )
        )[:8]
        sample_lines = "\n".join(f"- {url}" for url in sample_urls)
        reason_text = reason.strip() or "Host content audit found description or field gaps."
        runtime_lines = _runtime_task_lines(runtime)
        version_text = (
            ", ".join(f"`{version}`" for version in existing_versions or [])
            or "none recorded"
        )
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
- Existing managed versions: {version_text}
- Host validation sample: `{task.limits.get("max_products")}` products
- Repair reason: {reason_text}

## Current task evidence

{runtime_lines}

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
- Bump `rule_version` to a new unique value that is not in the existing managed
  versions list; the host rejects a collision.
- Write `../out/evidence/build-notes.md` with what changed and the sample URLs
  you checked.

## Known sample URLs

{sample_lines or "- No sample URLs recorded in the previous run or rule."}

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
- Host skills are available read-only. Before planning discovery, load
  `product-crawl-workflow`; before any challenge probe, load
  `resilient-browser-fetch`. Do not skip these two because the brief is short.
  Read their references or scripts as needed, but do not write into the skills
  directories. Other installed skills (`browser-automation`, `network-access`,
  `htmlmini`, `scrapling-official`, ...) are available when relevant.
- In `../out/evidence/build-notes.md`, state which skills you loaded and which
  discovery, field and challenge rules you applied.
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

## Visual evidence

- Before you finish the rule, pick one representative product page. Capture a
  viewport screenshot that shows the product name, current price, currency and
  main image. Save one product image locally; prefer the original image bytes,
  and use the same browser or stealth session that passed any challenge. If the
  image request is blocked, capture the rendered image element and record
  `capture_method: rendered`.
- Write `../out/evidence/visual/baseline.json` and
  `../out/evidence/visual/compare.md`. The baseline must include product URL,
  screenshot path, image path and source URL, capture method, viewport,
  expected name, price, currency, image URL and description fragment, and
  review status.
- If a screenshot tool only writes inside its own file root, save there and
  copy the file into `../out/evidence/visual/` with the shell; do not leave
  evidence only in a temporary directory.
- If the model cannot inspect images, set `review.status` to `pending_manual`;
  never write that visual review passed.
- Visual evidence is a soft requirement in this pilot. If it is genuinely
  unavailable, record the attempted URL, blocker and missing files in
  `build-notes.md`; do not silently omit it.

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
        elif catalog_scope == "target":
            catalog_lines = (
                f"- Catalog scope: **bounded target** (at least {catalog_products} products)\n"
                f"- Host validation sample: {task.limits.get('max_products')} products\n"
                "- The rule's `scope.max_products` and discovery sources must cover at "
                "least the target; the host validates only a sample.\n"
            )
            discovery_instruction = (
                "This build targets a **bounded catalog** of at least "
                f"{catalog_products} products, not just the entry-page sample. Use the "
                "entry page first. If it exposes fewer product links than the target, "
                "inspect one category or sitemap and use `listing`, `html_index` or "
                "`sitemap` so discovery can cover the target. On Shopify, "
                "`product_source: shopify_json` can cover the target from "
                "`/products.json`. Do not crawl the whole site. Set "
                "`scope.max_products` to at least the target and put 3+ representative "
                "product URLs in `evidence.sample_urls`.\n"
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
        catalog_lines += (
            f"- Host validation budget: {task.limits.get('max_products')} products, "
            f"{self.validation_seconds}s; browser rules get at least "
            f"{self.browser_validation_seconds}s.\n"
        )
        shopify_instruction = (
            "For Shopify storefronts, prefer public JSON (`/products.json`) for "
            "name, price, currency, variants and description before parsing HTML. "
            "Declare a `product_source` section and keep `discovery` as the HTML "
            "fallback. The runtime seeds product work items from `/products.json`, "
            "commits complete descriptions directly, and fetches HTML/browser only "
            "for descriptions shorter than `description.min_chars` or when the JSON "
            "endpoint is blocked. Keep fallback concurrency at 1–2. Availability is "
            "optional; price and currency must match and the currency must remain "
            "the batch currency. Per-product `.js`/`.json` extraction is not "
            "implemented yet; do not claim it in the rule.\n"
        )
        stealth_instruction = (
            "If static and Patchright samples both hit a Cloudflare-style challenge, "
            "probe one product page with the `resilient-browser-fetch` skill and the "
            f"host runtime Python `{sys.executable}`:\n\n"
            "```text\n"
            f'"{sys.executable}" "<resilient-browser-fetch>/scripts/resilient_fetch.py" '
            "--url <product-url> --engine scrapling "
            "--profile-dir work/stealth-profile --timeout-ms 300000 "
            "--challenge-wait-ms 180000 --out ../out/evidence/stealth-sample.html "
            "--expect-text <product-title-or-price>\n"
            "```\n\n"
            "Replace `<resilient-browser-fetch>` with the installed skill directory. "
            "Pass the same proxy and reuse `work/stealth-profile` for the next "
            "sample. If the sitemap is an index, select product children with "
            "`sitemap_patterns` (for example `/sitemaps/products/`) and raise "
            "`max_sitemaps` enough to cover them; the host handles `.xml.gz`. If the "
            "stealth sample returns the real product title and price, "
            "set `fetch.default_engine: stealth`, `fetch.timeout_ms: 240000`, "
            "`fetch.browser.challenge_wait_ms: 180000` and a stable "
            "`fetch.browser.wait_selector`. The host validation uses the same stealth "
            "engine and gets at least 600 seconds. If the stealth sample still shows "
            "a challenge, record `ACCESS` and stop; do not declare a browser rule "
            "from a challenge page.\n\n"
            "Keep the entry page or a listing source first in `discovery.sources`; "
            "put a sitemap after it. A sitemap-only source makes the first request "
            "a document and pays the full challenge cold start on it, which can "
            "exhaust the host validation budget. Example:\n\n"
            "```yaml\n"
            "discovery:\n"
            "  strategies: [\"entry_links\"]\n"
            "  sources:\n"
            "    - type: listing\n"
            "      url: <entry-url>\n"
            "      product_link_selector: 'a[href*=\"/product/\"]'\n"
            "    - type: sitemap\n"
            "      urls: [<product-sitemap-url>]\n"
            "      max_sitemaps: 3\n"
            "```\n"
        )
        robots_note = str(task.extra.get("robots_note") or "robots.txt not probed")
        expected_currency = MARKET_CURRENCY.get((batch.market or "").upper(), "")
        expected_currency_line = (
            f"- Expected currency for market `{batch.market}`: `{expected_currency}` "
            "(verify on a static product page; the host rejects a mismatch)\n"
            if expected_currency
            else "- Expected currency: determine it from the site's static product page.\n"
        )
        robots_sitemaps = [
            str(url) for url in (task.extra.get("robots_sitemaps") or [])
        ][:20]
        robots_lines = (
            "\n".join(f"- {url}" for url in robots_sitemaps)
            or "- No Sitemap lines found."
        )
        product_source_currency = expected_currency or "EUR"
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
{expected_currency_line}- Stock／availability is not a required business field for this build;
  do not spend budget verifying it or reject a product only because it is out
  of stock. Price and currency must match; minor price differences between
  requests are acceptable.
{catalog_lines}{proxy_line}
Budget checkpoint: write a minimal valid rule by about 50% of the wall-clock
budget, stop discovery by about 70%, and leave the remainder for host
validation and repair. Do not wait until the budget is exhausted to write the
first rule.
{discovery_instruction}{shopify_instruction}{stealth_instruction}
## Required output

Write these files from the workspace (`work/` is your current directory):

- `../out/plan/rule.yaml` — the complete rule manifest.
- `../out/evidence/build-notes.md` — what you inspected, sample URLs, selectors,
  limitations and anything you could not verify.
- `../out/evidence/visual/` — at least one product page screenshot, one local
  product image, `baseline.json` and `compare.md`.

Visual evidence:

- Screenshot one representative product page with the name, current price,
  currency and main image visible. Save one product image locally; prefer the
  original bytes from the same browser or stealth session that passed any
  challenge. If the image request is blocked, save a rendered image-element
  screenshot and mark `capture_method: rendered`.
- `baseline.json` records product URL, screenshot path, image path and source
  URL, capture method, viewport, expected name, price, currency, image URL and
  description fragment, and `review.status`.
- `compare.md` compares the planned or sampled product fields with the visual
  baseline. Check name, price, currency, image, description and URL; call out
  all-same names or images, placeholders, review-widget images and material
  price or currency mismatches.
- If you cannot inspect images, set `review.status` to `pending_manual`; do not
  claim visual review passed.
- This pilot treats visual evidence as a soft requirement. If it is genuinely
  unavailable, record the attempted URL, blocker and missing files in
  `build-notes.md`; do not silently omit it.

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

If two responses from the same client are a challenge page (for example titles
such as "Verify your browser" or "Verifying your connection"), stop retrying
that path. Switch to a browser or stealth sample only when the final rule will
use that engine and the host can validate it; otherwise stop and record `ACCESS`
in `../out/evidence/build-notes.md`. Do not spend the remaining wall-clock
budget on repeated challenge retries.

Keep one exit for the rest of the build and host validation. If static product
pages return 429 on that exit, you may test at most two alternate same-market
exits or switch to the browser/stealth engine, record the chosen exit, and stop
rotating; do not change exit per request. Minor price differences are
acceptable, but the currency must remain the batch currency.

A generic reference rule is at `../input/reference-rule.yaml`; adapt it, do not
copy its site or selectors blindly.

## Rule contract (schema_version 1.1, 1.2 or 1.3)

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
  `product_url_patterns` and `url_identity: canonical`. `discovery.strategies`
  only accepts `entry_links`; use `discovery.sources` for other source types.
  A `listing` source needs `url` and `product_link_selector`. A sitemap source
  uses `urls` (list), not `strategies`:

  ```yaml
  discovery:
    sources:
      - type: sitemap
        urls:
          - https://www.example.com/sitemap.xml
        max_sitemaps: 3
    product_url_patterns:
      - ^/products/
  ```

- `product_source` (optional, Shopify only, requires `schema_version: "1.3"`):
  prefer this when the store exposes public `/products.json`. Keep `discovery`
  as the fallback; `product_source` does not replace it. Example:

  ```yaml
  product_source:
    type: shopify_json
    url: https://www.example.com/products.json
    product_url_template: https://www.example.com/products/{{handle}}
    page_size: 250
    max_pages: 1
    currency: {product_source_currency}
    description:
      min_chars: 200
      fallback_concurrency: 1
    variants:
      price: min_positive
  ```

  `page_size` is capped at 250. `variants.price` accepts `min_positive`,
  `first` or `product_price`. `description.fallback_concurrency` is 1 or 2.
  `currency` must equal `site.currency`. If `/products.json` returns 401/403,
  429, a challenge or invalid JSON, the runtime records
  `shopify_json_unavailable` and continues with `discovery`; do not invent a
  second JSON endpoint. Product `.js`/`.json` per-product extraction is not
  implemented.
- `fetch`: `default_engine` is `static` unless the page truly needs JavaScript
  or challenge handling. Supported values: `static`, `browser`, `stealth`,
  `http_json`. Use `browser` for JavaScript-rendered pages that are not behind a
  challenge, and `stealth` only when a Cloudflare-style challenge blocks the
  static and browser paths. Keep `concurrency: 1`, `delay_ms` at least `1000`,
  `retry: {{max_attempts: 2, backoff_ms: 1000}}`, `timeout_ms: 45000`, and
  `browser: false` for static pages.

  For a JavaScript page that passes a plain browser sample:

  ```yaml
  default_engine: browser
  browser:
    headless: true
    wait_selector: "h1"
    challenge_wait_ms: 15000
  ```

  For a page where the static and Patchright samples hit a challenge and the
  stealth sample returns the product content:

  ```yaml
  default_engine: stealth
  timeout_ms: 240000
  browser:
    headless: true
    wait_selector: "h1"
    challenge_wait_ms: 180000
  ```

  The host validation uses the same engine. A stealth rule gets at least 600
  seconds. If the stealth sample also hits a challenge, stop and record `ACCESS`
  instead of declaring the rule. Use `schema_version: "1.1"` by default, `"1.2"`
  only for `load_more`/`infinite_scroll`, and `"1.3"` when `product_source` is
  present.
- `extract.fields` must cover `name`, `price.amount`, `price.currency`,
  `primary_image_url`, `source_url`; add `description_html`, `category`,
  `brand`, `options` when available. Every field needs an ordered `fallbacks`
  list with explicit `type` and `label`; put `json_ld` first when the page has
  Product JSON-LD, then CSS/attribute/title fallbacks.
- Supported fallback `type` values: `json_ld`, `css_text`, `css_html`,
  `css_attr`, `compose`, `title`, `breadcrumb`, `option_groups`, `price_pair`,
  `canonical`, `constant`. There is no `url` or `meta` fallback type.
  `source_url` may use `canonical`; when it is absent, the runtime uses the
  page URL.
- Product descriptions are often split across a narrative block and a
  specification list/table. Do not accept a short microdata summary as the
  complete description when the page also shows specs. Use a `compose` fallback
  to merge the real blocks in DOM order, with `exclude_selectors` for promo
  badges or share controls. `compose` uses `parts:` (a list of
  `{{type: css_html, selector: ...}}`); the description audit uses `blocks:`.
  Add `extract.fields.description_html.audit.blocks` for every block used
  (narrative, feature list, specification tab); the host fails validation when
  a present block is not represented in the final `description_html`.
  Declare only blocks you actually extract: if a specification accordion is
  empty or rendered only by JavaScript, do not declare it; a single narrative
  block is valid when that is all the static page provides. Optional fields
  (`category`, `brand`, `options`) may be omitted when the page has no reliable
  static source; do not invent a fallback type or a value for them.
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
        catalog_products = int(
            task.extra.get("catalog_products") or task.limits.get("max_products") or 1
        )
        if catalog == "full":
            scope_note = (
                " This is a full-catalog build: enumerate the top-level product "
                "categories and their pagination, and set scope.max_products to the "
                "catalog target. The host validation uses only a small sample."
            )
        elif catalog == "target":
            scope_note = (
                " This is a bounded-target build: cover at least "
                f"{catalog_products} products and set scope.max_products to the "
                "target. The host validation uses only a small sample."
            )
        else:
            scope_note = ""
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
        record = self.store.get_build(build_id)
        if record is None:
            return
        # The build record carries its own wall-clock budget.  Using the
        # global default here made the per-build limit advisory: a 60-second
        # build would keep the manager's 600-second deadline or vice versa.
        request = record.request or {}
        budget = max(
            1,
            int(request.get("max_seconds") or self.max_seconds),
        )
        deadline = time.monotonic() + budget
        total_budget = _optional_int(request.get("max_total_seconds"))
        total_deadline = (
            time.monotonic() + total_budget if total_budget is not None else None
        )
        input_budget = _optional_int(request.get("max_input_tokens"))
        output_budget = _optional_int(request.get("max_output_tokens"))
        next_usage_check = 0.0
        try:
            while not self._stopping.is_set():
                record = self.store.get_build(build_id)
                if record is None:
                    return
                session = self._session(build_id)
                if session is None:
                    self._finalize(build_id, error="build session is no longer available")
                    return
                now = time.monotonic()
                if total_deadline is not None and now >= total_deadline:
                    self._cancel_for_budget(
                        build_id,
                        "build exceeded the total wall-clock budget "
                        f"({total_budget}s)",
                    )
                    return
                if (input_budget or output_budget) and now >= next_usage_check:
                    next_usage_check = now + max(0.5, float(self.usage_poll_seconds))
                    usage_error = self._token_budget_error(
                        self._usage(build_id), input_budget, output_budget
                    )
                    if usage_error is not None:
                        self._cancel_for_budget(build_id, usage_error)
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
                            error_class="budget",
                        )
                        return
                    self._finalize(
                        build_id,
                        error=f"build exceeded the wall-clock budget ({budget}s)",
                        error_class="budget",
                    )
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
                if self._slot_build_id == build_id:
                    self._slot_build_id = None
            if not self._stopping.is_set():
                self._drain_queue()

    def _usage(self, build_id: str) -> dict[str, Any] | None:
        try:
            usage = self.service.usage(build_id)
        except Exception:
            logger.debug("build usage check failed for %s", build_id, exc_info=True)
            return None
        return usage if isinstance(usage, dict) else None

    @staticmethod
    def _token_budget_error(
        usage: dict[str, Any] | None,
        input_budget: int | None,
        output_budget: int | None,
    ) -> str | None:
        if usage is None:
            return None
        used_input = int(usage.get("input") or 0)
        # Providers commonly bill reasoning as output; count it against the
        # output ceiling so a reasoning-heavy turn cannot exceed the cap.
        used_output = int(usage.get("output") or 0) + int(
            usage.get("reasoning") or 0
        )
        if input_budget is not None and used_input > input_budget:
            return (
                "build exceeded the token budget "
                f"(input {used_input}/{input_budget}, output {used_output}"
                + (f"/{output_budget}" if output_budget is not None else "")
                + ")"
            )
        if output_budget is not None and used_output > output_budget:
            return (
                "build exceeded the token budget "
                f"(input {used_input}"
                + (f"/{input_budget}" if input_budget is not None else "")
                + f", output {used_output}/{output_budget})"
            )
        return None

    def _cancel_for_budget(self, build_id: str, error: str) -> None:
        try:
            self.service.cancel(build_id)
        except Exception as exc:
            logger.warning(
                "budget cancel failed for %s: %s", build_id, exc, exc_info=True
            )
        self._finalize(build_id, error=error, error_class="budget")

    def _session(self, build_id: str) -> BuildSession | None:
        try:
            return self.service.status(build_id)
        except KeyError:
            return None

    def _restore_local_session(
        self,
        record: BuildRecord,
        *,
        outcome: str = "succeeded",
    ) -> BuildSession | None:
        """Recreate a finished session from workspace data without a server.

        Used when the agent had already finished but the host crashed before
        validating and installing the rule.  Host validation can then resume
        without a model call.
        """
        if not record.session_id or not record.workspace:
            return None
        root = Path(record.workspace)
        if not (root / "out").is_dir():
            return None
        workspace = BuildWorkspace(root=root, build_id=record.build_id)
        session = BuildSession(
            build_id=record.build_id,
            state="FINISHED",
            workspace=workspace,
            session_id=record.session_id,
            model=record.model,
            harness={
                "name": "opencode",
                "version": None,
                "adapter_version": "opencode-http/0.1",
                "transport": "http+sse",
                "restored": True,
            },
            outcome=outcome,
            error=record.error,
        )
        sessions = getattr(self.service.adapter, "sessions", None)
        if isinstance(sessions, dict):
            sessions[record.build_id] = session
        self.service.adopt(session, events=_workspace_events(workspace))
        return session

    def _ensure_build_session(self, record: BuildRecord) -> BuildSession:
        """Return the live session or re-attach a persisted one on demand."""
        existing = self._session(record.build_id)
        if existing is not None:
            return existing
        if not record.session_id or not record.workspace:
            raise BuildError(
                "build session is no longer available; start a new build instead"
            )
        root = Path(record.workspace)
        if not root.is_dir():
            raise BuildError(
                "build session is no longer available: build workspace is missing"
            )
        workspace = BuildWorkspace(root=root, build_id=record.build_id)
        adopt = getattr(self.service.adapter, "adopt_build", None)
        if not callable(adopt):
            raise BuildError(
                "build session is no longer available; start a new build instead"
            )
        try:
            session = adopt(
                record.build_id,
                session_id=record.session_id,
                workspace=workspace,
                model=record.model,
                error=record.error,
            )
        except Exception as exc:
            raise BuildError(
                "build session is no longer available: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        # A user-requested continuation clears a pause marker that was
        # persisted before the restart.
        session.workspace.set_paused(False)
        self.service.adopt(session, events=_workspace_events(workspace))
        return session

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
        self, build_id: str, *, error: str | None = None, error_class: str | None = None
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
                self._record_failure(build_id, message, error_class=error_class)
                return None
            try:
                # Use the session workspace directly: a session restored after
                # a restart has no live adapter-side object, but its artifacts
                # and rule files are still on disk.
                artifacts = session.workspace.artifact_map()
                session.workspace.update_result(artifacts=artifacts)
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
                self._record_failure(build_id, error, error_class=error_class)
                # Keep the failed session available for a user-triggered
                # manual continue; manager shutdown closes it.
                return None

            validation: dict[str, Any] | None = None
            archive_stats: dict[str, Any] | None = None
            visual_evidence = _visual_evidence_status(Path(session.workspace.root))
            try:
                rule_path = self._find_rule(session)
                rule = load_rule(rule_path)
                catalog = self._catalog_configs.get(build_id, {})
                catalog_scope = str(catalog.get("catalog_scope"))
                if catalog_scope in {"full", "target"}:
                    target = int(
                        catalog.get("catalog_products")
                        or (2000 if catalog_scope == "full" else 1)
                    )
                    payload = yaml.safe_load(rule_path.read_text(encoding="utf-8"))
                    scope = payload.setdefault("scope", {}) if isinstance(payload, dict) else {}
                    if isinstance(scope, dict):
                        changed = False
                        if int(scope.get("max_products") or 0) < target:
                            scope["max_products"] = target
                            changed = True
                        if (
                            catalog_scope == "full"
                            and int(scope.get("max_seconds") or 0) < 3600
                        ):
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
                target = self.store.get_batch_site(record.batch_id, record.site_key)
                if target is None or normalize_site(target.input_value).site_key not in domains:
                    raise BuildError(
                        "rule domains do not include the target site: "
                        f"{sorted(domains)}"
                    )
                batch = self.store.get_batch(record.batch_id)
                if batch is not None and batch.collection_mode and not rule_covers_entry(
                    rule, target_entry(target.input_value)
                ):
                    raise BuildError("rule discovery sources must start at the requested entry URL")
                self.store.update_build(build_id, state="VALIDATING")
                validating_site = self.store.get_batch_site(
                    record.batch_id, record.site_key
                )
                if (
                    validating_site is not None
                    and validating_site.build_id == build_id
                ):
                    self.store.update_batch_site(
                        record.batch_id,
                        record.site_key,
                        readiness="building",
                        note=f"验证中：{build_id}",
                    )
                work_dir = Path(session.workspace.root) / "validation"
                feedback = (
                    self.store.get_feedback(record.feedback_id)
                    if record.feedback_id
                    else None
                )
                feedback_samples = [
                    str(sample).strip()
                    for sample in (feedback.samples if feedback else [])
                    if str(sample).strip()
                ][:5]
                validation_products = max(
                    1, int(record.request.get("max_products") or self.max_products)
                )
                validation_seconds = validation_seconds_for_rule(
                    rule_path,
                    default=self.validation_seconds,
                    browser_default=self.browser_validation_seconds,
                )
                task_result = self.validator(
                    rule_path,
                    work_dir,
                    validation_products,
                    validation_seconds,
                    record.proxy,
                    archive_mode=str(archive.get("mode") or "off"),
                    archive_root=archive.get("root"),
                    archive_sample_limit=int(archive.get("sample_limit") or 20),
                    archive_max_bytes=archive.get("max_bytes"),
                    archive_reuse=True,
                    seed_urls=feedback_samples or None,
                    discover=True,
                )
                counts = task_result.get("counts") if isinstance(task_result, dict) else {}
                counts = counts if isinstance(counts, dict) else {}
                valid = int(counts.get("valid_products") or 0)
                failed = int(counts.get("failed_products") or 0)
                validation = {
                    "valid_products": valid,
                    "failed_products": failed,
                    "products_budget": validation_products,
                    "seconds_budget": validation_seconds,
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
                product_samples = task_result.get("product_samples") or []
                duplicate_error = _duplicate_product_sample_error(product_samples)
                if duplicate_error:
                    raise BuildError(
                        "host validation product samples look duplicated: "
                        f"{duplicate_error}; check the product JSON-LD or selector "
                        "source before retrying"
                    )
                site = self.store.get_batch_site(record.batch_id, record.site_key)
                parent_rule = self.store.get_site_rule(record.site_key)
                has_parent = record.mode == "repair" or bool(
                    parent_rule and parent_rule.rule_version
                )
                issue_checks = feedback_issue_checks(
                    feedback,
                    product_samples,
                    rule_currency=rule_currency,
                    audit_samples=audit.get("samples"),
                )
                regression = self._run_regression(
                    record,
                    site,
                    product_samples,
                    work_dir,
                    record.proxy,
                    archive,
                    has_parent=has_parent,
                    new_rule=rule,
                )
                validation["product_samples"] = product_samples
                validation["candidate_smoke"] = {
                    "executed": valid >= 1,
                    "valid_products": valid,
                    "failed_products": failed,
                    "excluded_products": int(
                        counts.get("excluded_products") or 0
                    ),
                    "currencies": currencies,
                    "product_samples": product_samples[:10],
                }
                validation["issue_checks"] = issue_checks
                validation["regression"] = regression
                validation["feedback_samples"] = (
                    feedback_samples if issue_checks else []
                )
                rule_id, rule_version, rule_name, rule_sha256, change_summary = (
                    self._install_rule(
                        rule_path,
                        record,
                        counts,
                        task_result,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - rule/validation boundary
                message = f"{type(exc).__name__}: {exc}"
                if self._start_repair(build_id, message, validation):
                    return "repairing"
                self._mark_repair_finished(build_id, resolved=False)
                self._write_trace(
                    build_id, session, validation=validation, error=message
                )
                if record.feedback_id:
                    feedback = self.store.get_feedback(record.feedback_id)
                    if feedback and feedback.status == "REPAIRING":
                        self.store.update_feedback(
                            record.feedback_id,
                            status="TRIAGED",
                            triage_note=message[:2000],
                        )
                self._release_site(
                    record.batch_id,
                    record.site_key,
                    build_id,
                    f"构建失败：{message}",
                )
                self._record_failure(build_id, message)
                # Keep the failed session for manual continue.
                return None

            validation.update(
                {
                    "rule_id": rule_id,
                    "rule_version": rule_version,
                    "rule_path": rule_name,
                    "rule_sha256": rule_sha256,
                    "batch_market": batch_market or None,
                }
            )
            validation = normalize_validation(validation, change_summary)
            validation["visual_evidence"] = visual_evidence
            validation_status = str(validation.get("status") or "FAILED")
            auto_activate = (
                record.mode == "build" or self.activation_mode == "legacy"
            ) and validation_status == "PASSED"
            note_prefix = "已激活方案" if auto_activate else "候选方案"
            reasons = [
                str(reason)
                for reason in (validation.get("status_reasons") or [])
                if str(reason).strip()
            ]
            note = (
                f"{note_prefix}：{rule_id}@{rule_version}，"
                f"有界验证 {valid} 条有效、{failed} 失败"
            )
            if not auto_activate:
                if validation_status == "PASSED":
                    note += "；待人工激活"
                else:
                    note += f"；验证{validation_status}"
                    if reasons:
                        note += "：" + "；".join(reasons[:2])
            if visual_evidence["status"] != "complete":
                missing = "、".join(visual_evidence["missing"][:4])
                note += f"；视觉证据缺失：{missing}"
            if auto_activate:
                current = self.store.get_site_rule(record.site_key)
                self.store.activate_rule(
                    site_key=record.site_key,
                    rule_id=rule_id,
                    rule_version=rule_version,
                    sha256=rule_sha256,
                    expected_active_version=(
                        current.rule_version if current else None
                    ),
                    expected_active_sha256=current.sha256 if current else None,
                    feedback_id=record.feedback_id,
                    request_id=f"{build_id}-activate",
                    reason="host validation passed",
                    actor="build" if record.mode == "build" else "legacy-build",
                    action="activate",
                )
                if site is not None and site.build_id == build_id:
                    self.store.update_batch_site(
                        record.batch_id,
                        record.site_key,
                        readiness="ready",
                        build_id=build_id,
                        proxy=record.proxy,
                        rule_id=rule_id,
                        rule_version=rule_version,
                        rule_path=rule_name,
                        note=note,
                    )
                if record.feedback_id:
                    feedback = self.store.get_feedback(record.feedback_id)
                    if feedback and feedback.status == "REPAIRING":
                        self.store.update_feedback(
                            record.feedback_id,
                            status="AWAITING_RERUN",
                            repair_build_id=build_id,
                        )
                if record.request.get("auto_collect") and batch is not None and site is not None:
                    mode = batch.collection_mode
                    if mode in BATCH_COLLECTION_LIMITS and site.build_id == build_id:
                        task = build_task(
                            rule_path=self.rules_dir / rule_name,
                            task_id=f"web-{uuid.uuid4().hex[:12]}",
                            task_type="product",
                            max_attempts=2,
                            proxy=record.proxy,
                            **BATCH_COLLECTION_LIMITS[mode],
                        )
                        task.batch_id = batch.batch_id
                        task.site_key = site.site_key
                        task.domain_key = normalize_site(site.input_value).site_key or site.domain
                        task.market = batch.market or task.market
                        task.rule_sha256 = rule_sha256
                        task.input["collection_mode"] = mode
                        if entry := target_entry(site.input_value):
                            task.input["target_entry"] = entry
                        task.state = "QUEUED"
                        try:
                            self.store.create_task_for_site(task, site_key=site.site_key)
                        except BatchNotFoundError:
                            logger.info("skipping automatic collection for unavailable batch target %s", site.site_key)
            elif site is not None and site.build_id == build_id:
                self.store.update_batch_site(
                    record.batch_id,
                    record.site_key,
                    readiness="ready",
                    proxy=record.proxy,
                    note=note,
                )
                if record.feedback_id:
                    if validation_status == "PASSED":
                        self.store.update_feedback(
                            record.feedback_id,
                            status="AWAITING_ACTIVATION",
                            repair_build_id=build_id,
                        )
                    else:
                        self.store.update_feedback(
                            record.feedback_id,
                            status="TRIAGED",
                            repair_build_id=build_id,
                            triage_note=(
                                f"候选验证{validation_status}，未进入待激活："
                                + ("；".join(reasons[:2]) or "缺少验证证据")
                            )[:2000],
                        )
            self._mark_repair_finished(
                build_id, resolved=validation_status == "PASSED"
            )
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
                target_rule_version=rule_version,
                target_rule_sha256=rule_sha256,
                change_summary=change_summary,
                validation=validation,
                evidence_sha256=str(validation.get("evidence_sha256") or "") or None,
                finished_at=utc_now(),
                error=None,
                error_class=None,
            )
            self._close_session(build_id)
            return None
        finally:
            with self._lock:
                self._finalizing.discard(build_id)
                self._recovered_finalize.discard(build_id)
                self._handled_permissions.pop(build_id, None)

    def _source_rule_path(
        self,
        record: BuildRecord,
        site: BatchSite | None,
        *,
        has_parent: bool = False,
    ) -> Path | None:
        """Locate the source rule with its recorded hash."""
        if record.mode != "repair" and not has_parent:
            return None
        candidates: list[Path] = []
        if site is not None and site.rule_path:
            candidates.append(self.rules_dir / site.rule_path)
        active = self.store.get_site_rule(record.site_key)
        if active is not None:
            candidates.append(self.rules_dir / active.path)
        for path in candidates:
            if self._rule_file_matches(record, site, path):
                return path
        try:
            scanned = sorted(self.rules_dir.glob("*.yaml")) + sorted(
                self.rules_dir.glob("*.yml")
            )
        except OSError:
            return None
        for path in scanned[:500]:
            if self._rule_file_matches(record, site, path):
                return path
        return None

    def _rule_file_matches(
        self,
        record: BuildRecord,
        site: BatchSite | None,
        path: Path,
    ) -> bool:
        if not path.is_file():
            return False
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return False
        if record.source_rule_sha256 and digest != record.source_rule_sha256:
            return False
        if record.source_rule_version:
            try:
                rule = load_rule(path)
            except Exception:  # noqa: BLE001 - candidate file boundary
                return False
            if rule.rule_version != record.source_rule_version:
                return False
            if site is not None and site.rule_id and rule.rule_id != site.rule_id:
                return False
        return True

    def _run_regression(
        self,
        record: BuildRecord,
        site: BatchSite | None,
        new_samples: list[dict[str, Any]],
        work_dir: Path,
        proxy: str | None,
        archive: dict[str, Any],
        *,
        has_parent: bool = False,
        new_rule: Any | None = None,
    ) -> dict[str, Any]:
        """Run the source rule over the candidate's fixed product page set."""
        if record.mode != "repair" and not has_parent:
            return {
                "executed": False,
                "required": False,
                "required_checked": 0,
                "checked": 0,
                "regressions": [],
                "reason": "initial build has no source rule to compare",
            }
        source_path = self._source_rule_path(
            record, site, has_parent=has_parent
        )
        if source_path is None:
            return {
                "executed": False,
                "required": True,
                "required_checked": 0,
                "checked": 0,
                "regressions": [],
                "reason": "source rule file is unavailable or its hash changed",
            }
        if getattr(new_rule, "product_source", None):
            try:
                source_rule = load_rule(source_path)
            except Exception:  # noqa: BLE001 - keep the normal failure path below
                source_rule = None
            if source_rule is None or not source_rule.product_source:
                return {
                    "executed": False,
                    "required": False,
                    "required_checked": 0,
                    "checked": 0,
                    "regressions": [],
                    "reason": (
                        "source switched to product_source; cross-version "
                        "name/image comparison is not applicable"
                    ),
                }
        seeds = [
            str(item.get("source_url") or "").strip()
            for item in new_samples
            if str(item.get("source_url") or "").strip()
        ][:5]
        if not seeds:
            return {
                "executed": False,
                "required": True,
                "required_checked": 0,
                "checked": 0,
                "regressions": [],
                "reason": "candidate validation produced no product URLs",
            }
        old_validation_seconds = validation_seconds_for_rule(
            source_path,
            default=self.validation_seconds,
            browser_default=self.browser_validation_seconds,
        )
        try:
            old_result = self.validator(
                source_path,
                work_dir / "regression-old",
                len(seeds),
                max(30, old_validation_seconds),
                proxy,
                archive_mode=str(archive.get("mode") or "off"),
                archive_root=archive.get("root"),
                archive_sample_limit=int(archive.get("sample_limit") or 20),
                archive_max_bytes=archive.get("max_bytes"),
                archive_reuse=True,
                seed_urls=seeds,
                discover=False,
            )
        except Exception as exc:  # noqa: BLE001 - regression boundary
            return {
                "executed": False,
                "required": True,
                "required_checked": min(3, len(seeds)),
                "checked": 0,
                "regressions": [],
                "reason": f"source rule run failed: {type(exc).__name__}: {exc}",
            }
        result = compare_product_samples(
            old_result.get("product_samples") if isinstance(old_result, dict) else [],
            new_samples,
            source_rule_version=record.source_rule_version,
            source_rule_sha256=record.source_rule_sha256,
        )
        result["required_checked"] = min(3, len(seeds))
        return result

    def _assert_catalog_rule(self, build_id: str, rule: Any) -> None:
        catalog = self._catalog_configs.get(build_id, {})
        catalog_scope = str(catalog.get("catalog_scope"))
        if catalog_scope not in {"full", "target"}:
            return
        target = int(
            catalog.get("catalog_products")
            or (2000 if catalog_scope == "full" else 1)
        )
        scope_products = int(rule.scope.get("max_products") or 0)
        if scope_products < target:
            raise BuildError(
                f"{catalog_scope} catalog build requires scope.max_products >= "
                f"{target}; got {scope_products}"
            )
        sources = rule.discovery.get("sources")
        source_types = {
            str(source.get("type"))
            for source in sources or []
            if isinstance(source, dict)
        }
        has_product_source = bool(rule.product_source)
        if not has_product_source and not source_types & {
            "listing",
            "sitemap",
            "html_index",
            "public_json",
        }:
            raise BuildError(
                f"{catalog_scope} catalog build requires discovery.sources with a "
                "listing, sitemap, html_index or public_json source, or a "
                "Shopify product_source; entry_links alone does not cover the target"
            )

    def _start_repair(
        self,
        build_id: str,
        message: str,
        validation: dict[str, Any] | None,
    ) -> bool:
        """Hand one validation failure back to the same harness session."""
        if build_id in self._recovered_finalize:
            # Restart recovery re-runs host validation only.  Starting a new
            # model turn is an explicit user decision after that.
            return False
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
        self._repair_pending.add(build_id)
        try:
            self.service.continue_after_finish(build_id, prompt)
        except Exception as exc:  # noqa: BLE001 - continuation boundary
            self._repair_pending.discard(build_id)
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
            self._repair_pending.discard(build_id)
            return
        if resolved and build_id not in self._repair_pending:
            # A successful manual continuation is not the auto-repair round's
            # result. Keep the round unresolved so the build page shows that
            # the user-supplied instruction, not the automatic round, fixed it.
            return
        self._repair_pending.discard(build_id)
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
        capture_trace_reasoning = (
            self._trace_reasoning.get(build_id, False)
            and self.persist_reasoning_enabled
        )
        trace = build_trace(
            export,
            build_id=build_id,
            model=session.model,
            events=events,
            validation=validation,
            repairs=list(self._repairs.get(build_id, [])),
            repair_limit=self._repair_limits.get(build_id, 0),
            error=error,
            capture_reasoning=capture_trace_reasoning,
        )
        if not trace.get("messages") and not trace.get("tools"):
            # Cancelled or interrupted sessions may export no messages even
            # though session.ndjson has the full event log.  Persist a compact
            # fallback so failure evidence does not become empty.
            fallback_events = _workspace_events(session.workspace)
            fallback_timeline, _ = _live_timeline(fallback_events)
            if not trace.get("tokens"):
                for event in reversed(fallback_events):
                    data = getattr(event, "data", {}) or {}
                    tokens = data.get("tokens")
                    if isinstance(tokens, dict) and tokens:
                        trace["tokens"] = tokens
                        cost = data.get("cost")
                        if type(cost) in {int, float}:
                            trace["cost"] = cost
                        break
            fallback_messages = [
                {
                    "created_at": item.get("created_at"),
                    "role": str(item.get("role") or "assistant"),
                    "text": str(item.get("text") or ""),
                }
                for item in fallback_timeline
                if item.get("kind") == "text" and item.get("text")
            ]
            fallback_reasoning = (
                [
                    {
                        "created_at": item.get("created_at"),
                        "text": str(item.get("text") or ""),
                    }
                    for item in fallback_timeline
                    if item.get("kind") == "reasoning" and item.get("text")
                ]
                if capture_trace_reasoning
                else []
            )
            fallback_tools = [
                {
                    "created_at": item.get("created_at"),
                    "name": str(item.get("name") or "unknown"),
                    "status": str(item.get("status") or ""),
                    "call_id": item.get("call_id"),
                }
                for item in fallback_timeline
                if item.get("kind") == "tool"
            ]
            if fallback_messages:
                trace["messages"] = fallback_messages
            if fallback_reasoning:
                trace["reasoning"] = fallback_reasoning
            if fallback_tools:
                trace["tools"] = fallback_tools
            counts = trace.setdefault("counts", {})
            counts["messages"] = len(fallback_messages)
            counts["reasoning_parts"] = len(fallback_reasoning)
            counts["reasoning_chars"] = sum(
                len(item["text"]) for item in fallback_reasoning
            )
            counts["tools"] = len(fallback_tools)
            counts["failed_tools"] = sum(
                1
                for item in fallback_tools
                if item.get("status") not in {"completed", "success", ""}
            )
            counts["by_tool"] = dict(
                sorted(Counter(item["name"] for item in fallback_tools).items())
            )
            if fallback_reasoning:
                trace["reasoning_retained"] = True
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
    ) -> tuple[str, str, str, str]:
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
        previous = self.store.get_batch_site(record.batch_id, record.site_key)
        if record.mode == "repair" and previous is not None and previous.rule_id:
            if rule_id != previous.rule_id:
                raise BuildError(
                    "repair must keep the same rule_id: "
                    f"{previous.rule_id} != {rule_id}"
                )
            if rule_version == previous.rule_version:
                raise BuildError(
                    "repair must bump rule_version: "
                    f"{rule_id}@{rule_version} is already installed"
                )
        parent_rule = self.store.get_site_rule(record.site_key)
        parent_version = (
            parent_rule.rule_version
            if parent_rule is not None
            else (previous.rule_version if previous else None)
        )
        parent_path_name = (
            parent_rule.path
            if parent_rule is not None
            else (previous.rule_path if previous else None)
        )
        parent_payload: Any = None
        if parent_path_name:
            parent_path = self.rules_dir / parent_path_name
            try:
                parent_payload = yaml.safe_load(
                    parent_path.read_text(encoding="utf-8")
                )
            except (OSError, yaml.YAMLError):
                logger.warning(
                    "parent rule is not readable; skipping field diff: %s",
                    parent_path_name,
                    exc_info=True,
                )
        change_summary = build_change_summary(
            parent_payload,
            payload,
            rule_id=rule_id,
            rule_version=rule_version,
            parent_version=parent_version,
        )
        existing = self.store.get_rule_version(rule_id, rule_version)
        if existing is not None:
            if existing.source_build_id == record.build_id:
                existing_path = self.rules_dir / existing.path
                if not existing_path.is_file():
                    raise BuildError(
                        f"existing rule version file is missing: {existing.path}"
                    )
                existing_payload = yaml.safe_load(
                    existing_path.read_text(encoding="utf-8")
                )
                if _stable_rule_payload(existing_payload) != _stable_rule_payload(
                    payload
                ):
                    raise BuildError(
                        "rule version content changed without bumping rule_version: "
                        f"{rule_id}@{rule_version}"
                    )
                return (
                    rule_id,
                    rule_version,
                    existing.path,
                    existing.sha256,
                    change_summary,
                )
            raise BuildError(
                f"rule version already exists: {rule_id}@{rule_version}"
            )
        self.rules_dir.mkdir(parents=True, exist_ok=True)
        base = f"{_safe_filename(rule_id)}-{_safe_filename(rule_version)}"
        target = self.rules_dir / f"{base}.yaml"
        if target.exists():
            if record.mode == "repair":
                raise BuildError(
                    f"rule version already exists: {rule_id}@{rule_version}"
                )
            target = self.rules_dir / f"{base}-{record.build_id}.yaml"
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        os.replace(temporary, target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        self.store.create_rule_version(
            RuleVersion(
                rule_id=rule_id,
                rule_version=rule_version,
                sha256=digest,
                path=target.name,
                status="candidate",
                parent_version=parent_version,
                source_build_id=record.build_id,
                source_feedback_id=record.feedback_id,
                created_at=utc_now(),
            )
        )
        return rule_id, rule_version, target.name, digest, change_summary

    def _record_failure(
        self, build_id: str, message: str, *, error_class: str | None = None
    ) -> None:
        record = self.store.get_build(build_id)
        if record is None or record.state in TERMINAL_BUILD_STATES:
            return
        self.store.update_build(
            build_id,
            state="FINISHED",
            outcome="failed",
            error=message,
            error_class=error_class,
            finished_at=utc_now(),
        )
        self._release_feedback(build_id, message)

    def _release_feedback(self, build_id: str, note: str) -> None:
        """Return a repair feedback to TRIAGED when its build ends early."""
        record = self.store.get_build(build_id)
        if record is None or record.mode != "repair" or not record.feedback_id:
            return
        feedback = self.store.get_feedback(record.feedback_id)
        if feedback is None or feedback.status != "REPAIRING":
            return
        self.store.update_feedback(
            record.feedback_id,
            status="TRIAGED",
            triage_note=note[:2000],
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
    @property
    def dependency_installer_configured(self) -> bool:
        return bool(
            self.dependency_policy.build_python
            and self.dependency_policy.installers
        )

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
        queue_position: int | None = None
        if state == "QUEUED":
            queued = self.store.list_builds(
                states={"QUEUED"}, limit=500, oldest_first=True
            )
            for index, item in enumerate(queued, 1):
                if item.build_id == build_id:
                    queue_position = index
                    break
        events: list[dict[str, Any]] = []
        pending_permissions: list[dict[str, Any]] = []
        pending_dependencies: list[str] = []
        pending_dependency_requests: list[dict[str, Any]] = []
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
            try:
                pending_dependency_requests = (
                    self.service.pending_dependency_requests(build_id)
                )
            except Exception:
                logger.debug("dependency detail read failed", exc_info=True)
                pending_dependency_requests = []
        else:
            events = self._read_events(record.workspace, limit=max(1, event_limit))
        repair_limit = self._repair_limits.get(build_id)
        repairs = list(self._repairs.get(build_id, []))
        request = dict(record.request or {})
        trace_meta: dict[str, Any] = {}
        if repair_limit is None:
            trace_meta = self._trace_meta(build_id, record.workspace)
            repair_limit = int(trace_meta.get("repair_limit") or 0)
            if not trace_meta and request.get("repair_rounds") is not None:
                repair_limit = int(request.get("repair_rounds") or 0)
        if not repairs:
            repairs = list(trace_meta.get("repairs") or [])
        return {
            "build_id": record.build_id,
            "batch_id": record.batch_id,
            "site_key": record.site_key,
            "state": state,
            "outcome": outcome,
            "queue_position": queue_position,
            "mode": record.mode,
            "workspace": record.workspace,
            "session_id": record.session_id,
            "recoverable": bool(
                state == "FINISHED"
                and outcome in {"failed", "interrupted"}
                and record.session_id
                and record.workspace
                and Path(record.workspace).is_dir()
            ),
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
            "feedback_id": record.feedback_id,
            "source_rule": (
                {
                    "rule_version": record.source_rule_version,
                    "sha256": record.source_rule_sha256,
                }
                if record.source_rule_version
                else None
            ),
            "candidate_rule": (
                {
                    "rule_version": record.target_rule_version,
                    "sha256": record.target_rule_sha256,
                }
                if record.target_rule_version
                else None
            ),
            "error_class": record.error_class,
            "change_summary": record.change_summary,
            "validation": record.validation,
            "continuations": [
                {
                    "request_id": item.request_id,
                    "state": item.state,
                    "message_chars": item.message_chars,
                    "error": item.error,
                    "created_at": item.created_at,
                }
                for item in self.store.list_build_continuations(build_id)
            ],
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
            "pending_dependency_requests": pending_dependency_requests,
            "dependency_installer_configured": self.dependency_installer_configured,
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
            "archive": self._archive_configs.get(build_id)
            or (
                dict(request["archive"])
                if isinstance(request.get("archive"), dict)
                else None
            ),
            "archive_stats": self._archive_stats.get(build_id),
            "catalog": self._catalog_configs.get(build_id)
            or (
                dict(request["catalog"])
                if isinstance(request.get("catalog"), dict)
                else None
            ),
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
            if not timeline and record.workspace:
                # A cancelled or interrupted build may have an empty export
                # even though the workspace event log is complete.  Keep the
                # timeline observable instead of showing an empty panel.
                fallback_events = _workspace_events(
                    BuildWorkspace(root=Path(record.workspace), build_id=build_id)
                )
                fallback_timeline, fallback_truncated = _live_timeline(fallback_events)
                if fallback_timeline:
                    timeline = fallback_timeline
                    timeline_truncated = fallback_truncated
                    if not trace.get("messages"):
                        trace["messages"] = [
                            {
                                "created_at": item.get("created_at"),
                                "text": str(item.get("text") or ""),
                                "role": "assistant",
                            }
                            for item in fallback_timeline
                            if item.get("kind") == "text" and item.get("text")
                        ]
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
        if not events and record.workspace:
            events = _workspace_events(
                BuildWorkspace(root=Path(record.workspace), build_id=build_id)
            )
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
            "live": record.state != "QUEUED",
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
    def continue_session(self, build_id: str, message: str) -> dict[str, Any]:
        """Continue one failed build session with a user instruction."""
        record = self.store.get_build(build_id)
        if record is None:
            raise BuildError(f"unknown build: {build_id}")
        if record.state != "FINISHED":
            raise BuildError(
                f"build {build_id} is {record.state}; only finished builds can continue"
            )
        if record.outcome not in {"failed", "interrupted"}:
            raise BuildError(
                f"build {build_id} is {record.outcome or 'unfinished'}; "
                "only failed or interrupted builds can continue"
            )
        if record.request:
            self._hydrate_request(record)
        with self._lock:
            if build_id in self._watchers:
                raise BuildError(f"build {build_id} already has an active watcher")
            active = self.service.active_build_id
            if active is not None and active != build_id:
                raise BuildError(f"another build is still active: {active}")
            if self._slot_build_id is not None and self._slot_build_id != build_id:
                raise BuildError(
                    f"another build is still active: {self._slot_build_id}"
                )
            self._slot_build_id = build_id
        # Manual continuation is outside the automatic repair budget. If the
        # last auto-repair round failed, keep it visibly unresolved and let the
        # continuation record explain how the build eventually succeeded.
        self._repair_pending.discard(build_id)
        self._recovered_finalize.discard(build_id)
        rounds = self._repairs.get(build_id) or []
        if rounds:
            rounds[-1].setdefault("finished_at", utc_now())
            rounds[-1]["resolved"] = False
        try:
            session = self._ensure_build_session(record)
            session.workspace.set_paused(False)
            self.service.continue_after_finish(build_id, message)
        except Exception as exc:
            with self._lock:
                if self._slot_build_id == build_id:
                    self._slot_build_id = None
            raise BuildError(
                "build session is no longer available; start a new build "
                f"instead ({type(exc).__name__}: {exc})"
            ) from exc
        self.store.update_build(
            build_id,
            state="RUNNING",
            outcome=None,
            error=None,
            error_class=None,
            finished_at=None,
        )
        self._repair_limits.setdefault(build_id, self.max_repair_rounds)
        self._start_watcher(build_id)
        return self.describe(build_id)

    def pause(self, build_id: str) -> dict[str, Any]:
        record = self.store.get_build(build_id)
        if record is None:
            raise KeyError(f"unknown build: {build_id}")
        if record.state == "QUEUED":
            raise BuildError(
                "queued build has not started; cancel it or wait for the slot"
            )
        session = self.service.pause(build_id)
        self.store.update_build(build_id, state=session.state)
        return self.describe(build_id)

    def resume(self, build_id: str) -> dict[str, Any]:
        record = self.store.get_build(build_id)
        if record is None:
            raise KeyError(f"unknown build: {build_id}")
        if record.state == "QUEUED":
            raise BuildError(
                "queued build has not started; cancel it or wait for the slot"
            )
        session = self.service.resume(build_id)
        self.store.update_build(build_id, state=session.state)
        return self.describe(build_id)

    def cancel(self, build_id: str) -> dict[str, Any]:
        record = self.store.get_build(build_id)
        if record is None:
            raise KeyError(f"unknown build: {build_id}")
        if record.state == "QUEUED":
            self.store.update_build(
                build_id,
                state="CANCELLED",
                outcome="cancelled",
                finished_at=utc_now(),
            )
            self._release_site(
                record.batch_id,
                record.site_key,
                build_id,
                "构建已取消：可重新开始",
            )
            self._release_feedback(build_id, "构建已取消：未安装候选规则")
            self._drain_queue()
            return self.describe(build_id)
        session = self.service.cancel(build_id)
        self._write_trace(build_id, session, error="build was cancelled")
        self._release_site(
            record.batch_id,
            record.site_key,
            build_id,
            "构建已取消：可重新开始",
        )
        self._release_feedback(build_id, "构建已取消：未安装候选规则")
        self.store.update_build(
            build_id,
            state=session.state,
            outcome="cancelled",
            finished_at=utc_now(),
        )
        self._close_session(build_id)
        self._drain_queue()
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
    def _read_workspace_result(self, record: BuildRecord) -> dict[str, Any]:
        if not record.workspace:
            return {}
        path = Path(record.workspace) / "out" / "result.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def reconcile(self) -> list[str]:
        """Recover builds left active by a previous service process.

        Conversations are persistent in OpenCode storage, so the host does
        not delete them on restart.  A build whose agent had already finished
        is revalidated and installed without a model call.  Other active
        builds become ``FINISHED`` / ``interrupted`` and can be continued
        explicitly from the build page; they do not hold the queue slot.
        """
        if self.read_only:
            return []
        interrupted: list[str] = []
        for record in self.store.list_builds(states=RUNNING_BUILD_STATES, limit=500):
            if record.state == "CANCELLING":
                message = "服务重启，取消操作已完成"
                self.store.update_build(
                    record.build_id,
                    state="CANCELLED",
                    outcome="cancelled",
                    error=None,
                    finished_at=utc_now(),
                )
                self._release_site(
                    record.batch_id,
                    record.site_key,
                    record.build_id,
                    "构建已取消：可重新开始",
                )
                self._release_feedback(
                    record.build_id, "构建已取消：未安装候选规则"
                )
                interrupted.append(record.build_id)
                continue
            result = self._read_workspace_result(record)
            result_state = str(result.get("state") or "")
            result_outcome = str(result.get("outcome") or "")
            agent_finished = record.state == "VALIDATING" or (
                result_state == "FINISHED" and result_outcome == "succeeded"
            )
            if agent_finished:
                restored = self._restore_local_session(record)
                if restored is not None:
                    with self._lock:
                        slot_free = self._slot_build_id is None
                        if slot_free:
                            self._slot_build_id = record.build_id
                    if slot_free:
                        self._hydrate_request(record)
                        self._recovered_finalize.add(record.build_id)
                        self.store.update_build(
                            record.build_id,
                            state="VALIDATING",
                            error=None,
                            error_class="service_restart",
                        )
                        logger.info(
                            "recovering host validation for %s", record.build_id
                        )
                        self._start_watcher(record.build_id)
                        continue
            if result_state == "FINISHED" and result_outcome in {"failed", "closed"}:
                outcome = "failed"
                message = str(
                    result.get("error")
                    or f"构建会话在服务重启前已结束：{result_outcome}"
                )
            elif (
                record.session_id
                and record.workspace
                and Path(record.workspace).is_dir()
            ):
                outcome = "interrupted"
                message = "服务重启，构建会话已中断；会话已保留，可在构建详情继续"
            else:
                outcome = "failed"
                message = "服务重启，构建会话已中断；没有可恢复的会话，请重新构建"
            self.store.update_build(
                record.build_id,
                state="FINISHED",
                outcome=outcome,
                error=message,
                error_class="service_restart",
                finished_at=utc_now(),
            )
            self._release_site(
                record.batch_id,
                record.site_key,
                record.build_id,
                (
                    f"构建已中断：{message}"
                    if outcome == "interrupted"
                    else f"构建失败：{message}"
                ),
            )
            self._release_feedback(record.build_id, message)
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
        for record in self.store.list_builds(
            states={"QUEUED"}, limit=500, oldest_first=True
        ):
            self._hydrate_request(record)
        self._drain_queue()
        return interrupted

    def shutdown(self) -> None:
        self._stopping.set()
        if self.read_only:
            return
        records = {
            record.build_id: record
            for record in self.store.list_builds(
                states=RUNNING_BUILD_STATES, limit=500
            )
        }
        message = "服务停止，构建会话已中断；会话已保留，可在构建详情继续"
        for build_id, record in sorted(records.items()):
            if record.state == "CANCELLING":
                try:
                    self.service.cancel(build_id)
                except Exception:
                    logger.debug("build cancel on shutdown failed", exc_info=True)
                self._release_site(
                    record.batch_id,
                    record.site_key,
                    build_id,
                    "构建已取消：可重新开始",
                )
                self.store.update_build(
                    build_id,
                    state="CANCELLED",
                    outcome="cancelled",
                    error=None,
                    finished_at=utc_now(),
                )
                self._release_feedback(
                    build_id, "构建已取消：未安装候选规则"
                )
                continue
            try:
                self.service.detach(build_id)
            except Exception:
                logger.debug("build detach on shutdown failed", exc_info=True)
            self._release_site(
                record.batch_id,
                record.site_key,
                build_id,
                f"构建已中断：{message}",
            )
            self.store.update_build(
                build_id,
                state="FINISHED",
                outcome="interrupted",
                error=message,
                error_class="service_stop",
                finished_at=utc_now(),
            )
            self._release_feedback(build_id, message)
        with self._lock:
            threads = list(self._watchers.values())
        for thread in threads:
            thread.join(timeout=2)
        # Stop adapter-owned processes but keep persisted conversations for a
        # later "continue" action.
        shutdown = getattr(self.service.adapter, "shutdown", None)
        if callable(shutdown):
            try:
                shutdown()
            except Exception:
                logger.debug("harness shutdown failed", exc_info=True)
        with self._lock:
            self._slot_build_id = None
            self._dispatching = None
