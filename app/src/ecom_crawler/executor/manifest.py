"""Load and validate the declarative plan subset supported by R06."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .errors import PlanError

SCHEMA_VERSIONS = {"1.0"}
SUPPORTED_KINDS = {"declarative"}
PLAN_STATUSES = {"candidate", "verified", "deprecated"}
SUPPORTED_DISCOVERY = {"entry_links"}
SUPPORTED_EXTRACTORS = {
    "json_ld",
    "css_text",
    "css_attr",
    "css_html",
    "title",
    "breadcrumb",
    "option_groups",
    "price_pair",
    "canonical",
    "constant",
}
CORE_FIELDS = {"name", "price.amount", "price.currency", "primary_image_url", "source_url"}
OPTIONAL_FIELDS = {"description_html", "category", "brand", "options"}
KNOWN_FIELDS = CORE_FIELDS | OPTIONAL_FIELDS
DESCRIPTION_STATUSES = {"complete", "partial", "fallback", "not_provided", "failed"}
TAKE_VALUES = {"first", "first_positive", "min_positive"}
ASSERTION_OPS = {">", ">=", "<", "<=", "==", "matches"}
PLAN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,80}$")

REQUIRED_TOP_LEVEL = {
    "schema_version",
    "plan_id",
    "plan_version",
    "kind",
    "status",
    "created_at",
    "updated_at",
    "site",
    "scope",
    "discovery",
    "fetch",
    "extract",
    "normalize",
    "validate",
    "compatibility",
}
OPTIONAL_TOP_LEVEL = {"runtime", "entrypoint", "rules", "evidence", "notes"}


def load_plan(path: str | Path) -> dict[str, Any]:
    plan_path = Path(path)
    if not plan_path.is_file():
        raise PlanError(f"plan not found: {plan_path}")
    try:
        data = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PlanError(f"invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise PlanError("plan must be a YAML mapping")
    validate_plan(data)
    return data


def validate_plan(plan: dict[str, Any]) -> None:
    unknown = set(plan) - REQUIRED_TOP_LEVEL - OPTIONAL_TOP_LEVEL
    if unknown:
        raise PlanError(f"unknown top-level keys: {', '.join(sorted(unknown))}")
    missing = REQUIRED_TOP_LEVEL - set(plan)
    if missing:
        raise PlanError(f"missing top-level keys: {', '.join(sorted(missing))}")

    schema_version = plan["schema_version"]
    if not isinstance(schema_version, str) or schema_version not in SCHEMA_VERSIONS:
        raise PlanError(f"unsupported schema_version: {schema_version!r}")

    plan_id = _require_string(plan["plan_id"], "plan_id")
    if not PLAN_ID_RE.fullmatch(plan_id):
        raise PlanError("plan_id must be lowercase letters, digits and hyphens")
    _require_string(plan["plan_version"], "plan_version")

    kind = _require_string(plan["kind"], "kind")
    if kind not in SUPPORTED_KINDS:
        raise PlanError(f"R06 supports kind=declarative only, got {kind!r}")
    status = _require_string(plan["status"], "status")
    if status not in PLAN_STATUSES:
        raise PlanError(f"unsupported status: {status!r}")
    _validate_iso_datetime(plan["created_at"], "created_at")
    _validate_iso_datetime(plan["updated_at"], "updated_at")

    _validate_site(_require_mapping(plan["site"], "site"))
    _validate_scope(_require_mapping(plan["scope"], "scope"))
    _validate_discovery(_require_mapping(plan["discovery"], "discovery"))
    _validate_fetch(_require_mapping(plan["fetch"], "fetch"))
    fields = _validate_extract(_require_mapping(plan["extract"], "extract"))
    _validate_normalize(_require_mapping(plan["normalize"], "normalize"))
    _validate_validate(_require_mapping(plan["validate"], "validate"), fields)
    _validate_compatibility(_require_mapping(plan["compatibility"], "compatibility"))

    runtime = plan.get("runtime")
    if runtime is not None:
        runtime = _require_mapping(runtime, "runtime")
        _require_string(runtime.get("entrypoint"), "runtime.entrypoint")
        _require_string(runtime.get("protocol"), "runtime.protocol")

    if status == "verified":
        evidence = _require_mapping(plan.get("evidence"), "evidence")
        sample_urls = _require_list(evidence.get("sample_urls"), "evidence.sample_urls")
        if not sample_urls:
            raise PlanError("verified plans need evidence.sample_urls")
        if evidence.get("verified_at") in (None, ""):
            raise PlanError("verified plans need evidence.verified_at")


def plan_entry_url(plan: dict[str, Any]) -> str:
    discovery = plan["discovery"]
    return str(discovery.get("entry_url") or plan["site"]["entry_urls"][0])


def _validate_site(site: dict[str, Any]) -> None:
    for key in ("name", "market", "locale", "currency"):
        _require_string(site.get(key), f"site.{key}")
    entry_urls = _require_list(site.get("entry_urls"), "site.entry_urls")
    if not entry_urls:
        raise PlanError("site.entry_urls must not be empty")
    for url in entry_urls:
        _validate_http_url(url, "site.entry_urls")
    origins = _require_list(site.get("allowed_origins"), "site.allowed_origins")
    if not origins:
        raise PlanError("site.allowed_origins must not be empty")
    for origin in origins:
        _validate_http_url(origin, "site.allowed_origins")
    prefixes = _require_list(site.get("allowed_path_prefixes"), "site.allowed_path_prefixes")
    if not prefixes:
        raise PlanError("site.allowed_path_prefixes must not be empty")
    for prefix in prefixes:
        if not isinstance(prefix, str) or not prefix.startswith("/"):
            raise PlanError("site.allowed_path_prefixes entries must start with '/'")


def _validate_scope(scope: dict[str, Any]) -> None:
    include = scope.get("include", [])
    exclude = scope.get("exclude", [])
    if not isinstance(include, list) or not isinstance(exclude, list):
        raise PlanError("scope.include and scope.exclude must be lists")
    _validate_regex_list(include, "scope.include")
    _validate_regex_list(exclude, "scope.exclude")
    if "max_products" in scope:
        _require_positive_int(scope["max_products"], "scope.max_products")
    if "max_seconds" in scope:
        _require_positive_number(scope["max_seconds"], "scope.max_seconds")


def _validate_regex_list(values: list[Any], name: str) -> None:
    for pattern in values:
        if not isinstance(pattern, str) or not pattern:
            raise PlanError(f"{name} entries must be non-empty strings")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise PlanError(f"invalid {name} regex: {exc}") from exc


def _validate_discovery(discovery: dict[str, Any]) -> None:
    strategies = _require_list(discovery.get("strategies"), "discovery.strategies")
    if not strategies:
        raise PlanError("discovery.strategies must not be empty")
    unsupported = set(strategies) - SUPPORTED_DISCOVERY
    if unsupported:
        raise PlanError(
            "R06 supports discovery.strategies="
            f"{sorted(SUPPORTED_DISCOVERY)}; unsupported: {sorted(unsupported)}"
        )
    if "entry_links" in strategies:
        _require_string(discovery.get("link_selector"), "discovery.link_selector")
        patterns = _require_list(
            discovery.get("product_url_patterns"), "discovery.product_url_patterns"
        )
        if not patterns:
            raise PlanError("discovery.product_url_patterns must not be empty")
        for pattern in patterns:
            if not isinstance(pattern, str):
                raise PlanError("discovery.product_url_patterns entries must be strings")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise PlanError(f"invalid product_url_patterns regex: {exc}") from exc
    identity = discovery.get("url_identity", "canonical")
    if identity not in {"canonical", "final_url", "normalized_path"}:
        raise PlanError(f"unsupported discovery.url_identity: {identity!r}")


def _validate_fetch(fetch: dict[str, Any]) -> None:
    _require_string(fetch.get("default_engine"), "fetch.default_engine")
    concurrency = _require_positive_int(fetch.get("concurrency"), "fetch.concurrency")
    if concurrency != 1:
        raise PlanError("R06 supports fetch.concurrency=1 only")
    delay_ms = _require_non_negative_number(fetch.get("delay_ms"), "fetch.delay_ms")
    if delay_ms < 1000:
        raise PlanError("R06 requires fetch.delay_ms >= 1000")
    _require_positive_number(fetch.get("timeout_ms"), "fetch.timeout_ms")
    retry = _require_mapping(fetch.get("retry"), "fetch.retry")
    _require_positive_int(retry.get("max_attempts"), "fetch.retry.max_attempts")
    _require_non_negative_number(retry.get("backoff_ms"), "fetch.retry.backoff_ms")
    if "max_seconds" in fetch:
        _require_positive_number(fetch["max_seconds"], "fetch.max_seconds")


def _validate_extract(extract: dict[str, Any]) -> dict[str, Any]:
    fields = _require_mapping(extract.get("fields"), "extract.fields")
    if not fields:
        raise PlanError("extract.fields must not be empty")
    unknown = set(fields) - KNOWN_FIELDS
    if unknown:
        raise PlanError(f"unknown extract fields: {', '.join(sorted(unknown))}")
    missing = CORE_FIELDS - set(fields)
    if missing:
        raise PlanError(f"missing core extract fields: {', '.join(sorted(missing))}")
    for field_name, spec in fields.items():
        _validate_field_spec(field_name, spec)
    return fields


def _validate_field_spec(field_name: str, spec: Any) -> None:
    spec = _require_mapping(spec, f"extract.fields.{field_name}")
    fallbacks = _require_list(spec.get("fallbacks"), f"extract.fields.{field_name}.fallbacks")
    if not fallbacks:
        raise PlanError(f"extract.fields.{field_name}.fallbacks must not be empty")
    for index, fallback in enumerate(fallbacks):
        _validate_fallback(field_name, index, fallback)


def _validate_fallback(field_name: str, index: int, fallback: Any) -> None:
    path = f"extract.fields.{field_name}.fallbacks[{index}]"
    fallback = _require_mapping(fallback, path)
    extractor_type = _require_string(fallback.get("type"), f"{path}.type")
    if extractor_type not in SUPPORTED_EXTRACTORS:
        raise PlanError(f"unsupported extractor type {extractor_type!r} at {path}")
    required_keys = {
        "json_ld": ("path",),
        "css_text": ("selector",),
        "css_attr": ("selector", "attr"),
        "css_html": ("selector",),
        "breadcrumb": ("selector",),
        "option_groups": ("group_selector",),
        "price_pair": ("gross", "pretax"),
        "canonical": (),
        "title": (),
        "constant": ("value",),
    }[extractor_type]
    for key in required_keys:
        if fallback.get(key) in (None, ""):
            raise PlanError(f"{path}.{key} is required for {extractor_type}")
    if extractor_type == "price_pair":
        for side in ("gross", "pretax"):
            side_spec = _require_mapping(fallback.get(side), f"{path}.{side}")
            _require_string(side_spec.get("selector"), f"{path}.{side}.selector")
            _require_string(side_spec.get("attr"), f"{path}.{side}.attr")
    take = fallback.get("take", "first")
    if take not in TAKE_VALUES:
        raise PlanError(f"unsupported take={take!r} at {path}")
    status = fallback.get("description_status")
    if status is not None and status not in DESCRIPTION_STATUSES:
        raise PlanError(f"unsupported description_status={status!r} at {path}")


def _validate_normalize(normalize: dict[str, Any]) -> None:
    price = _require_mapping(normalize.get("price"), "normalize.price")
    if price.get("positive_only") is False:
        raise PlanError("normalize.price.positive_only must be true")
    description = _require_mapping(normalize.get("description"), "normalize.description")
    if description.get("mode") != "clean_html":
        raise PlanError("R06 supports normalize.description.mode=clean_html only")
    statuses = _require_list(
        description.get("statuses"), "normalize.description.statuses"
    )
    unknown = set(statuses) - DESCRIPTION_STATUSES
    if unknown:
        raise PlanError(f"unsupported normalize.description.statuses: {sorted(unknown)}")
    options = _require_mapping(normalize.get("options"), "normalize.options")
    if options.get("exclude_quantity") is False:
        raise PlanError("normalize.options.exclude_quantity must be true")
    if options.get("strip_price_delta") is False:
        raise PlanError("normalize.options.strip_price_delta must be true")


def _validate_validate(validate: dict[str, Any], fields: dict[str, Any]) -> None:
    required = _require_list(validate.get("required_fields"), "validate.required_fields")
    if not required:
        raise PlanError("validate.required_fields must not be empty")
    unknown = set(required) - set(fields)
    if unknown:
        raise PlanError(f"validate.required_fields not in extract.fields: {sorted(unknown)}")
    assertions = validate.get("assertions", [])
    if not isinstance(assertions, list):
        raise PlanError("validate.assertions must be a list")
    for assertion in assertions:
        assertion = _require_mapping(assertion, "validate.assertions[]")
        _require_string(assertion.get("field"), "validate.assertions[].field")
        op = _require_string(assertion.get("op"), "validate.assertions[].op")
        if op not in ASSERTION_OPS:
            raise PlanError(f"unsupported assertion op: {op!r}")
        if "value" not in assertion:
            raise PlanError("validate.assertions[].value is required")


def _validate_compatibility(compatibility: dict[str, Any]) -> None:
    os_list = _require_list(compatibility.get("os"), "compatibility.os")
    if not os_list:
        raise PlanError("compatibility.os must not be empty")
    _require_string(compatibility.get("runtime"), "compatibility.runtime")


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlanError(f"{name} must be a mapping")
    return value


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlanError(f"{name} must be a non-empty string")
    return value.strip()


def _require_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise PlanError(f"{name} must be a list")
    return value


def _require_positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PlanError(f"{name} must be a positive integer")
    return value


def _require_positive_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise PlanError(f"{name} must be a positive number")
    return float(value)


def _require_non_negative_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise PlanError(f"{name} must be a non-negative number")
    return float(value)


def _validate_http_url(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        raise PlanError(f"{name} entries must be http(s) URLs")


def _validate_iso_datetime(value: Any, name: str) -> None:
    if not isinstance(value, str):
        raise PlanError(f"{name} must be an ISO 8601 string")
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise PlanError(f"{name} is not ISO 8601: {value!r}") from exc
