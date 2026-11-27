"""Server-side product-image fetcher with explicit proxy selection.

The browser cannot apply the crawler's per-task proxy to an ``<img>`` request.
This module gives the web UI one same-origin endpoint that resolves the
appropriate egress from the task, the service default and the system image
proxy setting, then fetches the image with a bounded, validated request.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

IMAGE_PROXY_SETTING = "image_proxy"
IMAGE_PROXY_MODES = ("auto", "specified", "direct")
DEFAULT_IMAGE_PROXY: dict[str, Any] = {"mode": "auto", "proxy": None}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_TIMEOUT_SECONDS = 20.0
IMAGE_CONNECT_TIMEOUT_SECONDS = 10.0
MAX_IMAGE_REDIRECTS = 3
MAX_IMAGE_URL_LENGTH = 2048
IMAGE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36 ecom-crawler-image-proxy"
)
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_REDIRECT_LIMIT_MESSAGE = "图片重定向次数过多"

logger = logging.getLogger(__name__)


class ImageProxyConfigError(ValueError):
    """The image proxy setting is malformed or outside its bounds."""


class ImageProxyError(RuntimeError):
    """An image could not be fetched through the selected route."""

    def __init__(self, message: str, *, attempts: list[str] | None = None) -> None:
        super().__init__(message)
        self.attempts = attempts or []


class ImageProxyUrlError(ImageProxyError):
    """The target URL is not an allowed public HTTP(S) image URL."""


@dataclass(frozen=True)
class ProxyAttempt:
    """One egress route attempted for an image fetch."""

    source: str
    proxy: str | None


def _proxy_host(proxy: str) -> str:
    return urlsplit(proxy).hostname or "unknown"


def validate_proxy_url(value: str) -> str:
    """Validate a proxy URL without accepting embedded credentials.

    The same rules as task/build proxies apply: http, https or socks5 URLs and
    no userinfo. Credentials in a URL end up in screenshots, logs and copied
    settings; use a local proxy without authentication instead.
    """

    text = str(value or "").strip()
    if not text:
        raise ImageProxyConfigError("代理 URL 不能为空")
    if len(text) > 500:
        raise ImageProxyConfigError("代理 URL 不能超过 500 个字符")
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https", "socks5"}:
        raise ImageProxyConfigError("代理 URL 只支持 http、https 或 socks5")
    if not parsed.hostname:
        raise ImageProxyConfigError("代理 URL 缺少主机名")
    if parsed.username or parsed.password:
        raise ImageProxyConfigError("代理 URL 不能包含账号或密码")
    if parsed.query or parsed.fragment:
        raise ImageProxyConfigError("代理 URL 不能包含查询参数或片段")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ImageProxyConfigError("代理 URL 端口无效") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ImageProxyConfigError("代理 URL 端口无效")
    return text


def validate_image_proxy(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ImageProxyConfigError("图片代理设置必须是对象")
    unknown = sorted(set(payload) - {"mode", "proxy"})
    if unknown:
        raise ImageProxyConfigError(f"未知的图片代理字段：{unknown[0]}")
    mode = str(payload.get("mode") or "auto").strip().lower()
    if mode not in IMAGE_PROXY_MODES:
        raise ImageProxyConfigError("图片代理模式必须是 auto、specified 或 direct")
    raw_proxy = payload.get("proxy")
    proxy = str(raw_proxy).strip() if raw_proxy is not None else ""
    if mode == "direct":
        proxy = ""
    if proxy:
        proxy = validate_proxy_url(proxy)
    if mode == "specified" and not proxy:
        raise ImageProxyConfigError("指定代理模式需要填写代理 URL")
    return {"mode": mode, "proxy": proxy or None}


def load_image_proxy(store: Any) -> dict[str, Any]:
    raw = store.get_setting(IMAGE_PROXY_SETTING)
    if not raw:
        return dict(DEFAULT_IMAGE_PROXY)
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return dict(DEFAULT_IMAGE_PROXY)
    if not isinstance(value, Mapping):
        return dict(DEFAULT_IMAGE_PROXY)
    try:
        return validate_image_proxy(value)
    except ImageProxyConfigError:
        return dict(DEFAULT_IMAGE_PROXY)


def dump_image_proxy(setting: Mapping[str, Any]) -> str:
    return json.dumps(
        validate_image_proxy(setting),
        ensure_ascii=False,
        sort_keys=True,
    )


def image_proxy_attempts(
    *,
    mode: str,
    task_proxy: str | None,
    service_proxy: str | None,
    system_proxy: str | None,
) -> list[ProxyAttempt]:
    """Resolve the bounded route list for the selected mode.

    Auto deliberately de-duplicates identical proxy URLs so a service default
    that matches the task proxy is not requested twice. Direct is always the
    last auto fallback and is never added to specified mode.
    """

    def clean(value: str | None) -> str | None:
        text = (value or "").strip()
        return text or None

    selected = clean(system_proxy)
    if mode == "specified":
        return [ProxyAttempt("system", selected)]
    if mode == "direct":
        return [ProxyAttempt("direct", None)]

    attempts: list[ProxyAttempt] = []
    seen: set[str] = set()
    for source, value in (
        ("task", clean(task_proxy)),
        ("service", clean(service_proxy)),
        ("system", selected),
    ):
        if value and value not in seen:
            seen.add(value)
            attempts.append(ProxyAttempt(source, value))
    attempts.append(ProxyAttempt("direct", None))
    return attempts


def _address_is_public(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(address.is_global)


def _hostname_is_public(hostname: str) -> bool:
    host = hostname.strip().strip("[]").rstrip(".")
    if not host:
        raise ImageProxyUrlError("图片 URL 缺少主机名")
    lowered = host.lower()
    if lowered == "localhost" or lowered.endswith((".localhost", ".local", ".internal")):
        raise ImageProxyUrlError("图片地址不是公网地址")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise ImageProxyUrlError("无法解析图片域名") from exc
    if not addresses or not all(_address_is_public(item) for item in addresses):
        raise ImageProxyUrlError("图片地址不是公网地址")
    return True


def validate_image_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ImageProxyUrlError("图片 URL 不能为空")
    if len(text) > MAX_IMAGE_URL_LENGTH:
        raise ImageProxyUrlError("图片 URL 过长")
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"}:
        raise ImageProxyUrlError("图片 URL 只支持 http 或 https")
    if not parsed.hostname:
        raise ImageProxyUrlError("图片 URL 缺少主机名")
    if parsed.username or parsed.password:
        raise ImageProxyUrlError("图片 URL 不能包含账号或密码")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ImageProxyUrlError("图片 URL 端口无效") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ImageProxyUrlError("图片 URL 端口无效")
    _hostname_is_public(parsed.hostname)
    return text


def _content_type(response: httpx.Response, content: bytes) -> str:
    raw = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    if raw == "image/svg+xml":
        # Serving SVG as a top-level document can execute embedded script. The
        # product pipeline does not need SVG images; keep the proxy raster-only.
        raise ImageProxyError("不支持 SVG 图片")
    if raw.startswith("image/"):
        return raw
    if raw in {"", "application/octet-stream", "binary/octet-stream"}:
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if content.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if content.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
            return "image/webp"
        if content.startswith(b"BM"):
            return "image/bmp"
        if content.startswith((b"II*\x00", b"MM\x00*")):
            return "image/tiff"
        if content[4:12] in {b"ftypavif", b"ftypavis"}:
            return "image/avif"
    raise ImageProxyError("图片源返回的不是可识别的图片")


def fetch_image(
    url: str,
    *,
    proxy: str | None,
    timeout: float = IMAGE_TIMEOUT_SECONDS,
    max_bytes: int = MAX_IMAGE_BYTES,
) -> tuple[bytes, str]:
    """Fetch one image with redirects, size and content-type guards."""

    current = validate_image_url(url)
    if proxy:
        proxy = validate_proxy_url(proxy)
    request_timeout = httpx.Timeout(
        timeout,
        connect=min(timeout, IMAGE_CONNECT_TIMEOUT_SECONDS),
    )
    headers = {
        "User-Agent": IMAGE_USER_AGENT,
        "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8",
    }
    # trust_env=False keeps direct attempts genuinely direct and prevents a
    # shell HTTP(S)_PROXY from silently changing the selected egress.
    with httpx.Client(
        proxy=proxy,
        timeout=request_timeout,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        for redirect in range(MAX_IMAGE_REDIRECTS + 1):
            with client.stream("GET", current, headers=headers) as response:
                if response.status_code in _REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location:
                        raise ImageProxyError("图片重定向缺少目标地址")
                    if redirect >= MAX_IMAGE_REDIRECTS:
                        raise ImageProxyError(_REDIRECT_LIMIT_MESSAGE)
                    current = validate_image_url(urljoin(current, location))
                    continue
                if response.status_code >= 400:
                    raise ImageProxyError(f"图片源返回 HTTP {response.status_code}")
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise ImageProxyError("图片超过大小上限")
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        raise ImageProxyError("图片超过大小上限")
                if not content:
                    raise ImageProxyError("图片源返回了空内容")
                return bytes(content), _content_type(response, bytes(content))
    raise ImageProxyError(_REDIRECT_LIMIT_MESSAGE)


def fetch_image_with_attempts(
    url: str,
    attempts: list[ProxyAttempt],
    *,
    timeout: float = IMAGE_TIMEOUT_SECONDS,
    max_bytes: int = MAX_IMAGE_BYTES,
) -> tuple[bytes, str]:
    """Try the selected routes in order and return the first usable image."""

    validate_image_url(url)
    errors: list[str] = []
    for attempt in attempts:
        try:
            return fetch_image(url, proxy=attempt.proxy, timeout=timeout, max_bytes=max_bytes)
        except ImageProxyUrlError:
            # A private/invalid target is independent of the egress; trying
            # more proxies would only repeat the same rejected request.
            raise
        except (
            ImageProxyConfigError,
            ImageProxyError,
            httpx.HTTPError,
            OSError,
        ) as exc:
            marker = attempt.source if attempt.proxy is None else f"{attempt.source} proxy"
            errors.append(f"{marker}: {exc}")
            logger.info(
                "image proxy attempt failed: route=%s proxy_host=%s host=%s error=%s",
                attempt.source,
                _proxy_host(attempt.proxy) if attempt.proxy else "direct",
                urlsplit(url).hostname or "unknown",
                exc,
            )
    raise ImageProxyError("图片加载失败，请检查图片代理设置", attempts=errors)
