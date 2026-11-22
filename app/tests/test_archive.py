from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from ecom_crawler.runtime.archive import (
    ArchiveError,
    ArchiveFetcher,
    ArchiveMissError,
    ArchiveStore,
    archive_url_key,
)
from ecom_crawler.runtime.models import FetchResult


class FakeFetcher:
    def __init__(self, body: bytes = b"<html>ok</html>") -> None:
        self.body = body
        self.calls = 0
        self.requests = 0
        self.retries = 0
        self.thread_affine = False

    def get(self, url: str, *, item_type: str | None = None) -> FetchResult:
        self.calls += 1
        self.requests += 1
        return FetchResult(status=200, url=url, body=self.body, meta={"content_type": "text/html"})

    def describe(self) -> dict[str, Any]:
        return {"engine": "fake", "engines_used": ["fake"] if self.requests else []}


class ArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temporary.name) / "archive"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_sample_store_roundtrip_and_limit(self) -> None:
        store = ArchiveStore(self.root, mode="sample", sample_limit=1)
        self.assertTrue(
            store.save(
                "https://example.test/a?x=1",
                FetchResult(status=200, url="https://example.test/a?x=1", body=b"<html>A</html>"),
                engine="test",
            )
        )
        body, meta = store.lookup("https://example.test/a?x=1")
        self.assertEqual(body, b"<html>A</html>")
        self.assertEqual(meta["status"], 200)
        self.assertFalse(
            store.save(
                "https://example.test/b",
                FetchResult(status=200, url="https://example.test/b", body=b"<html>B</html>"),
                engine="test",
            )
        )
        stats = store.stats()
        self.assertEqual(stats["pages"], 1)
        self.assertEqual(stats["hits"], 1)
        self.assertTrue(stats["limit_reached"])
        body_path = store.body_path("https://example.test/a?x=1")
        self.assertTrue(body_path.is_file())
        self.assertEqual(gzip.decompress(body_path.read_bytes()), b"<html>A</html>")
        index = (self.root / "index.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(index), 1)
        self.assertEqual(json.loads(index[0])["url"], "https://example.test/a?x=1")

    def test_full_store_ignores_off_and_failed_status(self) -> None:
        off = ArchiveStore(self.root, mode="off")
        self.assertFalse(
            off.save(
                "https://example.test/a",
                FetchResult(status=200, url="https://example.test/a", body=b"x"),
            )
        )
        full = ArchiveStore(self.root, mode="full")
        self.assertFalse(
            full.save(
                "https://example.test/a",
                FetchResult(status=500, url="https://example.test/a", body=b"missing"),
            )
        )
        self.assertTrue(
            full.save(
                "https://example.test/a",
                FetchResult(status=200, url="https://example.test/a", body=b"ok"),
            )
        )

    def test_offline_miss_and_mode_guard(self) -> None:
        with self.assertRaises(ArchiveError):
            ArchiveFetcher(FakeFetcher(), ArchiveStore(self.root, mode="sample"), offline=True)
        fetcher = ArchiveFetcher(
            FakeFetcher(), ArchiveStore(self.root, mode="full"), offline=True
        )
        with self.assertRaises(ArchiveMissError):
            fetcher.get("https://example.test/missing")

    def test_offline_replay_does_not_call_inner(self) -> None:
        store = ArchiveStore(self.root, mode="full")
        store.save(
            "https://example.test/a",
            FetchResult(status=200, url="https://example.test/a", body=b"<html>cached</html>"),
        )
        inner = FakeFetcher()
        fetcher = ArchiveFetcher(inner, store, offline=True)
        result = fetcher.get("https://example.test/a")
        self.assertEqual(result.body, b"<html>cached</html>")
        self.assertTrue(result.meta["archived"])
        self.assertEqual(inner.calls, 0)
        self.assertEqual(fetcher.requests, 0)
        self.assertEqual(fetcher.describe()["archive"]["hits"], 1)

    def test_reuse_hits_archive_then_falls_back_to_network(self) -> None:
        store = ArchiveStore(self.root, mode="sample", sample_limit=2)
        store.save(
            "https://example.test/a",
            FetchResult(status=200, url="https://example.test/a", body=b"cached"),
        )
        inner = FakeFetcher(body=b"fresh")
        fetcher = ArchiveFetcher(inner, store, reuse=True)
        self.assertEqual(fetcher.get("https://example.test/a").body, b"cached")
        self.assertEqual(fetcher.get("https://example.test/b").body, b"fresh")
        self.assertEqual(inner.calls, 1)

    def test_url_key_ignores_fragment(self) -> None:
        self.assertEqual(
            archive_url_key("https://Example.test/a?x=1#top"),
            archive_url_key("https://example.test/a?x=1"),
        )


if __name__ == "__main__":
    unittest.main()
