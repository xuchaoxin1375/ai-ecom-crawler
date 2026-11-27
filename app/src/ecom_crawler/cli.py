"""Command-line entry point for the D02 export pipeline."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import signal
import socket
import sys
import threading
from collections.abc import Sequence
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .execution import run_and_export, submit_task
from .model import ContractError
from .pipeline import export_run
from .runtime.lock import WorkerLockError, worker_lock
from .runtime.models import Task, utc_now
from .runtime.rule import RuleError
from .runtime.store import TaskNotFoundError, TaskStore, TaskTransitionError
from .runtime.worker import Worker
from .validate import validate_run, validate_task_result_file
from .web.access import (
    MAX_ACCESS_TOKEN_LENGTH,
    new_token,
    reset_token_setting,
    stored_token_available,
    validate_access_token,
)


def _add_archive_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--archive-mode",
        choices=("off", "sample", "full"),
        default="off",
        help="save fetched pages locally: off, sample (bounded) or full",
    )
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=None,
        help="archive directory; defaults to <out-root>/archive",
    )
    parser.add_argument(
        "--archive-sample-limit",
        type=int,
        default=20,
        help="maximum pages written in sample mode (default: 20)",
    )
    parser.add_argument(
        "--archive-max-bytes",
        type=int,
        default=None,
        help="optional stored-bytes cap for one task",
    )
    parser.add_argument(
        "--archive-reuse",
        action="store_true",
        help="read archived pages before requesting the network",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="strict offline replay; requires --archive-mode full",
    )


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
        "--proxy",
        default=None,
        help="HTTP(S) or socks5 proxy for fetches; defaults to ECOM_FETCH_PROXY",
    )
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
    _add_archive_arguments(run)

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
    submit.add_argument(
        "--proxy",
        default=None,
        help="HTTP(S) or socks5 proxy recorded on the task; defaults to ECOM_FETCH_PROXY",
    )
    _add_archive_arguments(submit)

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
    worker.add_argument(
        "--max-browser-tasks",
        type=int,
        default=1,
        help="concurrent browser/hybrid task slots per worker; 0 disables the cap (default: 1)",
    )
    worker.add_argument("--per-domain-rps", type=float, default=1.0)
    worker.add_argument(
        "--proxy",
        default=None,
        help="HTTP(S) or socks5 proxy for fetches; defaults to ECOM_FETCH_PROXY",
    )
    worker.add_argument("--poll-interval", type=float, default=0.5)
    worker.add_argument(
        "--lease-ttl",
        type=float,
        default=30.0,
        help="task lease lifetime in seconds (default: 30)",
    )
    worker.add_argument(
        "--heartbeat-interval",
        type=float,
        default=None,
        help="lease renewal interval in seconds (default: min(5, ttl/3))",
    )
    worker.add_argument(
        "--allow-multi-worker",
        action="store_true",
        help="skip the single-instance lock and share the ledger via task leases",
    )

    for name, help_text in (
        ("pause", "pause a queued or running task"),
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

    audit = subparsers.add_parser(
        "audit-content",
        help="render sample product pages and report visible content missing from extraction",
    )
    audit.add_argument("--rule", required=True, type=Path, help="rule package YAML")
    audit.add_argument(
        "--url",
        action="append",
        required=True,
        dest="urls",
        help="product URL to audit; repeat for multiple pages",
    )
    audit.add_argument("--out", required=True, type=Path, help="audit output directory")
    audit.add_argument(
        "--headful",
        action="store_true",
        help="show the browser window instead of running headless",
    )
    audit.add_argument(
        "--no-screenshots",
        action="store_true",
        help="skip full-page screenshots",
    )
    audit.add_argument("--timeout-ms", type=int, default=45000)
    serve = subparsers.add_parser(
        "serve",
        help="serve the local web UI and API",
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
        help=(
            "bind address (default: 127.0.0.1); a non-loopback address requires "
            "an access key or a stored key from the system settings page"
        ),
    )
    serve.add_argument(
        "--access-token",
        default=None,
        help=(
            f"access key for LAN access (1-{MAX_ACCESS_TOKEN_LENGTH} characters); "
            "defaults to ECOM_SERVE_TOKEN. Required for a non-loopback --host"
        ),
    )
    serve.add_argument(
        "--dev-no-auth",
        action="store_true",
        help=(
            "skip access-key checks for loopback requests; development only; "
            "non-loopback clients still require the key"
        ),
    )
    serve.add_argument(
        "--allow-host",
        action="append",
        default=[],
        metavar="NAME",
        help=(
            "extra Host header name accepted with a non-loopback --host; "
            "repeat for multiple names"
        ),
    )
    serve.add_argument("--port", type=int, default=8765, help="HTTP port (default: 8765)")
    serve.add_argument(
        "--no-worker",
        action="store_true",
        help=(
            "do not start an in-process worker; API writes remain enabled "
            "for an external worker"
        ),
    )
    serve.add_argument(
        "--read-only",
        action="store_true",
        help=(
            "reject all write requests and build scheduling; requires an "
            "existing ledger and does not create a worker or build manager"
        ),
    )
    serve.add_argument(
        "--max-tasks",
        type=int,
        default=None,
        help="override saved managed worker task slots (application default: 1)",
    )
    serve.add_argument(
        "--max-builds",
        type=int,
        default=None,
        help="override saved rule-analysis slots (application default: 1)",
    )
    serve.add_argument(
        "--max-browser-tasks",
        type=int,
        default=1,
        help="managed worker browser/hybrid slots; 0 disables the cap (default: 1)",
    )
    serve.add_argument("--per-domain-rps", type=float, default=1.0)
    serve.add_argument(
        "--proxy",
        default=None,
        help="HTTP(S) or socks5 proxy for builds and managed worker fetches; defaults to ECOM_FETCH_PROXY",
    )
    serve.add_argument(
        "--lease-ttl",
        type=float,
        default=30.0,
        help="managed worker task lease lifetime in seconds (default: 30)",
    )
    serve.add_argument(
        "--heartbeat-interval",
        type=float,
        default=None,
        help="managed worker lease renewal interval in seconds",
    )
    serve.add_argument(
        "--allow-multi-worker",
        action="store_true",
        help="skip the single-instance lock and share the ledger via task leases",
    )
    reset_access = subparsers.add_parser(
        "reset-access-key",
        help="reset the web access key in an existing ledger (stop serve first)",
    )
    reset_access.add_argument(
        "--db",
        required=True,
        type=Path,
        help="SQLite task ledger",
    )
    reset_access.add_argument(
        "--key",
        default=None,
        help="custom access key; omit to generate a random key and print it once",
    )
    return parser


def _run_worker(args: argparse.Namespace) -> int:
    lock = nullcontext() if args.allow_multi_worker else worker_lock(args.db)
    with lock:
        store = TaskStore(args.db)
        worker = Worker(
            store,
            out_root=args.out_root,
            max_tasks=args.max_tasks,
            max_browser_tasks=args.max_browser_tasks,
            per_domain_rps=args.per_domain_rps,
            lease_ttl_seconds=args.lease_ttl,
            heartbeat_interval=args.heartbeat_interval,
            proxy=args.proxy,
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


WILDCARD_HOSTS = frozenset({"0.0.0.0", "::"})


def _access_token_from(value: str | None) -> str | None:
    # Consume the environment copy so build subprocesses cannot inherit the token.
    env_token = (os.environ.pop("ECOM_SERVE_TOKEN", "") or "").strip()
    if value is not None:
        token = value.strip()
        if not token:
            raise ContractError("--access-token must not be empty")
        return token
    return env_token or None


def _normalize_allow_host(value: str) -> str:
    text = value.strip().lower()
    if not text:
        raise ContractError("--allow-host must not be empty")
    if "://" in text or any(character in text for character in "/?#"):
        raise ContractError(f"--allow-host must be a host name, not a URL: {value}")
    if text.startswith("["):
        if not text.endswith("]"):
            raise ContractError(f"--allow-host has an invalid IPv6 name: {value}")
        text = text[1:-1]
    elif text.count(":") == 1:
        text = text.rsplit(":", 1)[0]
    if ":" in text:
        try:
            ipaddress.IPv6Address(text)
        except ValueError as exc:
            raise ContractError(
                f"--allow-host has an invalid IPv6 name: {value}"
            ) from exc
    if not text or any(character.isspace() for character in text):
        raise ContractError(f"--allow-host has an invalid host name: {value}")
    return text.rstrip(".")


def _primary_lan_address() -> str | None:
    """Return the source address for the default route without sending a packet."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            address = str(probe.getsockname()[0])
    except OSError:
        return None
    return address if address and address != "0.0.0.0" else None


