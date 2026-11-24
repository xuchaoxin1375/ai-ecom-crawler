from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.run import PARALLEL_GROUPS, load_suite, parallel_plan


class TestSelectionTests(unittest.TestCase):
    def test_project_parallel_groups_are_disjoint(self) -> None:
        plan = parallel_plan({group: load_suite(group, []) for group in PARALLEL_GROUPS})
        self.assertEqual(tuple(plan), ("build", "runtime"))

    def test_overlapping_groups_are_rejected(self) -> None:
        test = unittest.FunctionTestCase(lambda: None)
        with self.assertRaisesRegex(ValueError, "overlapping"):
            parallel_plan({name: unittest.TestSuite([test]) for name in PARALLEL_GROUPS})

    def test_empty_group_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "empty"):
            parallel_plan({"build": unittest.TestSuite()})


if sys.platform == "win32":
    from ecom_crawler.runtime.resources import pid_alive
    from tests.parallel_runner import run_parallel

    _FAKE_WORKER = """
import os, subprocess, sys, tempfile, time
from pathlib import Path
mode, probe, group, fingerprint, receipt, quiet = sys.argv[1:]
receipt = Path(receipt)
marker = receipt.with_suffix('.pid')
staging = marker.with_suffix('.pid.tmp')
staging.write_text(str(os.getpid()), encoding='ascii')
staging.replace(marker)
if sys.stdin.buffer.read(1) != b'1':
    sys.exit(2)
assert Path(tempfile.gettempdir()) == receipt.parent / group
if mode == 'pass':
    # Neither phase can finish without seeing the other: this fails if the
    # runner starts one group and waits before starting the second.
    (receipt.parent / f'{group}.ready').touch()
    peer = 'runtime' if group == 'build' else 'build'
    while not (receipt.parent / f'{peer}.ready').exists():
        time.sleep(0.02)
if group == 'build':
    if mode == 'timeout':
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        Path(probe).write_text(str(child.pid), encoding='ascii')
        time.sleep(30)
    if mode == 'missing-receipt':
        sys.exit(0)
    if mode == 'failed-worker':
        sys.exit(1)
receipt.write_text(fingerprint, encoding='ascii')
"""

    class WindowsParallelRunnerTests(unittest.TestCase):
        def _run(self, mode: str, timeout: int = 10) -> tuple[int, str, bool | None]:
            with tempfile.TemporaryDirectory() as temporary:
                probe = Path(temporary) / "child.pid"
                report = io.StringIO()
                with patch("tempfile.tempdir", temporary), contextlib.redirect_stderr(report):
                    result = run_parallel(
                        [sys.executable, "-c", _FAKE_WORKER, mode, str(probe)],
                        {"build": "build-expected", "runtime": "runtime-expected"},
                        quiet=True, timeout=timeout,
                    )
                alive = pid_alive(int(probe.read_text(encoding="ascii"))) if probe.exists() else None
                if result == 0:
                    self.assertEqual(list(Path(temporary).iterdir()), [])
                return result, report.getvalue(), alive

        def test_both_workers_pass_and_remove_their_temporary_directories(self) -> None:
            code, report, _ = self._run("pass")
            self.assertEqual(code, 0, report)
            self.assertIn("build: passed", report)
            self.assertIn("runtime: passed", report)

        def test_zero_exit_without_completion_receipt_fails(self) -> None:
            code, report, _ = self._run("missing-receipt")
            self.assertEqual(code, 1, report)
            self.assertIn("build: failed or incomplete", report)

        def test_failed_worker_cannot_be_hidden_by_passing_worker(self) -> None:
            code, report, _ = self._run("failed-worker")
            self.assertEqual(code, 1, report)
            self.assertIn("build: failed or incomplete", report)
            self.assertIn("runtime: passed", report)

        def test_timeout_reclaims_worker_and_its_child(self) -> None:
            code, report, alive = self._run("timeout", timeout=3)
            self.assertEqual(code, 1, report)
            self.assertIn("parallel time limit reached", report)
            self.assertNotIn("cleanup could not be confirmed", report)
            self.assertIs(alive, False, report)
