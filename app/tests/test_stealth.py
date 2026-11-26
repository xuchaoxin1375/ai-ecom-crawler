from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from ecom_crawler.runtime.fetcher import UnsupportedAdvanceError, normalize_engine
from ecom_crawler.runtime.stealth import StealthConfig, StealthFetcher


class FakeSession:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []
        self.closed = False
        self.context = SimpleNamespace(request=FakeRequest())

    def fetch(self, url: str, **kwargs: Any) -> Any:
        self.calls.append({"url": url, **kwargs})
        return self.response

    def close(self) -> None:
        self.closed = True


class FakeRequest:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> Any:
        self.calls.append({"url": url, **kwargs})
        return SimpleNamespace(
            status=200,
            url=url,
            headers={"content-type": "application/gzip"},
            body=lambda: b"\x1f\x8bcompressed",
        )


class StealthConfigTests(unittest.TestCase):
    def test_default_engine_has_challenge_floor(self) -> None:
        config = StealthConfig.from_fetch({"timeout_ms": 45000, "browser": {}})
        self.assertEqual(config.timeout_ms, 240_000)
        self.assertEqual(config.challenge_wait_ms, 180_000)
        self.assertEqual(config.profile_name, "stealth-profile")
        self.assertTrue(config.solve_cloudflare)

    def test_profile_and_wait_options_are_namespaced(self) -> None:
        config = StealthConfig.from_fetch(
            {
                "timeout_ms": 300000,
                "browser": {
                    "profile_name": "parts",
                    "wait_selector": "main",
                    "wait_selector_state": "visible",
                    "wait_ms": 250,
                    "network_idle": True,
                    "disable_resources": True,
                },
            }
        )
        self.assertEqual(config.timeout_ms, 300_000)
        self.assertEqual(config.profile_name, "stealth-parts")
        self.assertEqual(config.wait_selector, "main")
        self.assertEqual(config.wait_selector_state, "visible")
        self.assertEqual(config.wait_ms, 250)
        self.assertTrue(config.network_idle)
        self.assertTrue(config.disable_resources)

    def test_engine_name_is_normalized(self) -> None:
        self.assertEqual(normalize_engine("stealth"), "stealth")


class StealthFetcherTests(unittest.TestCase):
    def _fetcher(
        self, response: Any, *, timeout_ms: int = 240_000
    ) -> tuple[StealthFetcher, FakeSession, Path]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        session = FakeSession(response)
        fetcher = StealthFetcher(
            mock.Mock(),
            task_id="task-1",
            out_root=root,
            config=StealthConfig(timeout_ms=timeout_ms),
            session=session,
            started=True,
        )
        return fetcher, session, root

    def test_get_maps_response_and_uses_challenge_options(self) -> None:
        response = SimpleNamespace(
            status=200,
            url="https://example.test/p/1",
            body=b"<html><title>Product one</title><body>ok</body></html>",
            headers={"content-type": "text/html; charset=utf-8"},
        )
        fetcher, session, _ = self._fetcher(response)
        result = fetcher.get("https://example.test/p/1")
        self.assertEqual(result.status, 200)
        self.assertIn(b"Product one", result.body)
        self.assertFalse(result.meta["challenge_suspected"])
        self.assertEqual(session.calls[0]["solve_cloudflare"], True)
        self.assertEqual(session.calls[0]["timeout"], 240_000)
        self.assertEqual(fetcher.requests, 1)
        self.assertIn("stealth", fetcher.describe()["engines_used"])

    def test_gzipped_sitemap_warms_origin_then_uses_context_request(self) -> None:
        response = SimpleNamespace(
            status=200,
            url="https://example.test/",
            body=b"<html></html>",
            headers={},
        )
        fetcher, session, _ = self._fetcher(response)
        result = fetcher.get("https://example.test/sitemap.xml.gz")
        self.assertEqual(result.status, 200)
        self.assertEqual(result.body, b"\x1f\x8bcompressed")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0]["url"], "https://example.test/")
        self.assertEqual(
            session.context.request.calls[0]["url"],
            "https://example.test/sitemap.xml.gz",
        )

    def test_sitemap_index_uses_page_then_children_use_context(self) -> None:
        response = SimpleNamespace(
            status=200,
            url="https://example.test/sitemap.xml",
            body=b"<sitemapindex><sitemap><loc>child</loc></sitemap></sitemapindex>",
            headers={"content-type": "text/xml"},
        )
        fetcher, session, _ = self._fetcher(response)
        index = fetcher.get("https://example.test/sitemap.xml")
        self.assertEqual(index.status, 200)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.context.request.calls, [])
        child = fetcher.get("https://example.test/products.xml.gz")
        self.assertEqual(child.body, b"\x1f\x8bcompressed")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(
            session.context.request.calls[0]["url"],
            "https://example.test/products.xml.gz",
        )

    def test_challenge_title_marks_the_result(self) -> None:
        response = SimpleNamespace(
            status=403,
            url="https://example.test/",
            body=b"<html><title>Just a moment...</title></html>",
            headers={},
        )
        fetcher, _, _ = self._fetcher(response)
        result = fetcher.get("https://example.test/")
        self.assertTrue(result.meta["challenge_suspected"])
        self.assertEqual(result.meta["challenge_title"], "Just a moment...")

    def test_challenge_wait_raises_request_ceiling(self) -> None:
        response = SimpleNamespace(status=200, url="", body=b"", headers={})
        fetcher, _, _ = self._fetcher(response)
        fetcher.config = StealthConfig(
            timeout_ms=240_000, challenge_wait_ms=300_000
        )
        self.assertEqual(fetcher._request_timeout_ms(), 360_000)
        self.assertEqual(fetcher._fetch_options()["timeout"], 360_000)

    def test_listing_actions_are_not_supported(self) -> None:
        response = SimpleNamespace(status=200, url="", body=b"", headers={})
        fetcher, _, _ = self._fetcher(response)
        with self.assertRaises(UnsupportedAdvanceError):
            fetcher.get_listing(
                "https://example.test/",
                advance={"type": "load_more"},
            )

    def test_close_releases_session(self) -> None:
        response = SimpleNamespace(status=200, url="", body=b"", headers={})
        fetcher, session, _ = self._fetcher(response)
        fetcher.close()
        self.assertTrue(session.closed)
        self.assertIsNone(fetcher._session)
        self.assertFalse(fetcher.describe()["browser_launched"])


if __name__ == "__main__":
    unittest.main()
