#!/usr/bin/env python3
"""Run the real virtual-list adapter through app run and save evidence.

The fixture server and the app run in the same process; the adapter is started
as a child process by the app runtime, matching the hybrid contract.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from fixture import fixture_server

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "manifest.example.yaml"
ADAPTER = ROOT / "adapter.py"
PLACEHOLDER = "http://127.0.0.1:8000"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", default="virtual-list-app-001")
    args = parser.parse_args()

    from ecom_crawler.execution import run_and_export

    evidence_root = ROOT / "app-evidence"
    task_dir = evidence_root / args.task_id
    if task_dir.exists():
        shutil.rmtree(task_dir)
    db_path = evidence_root / "tasks.db"
    if db_path.exists():
        db_path.unlink()

    with fixture_server() as base, tempfile.TemporaryDirectory() as temporary:
        package = Path(temporary)
        shutil.copy2(ADAPTER, package / "adapter.py")
        rule_path = package / "rule.yaml"
        rule_path.write_text(
            MANIFEST.read_text(encoding="utf-8").replace(PLACEHOLDER, base),
            encoding="utf-8",
        )
        result = run_and_export(
            rule_path=rule_path,
            db_path=db_path,
            out_root=evidence_root,
            task_id=args.task_id,
            task_type="product",
            max_products=20,
            max_seconds=60,
            max_attempts=1,
            per_domain_rps=50,
        )
        rule_copy = task_dir / "rule-used.yaml"
        rule_copy.write_text(
            MANIFEST.read_text(encoding="utf-8").replace(PLACEHOLDER, base),
            encoding="utf-8",
        )

    counts = result.task_result.get("counts", {})
    adapter = result.task_result.get("runtime", {}).get("adapter", {})
    print(json.dumps({"counts": counts, "adapter": adapter}, ensure_ascii=False, indent=2))
    print(f"task dir: {task_dir}")
    if int(counts.get("valid_products", 0)) != 12:
        print("expected 12 valid products", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
