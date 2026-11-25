"""Load and validate the declarative rule subset used by the runtime prototype."""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from ecom_crawler.executor.manifest import validate_plan

from .models import TASK_TYPES, utc_now

SCHEMA_VERSIONS = {"1.0", "1.1", "1.2", "1.3"}
RULE_STATUSES = {"candidate", "verified", "deprecated"}
SUPPORTED_KINDS = {"declarative", "hybrid"}
SUPPORTED_DISCOVERY = {"entry_links"}
SUPPORTED_SOURCES = {
    "entry_links",
    "sitemap",
    "listing",
    "html_index",
    "public_json",
    "adapter",
}
SUPPORTED_ADVANCE = {
    "none",
    "page_param",
    "next_link",
    "load_more",
    "infinite_scroll",
}
SUPPORTED_SCROLL_MODES = {"auto", "scroll", "wheel"}
SUPPORTED_ENGINES = {"static", "browser", "http_json"}
SUPPORTED_WAIT_UNTIL = {"commit", "domcontentloaded", "load", "networkidle"}
SUPPORTED_SELECTOR_STATES = {"attached", "detached", "hidden", "visible"}
BROWSER_OPTION_KEYS = {
    "headless",
    "real_chrome",
    "executable_path",
    "extra_flags",
    "user_agent",
    "locale",
    "timezone",
    "challenge_wait_ms",
    "profile_name",
    "proxy",
    "timeout_ms",
    "wait_until",
    "wait_selector",
    "wait_selector_state",
    "wait_ms",
    "network_idle",
    "network_idle_timeout_ms",
    "disable_resources",
}
PAGE_OVERRIDE_KEYS = {
    "engine",
    "wait_until",
    "wait_selector",
    "wait_selector_state",
    "wait_ms",
    "network_idle",
    "network_idle_timeout_ms",
    "disable_resources",
    "timeout_ms",
}
ADAPTER_BROWSER_KEYS = {
    "headless",
    "timeout_ms",
    "locale",
    "timezone",
    "wait_state",
    "profile_mode",
    "proxy",
}
CORE_FIELDS = {"name", "price.amount", "price.currency", "primary_image_url", "source_url"}
RULE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,80}$")

REQUIRED_TOP_LEVEL = {
    "schema_version",
    "rule_id",
    "rule_version",
    "kind",
    "site",
    "scope",
    "capabilities",
    "discovery",
    "fetch",
    "output",
}
OPTIONAL_TOP_LEVEL = {
    "status",
    "created_at",
    "updated_at",
    "extract",
    "normalize",
    "validate",
    "task_defaults",
    "compatibility",
    "evidence",
    "notes",
    "runtime",
    "product_source",
}


class RuleError(ValueError):
    """Raised when a rule package cannot be loaded by this runtime."""


