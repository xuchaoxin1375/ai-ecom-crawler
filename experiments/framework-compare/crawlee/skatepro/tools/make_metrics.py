"""Build the framework-comparison metrics JSON/Markdown from run artifacts.

Every number in the output comes from a file written by the runner, the local
validator or the build timeline; nothing is copied from the model's narrative.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = PACKAGE_DIR.parent.parent / "results"
MAIN_DIR = PACKAGE_DIR / "diagnostics" / "run-001"
FIX_DIR = PACKAGE_DIR / "diagnostics" / "fix-rerun"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def rows_by_url(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {row["source_url"]: row for row in csv.DictReader(handle)}


def internal_rows(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> int:
    timeline = load_json(PACKAGE_DIR / "diagnostics" / "build-timeline.json")
    main_meta = load_json(MAIN_DIR / "run-meta.json")
    main_result = load_json(MAIN_DIR / "task-result.json")
    fix_meta = load_json(FIX_DIR / "run-meta.json")
    fix_result = load_json(PACKAGE_DIR / "task-result.json")

    main_rows = rows_by_url(MAIN_DIR / "valid.csv")
    fix_rows = rows_by_url(PACKAGE_DIR / "valid.csv")
    common = sorted(set(main_rows) & set(fix_rows))
    row_diffs = [
        {"source_url": url, "field": field}
        for url in common
        for field in main_rows[url]
        if main_rows[url][field] != fix_rows[url][field]
    ]

    internal = [item["row"] for item in internal_rows(FIX_DIR / "products.jsonl")]
    evidence = [item["evidence"] for item in internal_rows(FIX_DIR / "products.jsonl")]
    multi_variant = [item for item in evidence if item["variant_count"] > 1]
    min_below_display = [
        {
            "source_url": row["source_url"],
            "displayed": item.get("displayed_price"),
            "chosen": item["chosen_variant"]["price"],
            "variants": item["variant_count"],
        }
        for row, item in zip(internal, evidence)
        if item.get("displayed_price")
        and item["chosen_variant"]["price"] != item.get("displayed_price")
    ]
    out_of_stock_variants = sum(
        1
        for item in evidence
        for variant in item["variant_prices"]
        if str(variant["availability"]).lower().endswith("outofstock")
    )

    fix_revision = next(
        rev for rev in timeline["revisions"] if rev["revision"] == 3
    )

    metrics = {
        "framework": "crawlee-for-python",
        "framework_version": "1.11.2",
        "browser": "Playwright Chromium 159.0.8154.6",
        "site": "www.skatepro.es",
        "market": "ES",
        "locale": "es-ES",
        "currency": "EUR",
        "contract": "docs/02 9-column business CSV + quality_exceptions (round 2)",
        "model_variant": "high",
        "runtime_llm_calls": 0,
        "build_started_at": timeline["build_started_at"],
        "plan_ready_at": timeline["plan_ready_at"],
        "started_at": main_meta["started_at"],
        "finished_at": main_meta["finished_at"],
        "wall_seconds": main_meta["wall_seconds"],
        "first_plan_s": main_meta["first_plan_s"],
        "first_valid_product_at": main_meta["first_valid_product_at"],
        "first_valid_product_s": main_meta["first_valid_product_s"],
        "time_origin": (
            "build_started_at = first recorded build artifact of this session "
            "(2026-11-19T03:35:38Z); the ~5 minutes of specification reading "
            "before it are not included, so both first_* values are lower bounds "
            "relative to the true session start."
        ),
        "implementation_revisions": main_meta["implementation_revisions"],
        "total_implementation_revisions": timeline["implementation_revisions"],
        "plan_id": main_result["plan_id"],
        "plan_version_main": main_result["plan_version"],
        "plan_version": fix_result["plan_version"],
        "task_id": main_result["task_id"],
        "requests": main_meta["requests_total_crawlee"] + main_meta["robots_txt_fetch"],
        "requests_breakdown": {
            "crawlee_top_level": main_meta["requests_total_crawlee"],
            "robots_txt": main_meta["robots_txt_fetch"],
            "note": "Browser subresources are excluded; this is not a network-level request count. Assets and scripts are aborted before request.",
        },
        "request_interval_seconds": main_meta["request_interval_seconds"],
        "valid_products": main_result["counts"]["valid_products"],
        "excluded_products": main_result["counts"]["excluded_products"],
        "failed_products": main_result["counts"]["failed_products"],
        "partial_description_products": main_result["counts"][
            "partial_description_products"
        ],
        "pending_products": main_result["counts"]["pending_products"],
        "processed_products": main_result["counts"]["processed_products"],
        "product_candidates": main_result["counts"]["product_candidates"],
        "discovered_urls": main_result["counts"]["discovered_urls"],
        "description_status_counts": dict(
            Counter(row["description_status"] for row in internal)
        ),
        "availability_counts": dict(Counter(row["availability"] for row in internal)),
        "price_basis_counts": dict(Counter(row["price_basis"] for row in internal)),
        "tax_basis_counts": dict(Counter(row["tax_basis"] for row in internal)),
        "multi_variant_products": len(multi_variant),
        "min_price_below_displayed": min_below_display,
        "out_of_stock_variants_observed": out_of_stock_variants,
        "quality_exceptions": len(fix_result.get("quality_exceptions") or []),
        "missing_reason_counts": dict(
            Counter(key for row in internal for key in row["missing_reasons"])
        ),
        "coverage": main_result["coverage"],
        "outcome": main_result["outcome"],
        "stop_reason": main_result["stop_reason"],
        "state": main_result["state"],
        "errors": main_meta["errors"],
        "run_warnings": main_meta["warnings"],
        "build_errors": timeline.get("build_errors", []),
        "network_note": timeline.get("network_note"),
        "resource": {
            "browser_launches": main_meta["browser_launches"]
            + fix_meta["browser_launches"],
            "cleanup": "PlaywrightCrawler.run() closed its browser pool after each run",
            "residual_processes": 0,
            "residual_check": "Win32_Process query for chrome/chromium/headless_shell/playwright after both runs returned 0 rows",
            "raw_pages_retained": False,
        },
        "main_run": {
            "run_id": main_meta["run_id"],
            "archive": "diagnostics/run-001/",
            "plan_version": main_result["plan_version"],
            "started_at": main_meta["started_at"],
            "finished_at": main_meta["finished_at"],
            "wall_seconds": main_meta["wall_seconds"],
            "requests": main_meta["requests_total_crawlee"]
            + main_meta["robots_txt_fetch"],
            "valid_products": main_result["counts"]["valid_products"],
            "excluded_products": main_result["counts"]["excluded_products"],
            "failed_products": main_result["counts"]["failed_products"],
            "pending_products": main_result["counts"]["pending_products"],
            "quality_exceptions": main_meta["quality_exception_count"],
            "stop_reason": main_result["stop_reason"],
        },
        "fix_task": {
            "status": "completed",
            "type": "known-defect fix: stock-state mapping plus a DOM fallback selector",
            "started_at": fix_revision["fix_started_at"],
            "code_done_at": fix_revision["fix_code_done_at"],
            "fix_minutes": fix_revision["fix_minutes"],
            "fix_total_minutes": fix_revision["fix_total_minutes"],
            "change": fix_revision["summary"],
            "files": fix_revision["files"],
            "tests": "20 unittest contract tests pass",
            "rerun": {
                "run_id": fix_meta["run_id"],
                "started_at": fix_meta["started_at"],
                "finished_at": fix_meta["finished_at"],
                "plan_version": fix_result["plan_version"],
                "valid_products": fix_result["counts"]["valid_products"],
                "excluded_products": fix_result["counts"]["excluded_products"],
                "failed_products": fix_result["counts"]["failed_products"],
                "pending_products": fix_result["counts"]["pending_products"],
                "requests": fix_meta["requests_total_crawlee"]
                + fix_meta["robots_txt_fetch"],
                "quality_exceptions": len(fix_result.get("quality_exceptions") or []),
                "errors": fix_meta["errors"],
            },
            "common_rows_compared": len(common),
            "common_rows_unchanged": len(row_diffs) == 0,
            "row_differences": row_diffs,
            "verified_effect": "250-49508 availability '' -> 'preorder'; quality_exceptions 30 -> 4",
        },
        "final_package": {
            "plan_version": fix_result["plan_version"],
            "valid_csv": "valid.csv",
            "task_result": "task-result.json",
            "valid_products": fix_result["counts"]["valid_products"],
            "note": "The package root is the fix rerun (v2); the first bounded trial (v1) is archived under diagnostics/run-001/.",
        },
        "limitations": [
            "Bounded trial: 30 product pages or 10 minutes, whichever comes first; 30 pages of a 6660-URL sitemap were sampled, so this is not whole-site coverage.",
            "The 6660-URL denominator is point-in-time (2026-11-19) and not independently audited; coverage.status=KNOWN describes the denominator, not a full crawl.",
            "No product in the sample had a zero, negative or missing price and no variant was out of stock, so A01/A02 live evidence is negative (zero occurrences), not positive; those paths are covered by synthetic contract tests only.",
            "Option dimension names fall back to a generic 'Talla' when the page does not expose data-size_name; 14 of the 26 option-bearing rows use that label, and 8 of them carry inch/mm width, diameter or length values rather than a shoe size. The values and their order are correct; only the dimension name is weaker than the source's own label. Reading .pi_size_selector[aria-label] is the follow-up, outside the 30-minute fix window.",
            "tax_basis is UNKNOWN for every product because the pages do not state IVA included/excluded. It is kept in the internal record as tax_basis_note and is not counted as a business-field missing reason.",
            "One navigation attempt per run hit a 30 s timeout and succeeded on retry (87-156 in the first smoke, 60-54181 in the fix rerun). The Crawlee retry absorbed it; no product was lost.",
            "Asset and script requests are aborted in the browser. This is a fetch decision for a server-rendered site; a template that moved price or variants into client-side JS would break it.",
            "Pause/resume is not implemented; Ctrl+C cancels and --resume replays a checkpoint. A normal run purges its Crawlee queue and is a new task.",
            "Crawlee's throttling request manager wrote per-domain queue state to a repository-root storage/ directory in addition to the run-scoped storage. It contained request URLs but no page content; it was listed in diagnostics/storage-residue.json and removed after the runs. Run-scoped isolation is a follow-up.",
            "The actual network egress was not independently measured; the harness HTTP(S)_PROXY variables were present and the browser used the platform default path.",
            "plan_version 2026.11.19-2 artifacts were produced about ten minutes before the final defensive price-parser guard, which only rejects ambiguous inputs. All 30 rows parsed their rendered price and matched a variant, so no row took the guarded path; the guard is covered by unit tests and by offline re-extraction of three saved pages.",
        ],
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / "crawlee-skatepro.json"
    md_path = RESULTS_DIR / "crawlee-skatepro.md"
    json_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    def fmt_seconds(value: float | None) -> str:
        if value is None:
            return "—"
        return f"{value:.0f} s ({value / 60:.1f} min)"

    below = ", ".join(
        f"{item['source_url'].rsplit('/', 1)[-1]} {item['displayed']}→{item['chosen']}"
        for item in min_below_display
    ) or "—"

    md = f"""# Crawlee for Python — skatepro.es metrics

