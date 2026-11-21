from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ecom_crawler.runtime.atomic import append_jsonl, write_json, write_text


class AtomicWriteTests(unittest.TestCase):
    def test_text_and_json_outputs_use_lf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            append_jsonl(root / "events.ndjson", {"event": "one"})
            append_jsonl(root / "events.ndjson", {"event": "two"})
            write_json(root / "task.json", {"task": "one"})
            write_text(root / "products.csv", "a,b\n1,2\n")

            self.assertEqual(
                (root / "events.ndjson").read_bytes(),
                b'{"event": "one"}\n{"event": "two"}\n',
            )
            self.assertNotIn(b"\r\n", (root / "task.json").read_bytes())
            self.assertEqual((root / "products.csv").read_bytes(), b"a,b\n1,2\n")


if __name__ == "__main__":
    unittest.main()
