#!/usr/bin/env python3
"""Run the virtual-list adapter against the local fixture and save NDJSON."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from fixture import fixture_server

ROOT = Path(__file__).resolve().parent
ADAPTER = ROOT / "adapter.py"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "evidence.ndjson",
        help="where to write adapter NDJSON",
    )
    args = parser.parse_args()
    with fixture_server() as base:
        context: dict[str, Any] = {
            "plan_id": "virtual-list-fixture",
            "plan_version": "2026.11.22-1",
            "adapter_id": "virtual-list-patchright",
            "adapter_version": "2026.11.22-1",
            "task_id": "virtual-list-fixture-001",
            "task_type": "discovery",
            "entry_url": f"{base}/virtual.html",
            "scope": {"include": ["^/product/"], "exclude": []},
            "limits": {"max_items": 20, "max_batches": 10, "max_seconds": 30},
            "browser": {"headless": True, "timeout_ms": 15000},
            "advance": {
                "container": "#feed",
                "item_selector": "a.product",
                "id_attribute": "data-id",
                "mode": "scroll",
                "settle_ms": 100,
                "no_new_stop": 1,
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            context_path = Path(temporary) / "context.json"
            context_path.write_text(
                json.dumps(context, ensure_ascii=False), encoding="utf-8"
            )
            result = subprocess.run(
                [sys.executable, str(ADAPTER), "--context", str(context_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=90,
                check=False,
            )
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        args.output.write_text(result.stdout, encoding="utf-8")
        print(result.stdout, end="")
        print(f"wrote {args.output}", file=sys.stderr)
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
