from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from ecom_crawler.runtime.resources import (
    cleanup_task_resources,
    pid_alive,
    register_path,
    register_process,
)
from ecom_crawler.runtime.store import TaskStore


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
