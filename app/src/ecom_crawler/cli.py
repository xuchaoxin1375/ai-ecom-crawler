"""Command-line entry point for the D02 export pipeline."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .model import ContractError
from .pipeline import export_run
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
    except ContractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
