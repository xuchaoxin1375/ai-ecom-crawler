from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ecom_crawler.builds import _visual_evidence_status


class VisualEvidenceStatusTests(unittest.TestCase):
    def _visual_root(self, workspace: Path) -> Path:
        root = workspace / "out" / "evidence" / "visual"
        root.mkdir(parents=True)
        return root

    def _baseline(
        self,
        root: Path,
        *,
        screenshot: str = "product-example.png",
        product_image: str = "product-example-image.jpg",
    ) -> None:
        (root / "compare.md").write_text("# compare\n", encoding="utf-8")
        (root / "baseline.json").write_text(
            json.dumps(
                {
                    "capture": {
                        "screenshot": screenshot,
                        "product_image": product_image,
                    },
                    "review": {"status": "pending_manual"},
                }
            ),
            encoding="utf-8",
        )

    def test_complete_when_baseline_and_images_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            root = self._visual_root(workspace)
            self._baseline(root)
            (root / "product-example.png").write_bytes(b"png")
            (root / "product-example-image.jpg").write_bytes(b"jpg")

            result = _visual_evidence_status(workspace)

            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["missing"], [])
            self.assertEqual(result["review_status"], "pending_manual")

    def test_missing_when_files_are_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _visual_evidence_status(Path(tmp))

            self.assertEqual(result["status"], "missing")
            self.assertIn("baseline.json", result["missing"])
            self.assertIn("compare.md", result["missing"])
            self.assertIn("screenshot/image file", result["missing"])

    def test_invalid_baseline_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            root = self._visual_root(workspace)
            (root / "baseline.json").write_text("{bad", encoding="utf-8")
            (root / "compare.md").write_text("# compare\n", encoding="utf-8")

            result = _visual_evidence_status(workspace)

            self.assertEqual(result["status"], "missing")
            self.assertIn("baseline.json (unreadable)", result["missing"])

    def test_baseline_must_use_relative_image_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            root = self._visual_root(workspace)
            self._baseline(root, screenshot="../outside.png")
            (root / "product-example-image.jpg").write_bytes(b"jpg")

            result = _visual_evidence_status(workspace)

            self.assertEqual(result["status"], "missing")
            self.assertIn("capture.screenshot (must be relative)", result["missing"])


if __name__ == "__main__":
    unittest.main()
