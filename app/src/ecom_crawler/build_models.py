"""Model selection and explicitly requested, bounded connection checks."""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .harness.opencode import OpenCodeError, OpenCodeHttpError, OpenCodeServer
from .runtime.models import utc_now

MODEL_REF = re.compile(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_./:-]+(?:#[a-zA-Z0-9_.-]+)?")
CATALOG = {
    "opencode-go/deepseek-v4.1-flash": ("DeepSeek V4.1 Flash", ("low", "high", "max")),
    "yjwd-gpt-enterprise/gpt-6.1-terra": (
        "YJWD GPT-6.1 Terra", ("none", "low", "medium", "high", "xhigh", "max"),
    ),
}
PROBE_LIMIT_FIELDS = {
    "opencode-go/deepseek-v4.1-flash": {"max_tokens": 64},
    "yjwd-gpt-enterprise/gpt-6.1-terra": {"max_completion_tokens": 64},
}
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


class ModelPoolError(ValueError):
    pass


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
    """Return the models with known labels and thinking levels.

    Unknown models may still be configured; the UI uses this list for presets
    and only offers bounded probes where a probe request shape is known.
    """
    return [
        {
            "id": key,
            "label": label,
            "variants": list(variants),
            "probe_supported": key in PROBE_LIMIT_FIELDS,
        }
        for key, (label, variants) in CATALOG.items()
    ]


def probe_chat(model: dict[str, str], *, inherit_env: bool) -> int:
    """Use OpenCode's credentials without sending build context or registering tools."""
    limit = PROBE_LIMIT_FIELDS[_model_key(model)]
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


class BuildModelPool:
    def __init__(
        self, raw: str = "", *, inherit_env: bool = True,
    ) -> None:
        self.models: dict[str, dict[str, str]] = {}
        self._inherit_env = inherit_env
        self._results: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._probe_busy = False
        for ref in (item.strip() for item in raw.split(",") if item.strip()):
            model = parse_model_ref(ref)
            key = _model_key(model)
            if key in self.models or len(self.models) >= 16:
                raise ModelPoolError("模型池最多允许 16 个不同模型，同一模型只能配置一次")
            choices = CATALOG.get(key)
            if choices and model.get("variant") not in choices[1]:
                raise ModelPoolError(f"模型池的默认思考等级无效：{key}")
            self.models[key] = model

    def _variants(self, key: str) -> tuple[str, ...]:
        entry = CATALOG.get(key)
        return entry[1] if entry else (self.models[key].get("variant", ""),)

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
            return [{
                "id": key, "label": CATALOG.get(key, (key, ()))[0],
                "variant": model.get("variant", ""), "variants": self._variants(key),
                "probe_supported": key in PROBE_LIMIT_FIELDS,
                "health": {variant: self._results[_full_ref(model | {"variant": variant})]
                           for variant in self._variants(key)
                           if _full_ref(model | {"variant": variant}) in self._results},
            } for key, model in self.models.items()]

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
        model = self.manual(ref)
        if _model_key(model) not in PROBE_LIMIT_FIELDS:
            raise ModelPoolError("该模型未配置小请求探测")
        with self._lock:
            if self._probe_busy:
                raise ModelPoolError("已有模型探测正在运行")
            self._probe_busy = True
        started = time.monotonic()
        status, code = "ok", None
        try:
            try:
                if probe_chat(model, inherit_env=self._inherit_env) < 1:
                    status, code = "failed", "NO_OUTPUT"
            except OpenCodeHttpError as exc:
                upstream = exc.body.get("status") if isinstance(exc.body, dict) else None
                if type(upstream) is int and 100 <= upstream <= 599:
                    code = f"HTTP_{upstream}"
                elif exc.code in {"ModelNotFoundError", "ProviderNotFoundError"}:
                    code = "MODEL_UNAVAILABLE"
                else:
                    code = f"HTTP_{exc.status}"
                status = "failed"
            except (OSError, OpenCodeError):
                status, code = "failed", "CONNECTION_ERROR"
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
