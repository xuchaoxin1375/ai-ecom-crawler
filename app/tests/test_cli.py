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
from ecom_crawler.runtime.store import TaskStore
from ecom_crawler.web.access import (
    SETTING_LAN_ENABLED,
    SETTING_TOKEN,
    create_session,
    parse_token_setting,
    reset_token_setting,
    stored_token_available,
    token_setting,
    verify_session,
    verify_token,
)
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

    def test_simple_key_is_accepted(self) -> None:
        _host, token, _allowed = _resolve_serve_access("0.0.0.0", "a", [])
        self.assertEqual(token, "a")

    def test_empty_token_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "must not be empty"):
            _resolve_serve_access("0.0.0.0", "   ", [])

    def test_control_characters_are_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "control characters"):
            _resolve_serve_access("0.0.0.0", "abc\ndef", [])

    def test_overlong_token_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "at most 256 characters"):
            _resolve_serve_access("0.0.0.0", "x" * 257, [])

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
        self.assertEqual(urls[0], "http://192.168.1.20:8765/")

    def test_stored_token_allows_non_loopback_without_token(self) -> None:
        with mock.patch(
            "ecom_crawler.cli._local_host_names",
            return_value={"192.168.1.20"},
        ):
            _host, token, allowed = _resolve_serve_access(
                "0.0.0.0",
                None,
                [],
                stored_token=True,
            )
        self.assertIsNone(token)
        self.assertIn("192.168.1.20", allowed)

    def test_stored_token_setting_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            db_path = Path(temporary) / "tasks.db"
            self.assertFalse(stored_token_available(db_path))
            store = TaskStore(db_path)
            store.set_setting(
                SETTING_TOKEN,
                token_setting(
                    "00" * 16,
                    "11" * 32,
                    "2026-11-25T00:00:00Z",
                ),
            )
            self.assertTrue(stored_token_available(db_path))


class ResetAccessKeyTests(unittest.TestCase):
    def _ledger(self, root: Path) -> Path:
        db_path = root / "tasks.db"
        store = TaskStore(db_path)
        store.set_setting(SETTING_LAN_ENABLED, "1")
        return db_path

    def test_reset_writes_hash_and_preserves_lan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            db_path = self._ledger(Path(temporary))
            salt, digest, _ = reset_token_setting(
                db_path,
                "abc",
                updated_at="2026-11-25T00:00:00Z",
            )
            setting = parse_token_setting(TaskStore(db_path).get_setting(SETTING_TOKEN))
            self.assertIsNotNone(setting)
            assert setting is not None
            self.assertEqual(setting[0], salt)
            self.assertEqual(setting[1], digest)
            self.assertTrue(verify_token("abc", setting[0], setting[1]))
            self.assertTrue(stored_token_available(db_path))
            self.assertEqual(
                TaskStore(db_path).get_setting(SETTING_LAN_ENABLED),
                "1",
            )

    def test_cli_reset_generates_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            db_path = self._ledger(Path(temporary))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["reset-access-key", "--db", str(db_path)])
            self.assertEqual(code, 0)
            lines = output.getvalue().splitlines()
            token = next(
                line.split("access key: ", 1)[1]
                for line in lines
                if line.startswith("access key: ")
            )
            setting = parse_token_setting(TaskStore(db_path).get_setting(SETTING_TOKEN))
            self.assertIsNotNone(setting)
            assert setting is not None
            self.assertTrue(verify_token(token, setting[0], setting[1]))

    def test_cli_reset_custom_key_and_rejects_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            db_path = self._ledger(Path(temporary))
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(
                    ["reset-access-key", "--db", str(db_path), "--key", "home"]
                )
            self.assertEqual(code, 0)
            setting = parse_token_setting(TaskStore(db_path).get_setting(SETTING_TOKEN))
            self.assertIsNotNone(setting)
            assert setting is not None
            self.assertTrue(verify_token("home", setting[0], setting[1]))

            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                code = main(
                    ["reset-access-key", "--db", str(db_path), "--key", "   "]
                )
            self.assertEqual(code, 2)
            self.assertIn("must not be empty", error.getvalue())

    def test_reset_invalidates_old_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            db_path = self._ledger(Path(temporary))
            _, old_digest, _ = reset_token_setting(
                db_path,
                "old",
                updated_at="2026-11-25T00:00:00Z",
            )
            old_session = create_session(old_digest)
            _, new_digest, _ = reset_token_setting(
                db_path,
                "new",
                updated_at="2026-11-25T00:01:00Z",
            )
            self.assertFalse(verify_session(old_session, new_digest))
            self.assertTrue(verify_session(create_session(new_digest), new_digest))

    def test_cli_reset_missing_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing.db"
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                code = main(["reset-access-key", "--db", str(missing)])
            self.assertEqual(code, 2)
            self.assertIn("task ledger not found", error.getvalue())


if __name__ == "__main__":
    unittest.main()
