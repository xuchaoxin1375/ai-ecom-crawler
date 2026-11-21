"""Command-line entry point for the D02 export pipeline."""

from __future__ import annotations

import argparse
import ipaddress
import json
import signal
import sys
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .execution import run_and_export, submit_task
from .model import ContractError
from .pipeline import export_run
from .runtime.lock import WorkerLockError, worker_lock
from .runtime.models import Task
from .runtime.rule import RuleError
from .runtime.store import TaskNotFoundError, TaskStore, TaskTransitionError
from .runtime.worker import Worker
from .validate import validate_run, validate_task_result_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ecom-crawler",
        description=(
            "Normalize candidate product records and export the docs/02 9-column CSV "
            "plus a docs/09 task result."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export = subparsers.add_parser(
        "export",
        help="export a run directory into products.csv and task-result.json",
    )
    export.add_argument(
        "--run-dir",
        required=True,
        type=Path,
        help="directory containing task.json and candidates.jsonl",
    )
    export.add_argument("--out-dir", required=True, type=Path, help="output directory")
    export.add_argument(
        "--force",
        action="store_true",
        help="replace existing products.csv and task-result.json",
    )

    validate = subparsers.add_parser(
        "validate",
        help="validate a task result or an exported run directory",
    )
    target = validate.add_mutually_exclusive_group(required=True)
    target.add_argument("--task-result", type=Path, help="path to task-result.json")
    target.add_argument("--run-dir", type=Path, help="exported run directory")

    run = subparsers.add_parser(
        "run",
        help="run a declarative rule package and export its D02 outputs",
    )
    run.add_argument("--rule", required=True, type=Path, help="rule package YAML")
    run.add_argument("--db", required=True, type=Path, help="SQLite task ledger")
    run.add_argument("--out-root", required=True, type=Path, help="task output root")
    run.add_argument("--task-id", default=None, help="stable task id")
    run.add_argument("--task-type", choices=("product", "discovery"), default="product")
    run.add_argument("--max-urls", type=int, default=100)
    run.add_argument("--max-products", type=int, default=20)
    run.add_argument("--max-seconds", type=int, default=180)
    run.add_argument("--max-attempts", type=int, default=2)
    run.add_argument("--per-domain-rps", type=float, default=1.0)
    run.add_argument(
        "--export-dir",
        type=Path,
        default=None,
        help="D02 export directory; defaults to <out-root>/<task-id>/export",
    )
    run.add_argument(
        "--partial-reason",
        default=None,
        help="override the generic R06 partial-description reason",
    )

    submit = subparsers.add_parser(
        "submit",
        help="create a QUEUED task without executing it",
    )
    submit.add_argument("--rule", required=True, type=Path, help="rule package YAML")
    submit.add_argument("--db", required=True, type=Path, help="SQLite task ledger")
    submit.add_argument("--task-id", default=None, help="stable task id")
    submit.add_argument(
        "--task-type", choices=("product", "discovery"), default="product"
    )
    submit.add_argument("--max-urls", type=int, default=100)
    submit.add_argument("--max-products", type=int, default=20)
    submit.add_argument("--max-seconds", type=int, default=180)
    submit.add_argument("--max-attempts", type=int, default=2)

    worker = subparsers.add_parser(
        "worker",
        help="run queued tasks until interrupted; use pause/resume/cancel from another shell",
    )
    worker.add_argument("--db", required=True, type=Path, help="SQLite task ledger")
    worker.add_argument("--out-root", required=True, type=Path, help="task output root")
    worker.add_argument(
        "--max-tasks",
        type=int,
        default=1,
        help="concurrent task slots (default: 1)",
    )
    worker.add_argument("--per-domain-rps", type=float, default=1.0)
    worker.add_argument("--poll-interval", type=float, default=0.5)

    for name, help_text in (
        ("pause", "request a pause for a running task"),
        ("resume", "requeue a paused task"),
        ("cancel", "cancel a task and reject late results"),
    ):
        control = subparsers.add_parser(name, help=help_text)
        control.add_argument(
            "--db", required=True, type=Path, help="SQLite task ledger"
        )
        control.add_argument("--task-id", required=True, help="task to control")

    status = subparsers.add_parser(
        "status",
        help="show one task's state and item counts",
    )
    status.add_argument("--db", required=True, type=Path, help="SQLite task ledger")
    status.add_argument("--task-id", required=True, help="task to inspect")
    status.add_argument("--json", action="store_true", help="print JSON")

    task_list = subparsers.add_parser(
        "list",
        help="list tasks in the ledger",
    )
    task_list.add_argument("--db", required=True, type=Path, help="SQLite task ledger")
    task_list.add_argument(
        "--state",
        action="append",
        default=None,
        help="filter by state; repeat for multiple states",
    )
    task_list.add_argument("--json", action="store_true", help="print JSON")

    serve = subparsers.add_parser(
        "serve",
        help="serve the read-only local web UI and API",
    )
    serve.add_argument("--db", required=True, type=Path, help="SQLite task ledger")
    serve.add_argument("--out-root", required=True, type=Path, help="task output root")
    serve.add_argument(
        "--rules-dir",
        type=Path,
        default=None,
        help="managed rule package directory for create/control",
    )
    serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="loopback address (default: 127.0.0.1)",
    )
    serve.add_argument("--port", type=int, default=8765, help="HTTP port (default: 8765)")
    serve.add_argument(
        "--no-worker",
        action="store_true",
        help="serve only; do not start an in-process worker",
    )
    serve.add_argument(
        "--max-tasks",
        type=int,
        default=1,
        help="managed worker task slots (default: 1)",
    )
    serve.add_argument("--per-domain-rps", type=float, default=1.0)
    return parser


