"""Server-wide product-preview display preferences.

List thumbnails go through the same-origin image endpoint.  Loading every
thumbnail can be expensive on long product lists, so operators can disable
list preloading while keeping on-demand image previews available.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

PREVIEW_SETTINGS_SETTING = "preview_settings"
REALTIME_LIMIT_MIN = 10
REALTIME_LIMIT_MAX = 200
DEFAULT_REALTIME_LIMIT = 50
DEFAULT_PREVIEW_SETTINGS: dict[str, Any] = {
    "thumbnails_enabled": True,
    "realtime_limit": DEFAULT_REALTIME_LIMIT,
}
_FIELDS = set(DEFAULT_PREVIEW_SETTINGS)


class PreviewSettingsError(ValueError):
    """The preview display setting is malformed."""


def validate_preview_settings(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise PreviewSettingsError("列表与预览设置必须是对象")
    unknown = sorted(set(payload) - _FIELDS)
    if unknown:
        raise PreviewSettingsError(f"未知的列表与预览字段：{unknown[0]}")
    thumbnails = payload.get("thumbnails_enabled", True)
    if not isinstance(thumbnails, bool):
        raise PreviewSettingsError("thumbnails_enabled 必须是布尔值")
    limit = payload.get("realtime_limit", DEFAULT_REALTIME_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise PreviewSettingsError("realtime_limit 必须是整数")
    if not REALTIME_LIMIT_MIN <= limit <= REALTIME_LIMIT_MAX:
        raise PreviewSettingsError(
            f"realtime_limit 必须在 {REALTIME_LIMIT_MIN}–{REALTIME_LIMIT_MAX} 之间"
        )
    return {"thumbnails_enabled": thumbnails, "realtime_limit": limit}


def load_preview_settings(store: Any) -> dict[str, Any]:
    raw = store.get_setting(PREVIEW_SETTINGS_SETTING)
    if not raw:
        return dict(DEFAULT_PREVIEW_SETTINGS)
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return dict(DEFAULT_PREVIEW_SETTINGS)
    if not isinstance(value, Mapping):
        return dict(DEFAULT_PREVIEW_SETTINGS)
    try:
        return validate_preview_settings(value)
    except PreviewSettingsError:
        return dict(DEFAULT_PREVIEW_SETTINGS)


def dump_preview_settings(setting: Mapping[str, Any]) -> str:
    return json.dumps(
        validate_preview_settings(setting),
        ensure_ascii=False,
        sort_keys=True,
    )
