#!/usr/bin/env python3
"""control_smoke.py - exercise pause/resume or cancel against a real site.

Usage:
    python experiments/r06/tools/control_smoke.py \
        --rule experiments/r06/plans/tognar-next-link-runtime.yaml \
        --demo-dir experiments/r06/tognar-control-demo \
        --task-id tognar-pause-resume --pause-after 3 --per-domain-rps 0.1

The script creates one task, starts a worker thread, pauses (or cancels) it,
then either resumes it or checks the cancelled terminal state. It prints one
JSON summary to stdout; progress goes to stderr through logging.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.models import Task
from runtime.rule import RulePackage, load_rule
from runtime.store import TaskStore
from runtime.worker import Worker

logger = logging.getLogger("control-smoke")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pause/resume or cancel one R06 task against a real rule package.",
    )
    parser.add_argument("--rule", required=True, help="rule package path")
    parser.add_argument(
        "--demo-dir",
        required=True,
        help="output directory; tasks.db and tasks/ are created inside",
    )
    parser.add_argument(
        "--task-id",
        default="control-smoke",
        help="task id (default: control-smoke)",
    )
    parser.add_argument(
        "--task-type",
        choices=["discovery", "product"],
        default="discovery",
        help="task type (default: discovery)",
    )
    parser.add_argument(
        "--pause-after",
        type=float,
        default=3.0,
        help="seconds to wait before pausing/cancelling (default: 3.0)",
    )
    parser.add_argument(
        "--cancel",
        action="store_true",
        help="cancel instead of pause/resume",
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
        "--join-timeout",
        type=float,
        default=180.0,
        help="seconds to wait for the worker thread (default: 180)",
    )
    return parser.parse_args(argv)


def build_task(rule: RulePackage, args: argparse.Namespace) -> Task:
    defaults = rule.task_defaults
    limits = {
        "max_urls": args.max_urls or int(defaults.get("max_urls", 100)),
        "max_products": args.max_products or int(defaults.get("max_products", 20)),
        "max_seconds": args.max_seconds or float(defaults.get("max_seconds", 180)),
        "max_attempts": int(defaults.get("max_attempts", 2)),
        "retry_backoff_ms": int(defaults.get("retry_backoff_ms", 1000)),
        "concurrency": defaults.get(
            "concurrency", {"navigation": 1, "product": 2}
        ),
    }
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
        limits=limits,
        output={
            "url_list": True,
            "product_csv": args.task_type == "product",
        },
    )


def start_worker(worker: Worker) -> threading.Thread:
    thread = threading.Thread(target=worker.run_once, name="control-worker")
    thread.start()
    return thread


def join_worker(thread: threading.Thread, timeout: float) -> None:
    thread.join(timeout=timeout)
    if thread.is_alive():
        raise TimeoutError(f"worker did not stop within {timeout:.0f}s")


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


def run_pause_resume(
    store: TaskStore, worker: Worker, task_id: str, args: argparse.Namespace
) -> dict[str, Any]:
    thread = start_worker(worker)
    time.sleep(max(args.pause_after, 0.1))
    logger.info("requesting pause: %s", task_id)
    store.update_task(task_id, state="PAUSING")
    join_worker(thread, args.join_timeout)
    paused = task_summary(store, task_id)
    logger.info("paused state=%s", paused["state"])
    if paused["state"] != "PAUSED":
        raise RuntimeError(f"expected PAUSED, got {paused['state']}")
    store.update_task(task_id, state="QUEUED")
    logger.info("resuming: %s", task_id)
    worker.run_once()
    final = task_summary(store, task_id)
    logger.info("final state=%s outcome=%s", final["state"], final["outcome"])
    if final["state"] != "FINISHED" or final["outcome"] != "COMPLETED":
        raise RuntimeError(
            f"expected FINISHED/COMPLETED, got {final['state']}/{final['outcome']}"
        )
    return {"paused": paused, "final": final}


def run_cancel(
    store: TaskStore, worker: Worker, task_id: str, args: argparse.Namespace
) -> dict[str, Any]:
    thread = start_worker(worker)
    time.sleep(max(args.pause_after, 0.1))
    logger.info("requesting cancel: %s", task_id)
    store.update_task(task_id, state="CANCELLING")
    join_worker(thread, args.join_timeout)
    final = task_summary(store, task_id)
    logger.info("final state=%s outcome=%s", final["state"], final["outcome"])
    if final["state"] != "CANCELLED" or final["outcome"] != "CANCELLED":
        raise RuntimeError(
            f"expected CANCELLED/CANCELLED, got {final['state']}/{final['outcome']}"
        )
    return {"final": final}


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
        store = TaskStore(demo_dir / "tasks.db")
        if store.get_task(args.task_id) is not None:
            raise RuntimeError(f"task already exists: {args.task_id}")
        task = build_task(rule, args)
        store.create_task(task)
        worker = Worker(
            store,
            out_root=tasks_dir,
            max_tasks=1,
            per_domain_rps=args.per_domain_rps,
        )
        logger.info(
            "task=%s type=%s pause_after=%.1fs cancel=%s",
            task.task_id,
            task.task_type,
            args.pause_after,
            args.cancel,
        )
        result = (
            run_cancel(store, worker, task.task_id, args)
            if args.cancel
            else run_pause_resume(store, worker, task.task_id, args)
        )
        payload = {"mode": "cancel" if args.cancel else "pause_resume", **result}
        payload["demo_dir"] = str(demo_dir)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        logger.exception("control smoke failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