def _run_worker(args: argparse.Namespace) -> int:
    with worker_lock(args.db):
        store = TaskStore(args.db)
        worker = Worker(
            store,
            out_root=args.out_root,
            max_tasks=args.max_tasks,
            per_domain_rps=args.per_domain_rps,
        )
        stop = threading.Event()

        def request_stop(signum: int, frame: Any) -> None:
            stop.set()

        previous: dict[int, Any] = {}
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                previous[sig] = signal.signal(sig, request_stop)
            except (ValueError, OSError):
                continue
        try:
            started = worker.run_forever(
                stop_event=stop,
                poll_interval=args.poll_interval,
            )
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    print(f"worker stopped; started {started} task(s)")
    return 0


def _serve(args: argparse.Namespace) -> int:
    host = str(args.host)
    if host != "localhost":
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ContractError("--host must be localhost or a loopback address") from exc
        if not address.is_loopback:
            raise ContractError("--host must be a loopback address")
    import uvicorn

    from .web.app import create_app

    app = create_app(
        args.db,
        args.out_root,
        args.rules_dir,
        manage_worker=not args.no_worker,
        max_tasks=args.max_tasks,
        per_domain_rps=args.per_domain_rps,
    )
    mode = "read-only" if args.no_worker else "managed worker"
    print(f"serving http://{host}:{args.port} ({mode})")
    if args.no_worker:
        uvicorn.run(app, host=host, port=args.port, log_level="info")
    else:
        with worker_lock(args.db):
            uvicorn.run(app, host=host, port=args.port, log_level="info")
    return 0


def _task_payload(store: TaskStore, task: Task) -> dict[str, Any]:
    states = ("PENDING", "IN_FLIGHT", "DONE", "EXCLUDED", "FAILED")
    counts = store.item_counts(task.task_id)
    return {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "plan_id": task.plan_id,
        "plan_version": task.plan_version,
        "state": task.state,
        "outcome": task.outcome,
        "stop_reason": task.stop_reason,
        "items": {state: counts.get(state, 0) for state in states},
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
    }


def _print_status(store: TaskStore, task_id: str, *, as_json: bool) -> int:
    task = store.get_task(task_id)
    if task is None:
        raise TaskNotFoundError(f"unknown task: {task_id}")
    payload = _task_payload(store, task)
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"task: {payload['task_id']}")
    print(
        f"state: {payload['state']}  outcome: {payload['outcome'] or '-'}  "
        f"stop_reason: {payload['stop_reason'] or '-'}"
    )
    print(
        f"plan: {payload['plan_id']}@{payload['plan_version']}  "
        f"type: {payload['task_type']}"
    )
    print("items: " + " ".join(f"{key}={value}" for key, value in payload["items"].items()))
    print(f"updated: {payload['updated_at']}")
    return 0


