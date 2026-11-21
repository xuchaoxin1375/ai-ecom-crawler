from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from fixture import fixture_server

ROOT = Path(__file__).resolve().parent
ADAPTER = ROOT / "adapter.py"


def browser_available() -> bool:
    try:
        from patchright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        try:
            return Path(playwright.chromium.executable_path).is_file()
        finally:
            playwright.stop()
    except Exception:  # noqa: BLE001 - optional browser probe
        return False


BROWSER_AVAILABLE = browser_available()


def run_adapter(context: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "context.json"
        path.write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(ADAPTER), "--context", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
            check=False,
        )


def events_of(result: subprocess.CompletedProcess[str]) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in result.stdout.splitlines()
        if line.strip()
    ]


class VirtualListAdapterTests(unittest.TestCase):
    @unittest.skipUnless(BROWSER_AVAILABLE, "Patchright Chromium is not installed")
    def test_collects_all_batches_from_replaced_dom(self) -> None:
        with fixture_server() as base:
            context = {
                "plan_id": "virtual-list-fixture",
                "plan_version": "2026.11.22-1",
                "adapter_id": "virtual-list-patchright",
                "adapter_version": "2026.11.22-1",
                "task_id": "virtual-list-001",
                "task_type": "discovery",
                "entry_url": f"{base}/virtual.html",
                "scope": {"include": ["^/product/"], "exclude": []},
                "limits": {"max_items": 20, "max_batches": 10, "max_seconds": 30},
                "browser": {"headless": True, "timeout_ms": 15000},
                "advance": {
                    "container": "#feed",
                    "item_selector": "a.product",
                    "id_attribute": "data-id",
                    "mode": "scroll",
                    "settle_ms": 100,
                    "no_new_stop": 1,
                },
            }
            result = run_adapter(context)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            events = events_of(result)
            self.assertEqual(events[0]["event"], "start")
            self.assertEqual(events[-1]["event"], "done")
            discovered = next(event for event in events if event["event"] == "discovered")
            batches = [event for event in events if event["event"] == "batch"]
            done = events[-1]
            self.assertEqual(discovered["count"], 12)
            self.assertEqual(len(discovered["urls"]), 12)
            self.assertEqual(len(set(discovered["urls"])), 12)
            self.assertEqual(sum(event["new"] for event in batches), 12)
            self.assertGreaterEqual(len(batches), 4)
            self.assertEqual(done["items"], 12)
            self.assertEqual(done["stop"], "NO_NEW_ITEMS")
            self.assertEqual(done["requests"], 1)
            self.assertEqual(done["url_changes"], 0)

    def test_invalid_context_reports_structured_error(self) -> None:
        result = run_adapter({"entry_url": "not-a-url", "advance": {}})
        self.assertEqual(result.returncode, 2)
        events = events_of(result)
        self.assertEqual(events, [
            {
                "event": "error",
                "reason": "invalid_context",
                "failure_class": "permanent",
                "detail": "entry_url must be an absolute http(s) URL",
            }
        ])


if __name__ == "__main__":
    unittest.main()
