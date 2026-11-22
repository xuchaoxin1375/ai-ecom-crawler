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
import json
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import yaml

from .execution import run_task
from .harness import BuildService, BuildTask, OpenCodeHttpAdapter
from .harness.adapter import BuildSession
from .harness.dependencies import DependencyPolicy
from .harness.trace import build_trace, render_trace_markdown
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
logger = logging.getLogger(__name__)


class BuildError(ValueError):
    """Raised when a build cannot start or is invalid for the site."""


Validator = Callable[[Path, Path, int, int, str | None], dict[str, Any]]


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


def default_permissions() -> list[dict[str, Any]]:
    return [
        {"action": action, "resource": "*", "effect": "allow"}
        for action in ("shell", "edit", "read", "webfetch", "websearch", "browser")
    ]


def default_validator(
    rule_path: Path,
    work_dir: Path,
    max_products: int,
    max_seconds: int,
    proxy: str | None = None,
) -> dict[str, Any]:
    """Run the bounded validation task in an isolated ledger/output tree."""
    work_dir.mkdir(parents=True, exist_ok=True)
    task_id = f"validate-{uuid.uuid4().hex[:10]}"
    result, _ = run_task(
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
    )
    currencies: dict[str, int] = {}
    products_path = work_dir / "out" / task_id / "export" / "products.csv"
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


def _seconds_since(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return max(0.0, (datetime.now(UTC) - parsed).total_seconds())


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
    ) -> None:
        self.store = store
        self.out_root = Path(out_root)
        self.rules_dir = Path(rules_dir)
        self.workspace_root = self.out_root / "builds"
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
        self._trace_reasoning: dict[str, bool] = {}
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
    ) -> BuildRecord:
        if site.readiness in {"invalid", "duplicate"}:
            raise BuildError("invalid or duplicate sites cannot be built")
        if site.task_id:
            raise BuildError("site already has a task")
        if not self.rules_dir.is_dir():
            raise BuildError("rules directory is not configured")
        with self._lock:
            active = self.service.active_build_id
            if active is not None:
                raise BuildError(f"another build is still active: {active}")
            latest = self.store.latest_build_for_site(batch.batch_id, site.site_key)
            if latest is not None and latest.state in ACTIVE_BUILD_STATES:
                raise BuildError(f"site already has an active build: {latest.build_id}")

            entry_url = _entry_url(site)
            product_budget = max(1, int(max_products or self.max_products))
            second_budget = max(60, int(max_seconds or self.max_seconds))
            resolved_proxy = (proxy or site.proxy or self.default_proxy or "").strip() or None
            if resolved_proxy:
                _validate_proxy(resolved_proxy)
            build_id = f"build-{uuid.uuid4().hex[:12]}"
            self._trace_reasoning[build_id] = bool(
                capture_reasoning and self.reasoning_capture_enabled
            )
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
                workspace=str(self.workspace_root / build_id),
                output_dir=str(self.workspace_root / build_id / "out" / "plan"),
                notes=(
                    "Build a declarative product rule from the batch site entry "
                    "and install it only after host validation."
                ),
                extra={"proxy": resolved_proxy} if resolved_proxy else {},
            )
            record = BuildRecord(
                build_id=build_id,
                batch_id=batch.batch_id,
                site_key=site.site_key,
                state="CREATED",
                model=self.model,
                proxy=resolved_proxy,
                workspace=str(self.workspace_root / build_id),
            )
            self.store.create_build(record)
            self.store.update_batch_site(
                batch.batch_id,
                site.site_key,
                readiness="building",
                build_id=build_id,
                proxy=resolved_proxy,
                note=f"构建中：{build_id}",
            )
            session: BuildSession | None = None
            try:
                session = self.service.start_build(task)
                self._write_inputs(session, batch, site, task)
                self.store.update_build(
                    build_id,
                    workspace=str(session.workspace.root),
                    session_id=session.session_id,
                    state=session.state,
                )
                self.service.send_prompt(build_id, self._prompt(site, batch, task))
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
- Product budget: `{task.limits.get("max_products")}`
- Wall-clock budget: `{task.limits.get("max_seconds")}` seconds
- Request budget: `{task.limits.get("max_requests")}`
{proxy_line}
Use the entry page first. If it has product links, a bounded `entry_links`
sample is enough; do not crawl the whole site. If it has no product links,
inspect one category or sitemap and use `listing`, `html_index` or `sitemap`.