def _local_host_names(bound_host: str) -> set[str]:
    """Collect local names and addresses that a LAN client may use in Host."""
    names: set[str] = set()
    if bound_host not in WILDCARD_HOSTS:
        names.add(bound_host.lower())
    try:
        hostname = socket.gethostname()
    except OSError:
        hostname = ""
    if hostname:
        names.add(hostname.lower().rstrip("."))
        try:
            names.add(socket.getfqdn(hostname).lower().rstrip("."))
        except OSError:
            pass
        try:
            for info in socket.getaddrinfo(hostname, None):
                names.add(str(info[4][0]).lower())
        except OSError:
            pass
    primary = _primary_lan_address()
    if primary is not None:
        names.add(primary.lower())
    names.discard("")
    names.discard("0.0.0.0")
    names.discard("::")
    return names


def _resolve_serve_access(
    host: str,
    access_token: str | None,
    allow_hosts: Sequence[str],
    *,
    stored_token: bool = False,
) -> tuple[str, str | None, frozenset[str]]:
    """Validate bind/auth settings and return (host, token, allowed Host names)."""
    text = str(host).strip()
    if not text:
        raise ContractError("--host must not be empty")
    loopback = text == "localhost"
    if not loopback:
        try:
            address = ipaddress.ip_address(text)
        except ValueError as exc:
            raise ContractError(
                "--host must be localhost or an IP address; use 0.0.0.0 to "
                "listen on all interfaces"
            ) from exc
        loopback = address.is_loopback
    token = _access_token_from(access_token)
    if token is not None:
        try:
            token = validate_access_token(token)
        except ValueError as exc:
            raise ContractError(str(exc)) from exc
    extras = frozenset(_normalize_allow_host(item) for item in allow_hosts)
    if loopback:
        if extras:
            raise ContractError("--allow-host requires a non-loopback --host")
        return text, token, frozenset()
    if token is None and not stored_token:
        raise ContractError(
            "non-loopback --host requires --access-token, ECOM_SERVE_TOKEN, "
            "or a token generated from the system settings page"
        )
    allowed = frozenset(_local_host_names(text) | set(extras))
    return text, token, allowed


