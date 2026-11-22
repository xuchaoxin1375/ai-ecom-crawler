#!/usr/bin/env python3
"""Summarize the 30-product/600-second same-window comparison."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
CASE = Path(__file__).resolve().parent
CRAWLEE = CASE / "crawlee"
SCRAPY = CASE / "scrapy"
CRAWLEE_RUN = "same-window-30-001"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl_prefix(path: Path, limit: int = 5) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
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


def load_jsonl_all(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_csv_all(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def main() -> int:
    shared = load_json(CASE / "shared-urls.json")
    shared_urls = list(shared["urls"])
    expected = len(shared_urls)
    time_limit = int(shared["budget"]["max_seconds"])

    crawlee_tr = load_json(CRAWLEE / "task-result.json")
    crawlee_meta = load_json(CRAWLEE / "diagnostics" / CRAWLEE_RUN / "run-meta.json")
    crawlee_selected = load_json(
        CRAWLEE / "diagnostics" / CRAWLEE_RUN / "selected_urls.json"
    )
    crawlee_counts = crawlee_tr["counts"]
    crawlee_failures = load_jsonl_prefix(
        CRAWLEE / "diagnostics" / CRAWLEE_RUN / "failed.jsonl"
    )
    crawlee_excluded = load_jsonl_all(
        CRAWLEE / "diagnostics" / CRAWLEE_RUN / "excluded.jsonl"
    )

    scrapy_tr = load_json(SCRAPY / "task-result.json")
    scrapy_metrics = load_json(SCRAPY / "results" / "scrapy-skatepro.json")
    scrapy_meta = load_json(SCRAPY / "diagnostics" / "run-meta.json")
    scrapy_counts = scrapy_tr["counts"]
    scrapy_selected = [entry["url"] for entry in scrapy_meta["selected"]]
    scrapy_failures = load_csv_prefix(SCRAPY / "diagnostics" / "failed_products.csv")
    scrapy_excluded = load_csv_all(SCRAPY / "diagnostics" / "excluded_products.csv")

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
            "excluded_samples": crawlee_excluded,
            "selected_urls": crawlee_selected["selected_urls"],
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
            "excluded_samples": scrapy_excluded,
            "selected_urls": scrapy_selected,
        },
    }

    same_url_set = arms["crawlee"]["selected_urls"] == arms["scrapy"]["selected_urls"]
    same_budget = (
        crawlee_meta.get("max_products") == scrapy_meta.get("max_products") == expected
        and crawlee_meta.get("time_budget_seconds")
        == scrapy_meta.get("max_seconds")
        == time_limit
    )
    no_failures = (
        arms["crawlee"]["failed"] == arms["scrapy"]["failed"] == 0
        and not arms["crawlee"]["failure_samples"]
        and not arms["scrapy"]["failure_samples"]
    )
    same_valid_count = arms["crawlee"]["valid"] == arms["scrapy"]["valid"]
    same_excluded_set = {
        row.get("source_url") for row in crawlee_excluded
    } == {
        row.get("source_url") for row in scrapy_excluded
    }

    comparison = {
        "case": CASE.name,
        "site": "https://www.skatepro.es",
        "sample": {
            "file": "shared-urls.json",
            "selection": shared.get("selection"),
            "count": expected,
            "urls": shared_urls,
        },
        "budget": {"max_products": expected, "max_seconds": time_limit},
        "network": "direct; same machine; runs were sequential in the recorded windows",
        "kind": "runtime comparison on a fixed URL sample, not an AI build-time comparison",
        "arms": arms,
        "checks": {
            "same_url_set": same_url_set,
            "same_budget": same_budget,
            "same_valid_count": same_valid_count,
            "same_excluded_url_set": same_excluded_set,
            "no_product_failures": no_failures,
        },
        "excluded_sample_note": (
            "Both arms excluded the same product (250-21059.htm), but for "
            "different reasons: Crawlee NO_PRICE, Scrapy currency_unproven. "
            "The page shows a visible 17,95 EUR price, so this is a cross-arm "
            "disagreement worth follow-up, not two independent successes."
        ),
        "notes": [
            "Crawlee uses Playwright/Chromium; Scrapy uses its static HTTP downloader. That engine difference is part of each existing plan.",
            "Both arms fetched robots.txt and sitemap.xml. Scrapy also fetched one category probe; Crawlee did not.",
            "This is the full 30-product / 600-second runtime budget, but still one site and one run per arm.",
            "Scrapy counts use the selected sample (30), not the sitemap denominator (6660).",
            "The build-session component is not measured here; this is a runtime comparison of existing plans.",
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
        "# 同条件运行对照（30 商品／600 秒，2026-11-22）",
        "",
        "## 固定条件",
        "",
        "- 站点：`https://www.skatepro.es`",
        f"- 样本：{expected} 个均匀间隔的商品 URL，来自 sitemap 的 6660 个商品 URL；文件 `shared-urls.json`",
        f"- 预算：{expected} 个商品／{time_limit} 秒，先到为准",
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
        f"- 两臂有效数相同：**{same_valid_count}**（各 {arms['crawlee']['valid']}／{expected}）",
        f"- 两臂排除同一商品：**{same_excluded_set}**",
        f"- 无技术失败：**{no_failures}**",
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
        "排除样本：",
        "",
        "- `https://www.skatepro.es/250-21059.htm`",
        "- Crawlee：`NO_PRICE`，1 个变体无有限正价。",
        "- Scrapy：`currency_unproven`，展示报价未绑定 ISO 4217 币种。",
        "- 页面可见 `17,95 €`；两臂都排除同一商品但原因不同，属于需要后续判定的跨臂分歧，不应当作两次成功。",
        "",
        "失败样本：无技术失败；两臂 failed 均为 0，诊断文件中未出现商品级失败。",
        "",
        "## 构建耗时",
        "",
        "- 本实验只运行现有方案，**未测 AI 构建耗时**。",
        "- 历史构建值（不同时间窗，不能与本次运行时表直接比较）：Crawlee `skatepro` 首个方案 841.0s、首个有效 1104.0s；Scrapy 1229.0s、1513.0s。来源见 `results/crawlee-skatepro.json` 与 `results/scrapy-skatepro.json`。",
        "- 严格同窗的构建会话对照仍未做；本次只补了 30 商品／600 秒的运行时对照。",
        "",
        "## 读法",
        "",
        "- 请求数口径：Crawlee 的请求数是 sitemap + 商品，robots 另记为 `robots_txt_fetch=1`；Scrapy 的请求数含 robots + sitemap + 分类探针 + 商品。",
        "- 这是 30 商品／600 秒的完整运行预算，但仍是单站、单次运行；墙钟差不能当作框架性能排名。",
        "- 两臂有效数相同（各 29／30），并排除同一商品但给出不同原因；这比单纯的成功率更能说明字段规则的差异。",
        "- 这是运行时对照，不测 AI 构建耗时；严格同窗的构建会话对照仍未做。",
        "- 有界样本不代表全站覆盖；真实虚拟列表仍未由本实验覆盖。",
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