## Required output

Write these files from the workspace (`work/` is your current directory):

- `../out/plan/rule.yaml` — the complete rule manifest.
- `../out/evidence/build-notes.md` — what you inspected, sample URLs, selectors,
  limitations and anything you could not verify.

Do not write outside the workspace. Do not install packages. Do not log in,
pay, solve captchas or bypass access control. Respect the request budget.

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
        return (
            "Read ../input/build-brief.md and ../input/reference-rule.yaml, "
            f"then build the rule package for {site.site_key}. "
            f"Entry: {task.site['entry_urls'][0]}. "
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
                    self._finalize(build_id)
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
    def _finalize(self, build_id: str, *, error: str | None = None) -> None:
        with self._lock:
            if build_id in self._finalizing:
                return
            self._finalizing.add(build_id)
        try:
            record = self.store.get_build(build_id)
            if record is None:
                return
            session = self._session(build_id)
            if session is None:
                message = error or "build session disappeared"
                self._release_site(
                    record.batch_id,
                    record.site_key,
                    build_id,
                    f"构建失败：{message}",
                )
                self._record_failure(build_id, message)
                return
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
                self._write_trace(build_id, session, error=error)
                self._release_site(
                    record.batch_id,
                    record.site_key,
                    build_id,
                    f"构建失败：{error}",
                )
                self._record_failure(build_id, error)
                self._close_session(build_id)
                return

            try:
                rule_path = self._find_rule(session)
                rule = load_rule(rule_path)
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
                )
                counts = task_result.get("counts") if isinstance(task_result, dict) else {}
                counts = counts if isinstance(counts, dict) else {}
                valid = int(counts.get("valid_products") or 0)
                failed = int(counts.get("failed_products") or 0)
                if valid < 1:
                    raise BuildError(
                        "host validation produced no valid products: "
                        f"valid={valid}, failed={failed}, "
                        f"stop_reason={task_result.get('stop_reason') if isinstance(task_result, dict) else None}"
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
                self._write_trace(build_id, session, error=message)
                self._release_site(
                    record.batch_id,
                    record.site_key,
                    build_id,
                    f"构建失败：{message}",
                )
                self._record_failure(build_id, message)
                self._close_session(build_id)
                return

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
            self._write_trace(
                build_id,
                session,
                validation={
                    "valid_products": valid,
                    "failed_products": failed,
                    "currencies": currencies,
                    "rule_id": rule_id,
                    "rule_version": rule_version,
                    "rule_path": rule_name,
                    "batch_market": batch_market or None,
                },
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
        finally:
            with self._lock:
                self._finalizing.discard(build_id)
                self._handled_permissions.pop(build_id, None)

    def _write_trace(
        self,
        build_id: str,
        session: BuildSession,
        *,
        validation: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
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
            error=error,
            capture_reasoning=self._trace_reasoning.get(build_id, False),
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
        if site.readiness == "building":
            self.store.update_batch_site(
                batch_id,
                site_key,
                readiness="needs_onboarding",
                note=note,
            )

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
        return {
            "build_id": record.build_id,
            "batch_id": record.batch_id,
            "site_key": record.site_key,
            "state": state,
            "outcome": outcome,
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
            "elapsed_seconds": _seconds_since(record.started_at),
            "events": events,
            "pending_permissions": pending_permissions,
            "pending_dependencies": pending_dependencies,
            "trace_available": (
                bool(record.workspace)
                and (Path(record.workspace) / "out" / "trace.json").is_file()
            ),
            "reasoning_capture_enabled": self.reasoning_capture_enabled,
            "reasoning_retained": self._trace_reasoning.get(build_id, False),
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
            return {
                "build_id": build_id,
                "state": record.state,
                "live": False,
                "messages": (trace.get("messages") or [])[-limit:],
                "reasoning": (trace.get("reasoning") or [])[-limit:],
                "reasoning_retained": bool(trace.get("reasoning_retained")),
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
        return {
            "build_id": build_id,
            "state": record.state,
            "live": True,
            "messages": messages[-limit:],
            "reasoning": reasoning[-limit:],
            "reasoning_retained": bool(reasoning),
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
