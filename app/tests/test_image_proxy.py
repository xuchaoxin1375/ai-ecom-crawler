from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import ClassVar, Self
from unittest import mock

from fastapi.testclient import TestClient

from ecom_crawler.image_proxy import (
    ImageProxyConfigError,
    ImageProxyError,
    ImageProxyUrlError,
    ProxyAttempt,
    fetch_image,
    image_proxy_attempts,
    validate_image_proxy,
    validate_image_url,
)
from ecom_crawler.runtime.models import Task
from ecom_crawler.runtime.store import TaskStore
from ecom_crawler.web.app import create_app

HEADERS = {
    "Host": "127.0.0.1:8765",
    "Origin": "http://127.0.0.1:8765",
    "X-Requested-With": "XMLHttpRequest",
}
PNG = b"\x89PNG\r\n\x1a\nfixture"


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        *,
        headers: dict[str, str] | None = None,
        content: bytes = b"",
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._content = content

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def iter_bytes(self):
        if self._content:
            yield self._content


class _FakeClient:
    responses: ClassVar[list[_FakeResponse]] = []
    requests: ClassVar[list[tuple[str, str | None]]] = []

    def __init__(self, *, proxy: str | None = None, **_: object) -> None:
        self.proxy = proxy

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def stream(self, method: str, url: str, **_: object) -> _FakeResponse:
        self.requests.append((url, self.proxy))
        return self.responses.pop(0)


class ImageProxyTests(unittest.TestCase):
    def test_config_defaults_and_validation(self) -> None:
        self.assertEqual(
            validate_image_proxy({}),
            {"mode": "auto", "proxy": None},
        )
        with self.assertRaises(ImageProxyConfigError):
            validate_image_proxy({"mode": "specified"})
        with self.assertRaises(ImageProxyConfigError):
            validate_image_proxy(
                {"mode": "specified", "proxy": "http://user:pass@127.0.0.1:7890"}
            )
        with self.assertRaises(ImageProxyConfigError):
            validate_image_proxy({"mode": "auto", "proxy": "ftp://127.0.0.1:21"})
        self.assertEqual(
            validate_image_proxy(
                {"mode": "direct", "proxy": "http://127.0.0.1:7890"}
            ),
            {"mode": "direct", "proxy": None},
        )

    def test_auto_attempts_prefer_task_then_service_then_system_then_direct(self) -> None:
        attempts = image_proxy_attempts(
            mode="auto",
            task_proxy="http://task:8080",
            service_proxy="http://task:8080",
            system_proxy="http://system:8080",
        )
        self.assertEqual(
            attempts,
            [
                ProxyAttempt("task", "http://task:8080"),
                ProxyAttempt("system", "http://system:8080"),
                ProxyAttempt("direct", None),
            ],
        )

    def test_specified_attempts_never_add_direct(self) -> None:
        attempts = image_proxy_attempts(
            mode="specified",
            task_proxy="http://task:8080",
            service_proxy=None,
            system_proxy="http://system:8080",
        )
        self.assertEqual(attempts, [ProxyAttempt("system", "http://system:8080")])

    def test_target_validation_blocks_private_and_non_http(self) -> None:
        self.assertEqual(
            validate_image_url("https://1.1.1.1/image.png?x=1"),
            "https://1.1.1.1/image.png?x=1",
        )
        for value in (
            "file:///etc/passwd",
            "ftp://1.1.1.1/image.png",
            "http://127.0.0.1/image.png",
            "http://localhost/image.png",
            "http://10.0.0.1/image.png",
            "http://user:pass@1.1.1.1/image.png",
        ):
            with self.subTest(value=value), self.assertRaises(ImageProxyUrlError):
                validate_image_url(value)

    def test_fetch_image_uses_response_content_type_and_sniffs_octet_stream(self) -> None:
        with mock.patch("ecom_crawler.image_proxy.httpx.Client", _FakeClient):
            _FakeClient.responses = [
                _FakeResponse(
                    headers={
                        "content-type": "application/octet-stream",
                        "content-length": str(len(PNG)),
                    },
                    content=PNG,
                )
            ]
            _FakeClient.requests = []
            content, content_type = fetch_image(
                "https://1.1.1.1/image.png",
                proxy=None,
            )
        self.assertEqual(content, PNG)
        self.assertEqual(content_type, "image/png")
        self.assertEqual(_FakeClient.requests[0][1], None)

    def test_fetch_image_rejects_svg_and_oversize(self) -> None:
        with mock.patch("ecom_crawler.image_proxy.httpx.Client", _FakeClient):
            _FakeClient.responses = [
                _FakeResponse(
                    headers={"content-type": "image/svg+xml"},
                    content=b"<svg/>",
                )
            ]
            with self.assertRaises(ImageProxyError):
                fetch_image("https://1.1.1.1/image.svg", proxy=None)

            _FakeClient.responses = [
                _FakeResponse(
                    headers={
                        "content-type": "image/png",
                        "content-length": "999",
                    },
                    content=PNG,
                )
            ]
            with self.assertRaises(ImageProxyError):
                fetch_image("https://1.1.1.1/image.png", proxy=None, max_bytes=8)

    def test_fetch_image_rejects_redirect_to_private_address(self) -> None:
        with mock.patch("ecom_crawler.image_proxy.httpx.Client", _FakeClient):
            _FakeClient.responses = [
                _FakeResponse(
                    status_code=302,
                    headers={"location": "http://127.0.0.1/private.png"},
                )
            ]
            with self.assertRaises(ImageProxyUrlError):
                fetch_image("https://1.1.1.1/image.png", proxy=None)


class ImageProxyApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.db_path = root / "tasks.db"
        self.out_root = root / "tasks"
        store = TaskStore(self.db_path)
        store.create_task(
            Task(
                task_id="task-1",
                plan_id="fixture",
                plan_version="1.0.0",
                task_type="product",
                state="FINISHED",
                input={"proxy": "http://task-proxy:8080"},
            )
        )
        self.client = TestClient(
            create_app(self.db_path, self.out_root),
            headers=HEADERS,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_system_image_proxy_round_trip_and_validation(self) -> None:
        self.assertEqual(
            self.client.get("/api/system/image-proxy").json(),
            {
                "mode": "auto",
                "proxy": None,
                "service_proxy_configured": False,
            },
        )
        saved = self.client.put(
            "/api/system/image-proxy",
            json={"mode": "specified", "proxy": "socks5://127.0.0.1:1080"},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["mode"], "specified")
        rejected = self.client.put(
            "/api/system/image-proxy",
            json={"mode": "specified", "proxy": "http://user:pass@127.0.0.1:1"},
        )
        self.assertEqual(rejected.status_code, 422)

    def test_media_endpoint_uses_task_proxy_then_direct(self) -> None:
        captured: list[list[ProxyAttempt]] = []

        def fake_fetch(url: str, attempts: list[ProxyAttempt]):
            captured.append(attempts)
            return PNG, "image/png"

        with mock.patch(
            "ecom_crawler.web.app.fetch_image_with_attempts",
            side_effect=fake_fetch,
        ):
            response = self.client.get(
                "/api/media/image",
                params={
                    "url": "https://1.1.1.1/image.png",
                    "task_id": "task-1",
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertIn("max-age=3600", response.headers["cache-control"])
        self.assertEqual(
            captured[0],
            [
                ProxyAttempt("task", "http://task-proxy:8080"),
                ProxyAttempt("direct", None),
            ],
        )

    def test_media_endpoint_specified_mode_has_no_direct_fallback(self) -> None:
        self.client.put(
            "/api/system/image-proxy",
            json={"mode": "specified", "proxy": "http://system-proxy:8080"},
        )
        captured: list[list[ProxyAttempt]] = []

        def fake_fetch(url: str, attempts: list[ProxyAttempt]):
            captured.append(attempts)
            raise ImageProxyError("proxy unavailable", attempts=["system"])

        with mock.patch(
            "ecom_crawler.web.app.fetch_image_with_attempts",
            side_effect=fake_fetch,
        ):
            response = self.client.get(
                "/api/media/image",
                params={
                    "url": "https://1.1.1.1/image.png",
                    "task_id": "task-1",
                },
            )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            captured[0],
            [ProxyAttempt("system", "http://system-proxy:8080")],
        )
