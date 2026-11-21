"""Command-line entry point for the D02 export pipeline."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .execution import run_and_export
from .model import ContractError
from .pipeline import export_run
from .runtime.rule import RuleError
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
    return parser


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
    except (ContractError, RuleError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