@dataclass
class RulePackage:
    path: Path
    raw: dict[str, Any]

    @property
    def rule_id(self) -> str:
        return str(self.raw["rule_id"])

    @property
    def rule_version(self) -> str:
        return str(self.raw["rule_version"])

    @property
    def kind(self) -> str:
        return str(self.raw["kind"])

    @property
    def runtime(self) -> dict[str, Any]:
        value = self.raw.get("runtime", {})
        return value if isinstance(value, dict) else {}

    @property
    def site(self) -> dict[str, Any]:
        return self.raw["site"]

    @property
    def scope(self) -> dict[str, Any]:
        return self.raw["scope"]

    @property
    def discovery(self) -> dict[str, Any]:
        return self.raw["discovery"]

    @property
    def fetch(self) -> dict[str, Any]:
        return self.raw["fetch"]

    @property
    def capabilities(self) -> dict[str, Any]:
        return self.raw["capabilities"]

    @property
    def output(self) -> dict[str, Any]:
        return self.raw["output"]

    @property
    def task_defaults(self) -> dict[str, Any]:
        return self.raw.get("task_defaults", {})

    @property
    def product_source(self) -> dict[str, Any]:
        value = self.raw.get("product_source", {})
        return value if isinstance(value, dict) else {}

    @property
    def entry_url(self) -> str:
        sources = self.discovery.get("sources")
        if isinstance(sources, list):
            for source in sources:
                if not isinstance(source, dict):
                    continue
                if source.get("url"):
                    return str(source["url"])
                if source.get("urls"):
                    return str(source["urls"][0])
        return str(self.discovery.get("entry_url") or self.site["entry_urls"][0])

    @property
    def sources(self) -> list[dict[str, Any]]:
        sources = self.discovery.get("sources")
        if isinstance(sources, list) and sources:
            return [dict(source) for source in sources if isinstance(source, dict)]
        strategies = self.discovery.get("strategies", [])
        normalized: list[dict[str, Any]] = []
        if "entry_links" in strategies:
            normalized.append(
                {
                    "type": "entry_links",
                    "url": self.entry_url,
                    "link_selector": self.discovery.get("link_selector", ""),
                }
            )
        if normalized:
            return normalized
        return [
            {
                "type": "entry_links",
                "url": self.entry_url,
                "link_selector": self.discovery.get("link_selector", ""),
            }
        ]

    def supports(self, task_type: str) -> bool:
        return bool(self.capabilities.get(task_type))

    def validate_task_type(self, task_type: str) -> None:
        if task_type not in TASK_TYPES:
            raise RuleError(f"unsupported task_type: {task_type!r}")
        if not self.supports(task_type):
            raise RuleError(f"rule {self.rule_id} does not support task_type={task_type}")
        if task_type == "discovery" and not self._output_enabled("url_list"):
            raise RuleError("discovery task needs output.url_list.enabled=true")
        if task_type == "product":
            if not self._output_enabled("product_csv"):
                raise RuleError("product task needs output.product_csv.enabled=true")
            if "extract" not in self.raw:
                raise RuleError("product task needs extract.fields")

    def product_plan(self) -> dict[str, Any]:
        """Return a plan dict compatible with the R06 extractor/validator."""
        discovery = self.discovery
        if "sources" in discovery:
            discovery = {
                "strategies": ["entry_links"],
                "entry_url": self.entry_url,
                "link_selector": discovery.get("link_selector") or "a",
                "product_url_patterns": discovery.get("product_url_patterns", []),
                "url_identity": discovery.get("url_identity", "canonical"),
            }
        return {
            "schema_version": "1.0",
            "plan_id": self.rule_id,
            "plan_version": self.rule_version,
            "kind": "declarative",
            "status": self.raw.get("status", "candidate"),
            "created_at": self.raw.get("created_at", utc_now()),
            "updated_at": self.raw.get("updated_at", utc_now()),
            "site": self.site,
            "scope": self.scope,
            "discovery": discovery,
            "fetch": self.fetch,
            "extract": self.raw.get("extract", {}),
            "normalize": self.raw.get("normalize", {}),
            "validate": self.raw.get("validate", {}),
            "compatibility": self.raw.get(
                "compatibility",
                {"os": ["windows", "linux", "wsl2"], "runtime": "python>=3.11"},
            ),
            "evidence": self.raw.get("evidence", {}),
        }

    def _output_enabled(self, key: str) -> bool:
        section = self.output.get(key, {})
        if isinstance(section, dict):
            return bool(section.get("enabled", True))
        return bool(section)

    def validate_entrypoint(self) -> None:
        """Ensure a hybrid adapter stays inside its package and exists."""
        if self.kind != "hybrid":
            return
        entrypoint = str(self.runtime.get("entrypoint") or "").strip()
        if not entrypoint:
            raise RuleError("hybrid rule needs runtime.entrypoint")
        relative = Path(entrypoint)
        if relative.is_absolute() or any(part == ".." for part in relative.parts):
            raise RuleError("runtime.entrypoint must stay inside the rule package")
        package_root = self.path.parent.resolve()
        resolved = (package_root / relative).resolve()
        try:
            resolved.relative_to(package_root)
        except ValueError as exc:
            raise RuleError("runtime.entrypoint escapes the rule package") from exc
        if not resolved.is_file():
            raise RuleError(f"runtime.entrypoint not found: {resolved}")


