from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from ecom_crawler.cli import main
from tests.support import base_task, candidate


class CliTests(unittest.TestCase):
    def test_export_validate_and_force(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            out_dir = root / "out"
            run_dir.mkdir()
            (run_dir / "task.json").write_text(json.dumps(base_task()), encoding="utf-8")
            (run_dir / "candidates.jsonl").write_text(
                json.dumps(candidate(), ensure_ascii=False) + "\n", encoding="utf-8"
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(
                    main(["export", "--run-dir", str(run_dir), "--out-dir", str(out_dir)]),
                    0,
                )
                self.assertIn("exported: 1 valid", stdout.getvalue())
                self.assertEqual(
                    main(["validate", "--run-dir", str(out_dir)]),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "validate",
                            "--task-result",
                            str(out_dir / "task-result.json"),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(["export", "--run-dir", str(run_dir), "--out-dir", str(out_dir)]),
                    2,
                )
                self.assertEqual(
                    main(
                        [
                            "export",
                            "--run-dir",
                            str(run_dir),
                            "--out-dir",
                            str(out_dir),
                            "--force",
                        ]
                    ),
                    0,
                )

    def test_missing_run_directory_returns_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "export",
                        "--run-dir",
                        str(root / "missing"),
                        "--out-dir",
                        str(root / "out"),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("run directory not found", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
