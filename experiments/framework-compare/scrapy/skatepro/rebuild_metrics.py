#!/usr/bin/env python3
"""Assemble experiment metrics from completed run outputs (no network).

The crawl itself writes ``task-result.json`` and ``diagnostics/run-meta.json``.
This helper turns those files into ``results/scrapy-skatepro.json`` /
``.md`` so a metrics refresh never re-crawls and never invents numbers.

Usage (from the repository root):

    python -m uv run --project experiments/framework-compare/scrapy \
        python experiments/framework-compare/scrapy/skatepro/rebuild_metrics.py \
        --build-started-at 2026-11-19T02:13:00Z \
        --plan-created-at 2026-11-19T02:40:00Z \
        --initial-run-dir experiments/framework-compare/scrapy/skatepro/diagnostics/run-001 \
        --fix-minutes 8
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from run import build_metrics, load_json, rel, render_markdown, write_json  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble skatepro.es run metrics")
    parser.add_argument("--output-dir", type=Path, default=SCRIPT_DIR)
    parser.add_argument("--results-dir", type=Path, default=SCRIPT_DIR.parents[1] / "results")
    parser.add_argument("--initial-run-dir", type=Path, default=None)
    parser.add_argument("--build-started-at", required=True)
    parser.add_argument("--plan-created-at", default="")
    parser.add_argument("--implementation-revisions", type=int, default=0)
    parser.add_argument("--runtime-llm-calls", type=int, default=0)
    parser.add_argument("--model-variant", default="high")
    parser.add_argument("--fix-minutes", type=float, default=0)
    parser.add_argument("--fix-note", default="")
    parser.add_argument("--fix-changes", default="")
    return parser.parse_args()


def metrics_for(directory: Path, args: argparse.Namespace, results_dir: Path):
    task_result = load_json(directory / "task-result.json")
    run_meta = load_json(directory / "diagnostics" / "run-meta.json")
    if run_meta is None:
        # Archived runs keep the two files side by side.
        run_meta = load_json(directory / "run-meta.json")
    if task_result is None:
        raise SystemExit(f"missing task-result.json in {directory}")
    return build_metrics(
        task_id=task_result.get("task_id", ""),
        task_result=task_result,
        run_meta=run_meta,
        build_started_at=args.build_started_at,
        plan_created_at=args.plan_created_at,
        implementation_revisions=args.implementation_revisions,
        runtime_llm_calls=args.runtime_llm_calls,
        model_variant=args.model_variant,
        run_started_at=task_result.get("started_at", ""),
        run_finished_at=task_result.get("finished_at", ""),
        output_dir=directory,
        results_dir=results_dir,
    )


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    results_dir = args.results_dir.resolve()

    metrics = metrics_for(output_dir, args, results_dir)

    if args.initial_run_dir:
        initial = metrics_for(args.initial_run_dir.resolve(), args, results_dir)
        metrics["initial_run"] = {
            "task_id": initial["task_id"],
            "plan_version": initial["plan_version"],
            "started_at": initial["started_at"],
            "finished_at": initial["finished_at"],
            "valid_products": initial["valid_products"],
            "excluded_products": initial["excluded_products"],
            "failed_products": initial["failed_products"],
            "partial_description_products": initial["partial_description_products"],
            "requests": initial["requests"],
            "outcome": initial["outcome"],
            "stop_reason": initial["stop_reason"],
            "failures": (load_json(args.initial_run_dir.resolve() / "task-result.json") or {}).get("errors", []),
            "note": "First complete-plan run before the fix task; kept for comparison, not overwritten.",
        }
        # Build-efficiency timestamps belong to the first run that produced a
        # valid product and a complete plan.
        metrics["first_valid_product_s"] = initial["first_valid_product_s"]
        metrics["first_plan_s"] = initial["first_plan_s"]
        metrics["errors_history"] = [
            {"run": "initial", **failure} for failure in initial.get("errors") or []
        ] + [{"run": "fix", **failure} for failure in metrics.get("errors") or []]

    if args.fix_minutes > 0:
        metrics["fix"] = {
            "status": "done",
            "fix_minutes": args.fix_minutes,
            "changes": args.fix_changes,
            "note": args.fix_note,
            "task_id": metrics["task_id"],
            "started_at": metrics["started_at"],
            "finished_at": metrics["finished_at"],
            "valid_products": metrics["valid_products"],
            "excluded_products": metrics["excluded_products"],
            "failed_products": metrics["failed_products"],
            "partial_description_products": metrics["partial_description_products"],
            "requests": metrics["requests"],
            "outcome": metrics["outcome"],
            "stop_reason": metrics["stop_reason"],
            "outputs": metrics["outputs"],
        }

    write_json(results_dir / "scrapy-skatepro.json", metrics)
    (results_dir / "scrapy-skatepro.md").write_text(render_markdown(metrics), encoding="utf-8")

    print(
        json.dumps(
            {
                "metrics": rel(results_dir / "scrapy-skatepro.json"),
                "task_id": metrics["task_id"],
                "valid_products": metrics["valid_products"],
                "failed_products": metrics["failed_products"],
                "requests": metrics["requests"],
                "first_valid_product_s": metrics["first_valid_product_s"],
                "first_plan_s": metrics["first_plan_s"],
                "initial_run": metrics.get("initial_run", {}).get("valid_products"),
                "fix_minutes": (metrics.get("fix") or {}).get("fix_minutes"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