def load_rule(path: str | Path) -> RulePackage:
    rule_path = Path(path)
    if not rule_path.is_file():
        raise RuleError(f"rule not found: {rule_path}")
    try:
        data = yaml.safe_load(rule_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RuleError(f"invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise RuleError("rule manifest must be a YAML mapping")
    _validate_common(data)
    rule = RulePackage(path=rule_path, raw=data)
    rule.validate_entrypoint()
    if rule.capabilities.get("product"):
        try:
            validate_plan(rule.product_plan())
        except Exception as exc:
            raise RuleError(f"product rule invalid: {exc}") from exc
    return rule


def _validate_common(data: dict[str, Any]) -> None:
    unknown = set(data) - REQUIRED_TOP_LEVEL - OPTIONAL_TOP_LEVEL
    if unknown:
        raise RuleError(f"unknown top-level keys: {', '.join(sorted(unknown))}")
    missing = REQUIRED_TOP_LEVEL - set(data)
    if missing:
        raise RuleError(f"missing top-level keys: {', '.join(sorted(missing))}")

    if data["schema_version"] not in SCHEMA_VERSIONS:
        raise RuleError(f"unsupported schema_version: {data['schema_version']!r}")
    rule_id = _require_string(data["rule_id"], "rule_id")
    if not RULE_ID_RE.fullmatch(rule_id):
        raise RuleError("rule_id must be lowercase letters, digits and hyphens")
    _require_string(data["rule_version"], "rule_version")
    kind = _require_string(data["kind"], "kind")
    if kind not in SUPPORTED_KINDS:
        raise RuleError(
            f"unsupported kind {kind!r}; supported: {sorted(SUPPORTED_KINDS)}"
        )
    if kind == "hybrid":
        _validate_runtime(data.get("runtime"))
    elif "runtime" in data:
        raise RuleError("runtime is only allowed for kind=hybrid")
    status = data.get("status", "candidate")
    if status not in RULE_STATUSES:
        raise RuleError(f"unsupported status: {status!r}")

    site = _require_mapping(data["site"], "site")
    for key in ("name", "market", "locale", "currency"):
        _require_string(site.get(key), f"site.{key}")
    entry_urls = _require_list(site.get("entry_urls"), "site.entry_urls")
    if not entry_urls:
        raise RuleError("site.entry_urls must not be empty")
    _require_list(site.get("allowed_origins"), "site.allowed_origins")
    _require_list(site.get("allowed_path_prefixes"), "site.allowed_path_prefixes")

    scope = _require_mapping(data["scope"], "scope")
    if not isinstance(scope.get("include", []), list):
        raise RuleError("scope.include must be a list")
    if not isinstance(scope.get("exclude", []), list):
        raise RuleError("scope.exclude must be a list")
    _validate_regex_list(scope.get("include", []), "scope.include")
    _validate_regex_list(scope.get("exclude", []), "scope.exclude")

    capabilities = _require_mapping(data["capabilities"], "capabilities")
    for key in ("discovery", "product"):
        if not isinstance(capabilities.get(key, False), bool):
            raise RuleError(f"capabilities.{key} must be a boolean")
    if not capabilities.get("discovery") and not capabilities.get("product"):
        raise RuleError("at least one capability must be true")

    discovery = _require_mapping(data["discovery"], "discovery")
    sources = discovery.get("sources")
    strategies = discovery.get("strategies")
    if sources is not None:
        _validate_sources(sources, discovery)
        if strategies is not None:
            strategies = _require_list(strategies, "discovery.strategies")
            unsupported = set(strategies) - {"entry_links"}
            if unsupported:
                raise RuleError(
                    "when discovery.sources is present, discovery.strategies "
                    f"may only be ['entry_links']; got {sorted(unsupported)}"
                )
    else:
        strategies = _require_list(strategies, "discovery.strategies")
        if not strategies:
            raise RuleError("discovery.strategies must not be empty")
        unsupported = set(strategies) - SUPPORTED_DISCOVERY
        if unsupported:
            raise RuleError(
                f"v1 runtime supports discovery.strategies={sorted(SUPPORTED_DISCOVERY)}; "
                f"unsupported: {sorted(unsupported)}"
            )
        if "entry_links" in strategies:
            _require_string(discovery.get("link_selector"), "discovery.link_selector")
    adapter_sources = [
        source
        for source in (sources if isinstance(sources, list) else [])
        if isinstance(source, dict) and source.get("type") == "adapter"
    ]
    if kind == "hybrid" and not adapter_sources:
        raise RuleError("hybrid rule needs a discovery.sources entry with type=adapter")
    if kind != "hybrid" and adapter_sources:
        raise RuleError("adapter source requires kind=hybrid")

    patterns = _require_list(
        discovery.get("product_url_patterns"), "discovery.product_url_patterns"
    )
    if not patterns:
        raise RuleError("discovery.product_url_patterns must not be empty")
    for pattern in patterns:
        try:
            re.compile(str(pattern))
        except re.error as exc:
            raise RuleError(f"invalid product_url_patterns regex: {exc}") from exc

    fetch = _require_mapping(data["fetch"], "fetch")
    engine = _require_string(fetch.get("default_engine"), "fetch.default_engine")
    if engine not in SUPPORTED_ENGINES:
        raise RuleError(
            f"unsupported fetch.default_engine {engine!r}; "
            f"supported: {sorted(SUPPORTED_ENGINES)}"
        )
    concurrency = fetch.get("concurrency", 1)
    if not isinstance(concurrency, int) or concurrency < 1:
        raise RuleError("fetch.concurrency must be a positive integer")
    delay_ms = fetch.get("delay_ms", 1000)
    if not isinstance(delay_ms, (int, float)) or delay_ms < 1000:
        raise RuleError("fetch.delay_ms must be >= 1000")
    retry = _require_mapping(fetch.get("retry"), "fetch.retry")
    if not isinstance(retry.get("max_attempts", 1), int) or retry.get("max_attempts", 1) < 1:
        raise RuleError("fetch.retry.max_attempts must be a positive integer")
    if "browser" in fetch:
        _validate_browser_config(fetch["browser"])
    if "per_url_type" in fetch:
        _validate_per_url_type(fetch["per_url_type"])
    if fetch.get("browser") is False:
        engines = {engine}
        per_type = fetch.get("per_url_type")
        if isinstance(per_type, dict):
            engines.update(
                str(settings.get("engine"))
                for settings in per_type.values()
                if isinstance(settings, dict) and settings.get("engine")
            )
        if "browser" in engines:
            raise RuleError(
                "fetch.browser=false conflicts with a browser engine; "
                "remove browser: false or use a static engine"
            )
    advance_types = _listing_advance_types(discovery)
    if advance_types & {"load_more", "infinite_scroll"}:
        navigation_engine = _navigation_engine(fetch, engine)
        if navigation_engine != "browser":
            raise RuleError(
                "load_more/infinite_scroll require a browser engine for navigation; "
                "set fetch.default_engine=browser or "
                "fetch.per_url_type.navigation.engine=browser"
            )
        if data["schema_version"] != "1.2":
            raise RuleError(
                "load_more/infinite_scroll require schema_version 1.2"
            )

    output = _require_mapping(data["output"], "output")
    if not output:
        raise RuleError("output must not be empty")
    for key in output:
        if key not in {"url_list", "product_csv", "task_result"}:
            raise RuleError(f"unknown output section: {key!r}")
    if capabilities.get("discovery") and not _enabled(output.get("url_list")):
        raise RuleError("discovery capability needs output.url_list.enabled=true")
    if capabilities.get("product") and not _enabled(output.get("product_csv")):
        raise RuleError("product capability needs output.product_csv.enabled=true")

    if "task_defaults" in data:
        _validate_task_defaults(data["task_defaults"])

    if capabilities.get("product"):
        for key in ("extract", "normalize", "validate"):
            if key not in data:
                raise RuleError(f"product capability needs {key}")

    if "product_source" in data:
        _validate_product_source(data, fetch)


def _validate_browser_config(value: Any) -> None:
    if isinstance(value, bool):
        return
    browser = _require_mapping(value, "fetch.browser")
    unknown = set(browser) - BROWSER_OPTION_KEYS
    if unknown:
        raise RuleError(
            f"unknown fetch.browser keys: {', '.join(sorted(unknown))}; "
            f"supported: {', '.join(sorted(BROWSER_OPTION_KEYS))}"
        )
    for key in ("headless", "real_chrome", "network_idle", "disable_resources"):
        if key in browser and not isinstance(browser[key], bool):
            raise RuleError(f"fetch.browser.{key} must be a boolean")
    for key in ("challenge_wait_ms", "wait_ms", "network_idle_timeout_ms"):
        if key in browser and (
            isinstance(browser[key], bool)
            or not isinstance(browser[key], int)
            or browser[key] < 0
        ):
            raise RuleError(f"fetch.browser.{key} must be a non-negative integer")
    if "timeout_ms" in browser and (
        isinstance(browser["timeout_ms"], bool)
        or not isinstance(browser["timeout_ms"], (int, float))
        or browser["timeout_ms"] <= 0
    ):
        raise RuleError("fetch.browser.timeout_ms must be positive")
    for key in (
        "executable_path",
        "user_agent",
        "locale",
        "timezone",
        "profile_name",
        "wait_selector",
        "proxy",
    ):
        if key in browser and browser[key] is not None:
            _require_string(browser[key], f"fetch.browser.{key}")
    if "proxy" in browser:
        parsed = urlparse(str(browser["proxy"]))
        if parsed.scheme not in {"http", "https", "socks5"} or not parsed.netloc:
            raise RuleError("fetch.browser.proxy must be an http(s) or socks5 URL")
        if parsed.username or parsed.password:
            raise RuleError("fetch.browser.proxy must not contain credentials")
    if "extra_flags" in browser:
        flags = _require_list(browser["extra_flags"], "fetch.browser.extra_flags")
        for flag in flags:
            _require_string(flag, "fetch.browser.extra_flags[]")
    _validate_page_engine_fields(browser, "fetch.browser")


def _validate_per_url_type(value: Any) -> None:
    per_type = _require_mapping(value, "fetch.per_url_type")
    for item_type, settings in per_type.items():
        path = f"fetch.per_url_type.{item_type}"
        _require_string(item_type, path)
        settings = _require_mapping(settings, path)
        unknown = set(settings) - PAGE_OVERRIDE_KEYS
        if unknown:
            raise RuleError(
                f"unknown {path} keys: {', '.join(sorted(unknown))}; "
                f"supported: {', '.join(sorted(PAGE_OVERRIDE_KEYS))}"
            )
        if "engine" in settings:
            engine = _require_string(settings["engine"], f"{path}.engine")
            if engine not in SUPPORTED_ENGINES:
                raise RuleError(
                    f"unsupported {path}.engine {engine!r}; "
                    f"supported: {sorted(SUPPORTED_ENGINES)}"
                )
        _validate_page_engine_fields(settings, path)


def _validate_page_engine_fields(settings: dict[str, Any], path: str) -> None:
    if "wait_until" in settings:
        value = _require_string(settings["wait_until"], f"{path}.wait_until")
        if value not in SUPPORTED_WAIT_UNTIL:
            raise RuleError(
                f"unsupported {path}.wait_until {value!r}; "
                f"supported: {sorted(SUPPORTED_WAIT_UNTIL)}"
            )
    if "wait_selector_state" in settings:
        value = _require_string(
            settings["wait_selector_state"], f"{path}.wait_selector_state"
        )
        if value not in SUPPORTED_SELECTOR_STATES:
            raise RuleError(
                f"unsupported {path}.wait_selector_state {value!r}; "
                f"supported: {sorted(SUPPORTED_SELECTOR_STATES)}"
            )
    for key in ("network_idle", "disable_resources"):
        if key in settings and not isinstance(settings[key], bool):
            raise RuleError(f"{path}.{key} must be a boolean")
    for key in ("wait_ms", "network_idle_timeout_ms"):
        if key in settings and (
            isinstance(settings[key], bool)
            or not isinstance(settings[key], int)
            or settings[key] < 0
        ):
            raise RuleError(f"{path}.{key} must be a non-negative integer")
    if "timeout_ms" in settings and (
        isinstance(settings["timeout_ms"], bool)
        or not isinstance(settings["timeout_ms"], (int, float))
        or settings["timeout_ms"] <= 0
    ):
        raise RuleError(f"{path}.timeout_ms must be positive")
    if "wait_selector" in settings and settings["wait_selector"] is not None:
        _require_string(settings["wait_selector"], f"{path}.wait_selector")


def _validate_runtime(value: Any) -> None:
    runtime = _require_mapping(value, "runtime")
    for key in ("adapter_id", "adapter_version", "entrypoint", "protocol"):
        _require_string(runtime.get(key), f"runtime.{key}")
    if runtime["protocol"] != "ndjson-stdio-v1":
        raise RuleError(
            f"unsupported runtime.protocol {runtime['protocol']!r}; "
            "supported: ['ndjson-stdio-v1']"
        )
    capabilities = _require_list(
        runtime.get("capabilities"), "runtime.capabilities"
    )
    for capability in capabilities:
        _require_string(capability, "runtime.capabilities[]")
    if "discovery" not in capabilities:
        raise RuleError("runtime.capabilities must include 'discovery'")


def _validate_adapter_browser(value: Any, path: str) -> None:
    browser = _require_mapping(value, path)
    unknown = set(browser) - ADAPTER_BROWSER_KEYS
    if unknown:
        raise RuleError(
            f"unknown {path} keys: {', '.join(sorted(unknown))}; "
            f"supported: {', '.join(sorted(ADAPTER_BROWSER_KEYS))}"
        )
    if "headless" in browser and not isinstance(browser["headless"], bool):
        raise RuleError(f"{path}.headless must be a boolean")
    if "timeout_ms" in browser and (
        isinstance(browser["timeout_ms"], bool)
        or not isinstance(browser["timeout_ms"], (int, float))
        or browser["timeout_ms"] <= 0
    ):
        raise RuleError(f"{path}.timeout_ms must be positive")
    for key in ("locale", "timezone", "wait_state", "profile_mode"):
        if key in browser:
            _require_string(browser[key], f"{path}.{key}")
    if "wait_state" in browser and browser["wait_state"] not in {
        "attached",
        "visible",
        "hidden",
        "detached",
    }:
        raise RuleError(f"{path}.wait_state is not supported")
    if "profile_mode" in browser and browser["profile_mode"] not in {
        "ephemeral",
        "task",
    }:
        raise RuleError(f"{path}.profile_mode must be ephemeral or task")
    if "proxy" in browser:
        _require_string(browser["proxy"], f"{path}.proxy")
        parsed = urlparse(browser["proxy"])
        if parsed.scheme not in {"http", "https", "socks5"} or not parsed.netloc:
            raise RuleError(f"{path}.proxy must be an http(s) or socks5 URL")
        if parsed.username or parsed.password:
            raise RuleError(f"{path}.proxy must not contain credentials")


def _validate_sources(value: Any, discovery: dict[str, Any]) -> None:
    sources = _require_list(value, "discovery.sources")
    if not sources:
        raise RuleError("discovery.sources must not be empty")
    has_entry = False
    has_listing = False
    has_html_index = False
    for index, source in enumerate(sources):
        path = f"discovery.sources[{index}]"
        source = _require_mapping(source, path)
        source_type = _require_string(source.get("type"), f"{path}.type")
        if source_type not in SUPPORTED_SOURCES:
            raise RuleError(
                f"unsupported discovery source type {source_type!r}; "
                f"supported: {sorted(SUPPORTED_SOURCES)}"
            )
        if source_type == "entry_links":
            has_entry = True
            if "url" in source:
                _require_string(source.get("url"), f"{path}.url")
            if "link_selector" in source:
                _require_string(source.get("link_selector"), f"{path}.link_selector")
        if source_type == "listing":
            has_listing = True
            _require_string(source.get("url") or source.get("seed"), f"{path}.url")
            if "product_link_selector" in source:
                _require_string(
                    source.get("product_link_selector"),
                    f"{path}.product_link_selector",
                )
            _validate_advance(source.get("advance", {"type": "none"}), path)
        if source_type == "html_index":
            has_html_index = True
            _require_string(source.get("url") or source.get("seed"), f"{path}.url")
            if "link_selector" in source:
                _require_string(source.get("link_selector"), f"{path}.link_selector")
            if "category_patterns" in source:
                patterns = _require_list(
                    source.get("category_patterns"), f"{path}.category_patterns"
                )
                _validate_regex_list(patterns, f"{path}.category_patterns")
            if "max_depth" in source and (
                isinstance(source["max_depth"], bool)
                or not isinstance(source["max_depth"], int)
                or source["max_depth"] < 0
            ):
                raise RuleError(f"{path}.max_depth must be a non-negative integer")
        if source_type == "public_json":
            _validate_public_json_source(source, path)
        if source_type == "adapter":
            _require_string(source.get("url"), f"{path}.url")
            if "browser" in source:
                _validate_adapter_browser(source["browser"], f"{path}.browser")
            advance = _require_mapping(source.get("advance"), f"{path}.advance")
            _require_string(
                advance.get("item_selector"), f"{path}.advance.item_selector"
            )
            if "container" in advance:
                _require_string(advance.get("container"), f"{path}.advance.container")
            if "id_attribute" in advance:
                _require_string(
                    advance.get("id_attribute"), f"{path}.advance.id_attribute"
                )
            if "mode" in advance:
                mode = _require_string(advance.get("mode"), f"{path}.advance.mode")
                if mode not in SUPPORTED_SCROLL_MODES:
                    raise RuleError(
                        f"unsupported {path}.advance.mode {mode!r}; "
                        f"supported: {sorted(SUPPORTED_SCROLL_MODES)}"
                    )
            if "settle_ms" in advance and (
                isinstance(advance["settle_ms"], bool)
                or not isinstance(advance["settle_ms"], int)
                or advance["settle_ms"] < 0
            ):
                raise RuleError(
                    f"{path}.advance.settle_ms must be a non-negative integer"
                )
            if "no_new_stop" in advance and (
                isinstance(advance["no_new_stop"], bool)
                or not isinstance(advance["no_new_stop"], int)
                or advance["no_new_stop"] < 1
            ):
                raise RuleError(
                    f"{path}.advance.no_new_stop must be a positive integer"
                )
            for key in ("max_batches", "max_seconds"):
                if key in source and (
                    isinstance(source[key], bool)
                    or not isinstance(source[key], int)
                    or source[key] < 1
                ):
                    raise RuleError(f"{path}.{key} must be a positive integer")
        if source_type == "sitemap":
            urls = source.get("urls", [])
            if not isinstance(urls, list):
                raise RuleError(f"{path}.urls must be a list")
            for url in urls:
                _require_string(url, f"{path}.urls[]")
            if "robots" in source and not isinstance(source["robots"], bool):
                raise RuleError(f"{path}.robots must be a boolean")
            if "max_sitemaps" in source and (
                isinstance(source["max_sitemaps"], bool)
                or not isinstance(source["max_sitemaps"], int)
                or source["max_sitemaps"] < 1
            ):
                raise RuleError(f"{path}.max_sitemaps must be a positive integer")
            if "sitemap_patterns" in source:
                patterns = _require_list(
                    source.get("sitemap_patterns"), f"{path}.sitemap_patterns"
                )
                _validate_regex_list(patterns, f"{path}.sitemap_patterns")
    if (
        has_entry
        and not discovery.get("link_selector")
        and not any(
            source.get("type") == "entry_links" and source.get("link_selector")
            for source in sources
        )
    ):
        raise RuleError("entry_links source needs a link_selector")
    if (
        has_listing
        and not discovery.get("link_selector")
        and not any(
            source.get("type") == "listing" and source.get("product_link_selector")
            for source in sources
        )
    ):
        raise RuleError("listing source needs product_link_selector")
    if (
        has_html_index
        and not discovery.get("link_selector")
        and not any(
            source.get("type") == "html_index" and source.get("link_selector")
            for source in sources
        )
    ):
        raise RuleError("html_index source needs link_selector")


def _validate_advance(value: Any, path: str) -> None:
    advance = _require_mapping(value, f"{path}.advance")
    advance_type = _require_string(advance.get("type"), f"{path}.advance.type")
    if advance_type not in SUPPORTED_ADVANCE:
        raise RuleError(
            f"unsupported {path}.advance.type {advance_type!r}; "
            f"supported: {sorted(SUPPORTED_ADVANCE)}"
        )
    if advance_type == "page_param":
        _require_string(advance.get("param", "page"), f"{path}.advance.param")
    if advance_type == "next_link" and "selector" in advance:
        _require_string(advance.get("selector"), f"{path}.advance.selector")
    if advance_type == "load_more":
        _require_string(
            advance.get("button_selector"), f"{path}.advance.button_selector"
        )
        _validate_positive_int(advance.get("max_clicks", 10), f"{path}.advance.max_clicks")
    if advance_type == "infinite_scroll":
        mode = str(advance.get("mode", "auto")).strip().lower()
        if mode not in SUPPORTED_SCROLL_MODES:
            raise RuleError(
                f"unsupported {path}.advance.mode {mode!r}; "
                f"supported: {sorted(SUPPORTED_SCROLL_MODES)}"
            )
        _validate_positive_int(
            advance.get("max_scrolls", 10), f"{path}.advance.max_scrolls"
        )
    if "container" in advance and advance["container"] is not None:
        _require_string(advance.get("container"), f"{path}.advance.container")
    if "item_selector" in advance and advance["item_selector"] is not None:
        _require_string(advance.get("item_selector"), f"{path}.advance.item_selector")
    if "settle_ms" in advance and (
        isinstance(advance["settle_ms"], bool)
        or not isinstance(advance["settle_ms"], int)
        or advance["settle_ms"] < 0
    ):
        raise RuleError(f"{path}.advance.settle_ms must be a non-negative integer")
    if "no_new_stop" in advance:
        _validate_positive_int(
            advance.get("no_new_stop"), f"{path}.advance.no_new_stop"
        )
    if "start" in advance and (
        isinstance(advance["start"], bool) or not isinstance(advance["start"], int)
    ):
        raise RuleError(f"{path}.advance.start must be an integer")
    if "max_pages" in advance and (
        isinstance(advance["max_pages"], bool)
        or not isinstance(advance["max_pages"], int)
        or advance["max_pages"] < 1
    ):
        raise RuleError(f"{path}.advance.max_pages must be a positive integer")


def _listing_advance_types(discovery: dict[str, Any]) -> set[str]:
    types: set[str] = set()
    sources = discovery.get("sources", [])
    if not isinstance(sources, list):
        return types
    for source in sources:
        if not isinstance(source, dict) or source.get("type") != "listing":
            continue
        advance = source.get("advance", {})
        if isinstance(advance, dict) and advance.get("type"):
            types.add(str(advance["type"]))
    return types


def _navigation_engine(fetch: dict[str, Any], default: str) -> str:
    per_type = fetch.get("per_url_type", {})
    if isinstance(per_type, dict):
        navigation = per_type.get("navigation")
        if isinstance(navigation, dict) and navigation.get("engine"):
            return str(navigation["engine"])
    return default


def _validate_positive_int(value: Any, path: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RuleError(f"{path} must be a positive integer")


def _validate_public_json_source(source: dict[str, Any], path: str) -> None:
    _require_string(source.get("url"), f"{path}.url")
    method = str(source.get("method", "GET")).upper()
    if method != "GET":
        raise RuleError(f"{path}.method must be GET in the current runtime")
    _require_string(source.get("items_path"), f"{path}.items_path")
    if not source.get("url_field") and not source.get("url_template"):
        raise RuleError(f"{path} needs url_field or url_template")
    if "url_field" in source:
        _require_string(source.get("url_field"), f"{path}.url_field")
    if "url_template" in source:
        _require_string(source.get("url_template"), f"{path}.url_template")
    pagination = source.get("pagination", {"type": "none"})
    pagination = _require_mapping(pagination, f"{path}.pagination")
    pagination_type = str(pagination.get("type", "none"))
    if pagination_type not in {"none", "page_param", "offset", "cursor"}:
        raise RuleError(f"unsupported {path}.pagination.type: {pagination_type!r}")
    for key in ("param", "offset_param", "limit_param", "cursor_param", "next_cursor_path"):
        if key in pagination:
            _require_string(pagination.get(key), f"{path}.pagination.{key}")
    for key in ("start", "offset"):
        if key in pagination and (
            isinstance(pagination[key], bool)
            or not isinstance(pagination[key], int)
            or pagination[key] < 0
        ):
            raise RuleError(f"{path}.pagination.{key} must be a non-negative integer")
    for key in ("max_pages", "page_size"):
        if key in pagination and (
            isinstance(pagination[key], bool)
            or not isinstance(pagination[key], int)
            or pagination[key] < 1
        ):
            raise RuleError(f"{path}.pagination.{key} must be a positive integer")
    if pagination_type == "cursor" and not pagination.get("next_cursor_path"):
        raise RuleError(f"{path}.pagination.next_cursor_path is required for cursor")


def _validate_product_source(data: dict[str, Any], fetch: dict[str, Any]) -> None:
    raw = _require_mapping(data.get("product_source"), "product_source")
    if data["schema_version"] != "1.3":
        raise RuleError("product_source requires schema_version 1.3")
    if not data["capabilities"].get("product"):
        raise RuleError("product_source requires capabilities.product=true")
    unknown = set(raw) - {
        "type",
        "url",
        "product_url_template",
        "page_size",
        "max_pages",
        "currency",
        "description",
        "variants",
    }
    if unknown:
        raise RuleError(
            f"unknown product_source keys: {', '.join(sorted(unknown))}"
        )
    source_type = _require_string(raw.get("type"), "product_source.type")
    if source_type != "shopify_json":
        raise RuleError(
            f"unsupported product_source.type {source_type!r}; supported: ['shopify_json']"
        )

    origins = {
        f"{urlparse(str(origin)).scheme.lower()}://"
        f"{urlparse(str(origin)).netloc.lower()}".rstrip("/")
        for origin in data["site"].get("allowed_origins", [])
    }
    if "url" in raw:
        _validate_product_source_url(
            _require_string(raw.get("url"), "product_source.url"),
            "product_source.url",
            origins,
        )
    if "product_url_template" in raw:
        template = _require_string(
            raw.get("product_url_template"), "product_source.product_url_template"
        )
        placeholders = _template_placeholders(template)
        if not placeholders & {"handle", "id", "product_id"}:
            raise RuleError(
                "product_source.product_url_template needs {handle}, {id} or "
                "{product_id}"
            )
        if not placeholders <= {"handle", "id", "product_id"}:
            raise RuleError(
                "product_source.product_url_template has unsupported placeholders: "
                f"{sorted(placeholders - {'handle', 'id', 'product_id'})}"
            )
        if "://" in template:
            _validate_product_source_url(
                template.format(handle="handle", id=1, product_id=1),
                "product_source.product_url_template",
                origins,
            )

    if "page_size" in raw:
        _validate_positive_int(raw["page_size"], "product_source.page_size")
        if int(raw["page_size"]) > 250:
            raise RuleError("product_source.page_size must be <= 250 (Shopify limit)")
    if "max_pages" in raw:
        _validate_positive_int(raw["max_pages"], "product_source.max_pages")

    site_currency = str(data["site"].get("currency") or "")
    if "currency" in raw:
        currency = _require_string(raw.get("currency"), "product_source.currency")
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise RuleError("product_source.currency must be a 3-letter uppercase code")
        if site_currency and currency != site_currency:
            raise RuleError(
                "product_source.currency must match site.currency "
                f"({currency!r} != {site_currency!r})"
            )

    description = _require_mapping(
        raw.get("description", {}), "product_source.description"
    )
    unknown = set(description) - {"min_chars", "fallback_engine", "fallback_concurrency"}
    if unknown:
        raise RuleError(
            "unknown product_source.description keys: "
            f"{', '.join(sorted(unknown))}"
        )
    if "min_chars" in description:
        _validate_positive_int(
            description["min_chars"], "product_source.description.min_chars"
        )
    if "fallback_concurrency" in description:
        value = description["fallback_concurrency"]
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 2:
            raise RuleError(
                "product_source.description.fallback_concurrency must be 1 or 2"
            )
    if "fallback_engine" in description:
        engine = _require_string(
            description["fallback_engine"],
            "product_source.description.fallback_engine",
        ).lower()
        if engine not in {"static", "browser"}:
            raise RuleError(
                "product_source.description.fallback_engine must be static or browser"
            )
        effective = _product_engine(fetch)
        if effective != engine:
            raise RuleError(
                "product_source.description.fallback_engine must match the product "
                f"page engine ({engine!r} != {effective!r}); set "
                "fetch.per_url_type.product.engine instead"
            )

    variants = _require_mapping(
        raw.get("variants", {}), "product_source.variants"
    )
    unknown = set(variants) - {"price"}
    if unknown:
        raise RuleError(
            f"unknown product_source.variants keys: {', '.join(sorted(unknown))}"
        )
    if "price" in variants:
        mode = _require_string(variants["price"], "product_source.variants.price")
        if mode not in {"min_positive", "first", "product_price"}:
            raise RuleError(
                "product_source.variants.price must be min_positive, first or "
                "product_price"
            )


def _product_engine(fetch: dict[str, Any]) -> str:
    per_type = fetch.get("per_url_type")
    if isinstance(per_type, dict):
        product = per_type.get("product")
        if isinstance(product, dict) and product.get("engine"):
            engine = str(product["engine"]).lower()
            return "static" if engine == "http_json" else engine
    engine = str(fetch.get("default_engine", "static")).lower()
    return "static" if engine == "http_json" else engine


def _template_placeholders(template: str) -> set[str]:
    placeholders: set[str] = set()
    for _, field_name, _, _ in string.Formatter().parse(template):
        if field_name:
            placeholders.add(field_name.split(".", 1)[0].split("[", 1)[0])
    return placeholders


def _validate_product_source_url(url: str, path: str, origins: set[str]) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuleError(f"{path} must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise RuleError(f"{path} must not contain credentials")
    origin = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}".rstrip("/")
    if origins and origin not in origins:
        raise RuleError(f"{path} origin {origin!r} is not in site.allowed_origins")


def _validate_task_defaults(value: Any) -> None:
    defaults = _require_mapping(value, "task_defaults")
    for key in ("max_urls", "max_products"):
        if key in defaults and (not isinstance(defaults[key], int) or defaults[key] < 1):
            raise RuleError(f"task_defaults.{key} must be a positive integer")
    if "max_seconds" in defaults and (
        not isinstance(defaults["max_seconds"], (int, float)) or defaults["max_seconds"] <= 0
    ):
        raise RuleError("task_defaults.max_seconds must be positive")
    if "max_attempts" in defaults and (
        not isinstance(defaults["max_attempts"], int) or defaults["max_attempts"] < 1
    ):
        raise RuleError("task_defaults.max_attempts must be a positive integer")
    if "retry_backoff_ms" in defaults and (
        not isinstance(defaults["retry_backoff_ms"], (int, float))
        or defaults["retry_backoff_ms"] < 0
    ):
        raise RuleError("task_defaults.retry_backoff_ms must be non-negative")
    concurrency = defaults.get("concurrency", {})
    if concurrency:
        concurrency = _require_mapping(concurrency, "task_defaults.concurrency")
        for key, limit in concurrency.items():
            if key not in {"navigation", "product"}:
                raise RuleError(f"unknown task_defaults.concurrency key: {key!r}")
            if not isinstance(limit, int) or limit < 1:
                raise RuleError("task_defaults concurrency values must be positive integers")


def _enabled(section: Any) -> bool:
    if isinstance(section, dict):
        return bool(section.get("enabled", True))
    return bool(section)


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuleError(f"{name} must be a mapping")
    return value


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuleError(f"{name} must be a non-empty string")
    return value.strip()


def _require_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise RuleError(f"{name} must be a list")
    return value


def _validate_regex_list(values: list[Any], name: str) -> None:
    for pattern in values:
        if not isinstance(pattern, str) or not pattern:
            raise RuleError(f"{name} entries must be non-empty strings")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise RuleError(f"invalid {name} regex: {exc}") from exc
