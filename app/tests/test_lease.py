from __future__ import annotations

import multiprocessing
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

from ecom_crawler.runtime.models import Task, WorkItem
from ecom_crawler.runtime.store import LeaseLostError, TaskStore


def make_task(task_id: str, state: str = "QUEUED") -> Task:
    return Task(
        task_id=task_id,
        plan_id="lease-fixture",
        plan_version="1.0.0",
        task_type="product",
        state=state,
        limits={"max_attempts": 2},
    )


def make_item(task_id: str, item_id: str, state: str = "PENDING") -> WorkItem:
    return WorkItem(
        task_id=task_id,
        item_id=item_id,
        item_type="product",
        url=f"https://fixture.test/{item_id}.html",
        normalized_url=f"https://fixture.test/{item_id}.html",
        stage="product",
        state=state,
    )


def claim_in_child(
    db_path: str,
    owner: str,
    barrier: Any,
    queue: Any,
) -> None:
    store = TaskStore(db_path)
    barrier.wait(timeout=10)
    claimed = store.claim_tasks(owner, 1, 30)
    if claimed:
        task, lease = claimed[0]
        queue.put((owner, task.task_id, lease.token))
    else:
        queue.put((owner, None, None))


class LeaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temporary.name) / "tasks.db"
        self.store = TaskStore(self.db_path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_claim_is_exclusive_and_release_allows_reclaim(self) -> None:
        self.store.create_task(make_task("lease-1"))
        first = self.store.claim_tasks("worker-a", 1, 30)
        self.assertEqual(len(first), 1)
        task, lease = first[0]
        self.assertEqual(task.state, "RUNNING")
        self.assertEqual(lease.token, 1)
        self.assertTrue(self.store.check_lease(lease))
        self.assertEqual(self.store.claim_tasks("worker-b", 1, 30), [])

        self.assertTrue(self.store.renew_lease(lease, 30))
        self.store.release_lease(lease)
        self.assertFalse(self.store.check_lease(lease))
        self.store.update_task("lease-1", state="QUEUED")

        second = self.store.claim_tasks("worker-b", 1, 30)
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0][1].token, 2)

    def test_live_lease_survives_settlement_scan(self) -> None:
        self.store.create_task(make_task("lease-live"))
        _, lease = self.store.claim_tasks("worker-a", 1, 30)[0]
        report = self.store.settle_expired_tasks()
        self.assertEqual(report["recovered"], 0)
        task = self.store.get_task("lease-live")
        assert task is not None
        self.assertEqual(task.state, "RUNNING")
        self.assertTrue(self.store.check_lease(lease))

    def test_expired_lease_takeover_fences_old_writer(self) -> None:
        self.store.create_task(make_task("lease-expired"))
        self.store.add_item(make_item("lease-expired", "p1"))
        _, old = self.store.claim_tasks("worker-a", 1, 0.1)[0]
        self.store.mark_item(
            "lease-expired",
            "p1",
            "DONE",
            {"status": "valid"},
            lease=old,
        )
        time.sleep(0.2)
        self.assertFalse(self.store.renew_lease(old, 30))

        report = self.store.settle_expired_tasks()
        self.assertEqual(report["recovered"], 1)
        self.assertEqual(report["requeued"], 1)
        task = self.store.get_task("lease-expired")
        assert task is not None
        self.assertEqual(task.state, "QUEUED")
        self.assertFalse(self.store.check_lease(old))

        claimed = self.store.claim_tasks("worker-b", 1, 30)
        self.assertEqual(len(claimed), 1)
        _, new = claimed[0]
        self.assertEqual(new.token, old.token + 1)

        with self.assertRaises(LeaseLostError):
            self.store.update_task("lease-expired", lease=old, state="PAUSED")
        with self.assertRaises(LeaseLostError):
            self.store.add_item(make_item("lease-expired", "p2"), lease=old)
        with self.assertRaises(LeaseLostError):
            self.store.claim_items("lease-expired", 1, lease=old)

        self.store.update_task("lease-expired", lease=new, state="PAUSED")
        self.store.mark_item(
            "lease-expired",
            "p1",
            "DONE",
            {"status": "valid"},
            lease=new,
        )
        paused = self.store.get_task("lease-expired")
        assert paused is not None
        self.assertEqual(paused.state, "PAUSED")

    def test_expired_pausing_and_cancelling_settle_with_item_cleanup(self) -> None:
        self.store.create_task(make_task("lease-pausing", state="PAUSING"))
        self.store.add_item(
            make_item("lease-pausing", "p1", state="IN_FLIGHT")
        )
        self.store.create_task(make_task("lease-cancelling", state="CANCELLING"))
        self.store.add_item(
            make_item("lease-cancelling", "p1", state="IN_FLIGHT")
        )

        report = self.store.settle_expired_tasks()
        self.assertEqual(report["paused"], 1)
        self.assertEqual(report["cancelled"], 1)
        self.assertEqual(
            report["items"]["lease-pausing"],
            {"in_flight": 1, "reset": 1, "failed": 0},
        )
        self.assertEqual(
            report["items"]["lease-cancelling"],
            {"in_flight": 1, "reset": 0, "failed": 1},
        )

        paused = self.store.get_task("lease-pausing")
        cancelled = self.store.get_task("lease-cancelling")
        assert paused is not None and cancelled is not None
        self.assertEqual(paused.state, "PAUSED")
        self.assertEqual(cancelled.state, "CANCELLED")
        self.assertEqual(cancelled.output["recovery_takeover_failed"], 1)
        self.assertIsNotNone(cancelled.finished_at)
        self.assertEqual(
            self.store.item_counts("lease-pausing", "product").get("IN_FLIGHT", 0),
            0,
        )
        cancelled_items = self.store.items("lease-cancelling", "product")
        self.assertEqual(cancelled_items[0].state, "FAILED")
        self.assertEqual(cancelled_items[0].result.get("reason"), "task_cancelled")

    def test_two_threads_cannot_claim_the_same_task(self) -> None:
        self.store.create_task(make_task("lease-race"))
        barrier = threading.Barrier(2)
        results: list[tuple[str, int]] = []
        lock = threading.Lock()

        def claim(owner: str) -> None:
            store = TaskStore(self.db_path)
            barrier.wait(timeout=5)
            claimed = store.claim_tasks(owner, 1, 30)
            with lock:
                results.append((owner, len(claimed)))

        threads = [
            threading.Thread(target=claim, args=(f"worker-{index}",))
            for index in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)

        self.assertEqual(sorted(count for _, count in results), [0, 1])

    def test_old_ledger_migrates_lease_columns(self) -> None:
        old_path = Path(self.temporary.name) / "old.db"
        connection = sqlite3.connect(old_path)
        connection.executescript(
            """
            CREATE TABLE tasks (
                task_id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL,
                plan_version TEXT NOT NULL,
                task_type TEXT NOT NULL,
                state TEXT NOT NULL,
                outcome TEXT,
                stop_reason TEXT,
                site_key TEXT,
                domain_key TEXT,
                market TEXT,
                rule_path TEXT,
                archived_at TEXT,
                input_json TEXT NOT NULL,
                limits_json TEXT NOT NULL,
                output_json TEXT NOT NULL,
                counters_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            );
            CREATE TABLE task_items (
                task_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                item_type TEXT NOT NULL,
                url TEXT NOT NULL,
                normalized_url TEXT NOT NULL,
                stage TEXT NOT NULL,
                state TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                failure_class TEXT,
                parent_url TEXT,
                discovered_from TEXT,
                result_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (task_id, item_id)
            );
            """
        )
        connection.close()

        store = TaskStore(old_path)
        store.create_task(make_task("old-task"))
        claimed = store.claim_tasks("worker-old", 1, 30)
        self.assertEqual(len(claimed), 1)
        task, lease = claimed[0]
        self.assertEqual(task.task_id, "old-task")
        self.assertEqual(task.state, "RUNNING")
        self.assertEqual(lease.token, 1)
        self.assertTrue(store.check_lease(lease))

    def test_claim_is_exclusive_across_processes(self) -> None:
        self.store.create_task(make_task("lease-process"))
        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(2)
        queue = context.Queue()
        processes = [
            context.Process(
                target=claim_in_child,
                args=(str(self.db_path), f"process-{index}", barrier, queue),
            )
            for index in range(2)
        ]
        for process in processes:
            process.start()
        results = [queue.get(timeout=15) for _ in processes]
        for process in processes:
            process.join(15)
            self.assertEqual(process.exitcode, 0)

        claimed = [entry for entry in results if entry[1] is not None]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0][1], "lease-process")
        self.assertEqual(self.store.get_task("lease-process").state, "RUNNING")


if __name__ == "__main__":
    unittest.main()