def _print_task_list(store: TaskStore, states: list[str] | None, *, as_json: bool) -> int:
    tasks = store.list_tasks(set(states) if states else None)
    payloads = [_task_payload(store, task) for task in tasks]
    if as_json:
        print(json.dumps(payloads, ensure_ascii=False, indent=2))
        return 0
    if not payloads:
        print("no tasks")
        return 0
    print("task_id\tstate\toutcome\ttype\tplan\tupdated_at")
    for payload in payloads:
        print(
            f"{payload['task_id']}\t{payload['state']}\t{payload['outcome'] or '-'}\t"
            f"{payload['task_type']}\t"
            f"{payload['plan_id']}@{payload['plan_version']}\t"
            f"{payload['updated_at']}"
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            result = export_run(args.run_dir, args.out_dir, force=args.force)
            counts = result.task_result["counts"]
            print(
                "exported: "
                f"{counts['valid_products']} valid, "
                f"{counts['excluded_products']} excluded, "
                f"{counts['failed_products']} failed"
            )
            print(f"outcome: {result.task_result['outcome']}  output: {args.out_dir}")
            return 0
        if args.command == "run":
            task_id = args.task_id or f"run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
            result = run_and_export(
                rule_path=args.rule,
                db_path=args.db,
                out_root=args.out_root,
                task_id=task_id,
                task_type=args.task_type,
                max_urls=args.max_urls,
                max_products=args.max_products,
                max_seconds=args.max_seconds,
                max_attempts=args.max_attempts,
                per_domain_rps=args.per_domain_rps,
                export_dir=args.export_dir,
                partial_reason=args.partial_reason,
            )
            counts = result.task_result.get("counts", {})
            print(
                f"task: {result.task_id} "
                f"{result.task_result.get('state')}/{result.task_result.get('outcome')}"
            )
            print(
                "counts: "
                f"valid={counts.get('valid_products', 0)} "
                f"excluded={counts.get('excluded_products', 0)} "
                f"failed={counts.get('failed_products', 0)}"
            )
            if result.app_export is not None:
                export_counts = result.app_export.task_result["counts"]
                print(
                    "exported: "
                    f"{export_counts['valid_products']} valid, "
                    f"{export_counts['excluded_products']} excluded, "
                    f"{export_counts['failed_products']} failed"
                )
                print(f"export: {result.export_dir}")
            return 0
        if args.command == "submit":
            task_id = args.task_id or f"submit-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
            task = submit_task(
                rule_path=args.rule,
                db_path=args.db,
                task_id=task_id,
                task_type=args.task_type,
                max_urls=args.max_urls,
                max_products=args.max_products,
                max_seconds=args.max_seconds,
                max_attempts=args.max_attempts,
            )
            print(f"submitted: {task.task_id} state={task.state}")
            return 0
        if args.command == "worker":
            return _run_worker(args)
        if args.command == "serve":
            return _serve(args)
        if args.command in {"pause", "resume", "cancel"}:
            store = TaskStore(args.db)
            task = getattr(store, f"request_{args.command}")(args.task_id)
            print(
                f"{args.command}: {task.task_id} state={task.state} "
                f"outcome={task.outcome or '-'}"
            )
            return 0
        if args.command == "status":
            return _print_status(TaskStore(args.db), args.task_id, as_json=args.json)
        if args.command == "list":
            return _print_task_list(TaskStore(args.db), args.state, as_json=args.json)
        if args.command == "validate":
            if args.task_result is not None:
                errors = validate_task_result_file(args.task_result)
                target = args.task_result
            else:
                errors = validate_run(args.run_dir)
                target = args.run_dir
            if errors:
                for error in errors:
                    print(f"ERROR: {error}", file=sys.stderr)
                return 1
            print(f"OK: {target}")
            return 0
    except (
        ContractError,
        RuleError,
        TaskNotFoundError,
        TaskTransitionError,
        WorkerLockError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
