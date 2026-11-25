"""Model selection and explicitly requested, bounded connection checks."""

from __future__ import annotations

import copy
import json
import re
import subprocess
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .harness.opencode import (
    OpenCodeError,
    OpenCodeHttpError,
    OpenCodeServer,
    child_environment,
    resolve_opencode_command,
)
from .runtime.models import utc_now

MODEL_REF = re.compile(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_./:-]+(?:#[a-zA-Z0-9_.-]+)?")
CATALOG = {
    "commandcode/deepseek/deepseek-v4.1-flash": (
        "CommandCode DeepSeek V4.1 Flash", ("low", "high", "max"),
    ),
    "opencode-go/deepseek-v4.1-flash": ("DeepSeek V4.1 Flash", ("low", "high", "max")),
    "yjwd-gpt-enterprise/gpt-6.1-terra": (
        "YJWD GPT-6.1 Terra", ("none", "low", "medium", "high", "xhigh", "max"),
    ),
}
PROBE_FIELDS = {
    "opencode-go/deepseek-v4.1-flash": ("max_tokens",),
    "yjwd-gpt-enterprise/gpt-6.1-terra": ("max_completion_tokens",),
}
DEFAULT_PROBE_FIELDS = ("max_tokens", "max_completion_tokens")
PROBE_PLUGIN = """\
import { Plugin } from "@opencode/plugin"
import { writeFileSync } from "node:fs"
import { join } from "node:path"

export default Plugin.define({
  id: "ecom-model-probe",
  async setup(ctx) {
    await ctx.session.hook("retry", (event) => {
      event.decision = { retry: false }
    })
    await ctx.session.hook("http.response", (event) => {
      const status = event.response.status
      if (status < 400) return
      writeFileSync(join(ctx.location.directory, "probe-upstream.status"), String(status))
      // A health check reports the first failure, not the result of a retry.
      event.response = new Response('{"error":{"message":"Model health check failed"}}', {
        status: 400, headers: { "content-type": "application/json" },
      })
    })
    writeFileSync(join(ctx.location.directory, "probe-hook.ready"), "ready")
  },
})
"""


DISCOVERY_TTL_SECONDS = 60.0
_discovery_lock = threading.Lock()
_discovery_cache: tuple[float, list[dict[str, Any]]] | None = None
_metadata_cache: dict[str, dict[str, Any]] = {}


class ModelPoolError(ValueError):
    pass


def _positive_int(value: Any) -> int | None:
    return value if type(value) is int and value > 0 else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _available_model(
    ref: str, metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    provider, model = ref.split("/", 1)
    entry = CATALOG.get(ref)
    metadata = metadata or {}
    variants: list[str] = []
    if metadata:
        raw_variants = metadata.get("variants")
        if isinstance(raw_variants, list):
            variants = [
                str(item["id"])
                for item in raw_variants
                if isinstance(item, dict) and item.get("id")
            ]
    elif entry:
        variants = list(entry[1])
    limit = metadata.get("limit")
    limit = limit if isinstance(limit, dict) else {}
    capabilities = metadata.get("capabilities")
    capabilities = capabilities if isinstance(capabilities, dict) else {}
    compatibility = metadata.get("compatibility")
    compatibility = compatibility if isinstance(compatibility, dict) else {}
    max_tokens_field = compatibility.get("maxTokensField")
    if max_tokens_field not in {"max_tokens", "max_completion_tokens"}:
        max_tokens_field = ""
    return {
        "id": ref,
        "provider": provider,
        "model": model,
        "label": str(entry[0] if entry else (metadata.get("name") or model)),
        "variants": variants,
        "probe_supported": True,
        "known": bool(metadata) or entry is not None,
        "context_window": _positive_int(limit.get("context")),
        "max_output_tokens": _positive_int(limit.get("output")),
        "capabilities": (
            {
                "tools": bool(capabilities.get("tools", False)),
                "input": _string_list(capabilities.get("input")),
                "output": _string_list(capabilities.get("output")),
            }
            if metadata
            else None
        ),
        "status": metadata.get("status") if metadata else None,
        "enabled": (
            metadata.get("enabled")
            if isinstance(metadata.get("enabled"), bool)
            else None
        ),
        "max_tokens_field": max_tokens_field,
    }


def model_metadata(ref: str) -> dict[str, Any] | None:
    with _discovery_lock:
        item = _metadata_cache.get(ref)
        return copy.deepcopy(item) if item is not None else None


def _api_model_signature(models: list[dict[str, Any]]) -> tuple[Any, ...]:
    signature: list[Any] = []
    for item in models:
        provider = str(item.get("providerID") or "")
        model_id = str(item.get("modelID") or "")
        variants = tuple(
            str(variant.get("id"))
            for variant in item.get("variants") or []
            if isinstance(variant, dict) and variant.get("id")
        )
        limit = item.get("limit")
        limit = limit if isinstance(limit, dict) else {}
        signature.append(
            (
                f"{provider}/{model_id}",
                variants,
                limit.get("context"),
                limit.get("output"),
            )
        )
    return tuple(sorted(signature))


def _discover_from_opencode_api(
    *, inherit_env: bool, timeout: float
) -> list[dict[str, Any]]:
    """Read resolved model metadata from a short-lived OpenCode server.

    ``/api/model`` settles asynchronously after the server becomes ready:
    provider integrations can be added in stages (for example, a custom
    provider appears one beat after the first snapshot).  Wait through a short
    settling window and accept only a snapshot that has remained unchanged.
    """
    server = OpenCodeServer(
        inherit_env=inherit_env,
        startup_timeout=min(max(timeout, 5.0), 15.0),
    )
    try:
        client = server.start()
        deadline = time.monotonic() + timeout
        previous: tuple[Any, ...] | None = None
        last_models: list[dict[str, Any]] = []
        first_non_empty_at: float | None = None
        stable_since: float | None = None
        while time.monotonic() < deadline:
            remaining = max(0.5, deadline - time.monotonic())
            models = client.list_models(timeout=min(5.0, remaining))
            now = time.monotonic()
            if models:
                last_models = models
                signature = _api_model_signature(models)
                if signature != previous:
                    previous = signature
                    first_non_empty_at = first_non_empty_at or now
                    stable_since = now
                elif (
                    first_non_empty_at is not None
                    and now - first_non_empty_at >= 2.0
                    and stable_since is not None
                    and now - stable_since >= 0.75
                ):
                    return models
            time.sleep(0.25)
        if last_models:
            return last_models
        raise ModelPoolError("OpenCode 模型元数据未在时限内就绪")
    finally:
        server.stop()


def _list_cli_refs(*, inherit_env: bool, timeout: float) -> list[str]:
    try:
        command = [*resolve_opencode_command(), "models", "--standalone"]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_environment({}, inherit=inherit_env),
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, OpenCodeError) as exc:
        raise ModelPoolError(
            f"无法读取 OpenCode 模型列表：{type(exc).__name__}"
        ) from exc
    if completed.returncode != 0:
        raise ModelPoolError("OpenCode 模型列表读取失败")
    refs = sorted({
        line.strip()
        for line in completed.stdout.splitlines()
        if MODEL_REF.fullmatch(line.strip())
    })
    if not refs:
        raise ModelPoolError("OpenCode 没有返回可用模型")
    return refs


def discover_models(
    *,
    inherit_env: bool = True,
    refresh: bool = False,
    timeout: float = 25.0,
) -> list[dict[str, Any]]:
    """List models and capabilities visible to OpenCode.

    The rich source is OpenCode's ``/api/model`` snapshot: it includes names,
    reasoning variants, context/output limits and capabilities.  If that
    endpoint cannot be read, fall back to the ID-only CLI so the settings page
    remains usable, marking those entries as metadata-less.

    No model request is sent by discovery.
    """
    global _discovery_cache
    now = time.monotonic()
    with _discovery_lock:
        if (
            not refresh
            and _discovery_cache is not None
            and now - _discovery_cache[0] < DISCOVERY_TTL_SECONDS
        ):
            return copy.deepcopy(_discovery_cache[1])

        models: list[dict[str, Any]] = []
        try:
            api_models = _discover_from_opencode_api(
                inherit_env=inherit_env, timeout=timeout
            )
        except (OSError, subprocess.SubprocessError, OpenCodeError, ModelPoolError):
            api_models = []

        if api_models:
            seen: set[str] = set()
            for item in api_models:
                if item.get("type") not in {None, "chat"}:
                    continue
                if item.get("enabled") is False:
                    continue
                provider = str(item.get("providerID") or "").strip()
                model_id = str(item.get("modelID") or "").strip()
                ref = f"{provider}/{model_id}" if provider and model_id else ""
                if not ref or not MODEL_REF.fullmatch(ref) or ref in seen:
                    continue
                seen.add(ref)
                models.append(_available_model(ref, item))
            models.sort(key=lambda item: item["id"])

        if not models:
            refs = _list_cli_refs(inherit_env=inherit_env, timeout=timeout)
            models = [_available_model(ref) for ref in refs]

        _metadata_cache.clear()
        _metadata_cache.update({item["id"]: item for item in models})
        _discovery_cache = (now, models)
        return copy.deepcopy(models)


def parse_model_ref(ref: str) -> dict[str, str]:
    if not MODEL_REF.fullmatch(ref):
        raise ModelPoolError("模型须使用 provider/model#variant 格式")
    provider, model = ref.split("/", 1)
    model, _, variant = model.partition("#")
    return {"providerID": provider, "id": model, **({"variant": variant} if variant else {})}


def _model_key(model: dict[str, Any]) -> str:
    return f"{model['providerID']}/{model['id']}"


def _full_ref(model: dict[str, Any]) -> str:
    variant = model.get("variant")
    return _model_key(model) + (f"#{variant}" if variant else "")


def known_models() -> list[dict[str, Any]]:
    """Return curated presets plus any metadata already discovered.

    The available-model endpoint is the full catalog; this shorter list is kept
    for the manual preset selector and for startup fallback validation.
    """
    result: list[dict[str, Any]] = []
    for key, (label, variants) in CATALOG.items():
        metadata = model_metadata(key) or {}
        result.append(
            {
                "id": key,
                "label": label,
                "variants": list(metadata.get("variants") or variants),
                "probe_supported": True,
            }
        )
    return result


def _probe_fields_for(
    key: str, metadata: dict[str, Any] | None
) -> tuple[str, ...]:
    if key in PROBE_FIELDS:
        return PROBE_FIELDS[key]
    compatibility = metadata.get("compatibility") if metadata else None
    field = compatibility.get("maxTokensField") if isinstance(compatibility, dict) else None
    if field in {"max_tokens", "max_completion_tokens"}:
        return (field,)
    return DEFAULT_PROBE_FIELDS


def probe_chat(
    model: dict[str, str],
    *,
    inherit_env: bool,
    max_tokens_field: str = "max_tokens",
) -> int:
    """Use OpenCode's credentials without sending build context or registering tools."""
    limit = {max_tokens_field: 64}
    overrides: dict[str, Any] = {"body": limit}
    if variant := model.get("variant"):
        overrides["variants"] = [{"id": variant, "body": limit}]
    config = {
        "providers": {model["providerID"]: {"models": {model["id"]: overrides}}},
        "warming": False,
    }
    with TemporaryDirectory(prefix="ecom-model-check-") as tmp:
        directory = Path(tmp)
        local_config = directory / ".opencode"
        plugin_dir = local_config / "ecom-model-probe"
        plugin_dir.mkdir(parents=True)
        config["plugins"] = ["./ecom-model-probe"]
        (local_config / "opencode.json").write_text(json.dumps(config), encoding="utf-8")
        (plugin_dir / "package.json").write_text(json.dumps({
            "name": "ecom-model-probe", "type": "module", "exports": {".": "./index.js"},
        }), encoding="utf-8")
        (plugin_dir / "index.js").write_text(PROBE_PLUGIN, encoding="utf-8")
        server = OpenCodeServer(cwd=directory, inherit_env=inherit_env, startup_timeout=8)
        client = None
        session_id = None
        try:
            client = server.start()
            session_id = client.create_session(
                directory=str(directory), model=model, permissions=[
                    {"action": "*", "resource": "*", "effect": "deny"}
                ], timeout=5,
            )["id"]
            client.initialize_probe_plugins(str(directory))
            ready = directory / "probe-hook.ready"
            deadline = time.monotonic() + 3
            while not ready.is_file():
                if time.monotonic() >= deadline:
                    raise ModelPoolError("OpenCode 探测插件未就绪，未发出模型请求")
                time.sleep(0.05)
            try:
                return client.generate_probe(session_id)
            except OpenCodeHttpError:
                upstream = directory / "probe-upstream.status"
                if upstream.is_file():
                    code = upstream.read_text(encoding="utf-8")
                    if re.fullmatch(r"[45][0-9]{2}", code):
                        raise OpenCodeHttpError(
                            int(code), "PROVIDER_STATUS", "probe failed", None
                        ) from None
                raise
        finally:
            try:
                if client is not None and session_id is not None:
                    client.delete_session(session_id, timeout=3)
            except OpenCodeError:
                # A dead child cannot accept further requests. Stop it below.
                pass
            finally:
                server.stop()


def _variants_for_key(key: str) -> tuple[str, ...] | None:
    metadata = model_metadata(key)
    if metadata is not None and metadata.get("known"):
        variants = tuple(
            str(item)
            for item in metadata.get("variants") or []
            if isinstance(item, str) and item
        )
        return variants or ("",)
    entry = CATALOG.get(key)
    return entry[1] if entry else None


class BuildModelPool:
    def __init__(
        self, raw: str = "", *, inherit_env: bool = True,
    ) -> None:
        self.models: dict[str, dict[str, str]] = {}
        self.default_ref: str | None = None
        self._inherit_env = inherit_env
        self._results: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._probe_busy = False
        for ref in (item.strip() for item in raw.split(",") if item.strip()):
            model = parse_model_ref(ref)
            key = _model_key(model)
            if key in self.models or len(self.models) >= 16:
                raise ModelPoolError("模型池最多允许 16 个不同模型，同一模型只能配置一次")
            choices = _variants_for_key(key)
            if choices is not None:
                variant = model.get("variant")
                if variant is None:
                    if choices != ("",):
                        raise ModelPoolError(f"模型池的默认思考等级无效：{key}")
                elif variant not in choices:
                    raise ModelPoolError(f"模型池的默认思考等级无效：{key}")
            self.models[key] = model

    def _variants(self, key: str) -> tuple[str, ...]:
        choices = _variants_for_key(key)
        current = self.models[key].get("variant")
        if choices is not None:
            if current and current not in choices:
                return (current, *choices)
            return choices
        return (current or "",)

    def set_default(self, ref: str | None) -> None:
        """Pin new builds to one pool entry; empty means rotate."""
        if not ref:
            self.default_ref = None
            return
        asked = parse_model_ref(ref)
        if _full_ref(asked) not in self.refs():
            raise ModelPoolError("默认模型必须是模型池中的一项，且档位与配置一致")
        self.default_ref = _full_ref(asked)

    def manual(self, ref: str) -> dict[str, str]:
        asked = parse_model_ref(ref)
        key = _model_key(asked)
        if key not in self.models:
            raise ModelPoolError("所选模型不在已配置的模型池中")
        variant = asked.get("variant")
        if variant is None:
            return dict(self.models[key])
        if variant not in self._variants(key):
            raise ModelPoolError("所选思考等级不在该模型的可选范围内")
        return asked

    def balanced(self, last_key: str | None) -> dict[str, str]:
        keys = list(self.models)
        start = keys.index(last_key) + 1 if last_key in self.models else 0
        with self._lock:
            for key in keys[start:] + keys[:start]:
                model = self.models[key]
                if self._results.get(_full_ref(model), {}).get("status") != "failed":
                    return dict(model)
        raise ModelPoolError("模型池没有可分配模型；请重测可用性或手动选择")

    def describe(self) -> list[dict[str, Any]]:
        with self._lock:
            rows: list[dict[str, Any]] = []
            for key, model in self.models.items():
                metadata = model_metadata(key) or {}
                variants = list(self._variants(key))
                rows.append(
                    {
                        "id": key,
                        "label": (
                            CATALOG[key][0]
                            if key in CATALOG
                            else str(metadata.get("label") or key)
                        ),
                        "variant": model.get("variant", ""),
                        "variants": variants,
                        "probe_supported": bool(
                            metadata.get("probe_supported", True)
                        ),
                        "known": (
                            bool(metadata.get("known"))
                            if metadata
                            else key in CATALOG
                        ),
                        "context_window": metadata.get("context_window"),
                        "max_output_tokens": metadata.get("max_output_tokens"),
                        "capabilities": metadata.get("capabilities"),
                        "health": {
                            variant: self._results[
                                _full_ref(model | {"variant": variant})
                            ]
                            for variant in variants
                            if _full_ref(model | {"variant": variant})
                            in self._results
                        },
                    }
                )
            return rows

    def refs(self) -> list[str]:
        return [_full_ref(model) for model in self.models.values()]

    def _configured_refs(self) -> set[str]:
        refs: set[str] = set()
        for key, model in self.models.items():
            for variant in self._variants(key):
                refs.add(_full_ref(model | {"variant": variant}))
        return refs

    def snapshot_health(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {ref: dict(result) for ref, result in self._results.items()}

    def restore_health(self, snapshot: dict[str, dict[str, Any]]) -> None:
        """Keep probe results for models that remain in the pool after a save."""
        allowed = self._configured_refs()
        with self._lock:
            self._results = {
                ref: dict(result)
                for ref, result in snapshot.items()
                if ref in allowed
            }

    def check(self, ref: str) -> dict[str, Any]:
        """Probe any valid model ref, whether or not it is already pooled."""
        model = parse_model_ref(ref)
        key = _model_key(model)
        metadata = model_metadata(key)
        variant = model.get("variant")
        if metadata is not None and variant is not None:
            variants = [
                str(item)
                for item in metadata.get("variants") or []
                if isinstance(item, str) and item
            ]
            if variants and variant not in variants:
                raise ModelPoolError("所选思考等级不在该模型的可选范围内")
        fields = _probe_fields_for(key, metadata)
        with self._lock:
            if self._probe_busy:
                raise ModelPoolError("已有模型探测正在运行")
            self._probe_busy = True
        started = time.monotonic()
        status, code = "ok", None
        try:
            for index, max_tokens_field in enumerate(fields):
                try:
                    output = probe_chat(
                        model,
                        inherit_env=self._inherit_env,
                        max_tokens_field=max_tokens_field,
                    )
                    if output < 1:
                        status, code = "failed", "NO_OUTPUT"
                    break
                except OpenCodeHttpError as exc:
                    if exc.status in {400, 422} and index + 1 < len(fields):
                        # Provider schemas differ on max_tokens vs
                        # max_completion_tokens; retry once with the other
                        # bounded request shape.
                        continue
                    upstream = (
                        exc.body.get("status") if isinstance(exc.body, dict) else None
                    )
                    if type(upstream) is int and 100 <= upstream <= 599:
                        code = f"HTTP_{upstream}"
                    elif exc.code in {"ModelNotFoundError", "ProviderNotFoundError"}:
                        code = "MODEL_UNAVAILABLE"
                    else:
                        code = f"HTTP_{exc.status}"
                    status = "failed"
                    break
                except (OSError, OpenCodeError):
                    status, code = "failed", "CONNECTION_ERROR"
                    break
            result = {
                "status": status, "code": code, "checked_at": utc_now(),
                "latency_ms": round((time.monotonic() - started) * 1000),
            }
            with self._lock:
                self._results[_full_ref(model)] = result
            return result
        finally:
            with self._lock:
                self._probe_busy = False
