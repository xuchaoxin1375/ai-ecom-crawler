#!/usr/bin/env python3
"""Run the bounded Scrapy trial and write contract-shaped outputs.

Usage (from the repository root):

    python -m uv run --project experiments/framework-compare/scrapy \
        python experiments/framework-compare/scrapy/javaestate/run.py \
        --max-products 30 --max-seconds 600

The run is bounded by product count and wall-clock time.  It never calls an
LLM.  Outputs are written next to this script; experiment metrics are written
to experiments/framework-compare/results/.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

os.environ.setdefault("SCRAPY_SETTINGS_MODULE", "javaestate.settings")

from scrapy.crawler import CrawlerProcess  # noqa: E402
from scrapy.utils.project import get_project_settings  # noqa: E402

from javaestate.normalize import PLAN_ID, PLAN_VERSION  # noqa: E402
from javaestate.spiders.products import ProductsSpider  # noqa: E402

FRAMEWORK = "Scrapy"
FRAMEWORK_VERSION = "2.20.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bounded javaestate.com Scrapy trial")
    parser.add_argument("--max-products", type=int, default=30)
    parser.add_argument("--max-seconds", type=int, default=600)
    parser.add_argument("--output-dir", type=Path, default=SCRIPT_DIR)
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=SCRIPT_DIR.parents[1] / "results",
        help="experiments/framework-compare/results",
    )
    parser.add_argument("--task-id", default="")
    parser.add_argument(
        "--base-url",
        default="https://javaestate.com",
        help="Developer/testing override; production uses https://javaestate.com",
    )
    parser.add_argument(
        "--build-started-at",
        default="",
        help="ISO 8601 build/session start; used for first_valid_product_s and first_plan_s",
    )
    parser.add_argument("--plan-created-at", default="")
    parser.add_argument("--revisions", type=int, default=0)
    parser.add_argument("--implementation-revisions", type=int, default=0)
    parser.add_argument("--runtime-llm-calls", type=int, default=0)
    return parser.parse_args()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def compact_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_manifest_created_at(output_dir: Path) -> str:
    manifest = output_dir / "manifest.yaml"
    if not manifest.exists():
        return ""
    text = manifest.read_text(encoding="utf-8")
    match = re.search(r"^created_at:\s*[\"']?([^\"'\n]+)", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_metrics(
    *,
    task_id: str,
    task_result: dict[str, Any] | None,
    run_meta: dict[str, Any] | None,
    build_started_at: str,
    plan_created_at: str,
    revisions: int,
    implementation_revisions: int,
    runtime_llm_calls: int,
    run_started_at: str,
    run_finished_at: str,
    output_dir: Path,
    results_dir: Path,
) -> dict[str, Any]:
    result = task_result or {}
    meta = run_meta or {}
    counts = result.get("counts", {})
    stats = meta.get("stats", {})
    build_dt = parse_dt(build_started_at)
    plan_dt = parse_dt(plan_created_at)
    first_valid_dt = parse_dt(meta.get("first_valid_at"))

    first_valid_s = None
    if build_dt and first_valid_dt:
        first_valid_s = round((first_valid_dt - build_dt).total_seconds(), 1)
    first_plan_s = None
    if build_dt and plan_dt:
        first_plan_s = round((plan_dt - build_dt).total_seconds(), 1)

    requests = stats.get("downloader/request_count")
    catalog_429 = sum(
        1
        for event in meta.get("events") or []
        if str(event.get("stage", "")).startswith("catalog_page")
        and event.get("status") == 429
    )
    catalog_success = len(meta.get("catalog_pages") or [])
    request_stats = {
        "requests": requests,
        "responses_200": stats.get("downloader/response_status_count/200"),
        "responses_429": stats.get("downloader/response_status_count/429"),
        "responses_403": stats.get("downloader/response_status_count/403"),
        "responses_404": stats.get("downloader/response_status_count/404"),
        "robots_txt_requests": stats.get("robots_txt/request_count", 1),
        "sitemap_requests": 2 if meta.get("denominator") else 0,
        "homepage_requests": 1 if (meta.get("statuses") or {}).get("homepage") else 0,
        "catalog_page_requests": catalog_success + catalog_429,
        "catalog_http_429_events": catalog_429,
        "product_html_requests": 0,
    }

    return {
        "framework": FRAMEWORK,
        "framework_version": FRAMEWORK_VERSION,
        "plan_id": PLAN_ID,
        "plan_version": PLAN_VERSION,
        "plan_path": str(Path("experiments/framework-compare/scrapy/javaestate").as_posix()),
        "task_id": task_id,
        "started_at": result.get("started_at") or run_started_at,
        "finished_at": result.get("finished_at") or run_finished_at,
        "run_started_at": run_started_at,
        "run_finished_at": run_finished_at,
        "wall_clock_s": round(
            (
                (parse_dt(result.get("finished_at") or run_finished_at) or datetime.now(timezone.utc))
                - (parse_dt(result.get("started_at") or run_started_at) or datetime.now(timezone.utc))
            ).total_seconds(),
            1,
        ),
        "build_started_at": build_started_at or None,
        "plan_created_at": plan_created_at or None,
        "first_valid_product_s": first_valid_s,
        "first_plan_s": first_plan_s,
        "revisions": revisions,
        "implementation_revisions": implementation_revisions,
        "runtime_llm_calls": runtime_llm_calls,
        "requests": requests,
        "request_stats": request_stats,
        "valid_products": counts.get("valid_products", 0),
        "excluded_products": counts.get("excluded_products", 0),
        "failed_products": counts.get("failed_products", 0),
        "partial_description_products": counts.get("partial_description_products", 0),
        "pending_products": counts.get("pending_products", 0),
        "processed_products": counts.get("processed_products", 0),
        "outcome": result.get("outcome"),
        "stop_reason": result.get("stop_reason"),
        "coverage": result.get("coverage"),
        "counts": counts,
        "currency": result.get("currency"),
        "errors": result.get("errors") or meta.get("errors") or [],
        "limitations": result.get("limitations") or [],
        "outputs": {
            "valid_csv": rel(output_dir / "valid.csv"),
            "task_result": rel(output_dir / "task-result.json"),
            "diagnostics": rel(output_dir / "diagnostics"),
            "metrics_json": rel(results_dir / "scrapy-javaestate.json"),
            "metrics_md": rel(results_dir / "scrapy-javaestate.md"),
        },
        "notes": [
            "All numbers are read from the crawl stats and output files, not from model assertions.",
            "runtime_llm_calls is 0: extraction is deterministic Python.",
            "first_valid_product_s and first_plan_s are relative to --build-started-at when provided.",
        ],
    }


def render_markdown(metrics: dict[str, Any]) -> str:
    coverage = metrics.get("coverage") or {}
    lines = [
        "# Scrapy / javaestate.com 试跑指标",
        "",
        f"- 方案：`{metrics['plan_path']}`（{metrics['plan_id']} / {metrics['plan_version']}）",
        f"- 框架：{metrics['framework']} {metrics['framework_version']}",
        f"- 运行窗口：{metrics['started_at']} → {metrics['finished_at']}（{metrics['wall_clock_s']}s）",
        f"- 状态：{metrics['outcome']} / {metrics['stop_reason']}",
        "",
        "## 指标",
        "",
        "| 指标 | 值 |",
        "| --- | --- |",
        f"| 首个有效商品 | {metrics['first_valid_product_s']}s |",
        f"| 首个完整方案 | {metrics['first_plan_s']}s |",
        f"| 修订次数（方案） | {metrics['revisions']} |",
        f"| 实现修订（构建期） | {metrics.get('implementation_revisions', 0)} |",
        f"| 运行期 LLM 调用 | {metrics['runtime_llm_calls']} |",
        f"| 请求数 | {metrics['requests']} |",
        f"| 有效商品 | {metrics['valid_products']} |",
        f"| 排除商品 | {metrics['excluded_products']} |",
        f"| 失败商品 | {metrics['failed_products']} |",
        f"| 部分描述 | {metrics['partial_description_products']} |",
        f"| 待处理商品 | {metrics['pending_products']} |",
        "",
        "## 覆盖",
        "",
        f"- status: {coverage.get('status')}",
        f"- denominator: {coverage.get('denominator')}（{coverage.get('denominator_source')}）",
        f"- covered: {coverage.get('covered')}",
        f"- notes: {coverage.get('notes')}",
        "",
        "## 错误",
        "",
    ]
    errors = metrics.get("errors") or []
    if errors:
        for error in errors:
            lines.append(
                f"- {error.get('at')} `{error.get('stage')}` {error.get('code')}: "
                f"{error.get('message')} ({error.get('url')})"
            )
    else:
        lines.append("- 无请求或解析错误。")
    lines += ["", "## 限制", ""]
    for limitation in metrics.get("limitations") or []:
        lines.append(f"- {limitation}")
    rerun = metrics.get("rerun")
    if rerun:
        lines += [
            "",
            "## 复跑",
            "",
            f"- task_id: {rerun.get('task_id')}",
            f"- 运行窗口: {rerun.get('started_at')} → {rerun.get('finished_at')}",
            f"- 结果: {rerun.get('valid_products')} valid / {rerun.get('failed_products')} failed；"
            f"{rerun.get('outcome')} / {rerun.get('stop_reason')}",
            f"- 说明: {rerun.get('note')}",
        ]
    lines += [
        "",
        "## 输出",
        "",
        f"- 有效 CSV：`{metrics['outputs']['valid_csv']}`",
        f"- 任务结果：`{metrics['outputs']['task_result']}`",
        f"- 诊断：`{metrics['outputs']['diagnostics']}`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    results_dir = args.results_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "diagnostics").mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    run_started_at = iso_now()
    task_id = args.task_id or f"fc-scrapy-javaestate-{compact_utc()}"

    settings = get_project_settings()
    settings.set("CLOSESPIDER_TIMEOUT", args.max_seconds)
    settings.set("MAX_PRODUCTS", args.max_products)
    settings.set("MAX_SECONDS", args.max_seconds)
    settings.set("OUTPUT_DIR", str(output_dir))
    settings.set("RESULTS_DIR", str(results_dir))
    settings.set("TASK_ID", task_id)
    settings.set("LOG_FILE", str(output_dir / "diagnostics" / "scrapy.log"))
    settings.set("LOG_FILE_APPEND", False)

    process = CrawlerProcess(settings)
    process.crawl(
        ProductsSpider,
        max_products=args.max_products,
        max_seconds=args.max_seconds,
        base_url=args.base_url,
    )
    interrupted = False
    try:
        process.start()
    except KeyboardInterrupt:
        interrupted = True
        print("Interrupted; the pipeline writes accepted results at spider close.", file=sys.stderr)

    run_finished_at = iso_now()
    task_result = load_json(output_dir / "task-result.json")
    run_meta = load_json(output_dir / "diagnostics" / "run-meta.json")

    if task_result is None:
        task_result = {
            "task_id": task_id,
            "plan_id": PLAN_ID,
            "plan_version": PLAN_VERSION,
            "market": "US",
            "locale": "en-US",
            "state": "FINISHED",
            "outcome": "FAILED",
            "stop_reason": "ENVIRONMENT_ERROR",
            "started_at": run_started_at,
            "finished_at": run_finished_at,
            "counts": {
                "discovered_urls": 0,
                "pending_navigation_entries": 0,
                "product_candidates": 0,
                "pending_products": 0,
                "in_flight_products": 0,
                "processed_products": 0,
                "valid_products": 0,
                "excluded_products": 0,
                "failed_products": 0,
                "partial_description_products": 0,
            },
            "coverage": {
                "status": "UNKNOWN",
                "denominator_source": None,
                "denominator": None,
                "covered": None,
                "notes": "Spider closed before the pipeline produced task-result.json.",
            },
            "business_acceptance": {
                "status": "NOT_REVIEWED",
                "accepted_by": None,
                "accepted_at": None,
                "reason": None,
                "scope": "bounded framework-comparison trial",
            },
            "runtime": {"llm_calls": 0, "raw_pages_retained": False},
            "errors": [
                {
                    "at": run_finished_at,
                    "stage": "run",
                    "code": "pipeline_output_missing",
                    "url": "",
                    "message": "task-result.json was not written; see scrapy.log",
                }
            ],
            "limitations": ["Spider did not complete; see diagnostics/scrapy.log."],
        }
        write_json(output_dir / "task-result.json", task_result)

    plan_created_at = args.plan_created_at or read_manifest_created_at(output_dir)
    metrics = build_metrics(
        task_id=task_id,
        task_result=task_result,
        run_meta=run_meta,
        build_started_at=args.build_started_at,
        plan_created_at=plan_created_at,
        revisions=args.revisions,
        implementation_revisions=args.implementation_revisions,
        runtime_llm_calls=args.runtime_llm_calls,
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
        output_dir=output_dir,
        results_dir=results_dir,
    )
    if interrupted:
        metrics["notes"].append("Run was interrupted by the operator (KeyboardInterrupt).")
    write_json(results_dir / "scrapy-javaestate.json", metrics)
    (results_dir / "scrapy-javaestate.md").write_text(render_markdown(metrics), encoding="utf-8")

    print(
        json.dumps(
            {
                "task_id": task_id,
                "outcome": metrics["outcome"],
                "stop_reason": metrics["stop_reason"],
                "valid_products": metrics["valid_products"],
                "excluded_products": metrics["excluded_products"],
                "failed_products": metrics["failed_products"],
                "requests": metrics["requests"],
                "first_valid_product_s": metrics["first_valid_product_s"],
                "first_plan_s": metrics["first_plan_s"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if metrics["valid_products"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
