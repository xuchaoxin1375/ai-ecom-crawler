from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from ecom_crawler.runtime.browser import BrowserFetcher
from ecom_crawler.runtime.fetcher import ScraplingFetcher
from ecom_crawler.runtime.models import FetchResult
from ecom_crawler.runtime.telemetry import RequestRecorder


def read_lines(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class RequestRecorderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.path = self.root / "requests.ndjson"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_records_are_appended_and_truncation_is_marked(self) -> None:
        recorder = RequestRecorder(self.path, max_records=2)
        try:
            recorder.record({"ts": "2026-11-26T22:07:00Z", "status": 200})
            recorder.record({"ts": "2026-11-26T22:07:01Z", "status": 200})
            recorder.record({"ts": "2026-11-26T22:07:02Z", "status": 200})
            self.assertEqual(recorder.stats["records"], 2)
            self.assertTrue(recorder.stats["truncated"])
        finally:
            recorder.close()
        rows = read_lines(self.path)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1]["event"], "truncated")
        self.assertEqual(rows[-1]["reason"], "records")

    def test_existing_file_counts_toward_the_limit(self) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            handle.write('{"ts":"2026-11-26T22:07:00Z","status":200}\n')
        recorder = RequestRecorder(self.path, max_records=1)
        try:
            recorder.record({"ts": "2026-11-26T22:07:01Z", "status": 200})
            self.assertTrue(recorder.stats["truncated"])
        finally:
            recorder.close()
        rows = read_lines(self.path)
        self.assertEqual(rows[0]["status"], 200)
        self.assertEqual(rows[-1]["event"], "truncated")
        self.assertEqual(rows[-1]["reason"], "existing")

    def test_resume_after_truncation_does_not_append_more(self) -> None:
        recorder = RequestRecorder(self.path, max_records=1)
        try:
            recorder.record({"ts": "2026-11-26T22:07:00Z", "status": 200})
            recorder.record({"ts": "2026-11-26T22:07:01Z", "status": 200})
        finally:
            recorder.close()
        resumed = RequestRecorder(self.path, max_records=10)
        try:
            resumed.record({"ts": "2026-11-26T22:07:02Z", "status": 200})
            self.assertTrue(resumed.stats["truncated"])
        finally:
            resumed.close()
        rows = read_lines(self.path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["event"], "truncated")

    def test_oversized_payload_does_not_raise(self) -> None:
        recorder = RequestRecorder(self.path, max_bytes=1024)
        try:
            recorder.record({"ts": "2026-11-26T22:07:00Z", "body": "x" * 4096})
            self.assertTrue(recorder.stats["truncated"])
            self.assertEqual(recorder.stats["records"], 0)
        finally:
            recorder.close()
        rows = read_lines(self.path)
        self.assertEqual(rows[-1]["event"], "truncated")
        self.assertEqual(rows[-1]["reason"], "bytes")

    def test_static_fetcher_records_every_attempt(self) -> None:
        class Response:
            def __init__(self, status: int, headers: dict[str, str]) -> None:
                self.status = status
                self.body = b"ok" if status == 200 else b"limited"
                self.url = "https://example.test/product"
                self.headers = headers

        class Session:
            def __init__(self) -> None:
                self.calls = 0

            def get(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return Response(429, {"Retry-After": "0"})
                return Response(200, {"Content-Type": "text/html"})

        recorder = RequestRecorder(self.path)
        fetcher = ScraplingFetcher(
            Session(),
            max_attempts=2,
            backoff_ms=0,
            recorder=recorder,
        )
        try:
            result = fetcher.get("https://example.test/product", item_type="product")
            self.assertEqual(result.status, 200)
        finally:
            recorder.close()
        rows = read_lines(self.path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["status"], 429)
        self.assertEqual(rows[0]["attempt"], 1)
        self.assertEqual(rows[0]["engine"], "static")
        self.assertEqual(rows[0]["item_type"], "product")
        self.assertEqual(rows[1]["status"], 200)
        self.assertEqual(rows[1]["attempt"], 2)

    def test_browser_fetcher_records_engine_and_result(self) -> None:
        recorder = RequestRecorder(self.path)
        fetcher = BrowserFetcher(
            mock.Mock(),
            task_id="task-1",
            out_root=self.root,
            max_attempts=1,
            backoff_ms=0,
            recorder=recorder,
        )
        try:
            with mock.patch.object(
                fetcher,
                "_navigate",
                return_value=FetchResult(
                    status=200,
                    url="https://example.test/product",
                    body=b"<html></html>",
                ),
            ):
                result = fetcher.get(
                    "https://example.test/product", item_type="product"
                )
            self.assertEqual(result.status, 200)
        finally:
            recorder.close()
        rows = read_lines(self.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["engine"], "browser")
        self.assertEqual(rows[0]["status"], 200)
        self.assertEqual(rows[0]["bytes"], 13)
        self.assertEqual(rows[0]["item_type"], "product")


if __name__ == "__main__":
    unittest.main()