def _format_url_host(host: str) -> str:
    return f"[{host}]" if ":" in host else host


def _serve_urls(host: str, port: int, allowed_hosts: frozenset[str]) -> list[str]:
    if host not in WILDCARD_HOSTS:
        names = [host]
    else:
        want_ipv6 = host == "::"
        names = []
        for name in sorted(allowed_hosts):
            try:
                address = ipaddress.ip_address(name)
            except ValueError:
                continue
            if want_ipv6 and address.version != 6:
                continue
            if not want_ipv6 and address.version != 4:
                continue
            if address.is_loopback or address.is_link_local or address.is_unspecified:
                continue
            names.append(name)
        primary = _primary_lan_address()
        names.sort(key=lambda name: (name != primary, name))
    if not names:
        names = [host]
    return [f"http://{_format_url_host(name)}:{port}/" for name in names]


def _serve(args: argparse.Namespace) -> int:
    host, token, allowed_hosts = _resolve_serve_access(
        args.host,
        args.access_token,
        args.allow_host,
        stored_token=stored_token_available(args.db),
    )
    if args.read_only and not args.db.is_file():
        raise ContractError(
            f"--read-only requires an existing task ledger: {args.db}"
        )
    import uvicorn

    from .web.app import create_app

    urls = _serve_urls(host, args.port, allowed_hosts)
    app = create_app(
        args.db,
        args.out_root,
        args.rules_dir,
        manage_worker=not args.no_worker and not args.read_only,
        max_tasks=args.max_tasks,
        max_builds=args.max_builds,
        max_browser_tasks=args.max_browser_tasks,
        per_domain_rps=args.per_domain_rps,
        lease_ttl_seconds=args.lease_ttl,
        heartbeat_interval=args.heartbeat_interval,
        proxy=args.proxy,
        read_only=args.read_only,
        access_token=token,
        dev_no_auth=bool(args.dev_no_auth),
        allowed_hosts=allowed_hosts,
        serve_host=host,
        serve_port=args.port,
        access_urls=urls,
    )
    if args.read_only:
        mode = "read-only"
    elif args.no_worker:
        mode = "external worker"
    else:
        mode = "managed worker"
    if args.allow_multi_worker and not args.read_only:
        mode += ", shared ledger"
    if app.state.auth_required:
        mode += ", token auth"
    print(f"serving {urls[0]} ({mode})")
    for url in urls[1:]:
        print(f"also serving {url}")
    if app.state.auth_required:
        print(
            "access: browser login page (username ecom); "
            "CLI HTTP Basic username any, password = access key"
        )
    if app.state.dev_no_auth_active and app.state.auth_required:
        source = "startup flag" if app.state.dev_no_auth_forced else "saved setting"
        print(
            f"warning: developer mode ({source}) skips access-key checks for "
            "loopback requests; LAN clients still require the key"
        )
    if host in WILDCARD_HOSTS and urls[0] == (
        f"http://{_format_url_host(host)}:{args.port}/"
    ):
        print("warning: no LAN address detected; pass --allow-host or use a detected address")
    lock = (
        nullcontext()
        if args.read_only or args.no_worker or args.allow_multi_worker
        else worker_lock(args.db)
    )
    with lock:
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
        "lease": {
            "owner": task.lease_owner,
            "token": task.lease_token,
            "expires_at": task.lease_expires_at,
            "heartbeat_at": task.lease_heartbeat_at,
        },
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
    if payload["lease"]["owner"]:
        print(
            f"lease: {payload['lease']['owner']} "
            f"token={payload['lease']['token']} "
            f"expires_at={payload['lease']['expires_at']}"
        )
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


