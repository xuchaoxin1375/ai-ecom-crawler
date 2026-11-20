"""Tests for crash-tolerant output helpers."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.atomic import append_jsonl, write_json


class AtomicTests(unittest.TestCase):
    def test_write_json_replaces_without_temp_leftovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "result.json"
            write_json(path, {"a": 1})
            write_json(path, {"a": 2})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"a": 2})
            self.assertEqual(
                [item.name for item in path.parent.iterdir() if item.suffix == ".tmp"],
                [],
            )

    def test_append_jsonl_writes_complete_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "items.jsonl"
            append_jsonl(path, {"n": 1})
            append_jsonl(path, {"n": 2})
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual([json.loads(line) for line in lines], [{"n": 1}, {"n": 2}])
