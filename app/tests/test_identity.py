from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ecom_crawler.runtime.identity import code_fingerprint, frontend_info, git_info


class IdentityTests(unittest.TestCase):
    def test_code_fingerprint_tracks_python_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "pkg"
            root.mkdir()
            source = root / "module.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            code_fingerprint.cache_clear()
            first = code_fingerprint(root)
            self.assertEqual(len(first), 16)
            self.assertEqual(code_fingerprint(root), first)
            source.write_text("VALUE = 2\n", encoding="utf-8")
            code_fingerprint.cache_clear()
            self.assertNotEqual(code_fingerprint(root), first)

    def test_frontend_info_reports_missing_and_built_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dist = Path(temporary) / "dist"
            self.assertEqual(
                frontend_info(dist),
                {"exists": False, "sha256": None, "built_at": None},
            )
            dist.mkdir()
            (dist / "index.html").write_text("<html></html>", encoding="utf-8")
            info = frontend_info(dist)
            self.assertTrue(info["exists"])
            self.assertEqual(len(info["sha256"]), 16)
            self.assertTrue(str(info["built_at"]).endswith("Z"))

    def test_git_info_outside_repository_is_null(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            info = git_info(temporary)
            self.assertIsNone(info["commit"])
            self.assertIsNone(info["dirty"])


if __name__ == "__main__":
    unittest.main()
