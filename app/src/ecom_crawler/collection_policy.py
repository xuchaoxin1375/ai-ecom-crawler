"""System-wide collection policy defaults.

This is intentionally separate from the per-site rate policy:

* ``site_rate_policies`` lets an operator tune one domain.
* ``collection_policy`` sets the default formal-run limit and the default
  rate for domains without a site override.

Both are stored in the existing ``app_settings`` table.  Changes affect tasks
created afterwards; running and paused tasks keep their original limits.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .rate_policy import (
    RATE_LIMIT_MAX_CONCURRENCY,
    RATE_LIMIT_MAX_RPS,
    RATE_LIMIT_MIN_RPS,
)

COLLECTION_POLICY_SETTING = "collection_policy"

DEFAULT_COLLECTION_POLICY: dict[str, Any] = {
    "formal_unlimited": True,
    "formal_max_products": 10000,
    "formal_max_seconds": 3600,
    "default_per_domain_rps": None,
    "default_concurrency": None,
}

_FIELDS = set(DEFAULT_COLLECTION_POLICY)


class CollectionPolicyError(ValueError):
    """A collection policy value is malformed or outside its bounds."""


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CollectionPolicyError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise CollectionPolicyError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CollectionPolicyError(f"{name} must be a number")
    number = float(value)
    if number < minimum or number > maximum:
        raise CollectionPolicyError(
            f"{name} must be between {minimum:g} and {maximum:g}"
        )
    return number


def validate_collection_policy(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise CollectionPolicyError("collection policy must be an object")
    unknown = sorted(set(payload) - _FIELDS)
    if unknown:
        raise CollectionPolicyError(f"unknown collection policy field: {unknown[0]}")
    result = dict(DEFAULT_COLLECTION_POLICY)
    if "formal_unlimited" in payload:
        if not isinstance(payload["formal_unlimited"], bool):
            raise CollectionPolicyError("formal_unlimited must be a boolean")
        result["formal_unlimited"] = payload["formal_unlimited"]
    if payload.get("formal_max_products") is not None:
        result["formal_max_products"] = _integer(
            payload["formal_max_products"],
            "formal_max_products",
            1,
            100_000,
        )
    if payload.get("formal_max_seconds") is not None:
        result["formal_max_seconds"] = _integer(
            payload["formal_max_seconds"],
            "formal_max_seconds",
            60,
            86_400,
        )
    if payload.get("default_per_domain_rps") is not None:
        result["default_per_domain_rps"] = round(
            _number(
                payload["default_per_domain_rps"],
                "default_per_domain_rps",
                RATE_LIMIT_MIN_RPS,
                RATE_LIMIT_MAX_RPS,
            ),
            3,
        )
    if payload.get("default_concurrency") is not None:
        result["default_concurrency"] = _integer(
            payload["default_concurrency"],
            "default_concurrency",
            1,
            RATE_LIMIT_MAX_CONCURRENCY,
        )
    return result


def load_collection_policy(store: Any) -> dict[str, Any]:
    raw = store.get_setting(COLLECTION_POLICY_SETTING)
    if not raw:
        return dict(DEFAULT_COLLECTION_POLICY)
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return dict(DEFAULT_COLLECTION_POLICY)
    if not isinstance(value, Mapping):
        return dict(DEFAULT_COLLECTION_POLICY)
    try:
        return validate_collection_policy(value)
    except CollectionPolicyError:
        return dict(DEFAULT_COLLECTION_POLICY)


def dump_collection_policy(policy: Mapping[str, Any]) -> str:
    return json.dumps(
        validate_collection_policy(policy),
        ensure_ascii=False,
        sort_keys=True,
    )


def formal_collection_limits(policy: Mapping[str, Any]) -> dict[str, Any]:
    if bool(policy.get("formal_unlimited", True)):
        return {"max_urls": None, "max_products": None, "max_seconds": None}
    return {
        "max_urls": None,
        "max_products": int(policy["formal_max_products"]),
        "max_seconds": int(policy["formal_max_seconds"]),
    }


def default_rate_overrides(policy: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if policy.get("default_per_domain_rps") is not None:
        result["per_domain_rps"] = float(policy["default_per_domain_rps"])
    if policy.get("default_concurrency") is not None:
        result["concurrency"] = int(policy["default_concurrency"])
    return result
