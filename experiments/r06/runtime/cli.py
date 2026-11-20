"""CLI for the R06 task runtime prototype."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from .models import Task, utc_now
from .rule import RuleError, load_rule
from .store import TaskStore
from .worker import Worker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="R06 task runtime prototype: rules, tasks, SQLite ledger and parallel workers."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    rule = sub.add_parser("rule", help="rule package commands")
    rule_sub = rule.add_subparsers(dest="rule_command", required=True)
    rule_validate = rule_sub.add_parser("validate", help="validate a rule package")
    rule_validate.add_argument("--rule", required=True)

    task = sub.add_parser("task", help="task commands")
    task_sub = task.add_subparsers(dest="task_command", required=True)

    create = task_sub.add_parser("create", help="create a task")
    create.add_argument("--db", required=True)
    create.add_argument("--rule", required=True)
    create.add_argument("--task-type", choices=["discovery", "product"], required=True)
    create.add_argument("--out-root", required=True)
    create.add_argument("--task-id", default=None)
    create.add_argument("--max-urls", type=int, default=None)
    create.add_argument("--max-products", type=int, default=None)
    create.add_argument("--max-seconds", type=float, default=None)
    create.add_argument("--start", action="store_true", help="queue immediately")

    list_cmd = task_sub.add_parser("list", help="list tasks")
    list_cmd.add_argument("--db", required=True)

    status = task_sub.add_parser("status", help="show one task")
    status.add_argument("--db", required=True)
    status.add_argument("--task-id", required=True)

    for name in ("pause", "resume", "cancel"):
        control = task_sub.add_parser(name, help=f"{name} a task")
        control.add_argument("--db", required=True)
        control.add_argument("--task-id", required=True)

    worker = sub.add_parser("worker", help="worker commands")
    worker_sub = worker.add_subparsers(dest="worker_command", required=True)
    worker_run = worker_sub.add_parser("run", help="run queued tasks until idle")
    worker_run.add_argument("--db", required=True)
    worker_run.add_argument("--out-root", required=True)
    worker_run.add_argument("--max-tasks", type=int, default=2)
    worker_run.add_argument("--per-domain-rps", type=float, default=1.0)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "rule":
        return _rule(args)
    if args.command == "task":
        return _task(args)
    if args.command == "worker":
        return _worker(args)
    parser.error("unknown command")
    return 2


def _rule(args: argparse.Namespace) -> int:
    try:
        rule = load_rule(args.rule)
    except RuleError as exc:
        print(f"rule error: {exc}", file=sys.stderr)
        return 3
    print(
        f"OK: {rule.rule_id} {rule.rule_version} "
        f"discovery={rule.capabilities.get('discovery')} "
        f"product={rule.capabilities.get('product')} entry={rule.entry_url}"
    )
    return 0


def _task(args: argparse.Namespace) -> int:
    store = TaskStore(args.db)
    if args.task_command == "create":
        return _task_create(store, args)
    if args.task_command == "list":
        return _task_list(store)
    if args.task_command == "status":
        return _task_status(store, args.task_id)
    if args.task_command in {"pause", "resume", "cancel"}:
        return _task_control(store, args.task_id, args.task_command)
    return 2


def _task_create(store: TaskStore, args: argparse.Namespace) -> int:
    try:
        rule = load_rule(args.rule)
        rule.validate_task_type(args.task_type)
    except RuleError as exc:
        print(f"rule error: {exc}", file=sys.stderr)
        return 3
    defaults = rule.task_defaults
    max_urls = args.max_urls or int(defaults.get("max_urls", 100))
    max_products = args.max_products or int(defaults.get("max_products", 20))
    max_seconds = args.max_seconds or float(defaults.get("max_seconds", 180))
    task_id = args.task_id or _default_task_id(rule.rule_id, args.task_type)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", task_id):
        print("task_id may contain letters, digits, dot, underscore and hyphen", file=sys.stderr)
        return 3
    task = Task(
        task_id=task_id,
        rule_id=rule.rule_id,
        rule_version=rule.rule_version,
        task_type=args.task_type,
        state="QUEUED" if args.start else "DRAFT",
        input={
            "rule_path": str(Path(args.rule)),
            "entry_urls": [rule.entry_url],
        },
        limits={
            "max_urls": max_urls,
            "max_products": max_products,
            "max_seconds": max_seconds,
            "concurrency": defaults.get("concurrency", {"navigation": 1, "product": 2}),
        },
        output={
            "url_list": True,
            "product_csv": args.task_type == "product",
        },
    )
    try:
        store.create_task(task)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    print(
        f"created {task.task_id} type={task.task_type} state={task.state} "
        f"max_urls={max_urls} max_products={max_products} max_seconds={max_seconds}"
    )
    return 0


def _task_list(store: TaskStore) -> int:
    tasks = store.list_tasks()
    if not tasks:
        print("no tasks")
        return 0
    for task in tasks:
        counts = store.item_counts(task.task_id, "product")
        print(
            f"{task.task_id}\t{task.task_type}\t{task.state}\t"
            f"outcome={task.outcome or '-'}\tstop={task.stop_reason or '-'}\t"
            f"product_items={sum(counts.values())}"
        )
    return 0


def _task_status(store: TaskStore, task_id: str) -> int:
    task = store.get_task(task_id)
    if task is None:
        print(f"task not found: {task_id}", file=sys.stderr)
        return 3
    payload = {
        "task_id": task.task_id,
        "rule_id": task.rule_id,
        "rule_version": task.rule_version,
        "task_type": task.task_type,
        "state": task.state,
        "outcome": task.outcome,
        "stop_reason": task.stop_reason,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "limits": task.limits,
        "output": task.output,
        "counters": task.counters,
        "item_counts": {
            "navigation": store.item_counts(task.task_id, "navigation"),
            "product": store.item_counts(task.task_id, "product"),
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _task_control(store: TaskStore, task_id: str, action: str) -> int:
    task = store.get_task(task_id)
    if task is None:
        print(f"task not found: {task_id}", file=sys.stderr)
        return 3
    if action == "pause":
        if task.state == "RUNNING":
            store.update_task(task_id, state="PAUSING")
        elif task.state == "QUEUED":
            store.update_task(task_id, state="PAUSED")
        elif task.state in {"PAUSING", "PAUSED"}:
            pass
        else:
            print(f"cannot pause task in state {task.state}", file=sys.stderr)
            return 3
    elif action == "resume":
        if task.state == "PAUSED":
            store.update_task(task_id, state="QUEUED")
        elif task.state in {"QUEUED", "RUNNING"}:
            pass
        else:
            print(f"cannot resume task in state {task.state}", file=sys.stderr)
            return 3
    elif action == "cancel":
        if task.state in {"DRAFT", "QUEUED"}:
            store.update_task(
                task_id,
                state="CANCELLED",
                outcome="CANCELLED",
                stop_reason="USER_CANCELLED",
                finished_at=utc_now(),
            )
        elif task.state in {"RUNNING", "PAUSING"}:
            store.update_task(task_id, state="CANCELLING")
        elif task.state == "PAUSED":
            store.update_task(
                task_id,
                state="CANCELLED",
                outcome="CANCELLED",
                stop_reason="USER_CANCELLED",
                finished_at=utc_now(),
            )
        elif task.state in {"CANCELLING", "CANCELLED"}:
            pass
        else:
            print(f"cannot cancel task in state {task.state}", file=sys.stderr)
            return 3
    else:
        return 2
    current = store.get_task(task_id)
    print(f"{task_id} {current.state if current else 'MISSING'}")
    return 0


def _worker(args: argparse.Namespace) -> int:
    store = TaskStore(args.db)
    worker = Worker(
        store,
        out_root=args.out_root,
        max_tasks=args.max_tasks,
        per_domain_rps=args.per_domain_rps,
    )
    worker.run_once()
    print("worker idle")
    return 0


def _default_task_id(rule_id: str, task_type: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{rule_id}-{task_type}-{stamp}".lower()


if __name__ == "__main__":
    sys.exit(main())