def _reset_access_key(args: argparse.Namespace) -> int:
    print(
        "note: stop serve before resetting; a running process keeps the old key "
        "until it is restarted."
    )
    if args.key is None:
        token, _salt, _digest = new_token()
        generated = True
    else:
        try:
            token = validate_access_token(args.key)
        except ValueError as exc:
            raise ContractError(str(exc)) from exc
        generated = False
    try:
        reset_token_setting(args.db, token, updated_at=utc_now())
    except ValueError as exc:
        raise ContractError(str(exc)) from exc
    if generated:
        print(f"access key: {token}")
        print("Store this key now; it is not saved in plaintext.")
    else:
        print("access key updated")
    print("restart serve to load the new key")
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
                proxy=args.proxy,
                archive_mode=args.archive_mode,
                archive_root=args.archive_root,
                archive_sample_limit=args.archive_sample_limit,
                archive_max_bytes=args.archive_max_bytes,
                archive_reuse=args.archive_reuse,
                offline=args.offline,
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
                proxy=args.proxy,
                archive_mode=args.archive_mode,
                archive_root=args.archive_root,
                archive_sample_limit=args.archive_sample_limit,
                archive_max_bytes=args.archive_max_bytes,
                archive_reuse=args.archive_reuse,
                offline=args.offline,
            )
            print(f"submitted: {task.task_id} state={task.state}")
            return 0
        if args.command == "worker":
            return _run_worker(args)
        if args.command == "audit-content":
            from .content_audit import audit_urls

            summary = audit_urls(
                args.rule,
                args.urls,
                args.out,
                headless=not args.headful,
                screenshots=not args.no_screenshots,
                timeout_ms=args.timeout_ms,
            )
            print(
                f"audited {summary['pages']} page(s): "
                f"{summary['pages_with_uncovered']} with uncovered blocks, "
                f"{summary['errors']} error(s)"
            )
            for item in summary["results"]:
                if item.get("uncovered_blocks"):
                    print(f"  gap: {item['url']}")
                    for block in item["uncovered_blocks"][:3]:
                        print(f"    - {block['text'][:160]}")
                if item.get("error"):
                    print(f"  error: {item['url']}: {item['error']}")
            print(f"report: {Path(args.out) / 'visual-audit.json'}")
            return 0 if summary["errors"] == 0 else 1
        if args.command == "reset-access-key":
            return _reset_access_key(args)
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
