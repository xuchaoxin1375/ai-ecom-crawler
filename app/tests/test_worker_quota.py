from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ecom_crawler.runtime.rule import load_rule
from ecom_crawler.runtime.store import TaskStore
from ecom_crawler.runtime.worker import Worker

ROOT = Path(__file__).resolve().parents[2]


class WorkerBrowserQuotaTests(unittest.TestCase):
    def test_browser_need_is_detected_for_hybrid_and_browser_rules(self) -> None:
        hybrid = load_rule(
            ROOT / "experiments/d07/virtual-list-hybrid/manifest.example.yaml"
        )
        self.assertTrue(Worker._needs_browser(hybrid))

        browser = load_rule(ROOT / "experiments/d07/browser-mercerine/rule.yaml")
        self.assertTrue(Worker._needs_browser(browser))

        static = load_rule(ROOT / "experiments/d07/ecolaines-url/rule.yaml")
        self.assertFalse(Worker._needs_browser(static))

    def test_browser_slots_are_configurable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = TaskStore(Path(temporary) / "tasks.db")
            limited = Worker(store, out_root=temporary, max_browser_tasks=2)
            self.assertEqual(limited.max_browser_tasks, 2)
            self.assertIsNotNone(limited._browser_semaphore)
            unlimited = Worker(store, out_root=temporary, max_browser_tasks=0)
            self.assertEqual(unlimited.max_browser_tasks, 0)
            self.assertIsNone(unlimited._browser_semaphore)


if __name__ == "__main__":
    unittest.main()
