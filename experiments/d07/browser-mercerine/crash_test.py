"""Kill a browser task's worker, then verify lease takeover cleans up.

This is a bounded experiment helper, not a production command.  It submits
one task, waits until the browser process and profile are registered, kills
the worker process without touching its Chromium child, and starts a fresh
worker after the lease expires.

Run with the application virtualenv:

    app/.venv/Scripts/python.exe experiments/d07/browser-mercerine/crash_test.py

The script prints one JSON summary and exits non-zero when the takeover does
not finish or the old browser is still alive.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rule",
        type=Path,
        default=Path(__file__).with_name("rule.yaml"),
        help="Rule package to submit (default: rule.yaml next to this script).",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).with_name("crash"),
        help="Directory for the ledger and task outputs.",
    )
    parser.add_argument("--task-id", default="browser-crash-001")
    parser.add_argument("--lease-ttl", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=240)
    return parser.parse_args()


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=check,
    )


def task_state(db: Path, task_id: str) -> tuple[str, int]:
    with sqlite3.connect(db) as connection:
        row = connection.execute(
            "SELECT state, lease_token FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
    if row is None:
        return "MISSING", 0
    return str(row[0]), int(row[1])


def browser_resource(db: Path, task_id: str) -> tuple[int, str] | None:
    with sqlite3.connect(db) as connection:
        process = connection.execute(
            "SELECT pid FROM task_resources "
            "WHERE task_id = ? AND kind = 'process' LIMIT 1",
            (task_id,),
        ).fetchone()
        profile = connection.execute(
            "SELECT path FROM task_resources "
            "WHERE task_id = ? AND kind = 'path' LIMIT 1",
            (task_id,),
        ).fetchone()
    if process is None:
        return None
    return int(process[0] or 0), str(profile[0] or "") if profile else ""


def wait_for(predicate, timeout: float, interval: float = 1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        import os

        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    db = root / "tasks.db"
    out_root = root / "tasks"
    for path in (db, Path(f"{db}-wal"), Path(f"{db}-shm")):
        path.unlink(missing_ok=True)
    out_root.mkdir(parents=True, exist_ok=True)

    submit = run(
        [
            sys.executable,
            "-m",
            "ecom_crawler",
            "submit",
            "--rule",
            str(args.rule),
            "--db",
            str(db),
            "--task-id",
            args.task_id,
            "--task-type",
            "product",
            "--max-products",
            "1",
            "--max-seconds",
            "180",
            "--max-attempts",
            "2",
        ]
    )
    print(submit.stdout.strip())

    worker = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ecom_crawler",
            "worker",
            "--db",
            str(db),
            "--out-root",
            str(out_root),
            "--max-tasks",
            "1",
            "--lease-ttl",
            str(args.lease_ttl),
            "--per-domain-rps",
            "1",
        ],
        text=True,
    )
    summary: dict[str, object] = {
        "task_id": args.task_id,
        "worker_pid": worker.pid,
    }
    try:
        registered = wait_for(
            lambda: browser_resource(db, args.task_id),
            timeout=90,
        )
        if not registered:
            summary["error"] = "browser resources were not registered"
            return 1
        browser_pid, profile = registered
        summary["browser_pid"] = browser_pid
        summary["profile"] = profile
        summary["state_before_kill"] = task_state(db, args.task_id)[0]
        time.sleep(1.0)

        worker.kill()
        worker.wait(timeout=20)
        summary["worker_returncode"] = worker.returncode
        summary["browser_alive_after_worker_kill"] = pid_alive(browser_pid)

        time.sleep(max(2, args.lease_ttl + 3))
        fresh = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "ecom_crawler",
                "worker",
                "--db",
                str(db),
                "--out-root",
                str(out_root),
                "--max-tasks",
                "1",
                "--lease-ttl",
                str(args.lease_ttl),
                "--per-domain-rps",
                "1",
            ],
            text=True,
        )
        summary["fresh_worker_pid"] = fresh.pid
        try:
            finished = wait_for(
                lambda: task_state(db, args.task_id)[0] in {"FINISHED", "CANCELLED"},
                timeout=args.timeout,
            )
            state, token = task_state(db, args.task_id)
            summary["final_state"] = state
            summary["final_lease_token"] = token
            summary["finished"] = bool(finished)
            summary["browser_alive_after_takeover"] = pid_alive(browser_pid)
            summary["profile_exists_after_takeover"] = (
                Path(profile).exists() if profile else None
            )
            with sqlite3.connect(db) as connection:
                summary["remaining_resources"] = connection.execute(
                    "SELECT COUNT(*) FROM task_resources WHERE task_id = ?",
                    (args.task_id,),
                ).fetchone()[0]
            result_path = out_root / args.task_id / "task-result.json"
            if result_path.is_file():
                result = json.loads(result_path.read_text(encoding="utf-8"))
                summary["outcome"] = result.get("outcome")
                summary["stop_reason"] = result.get("stop_reason")
                summary["counts"] = result.get("counts")
                summary["runtime"] = result.get("runtime")
        finally:
            fresh.terminate()
            try:
                fresh.wait(timeout=15)
            except subprocess.TimeoutExpired:
                fresh.kill()
    finally:
        if worker.poll() is None:
            worker.kill()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    ok = (
        summary.get("finished")
        and summary.get("final_state") == "FINISHED"
        and summary.get("browser_alive_after_takeover") is False
        and summary.get("remaining_resources") == 0
        and summary.get("profile_exists_after_takeover") in {False, None}
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
