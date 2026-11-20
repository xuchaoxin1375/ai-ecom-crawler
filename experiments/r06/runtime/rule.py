"""Load and validate the declarative rule subset used by the runtime prototype."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from executor.manifest import validate_plan

from .models import TASK_TYPES, utc_now

SCHEMA_VERSIONS = {"1.0", "1.1"}
RULE_STATUSES = {"candidate", "verified", "deprecated"}
SUPPORTED_KINDS = {"declarative"}
SUPPORTED_DISCOVERY = {"entry_links"}
SUPPORTED_SOURCES = {"entry_links", "sitemap", "listing", "html_index", "public_json"}
SUPPORTED_ADVANCE = {"none", "page_param", "next_link"}
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
        raise RuleError(f"v1 runtime supports kind=declarative only, got {kind!r}")
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
    _require_string(fetch.get("default_engine"), "fetch.default_engine")
    concurrency = fetch.get("concurrency", 1)
    if not isinstance(concurrency, int) or concurrency < 1:
        raise RuleError("fetch.concurrency must be a positive integer")
    delay_ms = fetch.get("delay_ms", 1000)
    if not isinstance(delay_ms, (int, float)) or delay_ms < 1000:
        raise RuleError("fetch.delay_ms must be >= 1000")
    retry = _require_mapping(fetch.get("retry"), "fetch.retry")
    if not isinstance(retry.get("max_attempts", 1), int) or retry.get("max_attempts", 1) < 1:
        raise RuleError("fetch.retry.max_attempts must be a positive integer")

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
        if source_type == "sitemap":
            urls = source.get("urls", [])
            if not isinstance(urls, list):
                raise RuleError(f"{path}.urls must be a list")
            for url in urls:
                _require_string(url, f"{path}.urls[]")
            if not urls and source.get("robots") is not True:
                raise RuleError(f"{path} needs urls or robots=true")
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
