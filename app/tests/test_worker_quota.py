from __future__ import annotations

import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path

from ecom_crawler.runtime.models import Lease
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

        stealth_fetch = {**static.fetch, "default_engine": "stealth"}
        self.assertTrue(Worker._needs_browser(replace(
            static, raw={**static.raw, "fetch": stealth_fetch},
        )))
        for engine in ("browser", "stealth"):
            with self.subTest(engine=engine):
                mixed_fetch = {**static.fetch, "per_url_type": {"product": {"engine": engine}}}
                self.assertTrue(Worker._needs_browser(replace(
                    static, raw={**static.raw, "fetch": mixed_fetch},
                )))

    def test_browser_slot_claim_is_atomic_across_task_stores(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            db = Path(temporary) / "tasks.db"
            first = TaskStore(db)
            second = TaskStore(db)
            slot = first.claim_browser_slot(
                task_id="task-a", lease_token=1, limit=1, ttl_seconds=30
            )
            self.assertEqual(slot, "browser-slot:0")
            self.assertIsNone(
                second.claim_browser_slot(
                    task_id="task-b", lease_token=2, limit=1, ttl_seconds=30
                )
            )
            self.assertTrue(
                first.renew_browser_slot("task-a", slot or "", ttl_seconds=30)
            )
            first.release_browser_slot("task-a", slot or "")
            claimed = second.claim_browser_slot(
                task_id="task-b", lease_token=2, limit=1, ttl_seconds=30
            )
            self.assertEqual(claimed, "browser-slot:0")
            second.release_browser_slot("task-b", claimed or "")

    def test_two_workers_share_one_browser_slot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            db = Path(temporary) / "tasks.db"
            first = Worker(TaskStore(db), out_root=temporary, max_browser_tasks=1)
            second = Worker(TaskStore(db), out_root=temporary, max_browser_tasks=1)
            lease_a = Lease(task_id="task-a", owner="a", token=1, expires_at=time.time() + 30)
            lease_b = Lease(task_id="task-b", owner="b", token=1, expires_at=time.time() + 30)
            slot_a = first._acquire_browser_slot("task-a", lease_a)
            self.assertEqual(slot_a, "browser-slot:0")
            result: dict[str, str | None] = {}

            def claim_second() -> None:
                result["slot"] = second._acquire_browser_slot("task-b", lease_b)

            thread = threading.Thread(target=claim_second)
            thread.start()
            time.sleep(0.3)
            self.assertTrue(thread.is_alive())
            first._release_browser_slot("task-a")
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(result["slot"], "browser-slot:0")
            second._release_browser_slot("task-b")

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
