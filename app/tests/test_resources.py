from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from ecom_crawler.runtime.models import Task
from ecom_crawler.runtime.resources import (
    cleanup_orphan_profiles,
    cleanup_task_resources,
    pid_alive,
    register_path,
    register_process,
)
from ecom_crawler.runtime.store import TaskStore
from ecom_crawler.runtime.worker import Worker


class ResourceCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = TaskStore(self.root / "tasks.db")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_registered_path_is_removed(self) -> None:
        target = self.root / "profile"
        target.mkdir()
        (target / "cookie.txt").write_text("temporary", encoding="utf-8")
        register_path(self.store, "task-path", target, lease_token=1)

        report = cleanup_task_resources(self.store, "task-path", lease_token=1)
        self.assertEqual(report["paths"], 1)
        self.assertFalse(target.exists())
        self.assertEqual(self.store.list_resources("task-path"), [])

    def test_cleanup_respects_lease_token(self) -> None:
        target = self.root / "profile-token"
        target.mkdir()
        register_path(self.store, "task-token", target, lease_token=1)

        report = cleanup_task_resources(self.store, "task-token", lease_token=2)
        self.assertEqual(
            report,
            {"processes": 0, "paths": 0, "browser_slots": 0, "failed": 0},
        )
        self.assertTrue(target.exists())

        report = cleanup_task_resources(self.store, "task-token", lease_token=1)
        self.assertEqual(report["paths"], 1)
        self.assertFalse(target.exists())

    def _profile(self, task_id: str, age_seconds: float) -> Path:
        profile = self.root / "out" / task_id / "adapter-browser-profile"
        profile.mkdir(parents=True)
        (profile / "lock").write_text("x", encoding="utf-8")
        stamp = time.time() - age_seconds
        os.utime(profile, (stamp, stamp))
        return profile

    def _task(self, task_id: str, state: str = "QUEUED") -> Task:
        return Task(
            task_id=task_id,
            plan_id="profile-sweep",
            plan_version="2026.11.22-1",
            task_type="product",
            state=state,
        )

    def test_orphan_profile_for_unknown_task_is_removed(self) -> None:
        profile = self._profile("missing-task", 7200)

        report = cleanup_orphan_profiles(
            self.store, self.root / "out", min_age_seconds=3600
        )

        self.assertEqual(
            report,
            {"scanned": 1, "removed": 1, "kept": 0, "failed": 0},
        )
        self.assertFalse(profile.exists())

    def test_orphan_profile_with_live_lease_is_kept(self) -> None:
        self.store.create_task(self._task("active-task"))
        claimed = self.store.claim_tasks("owner", 1, 60)
        self.assertEqual(len(claimed), 1)
        profile = self._profile("active-task", 7200)

        report = cleanup_orphan_profiles(
            self.store, self.root / "out", min_age_seconds=3600
        )

        self.assertEqual(report["kept"], 1)
        self.assertEqual(report["removed"], 0)
        self.assertTrue(profile.exists())

    def test_orphan_profile_with_expired_lease_is_removed(self) -> None:
        self.store.create_task(self._task("expired-task"))
        claimed = self.store.claim_tasks("owner", 1, 0.1)
        self.assertEqual(len(claimed), 1)
        time.sleep(0.2)
        profile = self._profile("expired-task", 7200)

        report = cleanup_orphan_profiles(
            self.store, self.root / "out", min_age_seconds=3600
        )

        self.assertEqual(report["removed"], 1)
        self.assertFalse(profile.exists())

    def test_young_orphan_profile_is_kept(self) -> None:
        profile = self._profile("young-task", 0)

        report = cleanup_orphan_profiles(
            self.store, self.root / "out", min_age_seconds=3600
        )

        self.assertEqual(report["kept"], 1)
        self.assertEqual(report["removed"], 0)
        self.assertTrue(profile.exists())

    def test_terminal_task_profile_is_removed(self) -> None:
        self.store.create_task(self._task("finished-task", state="FINISHED"))
        profile = self._profile("finished-task", 7200)

        report = cleanup_orphan_profiles(
            self.store, self.root / "out", min_age_seconds=3600
        )

        self.assertEqual(report["removed"], 1)
        self.assertFalse(profile.exists())

    def test_worker_startup_sweeps_old_profile(self) -> None:
        profile = self._profile("orphan-at-startup", 7200)
        worker = Worker(
            self.store,
            out_root=self.root / "out",
            profile_sweep_age_seconds=3600,
        )

        self.assertEqual(worker.run_once(), 0)

        self.assertFalse(profile.exists())

    def test_non_profile_directory_is_ignored(self) -> None:
        other = self.root / "out" / "task-with-other-dir" / "exports"
        other.mkdir(parents=True)

        report = cleanup_orphan_profiles(
            self.store, self.root / "out", min_age_seconds=0
        )

        self.assertEqual(report["scanned"], 0)
        self.assertTrue(other.exists())

    def test_registered_process_is_terminated(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
        )
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not pid_alive(process.pid):
                time.sleep(0.05)
            self.assertTrue(pid_alive(process.pid))
            register_process(
                self.store, "task-process", process, lease_token=3
            )

            report = cleanup_task_resources(
                self.store, "task-process", lease_token=3, grace_seconds=1
            )
            self.assertEqual(report["processes"], 1)
            process.wait(timeout=10)
            self.assertIsNotNone(process.returncode)
            self.assertEqual(self.store.list_resources("task-process"), [])
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
