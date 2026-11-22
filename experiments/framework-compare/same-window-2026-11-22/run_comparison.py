#!/usr/bin/env python3
"""Run Crawlee and Scrapy on the same skatepro.es URL sample and budget.

This is a runtime comparison, not a build-session comparison.  Both arms read
the same JSON URL list and use the same 10-product / 300-second budget.  The
Crawlee arm uses Playwright; the Scrapy arm uses static HTTP.  That engine
difference is part of each framework's existing plan and is recorded in the
summary rather than hidden.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CASE = Path(__file__).resolve().parent
SHARED_URLS = CASE / "shared-urls.json"
BUDGET = {"max_products": 10, "max_seconds": 300}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def run_arm(name: str, command: list[str], log_path: Path) -> dict[str, object]:
    started_at = utc_now()
    started = time.monotonic()
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["NO_COLOR"] = "1"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"command: {' '.join(command)}\n")
        log.write(f"started_at: {started_at}\n\n")
        log.flush()
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=420,
            check=False,
        )
        log.write(result.stdout)
        log.write(f"\nreturncode: {result.returncode}\n")
    finished_at = utc_now()
    return {
        "arm": name,
        "command": command,
        "started_at": started_at,
        "finished_at": finished_at,
        "wall_seconds": round(time.monotonic() - started, 3),
        "returncode": result.returncode,
        "log": str(log_path.relative_to(ROOT)),
    }


def main() -> int:
    if not SHARED_URLS.is_file():
        print(f"missing shared URL list: {SHARED_URLS}", file=sys.stderr)
        return 2
    urls = json.loads(SHARED_URLS.read_text(encoding="utf-8"))
    count = len(urls.get("urls") or [])
    if count != BUDGET["max_products"]:
        print(
            f"shared URL count {count} does not match budget {BUDGET['max_products']}",
            file=sys.stderr,
        )
        return 2

    crawlee_dir = CASE / "crawlee"
    scrapy_dir = CASE / "scrapy"
    commands = [
        (
            "crawlee",
            [
                sys.executable,
                "-m",
                "uv",
                "run",
                "--project",
                str(ROOT / "experiments" / "framework-compare" / "crawlee"),
                "python",
                "-X",
                "utf8",
                str(
                    ROOT
                    / "experiments"
                    / "framework-compare"
                    / "crawlee"
                    / "skatepro"
                    / "run.py"
                ),
                "--run-id",
                "same-window-001",
                "--max-products",
                str(BUDGET["max_products"]),
                "--time-budget-seconds",
                str(BUDGET["max_seconds"]),
                "--urls-file",
                str(SHARED_URLS),
                "--output-dir",
                str(crawlee_dir),
            ],
        ),
        (
            "scrapy",
            [
                sys.executable,
                "-m",
                "uv",
                "run",
                "--project",
                str(ROOT / "experiments" / "framework-compare" / "scrapy"),
                "python",
                "-X",
                "utf8",
                str(
                    ROOT
                    / "experiments"
                    / "framework-compare"
                    / "scrapy"
                    / "skatepro"
                    / "run.py"
                ),
                "--max-products",
                str(BUDGET["max_products"]),
                "--max-seconds",
                str(BUDGET["max_seconds"]),
                "--urls-file",
                str(SHARED_URLS),
                "--output-dir",
                str(scrapy_dir),
                "--results-dir",
                str(scrapy_dir / "results"),
                "--task-id",
                "same-window-scrapy-001",
            ],
        ),
    ]

    arms = []
    for name, command in commands:
        print(f"running {name}...", flush=True)
        arm = run_arm(name, command, CASE / f"{name}-run.log")
        arms.append(arm)
        print(
            f"{name}: returncode={arm['returncode']} wall={arm['wall_seconds']}s",
            flush=True,
        )

    summary = {
        "case": CASE.name,
        "site": "https://www.skatepro.es",
        "sample": str(SHARED_URLS.relative_to(ROOT)),
        "budget": BUDGET,
        "network": "direct; same machine and time window",
        "arms": arms,
    }
    (CASE / "timing.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if all(arm["returncode"] == 0 for arm in arms) else 1


if __name__ == "__main__":
    raise SystemExit(main())
