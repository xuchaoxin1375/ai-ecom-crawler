"""CLI for the R06 declarative executor."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from .errors import PlanError
from .manifest import load_plan, plan_entry_url
from .runner import Runner, RunOptions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a declarative plan with the R06 minimal executor.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example:\n"
            "  python experiments/r06/run.py "
            "--plan experiments/r06/plans/familidoo.yaml "
            "--out-dir experiments/r06/familidoo --label r06-run-001\n"
        ),
    )
    parser.add_argument("--plan", required=True, help="declarative manifest YAML")
    parser.add_argument("--out-dir", required=True, help="output directory for CSV and task result")
    parser.add_argument("--label", default="r06-run-001", help="diagnostics label")
    parser.add_argument("--max-products", type=int, default=None, help="override the plan product cap")
    parser.add_argument("--max-seconds", type=float, default=None, help="override the wall-clock budget")
    parser.add_argument(
        "--build-started-at",
        default=None,
        help="optional ISO 8601 build-session start for first_valid_product_s",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        plan = load_plan(args.plan)
    except PlanError as exc:
        print(f"plan error: {exc}", file=sys.stderr)
        return 3

    scope = plan["scope"]
    fetch = plan["fetch"]
    max_products = args.max_products or scope.get("max_products") or 20
    max_seconds = args.max_seconds or scope.get("max_seconds") or fetch.get("max_seconds") or 180
    if max_products < 1:
        parser.error("--max-products must be >= 1")
    if max_seconds <= 0:
        parser.error("--max-seconds must be > 0")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.label):
        parser.error("--label may contain letters, digits, dot, underscore and hyphen only")
    if args.build_started_at:
        try:
            datetime.fromisoformat(args.build_started_at)
        except ValueError:
            parser.error("--build-started-at must be ISO 8601")

    options = RunOptions(
        out_dir=Path(args.out_dir).resolve(),
        label=args.label,
        max_products=int(max_products),
        max_seconds=float(max_seconds),
        build_started_at=args.build_started_at,
    )
    print(
        f"plan={plan['plan_id']} version={plan['plan_version']} "
        f"entry={plan_entry_url(plan)} max_products={options.max_products} "
        f"max_seconds={options.max_seconds}"
    )
    return Runner(plan, options).run()
