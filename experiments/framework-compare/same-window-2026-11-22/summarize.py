#!/usr/bin/env python3
"""Summarize the same-window Crawlee/Scrapy runtime comparison."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
CASE = Path(__file__).resolve().parent
CRAWLEE = CASE / "crawlee"
SCRAPY = CASE / "scrapy"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl_prefix(path: Path, limit: int = 5) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
        if len(records) >= limit:
            break
    return records


def load_csv_prefix(path: Path, limit: int = 5) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [row for _, row in zip(range(limit), reader)]


def rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def main() -> int:
    shared = load_json(CASE / "shared-urls.json")
    shared_urls = list(shared["urls"])

    crawlee_tr = load_json(CRAWLEE / "task-result.json")
    crawlee_meta = load_json(CRAWLEE / "diagnostics" / "same-window-001" / "run-meta.json")
    crawlee_selected = load_json(
        CRAWLEE / "diagnostics" / "same-window-001" / "selected_urls.json"
    )
    crawlee_counts = crawlee_tr["counts"]
    crawlee_failures = load_jsonl_prefix(
        CRAWLEE / "diagnostics" / "same-window-001" / "failed.jsonl"
    )

    scrapy_tr = load_json(SCRAPY / "task-result.json")
    scrapy_metrics = load_json(SCRAPY / "results" / "scrapy-skatepro.json")
    scrapy_meta = load_json(SCRAPY / "diagnostics" / "run-meta.json")
    scrapy_counts = scrapy_tr["counts"]
    scrapy_selected = [entry["url"] for entry in scrapy_meta["selected"]]
    scrapy_failures = load_csv_prefix(SCRAPY / "diagnostics" / "failed_products.csv")

    arms = {
        "crawlee": {
            "framework": "Crawlee for Python",
            "framework_version": "1.11.2",
            "engine": "Playwright Chromium (browser)",
            "task_id": crawlee_tr["task_id"],
            "started_at": crawlee_tr["started_at"],
            "finished_at": crawlee_tr["finished_at"],
            "wall_seconds": crawlee_meta["wall_seconds"],
            "requests": crawlee_tr["runtime"]["requests_total_crawlee"],
            "selected": len(crawlee_selected["selected_urls"]),
            "processed": crawlee_counts["processed_products"],
            "valid": crawlee_counts["valid_products"],
            "excluded": crawlee_counts["excluded_products"],
            "failed": crawlee_counts["failed_products"],
            "pending": crawlee_counts["pending_products"],
            "partial_description": crawlee_counts["partial_description_products"],
            "success_rate": rate(
                crawlee_counts["valid_products"],
                len(crawlee_selected["selected_urls"]),
            ),
            "requests_per_valid": round(
                crawlee_tr["runtime"]["requests_total_crawlee"]
                / max(1, crawlee_counts["valid_products"]),
                2,
            ),
            "outcome": crawlee_tr["outcome"],
            "stop_reason": crawlee_tr["stop_reason"],
            "quality_exceptions": crawlee_tr.get("quality_exceptions") or [],
            "failure_samples": crawlee_failures,
            "selected_urls": crawlee_selected["selected_urls"],
            "outputs": {
                "task_result": "crawlee/task-result.json",
                "metrics": "crawlee/diagnostics/same-window-001/run-meta.json",
            },
        },
        "scrapy": {
            "framework": "Scrapy",
            "framework_version": scrapy_metrics["framework_version"],
            "engine": "Scrapy downloader (static HTTP)",
            "task_id": scrapy_tr["task_id"],
            "started_at": scrapy_tr["started_at"],
            "finished_at": scrapy_tr["finished_at"],
            "wall_seconds": scrapy_metrics["wall_clock_s"],
            "requests": scrapy_metrics["requests"],
            "selected": scrapy_counts["selected_products"],
            "processed": scrapy_counts["processed_products"],
            "valid": scrapy_counts["valid_products"],
            "excluded": scrapy_counts["excluded_products"],
            "failed": scrapy_counts["failed_products"],
            "pending": scrapy_counts["pending_products"],
            "partial_description": scrapy_counts["partial_description_products"],
            "success_rate": rate(
                scrapy_counts["valid_products"],
                scrapy_counts["selected_products"],
            ),
            "requests_per_valid": round(
                scrapy_metrics["requests"]
                / max(1, scrapy_counts["valid_products"]),
                2,
            ),
            "outcome": scrapy_tr["outcome"],
            "stop_reason": scrapy_tr["stop_reason"],
            "quality_exceptions": scrapy_tr.get("quality_exceptions") or [],
            "failure_samples": scrapy_failures,
            "selected_urls": scrapy_selected,
            "outputs": {
                "task_result": "scrapy/task-result.json",
                "metrics": "scrapy/results/scrapy-skatepro.json",
            },
        },
    }

    same_url_set = arms["crawlee"]["selected_urls"] == arms["scrapy"]["selected_urls"]
    same_budget = (
        crawlee_meta.get("max_products") == scrapy_meta.get("max_products") == 10
        and crawlee_meta.get("time_budget_seconds")
        == scrapy_meta.get("max_seconds")
        == 300
    )
    no_failures = (
        arms["crawlee"]["failed"] == arms["scrapy"]["failed"] == 0
        and not arms["crawlee"]["failure_samples"]
        and not arms["scrapy"]["failure_samples"]
    )

    comparison = {
        "case": CASE.name,
        "site": "https://www.skatepro.es",
        "sample": {
            "file": "shared-urls.json",
            "selection": shared.get("selection"),
            "count": len(shared_urls),
            "urls": shared_urls,
        },
        "budget": {"max_products": 10, "max_seconds": 300},
        "network": "direct; same machine; runs were sequential in the recorded windows",
        "kind": "runtime comparison on a fixed URL sample, not an AI build-time comparison",
        "arms": arms,
        "checks": {
            "same_url_set": same_url_set,
            "same_budget": same_budget,
            "both_valid_10": arms["crawlee"]["valid"]
            == arms["scrapy"]["valid"]
            == 10,
            "no_product_failures": no_failures,
        },
        "notes": [
            "Crawlee uses Playwright/Chromium; Scrapy uses its static HTTP downloader. That engine difference is part of each existing plan, not an extra variable added for this run.",
            "Both arms fetched robots.txt and sitemap.xml. Crawlee's 11 counted requests are sitemap + 10 products (robots is recorded separately as robots_txt_fetch=1); Scrapy's 13 include robots + sitemap + one category probe + 10 products.",
            "The 10-product / 300-second budget is smaller than the earlier 30-product / 600-second build rounds, so these timings are not merged with the build-session table.",
            "Scrapy attempt-001 is archived under scrapy-attempt-001/. Attempt 002 fixes task counts to use the selected sample (10) rather than the sitemap denominator (6660); the raw crawl is otherwise the same.",
            "One run per arm; differences are descriptive and not statistically significant.",
        ],
    }

    (CASE / "comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    def exception_lines(arm: dict[str, Any]) -> list[str]:
        rows = arm["quality_exceptions"]
        if not rows:
            return ["- none"]
        lines: list[str] = []
        for row in rows:
            detail = ""
            if row.get("partial_reason"):
                detail += f" ({row['partial_reason']})"
            missing = row.get("missing_reasons") or {}
            if missing:
                detail += "; missing: " + ", ".join(
                    f"{key}={value}" for key, value in sorted(missing.items())
                )
            lines.append(
                f"- `{row.get('source_url')}`: {row.get('description_status')}{detail}"
            )
        return lines

    lines = [
        "# 同条件运行对照（2026-11-22）",
        "",
        "## 固定条件",
        "",
        f"- 站点：`https://www.skatepro.es`",
        f"- 样本：10 个均匀间隔的商品 URL，来自 sitemap 的 6660 个商品 URL；文件 `shared-urls.json`",
        "- 预算：10 个商品页 / 300 秒，先到为准",
        "- 网络：同机直连；两臂顺序执行，窗口见下表",
        "- 性质：固定样本的运行时对照，不是 AI 构建时间对照；Crawlee 用浏览器，Scrapy 用静态 HTTP",
        "",
        "## 结果",
        "",
        "| 指标 | Crawlee | Scrapy |",
        "| --- | --- | --- |",
        "| 框架版本 | 1.11.2 | 2.20.0 |",
        "| 引擎 | Playwright Chromium | 静态 HTTP downloader |",
        "| 运行窗口 | "
        f"{arms['crawlee']['started_at']} → {arms['crawlee']['finished_at']} | "
        f"{arms['scrapy']['started_at']} → {arms['scrapy']['finished_at']} |",
        f"| 墙钟 | {arms['crawlee']['wall_seconds']}s | {arms['scrapy']['wall_seconds']}s |",
        f"| 请求数 | {arms['crawlee']['requests']} | {arms['scrapy']['requests']} |",
        f"| 选中商品 | {arms['crawlee']['selected']} | {arms['scrapy']['selected']} |",
        f"| 已处理 | {arms['crawlee']['processed']} | {arms['scrapy']['processed']} |",
        f"| 有效 | {arms['crawlee']['valid']} | {arms['scrapy']['valid']} |",
        f"| 失败 / 排除 / 待处理 | {arms['crawlee']['failed']} / {arms['crawlee']['excluded']} / {arms['crawlee']['pending']} | {arms['scrapy']['failed']} / {arms['scrapy']['excluded']} / {arms['scrapy']['pending']} |",
        f"| 成功率 | {arms['crawlee']['success_rate']:.0%} | {arms['scrapy']['success_rate']:.0%} |",
        f"| 请求数／有效（含发现） | {arms['crawlee']['requests_per_valid']} | {arms['scrapy']['requests_per_valid']} |",
        f"| 部分描述 | {arms['crawlee']['partial_description']} | {arms['scrapy']['partial_description']} |",
        f"| 结果 / 停止 | {arms['crawlee']['outcome']} / {arms['crawlee']['stop_reason']} | {arms['scrapy']['outcome']} / {arms['scrapy']['stop_reason']} |",
        "",
        "## 样本校验",
        "",
        f"- 两臂选中 URL 集合相同：**{same_url_set}**",
        f"- 预算一致：**{same_budget}**",
        f"- 两臂各 10／10 有效：**{comparison['checks']['both_valid_10']}**",
        f"- 无商品失败：**{no_failures}**",
        "",
        "## 质量异常与失败样本",
        "",
        "Crawlee：",
        "",
        *exception_lines(arms["crawlee"]),
        "",
        "Scrapy：",
        "",
        *exception_lines(arms["scrapy"]),
        "",
        "失败样本：无；两臂 failed 均为 0，诊断文件中也未出现商品级失败。",
        "",
        "## 读法",
        "",
        "- 请求数口径：Crawlee 的 11 是 sitemap + 10 个商品，robots 另记为 `robots_txt_fetch=1`；Scrapy 的 13 含 robots + sitemap + 分类探针 + 10 个商品。两者都访问了 robots；Scrapy 另多一个分类探针。",
        "- 墙钟差约 19 秒，主要来自浏览器启动、渲染和 Scrapy 多出的分类探针；单次运行不能当作框架性能排名。",
        "- Scrapy 的 1 个部分描述是 `specifications_section_missing_or_empty`；Crawlee 的 2 个质量异常是 `NO_MEANINGFUL_OPTIONS`，不是空价格或数量错误。",
        "- 这是 10 个商品的有界样本，不代表全站覆盖；真实虚拟列表仍未由本实验覆盖。",
    ]
    (CASE / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    timing = {
        "case": CASE.name,
        "source": "task-result/run-meta; returncode inferred from completed outputs",
        "arms": {
            name: {
                "started_at": arm["started_at"],
                "finished_at": arm["finished_at"],
                "wall_seconds": arm["wall_seconds"],
                "returncode": 0,
            }
            for name, arm in arms.items()
        },
    }
    (CASE / "timing.json").write_text(
        json.dumps(timing, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(comparison["checks"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
