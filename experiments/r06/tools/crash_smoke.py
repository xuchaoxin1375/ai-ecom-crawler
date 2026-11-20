#!/usr/bin/env python3
"""crash_smoke.py - kill a worker subprocess, then verify restart recovery.

Usage:
    python experiments/r06/tools/crash_smoke.py \
        --rule experiments/r06/plans/tognar-next-link-runtime.yaml \
        --demo-dir experiments/r06/tognar-crash-demo \
        --task-id tognar-crash-recovery --kill-after 5 --per-domain-rps 0.1

The parent process creates one task, starts a worker subprocess, terminates it
while a request is in flight, then starts a new worker and checks that the task
is requeued, the in-flight item is reconciled, and the task finishes.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.models import Task
from runtime.rule import RulePackage, load_rule
from runtime.store import TaskStore

logger = logging.getLogger("crash-smoke")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Kill a worker subprocess and verify restart recovery.",
    )
    parser.add_argument("--rule", required=True, help="rule package path")
    parser.add_argument(
        "--demo-dir",
        required=True,
        help="output directory; tasks.db and tasks/ are created inside",
    )
    parser.add_argument(
        "--task-id",
        default="crash-smoke",
        help="task id (default: crash-smoke)",
    )
    parser.add_argument(
        "--task-type",
        choices=["discovery", "product"],
        default="discovery",
        help="task type (default: discovery)",
    )
    parser.add_argument(
        "--kill-after",
        type=float,
        default=5.0,
        help="seconds before terminating the worker (default: 5.0)",
    )
    parser.add_argument(
        "--per-domain-rps",
        type=float,
        default=0.1,
        help="per-domain requests per second (default: 0.1)",
    )
    parser.add_argument("--max-urls", type=int, default=None)
    parser.add_argument("--max-products", type=int, default=None)
    parser.add_argument("--max-seconds", type=float, default=None)
    parser.add_argument(
        "--timeout",
        type=float,
        default=240.0,
        help="seconds to wait for the recovery worker (default: 240)",
    )
    return parser.parse_args(argv)


def build_task(rule: RulePackage, args: argparse.Namespace) -> Task:
    defaults = rule.task_defaults
    return Task(
        task_id=args.task_id,
        plan_id=rule.rule_id,
        plan_version=rule.rule_version,
        task_type=args.task_type,
        state="QUEUED",
        input={
            "rule_path": str(Path(args.rule).resolve()),
            "entry_urls": [rule.entry_url],
        },
        limits={
            "max_urls": args.max_urls or int(defaults.get("max_urls", 100)),
            "max_products": args.max_products
            or int(defaults.get("max_products", 20)),
            "max_seconds": args.max_seconds
            or float(defaults.get("max_seconds", 180)),
            "max_attempts": int(defaults.get("max_attempts", 2)),
            "retry_backoff_ms": int(defaults.get("retry_backoff_ms", 1000)),
            "concurrency": defaults.get(
                "concurrency", {"navigation": 1, "product": 2}
            ),
        },
        output={
            "url_list": True,
            "product_csv": args.task_type == "product",
        },
    )


def worker_command(
    db: Path, tasks_dir: Path, per_domain_rps: float
) -> list[str]:
    return [
        sys.executable,
        str(ROOT / "runtime_cli.py"),
        "worker",
        "run",
        "--db",
        str(db),
        "--out-root",
        str(tasks_dir),
        "--max-tasks",
        "1",
        "--per-domain-rps",
        str(per_domain_rps),
    ]


def start_worker(
    db: Path, tasks_dir: Path, per_domain_rps: float, log_path: Path
) -> tuple[subprocess.Popen[bytes], Any]:
    log = log_path.open("wb")
    process = subprocess.Popen(
        worker_command(db, tasks_dir, per_domain_rps),
        cwd=str(REPO_ROOT),
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    return process, log


def task_summary(store: TaskStore, task_id: str) -> dict[str, Any]:
    task = store.get_task(task_id)
    if task is None:
        raise RuntimeError(f"task not found: {task_id}")
    return {
        "task_id": task.task_id,
        "state": task.state,
        "outcome": task.outcome,
        "stop_reason": task.stop_reason,
        "item_counts": {
            "navigation": store.item_counts(task.task_id, "navigation"),
            "product": store.item_counts(task.task_id, "product"),
        },
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    args = parse_args(argv)
    try:
        rule = load_rule(args.rule)
        rule.validate_task_type(args.task_type)
        demo_dir = Path(args.demo_dir)
        tasks_dir = demo_dir / "tasks"
        demo_dir.mkdir(parents=True, exist_ok=True)
        db = demo_dir / "tasks.db"
        store = TaskStore(db)
        if store.get_task(args.task_id) is not None:
            raise RuntimeError(f"task already exists: {args.task_id}")
        task = build_task(rule, args)
        store.create_task(task)
        logger.info("task=%s kill_after=%.1fs", task.task_id, args.kill_after)

        crash_log = demo_dir / "worker-crash.log"
        process, log = start_worker(
            db, tasks_dir, args.per_domain_rps, crash_log
        )
        try:
            time.sleep(max(args.kill_after, 0.1))
            if process.poll() is not None:
                raise RuntimeError("worker finished before it could be killed")
            logger.info("terminating worker pid=%s", process.pid)
            process.terminate()
            process.wait(timeout=15)
        finally:
            log.close()
        after_kill = task_summary(store, task.task_id)
        in_flight = sum(
            after_kill["item_counts"][kind].get("IN_FLIGHT", 0)
            for kind in ("navigation", "product")
        )
        logger.info("after kill state=%s in_flight=%s", after_kill["state"], in_flight)
        if after_kill["state"] != "RUNNING":
            raise RuntimeError(
                f"expected RUNNING after kill, got {after_kill['state']}"
            )
        if in_flight < 1:
            raise RuntimeError("no IN_FLIGHT item found after kill")

        recovery_log = demo_dir / "worker-recovery.log"
        recovery, recovery_handle = start_worker(
            db, tasks_dir, args.per_domain_rps, recovery_log
        )
        try:
            code = recovery.wait(timeout=args.timeout)
        finally:
            recovery_handle.close()
        final = task_summary(store, task.task_id)
        logger.info("recovery exited=%s final=%s/%s", code, final["state"], final["outcome"])
        if code != 0:
            raise RuntimeError(f"recovery worker exited with {code}")
        if final["state"] != "FINISHED" or final["outcome"] != "COMPLETED":
            raise RuntimeError(
                f"expected FINISHED/COMPLETED, got {final['state']}/{final['outcome']}"
            )
        result_path = tasks_dir / task.task_id / "task-result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        payload = {
            "task_id": task.task_id,
            "after_kill": after_kill,
            "final": final,
            "recovery": result.get("recovery", {}),
            "demo_dir": str(demo_dir),
            "crash_log": str(crash_log),
            "recovery_log": str(recovery_log),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        logger.exception("crash smoke failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
