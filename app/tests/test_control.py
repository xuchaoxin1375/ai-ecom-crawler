from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ecom_crawler.runtime.lock import WorkerLockError, worker_lock
from ecom_crawler.runtime.models import Task, WorkItem
from ecom_crawler.runtime.store import (
    TaskNotFoundError,
    TaskStore,
    TaskTransitionError,
)


def make_task(task_id: str, state: str = "RUNNING") -> Task:
    return Task(
        task_id=task_id,
        plan_id="fixture-control",
        plan_version="1.0.0",
        task_type="product",
        state=state,
    )


class ControlTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.temporary.name) / "tasks.db")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_pause_running_is_idempotent_until_settled(self) -> None:
        self.store.create_task(make_task("pause-1"))
        task = self.store.request_pause("pause-1")
        self.assertEqual(task.state, "PAUSING")
        again = self.store.request_pause("pause-1")
        self.assertEqual(again.state, "PAUSING")
        self.store.update_task("pause-1", state="PAUSED")
        settled = self.store.request_pause("pause-1")
        self.assertEqual(settled.state, "PAUSED")

    def test_pause_queued_is_rejected(self) -> None:
        self.store.create_task(make_task("pause-2", state="QUEUED"))
        with self.assertRaises(TaskTransitionError):
            self.store.request_pause("pause-2")

    def test_resume_paused_and_running(self) -> None:
        self.store.create_task(make_task("resume-1", state="PAUSED"))
        task = self.store.request_resume("resume-1")
        self.assertEqual(task.state, "QUEUED")
        running = self.store.request_resume("resume-1")
        self.assertEqual(running.state, "QUEUED")

    def test_cancel_running_moves_to_cancelling(self) -> None:
        self.store.create_task(make_task("cancel-1"))
        task = self.store.request_cancel("cancel-1")
        self.assertEqual(task.state, "CANCELLING")
        again = self.store.request_cancel("cancel-1")
        self.assertEqual(again.state, "CANCELLING")

    def test_cancel_queued_is_final(self) -> None:
        self.store.create_task(make_task("cancel-2", state="QUEUED"))
        task = self.store.request_cancel("cancel-2")
        self.assertEqual(task.state, "CANCELLED")
        self.assertEqual(task.outcome, "CANCELLED")
        self.assertEqual(task.stop_reason, "USER_CANCELLED")
        self.assertIsNotNone(task.finished_at)
        again = self.store.request_cancel("cancel-2")
        self.assertEqual(again.state, "CANCELLED")

    def test_cancel_finished_is_rejected(self) -> None:
        self.store.create_task(make_task("cancel-3", state="FINISHED"))
        with self.assertRaises(TaskTransitionError):
            self.store.request_cancel("cancel-3")

    def test_start_draft_and_repeat(self) -> None:
        self.store.create_task(make_task("start-1", state="DRAFT"))
        task = self.store.request_start("start-1")
        self.assertEqual(task.state, "QUEUED")
        again = self.store.request_start("start-1")
        self.assertEqual(again.state, "QUEUED")

    def test_unknown_task_is_reported(self) -> None:
        with self.assertRaises(TaskNotFoundError):
            self.store.request_cancel("missing")

    def test_worker_lock_is_exclusive_and_stale_file_is_reusable(self) -> None:
        lock_path = self.store.path.with_name(self.store.path.name + ".worker.lock")
        lock_path.write_text("stale\n", encoding="utf-8")
        with (
            worker_lock(self.store.path),
            self.assertRaises(WorkerLockError),
            worker_lock(self.store.path),
        ):
            pass
        with worker_lock(self.store.path):
            self.assertTrue(lock_path.is_file())

    def test_recovery_settles_running_pausing_and_cancelling(self) -> None:
        self.store.create_task(make_task("recover-running"))
        self.store.add_item(
            WorkItem(
                task_id="recover-running",
                item_id="item-1",
                item_type="product",
                url="https://fixture.test/p1.html",
                normalized_url="https://fixture.test/p1.html",
                stage="product",
                state="IN_FLIGHT",
            )
        )
        self.store.create_task(make_task("recover-pausing", state="PAUSING"))
        self.store.create_task(make_task("recover-cancelling", state="CANCELLING"))

        report = self.store.recover_orphaned_tasks()
        self.assertEqual(
            {key: report[key] for key in ("recovered", "requeued", "paused", "cancelled")},
            {"recovered": 3, "requeued": 1, "paused": 1, "cancelled": 1},
        )
        self.assertEqual(
            sorted(report["task_ids"]),
            ["recover-cancelling", "recover-pausing", "recover-running"],
        )
        running = self.store.get_task("recover-running")
        pausing = self.store.get_task("recover-pausing")
        cancelling = self.store.get_task("recover-cancelling")
        assert running is not None and pausing is not None and cancelling is not None
        self.assertEqual(running.state, "QUEUED")
        self.assertEqual(pausing.state, "PAUSED")
        self.assertEqual(cancelling.state, "CANCELLED")

        item = self.store.items("recover-running", "product")[0]
        self.assertEqual(item.state, "PENDING")
        reconciled = self.store.reconcile_task("recover-running", max_attempts=2)
        self.assertEqual(reconciled, {"in_flight": 0, "reset": 0, "failed": 0})


if __name__ == "__main__":
    unittest.main()
