from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ecom_crawler.cli import _resolve_serve_access, _serve_urls, main
from ecom_crawler.model import ContractError
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

    def test_serve_rejects_non_loopback_host_without_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stderr = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"ECOM_SERVE_TOKEN": ""}),
                contextlib.redirect_stderr(stderr),
            ):
                code = main(
                    [
                        "serve",
                        "--db",
                        str(root / "tasks.db"),
                        "--out-root",
                        str(root / "tasks"),
                        "--host",
                        "0.0.0.0",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("requires --access-token", stderr.getvalue())


class ServeAccessTests(unittest.TestCase):
    def test_loopback_needs_no_token(self) -> None:
        with mock.patch.dict(os.environ, {"ECOM_SERVE_TOKEN": ""}):
            host, token, allowed = _resolve_serve_access("127.0.0.1", None, [])
        self.assertEqual(host, "127.0.0.1")
        self.assertIsNone(token)
        self.assertEqual(allowed, frozenset())

    def test_lan_uses_environment_token_and_extra_hosts(self) -> None:
        with (
            mock.patch.dict(
                os.environ, {"ECOM_SERVE_TOKEN": "0123456789abcdef"}
            ),
            mock.patch(
                "ecom_crawler.cli._local_host_names",
                return_value={"192.168.1.20"},
            ),
        ):
            _host, token, allowed = _resolve_serve_access(
                "0.0.0.0",
                None,
                ["my-pc.local", "192.168.1.20:8765"],
            )
            self.assertNotIn("ECOM_SERVE_TOKEN", os.environ)
        self.assertEqual(token, "0123456789abcdef")
        self.assertIn("my-pc.local", allowed)
        self.assertIn("192.168.1.20", allowed)

    def test_non_loopback_requires_token(self) -> None:
        with (
            mock.patch.dict(os.environ, {"ECOM_SERVE_TOKEN": ""}),
            self.assertRaisesRegex(ContractError, "requires --access-token"),
        ):
            _resolve_serve_access("0.0.0.0", None, [])

    def test_short_token_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "at least 16 characters"):
            _resolve_serve_access("0.0.0.0", "too-short", [])

    def test_allow_host_requires_non_loopback_bind(self) -> None:
        with self.assertRaisesRegex(ContractError, "requires a non-loopback"):
            _resolve_serve_access("127.0.0.1", None, ["my-pc.local"])

    def test_allow_host_rejects_urls(self) -> None:
        with self.assertRaisesRegex(ContractError, "not a URL"):
            _resolve_serve_access(
                "0.0.0.0",
                "0123456789abcdef",
                ["http://my-pc.local"],
            )

    def test_primary_lan_address_is_listed_first(self) -> None:
        with mock.patch(
            "ecom_crawler.cli._primary_lan_address",
            return_value="192.168.1.20",
        ):
            urls = _serve_urls(
                "0.0.0.0",
                8765,
                frozenset({"172.17.0.1", "192.168.1.20"}),
            )
        self.assertEqual(urls[0], "http://192.168.1.20:8765/next/")


if __name__ == "__main__":
    unittest.main()
