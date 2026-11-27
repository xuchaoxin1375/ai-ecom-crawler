"""Per-site collection rate policies.

Policies are intentionally small and declarative: they only describe how fast a
site may be requested and how a task should retry.  They are stored in the
existing ``app_settings`` table under one JSON key so a policy survives restarts
without a schema migration.  A policy applies to tasks created after it is
saved; running tasks keep the limits they were created with.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

SITE_RATE_POLICIES_SETTING = "site_rate_policies"

RATE_LIMIT_MIN_RPS = 0.1
RATE_LIMIT_MAX_RPS = 10.0
RATE_LIMIT_MAX_CONCURRENCY = 8
RATE_LIMIT_MAX_DELAY_MS = 10_000
RATE_LIMIT_MAX_ATTEMPTS = 5
RATE_LIMIT_MAX_BACKOFF_MS = 60_000

_POLICY_FIELDS = (
    "per_domain_rps",
    "concurrency",
    "delay_ms",
    "max_attempts",
    "backoff_ms",
)


class RatePolicyError(ValueError):
    """A site rate policy is malformed or outside the supported bounds."""


def normalize_domain(value: str) -> str:
    """Return the host key used for policy lookup."""
    text = str(value or "").strip().lower().rstrip(".")
    if "://" in text:
        text = urlsplit(text).hostname or text
    return text


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RatePolicyError(f"{name} must be a number")
    number = float(value)
    if number < minimum or number > maximum:
        raise RatePolicyError(
            f"{name} must be between {minimum:g} and {maximum:g}"
        )
    return number


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RatePolicyError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise RatePolicyError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def validate_policy(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one policy and return only the explicitly set fields.

    ``None`` means "inherit" and is dropped.  Unknown keys are rejected so a
    typo cannot silently leave a task on the default rate.
    """
    if not isinstance(payload, Mapping):
        raise RatePolicyError("rate policy must be an object")
    unknown = sorted(set(payload) - set(_POLICY_FIELDS))
    if unknown:
        raise RatePolicyError(f"unknown rate policy field: {unknown[0]}")
    result: dict[str, Any] = {}
    if payload.get("per_domain_rps") is not None:
        result["per_domain_rps"] = round(
            _number(
                payload["per_domain_rps"],
                "per_domain_rps",
                RATE_LIMIT_MIN_RPS,
                RATE_LIMIT_MAX_RPS,
            ),
            3,
        )
    if payload.get("concurrency") is not None:
        result["concurrency"] = _integer(
            payload["concurrency"],
            "concurrency",
            1,
            RATE_LIMIT_MAX_CONCURRENCY,
        )
    if payload.get("delay_ms") is not None:
        result["delay_ms"] = _integer(
            payload["delay_ms"],
            "delay_ms",
            0,
            RATE_LIMIT_MAX_DELAY_MS,
        )
    if payload.get("max_attempts") is not None:
        result["max_attempts"] = _integer(
            payload["max_attempts"],
            "max_attempts",
            1,
            RATE_LIMIT_MAX_ATTEMPTS,
        )
    if payload.get("backoff_ms") is not None:
        result["backoff_ms"] = _integer(
            payload["backoff_ms"],
            "backoff_ms",
            0,
            RATE_LIMIT_MAX_BACKOFF_MS,
        )
    return result


def load_policies(store: Any) -> dict[str, dict[str, Any]]:
    """Read all stored policies, ignoring malformed legacy entries."""
    raw = store.get_setting(SITE_RATE_POLICIES_SETTING)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(value, Mapping):
        return {}
    policies: dict[str, dict[str, Any]] = {}
    for domain, item in value.items():
        key = normalize_domain(str(domain))
        if not key or not isinstance(item, Mapping):
            continue
        try:
            policies[key] = validate_policy(item)
        except RatePolicyError:
            continue
    return policies


def dump_policies(policies: Mapping[str, Mapping[str, Any]]) -> str:
    return json.dumps(
        {
            normalize_domain(domain): dict(policy)
            for domain, policy in policies.items()
            if normalize_domain(domain) and policy
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def effective_policy(
    policy: Mapping[str, Any] | None,
    *,
    default_rps: float,
    rule_fetch: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return display values without inventing a measured throughput."""
    fetch = rule_fetch if isinstance(rule_fetch, Mapping) else {}
    retry = fetch.get("retry") if isinstance(fetch.get("retry"), Mapping) else {}
    defaults: dict[str, Any] = {
        "per_domain_rps": round(float(default_rps or 1.0), 3),
        "concurrency": max(1, int(fetch.get("concurrency", 1) or 1)),
        "delay_ms": 0,
        "max_attempts": int(retry.get("max_attempts", 2) or 2),
        "backoff_ms": int(retry.get("backoff_ms", 1000) or 1000),
    }
    merged = dict(defaults)
    if isinstance(policy, Mapping):
        merged.update({key: policy[key] for key in _POLICY_FIELDS if key in policy})
    return merged
