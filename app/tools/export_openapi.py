"""Regenerate the committed OpenAPI snapshot used by frontend type generation."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ecom_crawler.web.app import create_app


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        app = create_app(root / "tasks.db", root / "out", None)
        schema = app.openapi()
    target = Path(__file__).resolve().parents[1] / "schemas" / "openapi.json"
    target.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(target)


if __name__ == "__main__":
    main()