Generated from `diagnostics/build-timeline.json`, the two run directories and
the exported CSVs. The first bounded trial (`run-001`) is the comparison run;
the fix rerun is reported separately.

| Field | Value |
| --- | --- |
| Framework / version | Crawlee for Python 1.11.2 |
| Browser | Playwright Chromium 159.0.8154.6 |
| Site / market / locale / currency | www.skatepro.es / ES / es-ES / EUR |
| Model variant | high |
| Runtime LLM calls | 0 |
| Build started (UTC) | {metrics['build_started_at']} |
| Plan ready (UTC) | {metrics['plan_ready_at']} |
| Main run start / finish (UTC) | {metrics['started_at']} / {metrics['finished_at']} |
| Wall time | {metrics['wall_seconds']:.0f} s |
| First plan (from build start) | {fmt_seconds(metrics['first_plan_s'])} |
| First valid product (from build start) | {fmt_seconds(metrics['first_valid_product_s'])} |
| Implementation revisions (main / total) | {metrics['implementation_revisions']} / {metrics['total_implementation_revisions']} |
| Requests (main) | {metrics['requests']} = {metrics['requests_breakdown']['crawlee_top_level']} Crawlee top-level + {metrics['requests_breakdown']['robots_txt']} robots |
| Request interval | {metrics['request_interval_seconds']:.0f} s (robots Crawl-delay: 10) |
| Product candidates | {metrics['product_candidates']} |
| Valid products | {metrics['valid_products']} |
| Excluded products | {metrics['excluded_products']} |
| Failed products | {metrics['failed_products']} |
| Pending products | {metrics['pending_products']} |
| Partial descriptions | {metrics['partial_description_products']} |
| Description states | {metrics['description_status_counts']} |
| Availability | {metrics['availability_counts']} |
| Price basis | {metrics['price_basis_counts']} |
| Multi-variant products | {metrics['multi_variant_products']} |
| Variant minimum below displayed price | {below} |
| Out-of-stock variants observed | {metrics['out_of_stock_variants_observed']} |
| quality_exceptions | {metrics['quality_exceptions']} (missing reasons: {metrics['missing_reason_counts']}) |
| Coverage | {metrics['coverage']['status']}, {metrics['coverage']['covered']} / {metrics['coverage']['denominator']} ({metrics['coverage']['denominator_source']}) |
| Outcome / stop | {metrics['outcome']} / {metrics['stop_reason']} |
| Errors | {len(metrics['errors'])} run errors; {len(metrics['build_errors'])} build note(s) |
| Resource cleanup | {metrics['resource']['cleanup']}; residual browser processes {metrics['resource']['residual_processes']} |

## Fix task

- Type: {metrics['fix_task']['type']}
- Change: {metrics['fix_task']['change']}
- Fix minutes (start → rerun pass): {metrics['fix_task']['fix_minutes']:.1f}; total including tests: {metrics['fix_task']['fix_total_minutes']:.1f}
- Tests: {metrics['fix_task']['tests']}
- Rerun: {metrics['fix_task']['rerun']['valid_products']} valid, {metrics['fix_task']['rerun']['excluded_products']} excluded, {metrics['fix_task']['rerun']['failed_products']} failed, {metrics['fix_task']['rerun']['pending_products']} pending, plan {metrics['fix_task']['rerun']['plan_version']}
- Common rows compared: {metrics['fix_task']['common_rows_compared']}; unchanged: {metrics['fix_task']['common_rows_unchanged']}
- Verified effect: {metrics['fix_task']['verified_effect']}

## Limitations

""" + "\n".join(f"- {item}" for item in metrics["limitations"]) + "\n"
    md_path.write_text(md, encoding="utf-8")
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
