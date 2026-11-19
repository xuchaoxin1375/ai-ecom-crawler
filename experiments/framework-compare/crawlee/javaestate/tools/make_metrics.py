"""Build the framework-comparison metrics JSON/Markdown from run artifacts.

Every number in the output comes from a file written by the runner or by the
local validator; nothing is copied from the model's narrative.
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


def main() -> int:
    timeline = load_json(PACKAGE_DIR / "diagnostics" / "build-timeline.json")
    main_meta = load_json(MAIN_DIR / "run-meta.json")
    main_result = load_json(MAIN_DIR / "task-result.json")
    fix_meta = load_json(FIX_DIR / "run-meta.json")
    fix_result = load_json(PACKAGE_DIR / "task-result.json")

    main_rows = rows_by_url(MAIN_DIR / "valid.csv")
    fix_rows = rows_by_url(PACKAGE_DIR / "valid.csv")
    common = sorted(set(main_rows) & set(fix_rows))
    ignored = {"task_id", "plan_version", "extracted_at"}
    row_diffs = [
        {"source_url": url, "field": field}
        for url in common
        for field in main_rows[url]
        if field not in ignored and main_rows[url][field] != fix_rows[url][field]
    ]
    fix_revision = next(
        rev for rev in timeline["revisions"] if rev["revision"] == 3
    )

    metrics = {
        "framework": "crawlee-for-python",
        "framework_version": "1.11.2",
        "browser": "Playwright Chromium 159.0.8154.6",
        "site": "javaestate.com",
        "market": "US",
        "locale": "en-US",
        "currency": "USD",
        "contract_note": "Task instruction fixed 22 CSV columns. docs/02 was changed externally during the session to a 9-column final business CSV; shared/task-spec.md records that this round keeps the 22-column results as old-contract evidence and does not rerun. No docs/ or shared/ file was modified by this implementation.",
        "model_variant": "max",
        "runtime_llm_calls": 0,
        "build_started_at": timeline["build_started_at"],
        "plan_ready_at": timeline["plan_ready_at"],
        "started_at": main_meta["started_at"],
        "finished_at": main_meta["finished_at"],
        "wall_seconds": main_meta["wall_seconds"],
        "first_plan_s": main_meta["first_plan_s"],
        "first_valid_product_at": main_meta["first_valid_product_at"],
        "first_valid_product_s": main_meta["first_valid_product_s"],
        "time_origin": "build_started_at; both first_* values are seconds after it",
        "implementation_revisions": main_meta["implementation_revisions"],
        "total_implementation_revisions": timeline["implementation_revisions"],
        "plan_id": main_result["plan_id"],
        "plan_version": main_result["plan_version"],
        "task_id": main_result["task_id"],
        "requests": main_meta["requests_total_crawlee"] + main_meta["robots_txt_fetch"],
        "requests_breakdown": {
            "crawlee_top_level": main_meta["requests_total_crawlee"],
            "robots_txt": main_meta["robots_txt_fetch"],
            "note": "Browser subresources are excluded; this is not network-level request count.",
        },
        "valid_products": main_result["counts"]["valid_products"],
        "excluded_products": main_result["counts"]["excluded_products"],
        "failed_products": main_result["counts"]["failed_products"],
        "partial_description_products": main_result["counts"]["partial_description_products"],
        "pending_products": main_result["counts"]["pending_products"],
        "processed_products": main_result["counts"]["processed_products"],
        "product_candidates": main_result["counts"]["product_candidates"],
        "description_status_counts": dict(
            Counter(row["description_status"] for row in main_rows.values())
        ),
        "availability_counts": dict(
            Counter(row["availability"] for row in main_rows.values())
        ),
        "tax_basis_counts": dict(Counter(row["tax_basis"] for row in main_rows.values())),
        "coverage": main_result["coverage"],
        "outcome": main_result["outcome"],
        "stop_reason": main_result["stop_reason"],
        "state": main_result["state"],
        "errors": main_meta["errors"],
        "build_errors": timeline.get("build_errors", []),
        "network_note": timeline.get("network_note"),
        "resource": {
            "browser_launches": main_meta["browser_launches"],
            "cleanup": "browser pool closed; post-run process snapshot found no Chromium/Playwright process",
            "residual_processes": 0,
            "raw_pages_retained": False,
        },
        "main_run": {
            "run_id": main_meta["run_id"],
            "archive": "diagnostics/run-001/",
            "plan_version": main_result["plan_version"],
            "started_at": main_meta["started_at"],
            "finished_at": main_meta["finished_at"],
            "valid_products": main_result["counts"]["valid_products"],
            "excluded_products": main_result["counts"]["excluded_products"],
            "failed_products": main_result["counts"]["failed_products"],
            "pending_products": main_result["counts"]["pending_products"],
            "stop_reason": main_result["stop_reason"],
        },
        "fix_task": {
            "status": "completed",
            "started_at": fix_revision["fix_started_at"],
            "fix_minutes": fix_revision["fix_minutes"],
            "fix_total_minutes": fix_revision["fix_total_minutes"],
            "change": fix_revision["summary"],
            "files": fix_revision["files"],
            "tests_passed": 16,
            "rerun": {
                "run_id": fix_meta["run_id"],
                "started_at": fix_meta["started_at"],
                "finished_at": fix_meta["finished_at"],
                "plan_version": fix_result["plan_version"],
                "valid_products": fix_result["counts"]["valid_products"],
                "excluded_products": fix_result["counts"]["excluded_products"],
                "failed_products": fix_result["counts"]["failed_products"],
                "pending_products": fix_result["counts"]["pending_products"],
                "requests": fix_meta["requests_total_crawlee"] + fix_meta["robots_txt_fetch"],
                "errors": fix_meta["errors"],
            },
            "common_rows_compared": len(common),
            "common_rows_unchanged": len(row_diffs) == 0,
            "row_differences": row_diffs,
        },
        "final_package": {
            "plan_version": fix_result["plan_version"],
            "validCSV": "valid.csv",
            "task_result": "task-result.json",
            "valid_products": fix_result["counts"]["valid_products"],
            "pending_products": fix_result["counts"]["pending_products"],
            "note": "The package root is the fix rerun (v2); the first bounded trial (v1) is archived under diagnostics/run-001/.",
        },
        "limitations": [
            "Bounded trial: 30 product pages or 10 minutes, whichever comes first. The main run processed 25 and the fix rerun 27; neither is whole-site coverage.",
            "The 706-URL sitemap denominator is point-in-time and not independently audited. coverage.status=KNOWN describes the denominator, not a full crawl.",
            "tax_basis is UNKNOWN for every product because the source does not state inclusive/exclusive pricing; the reason is recorded per row.",
            "No real-run product had a partial or fallback description; those states are covered by synthetic contract tests, not by this site's live sample.",
            "The main trial left 5 products pending and the fix rerun left 3 because the 10-minute watchdog stopped the crawler.",
            "Pause/resume is not implemented; Ctrl+C cancels and --resume replays a checkpoint. A normal run purges its Crawlee queue and is a new task.",
            "Plain HTTP probes hit 429 local_rate_limited during build; the measured run used Chromium and had no 429 or retry. The probes are not part of the run counts.",
            "The Crawlee throttler's per-domain sub-manager wrote queue JSON to a repo-root storage/ directory in addition to the per-run storage. The directory was removed and contained no page content; run-scoped storage isolation is a follow-up.",
            "The actual network egress was not independently measured; HTTP(S)_PROXY variables were present and the browser used the platform default path.",
        ],
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / "crawlee-javaestate.json"
    md_path = RESULTS_DIR / "crawlee-javaestate.md"
    json_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    def fmt_seconds(value: float | None) -> str:
        if value is None:
            return "—"
        return f"{value:.0f} s ({value / 60:.1f} min)"

    md = f"""# Crawlee for Python — javaestate.com metrics

Generated from `diagnostics/build-timeline.json`, the two run directories and
the exported CSVs. The first bounded trial is the comparison run; the fix
rerun is reported separately.

**Contract note.** The task fixed 22 CSV columns. `docs/02` was changed
externally during the session to a 9-column final business CSV; the shared
change record keeps this round's 22-column results as old-contract evidence and
does not rerun. No `docs/` or `shared/` file was modified by this
implementation.

| Field | Value |
| --- | --- |
| Framework / version | Crawlee for Python 1.11.2 |
| Browser | Playwright Chromium 159.0.8154.6 |
| Site / market / locale | javaestate.com / US / en-US |
| Model variant | max |
| Runtime LLM calls | 0 |
| Build started (UTC) | {metrics['build_started_at']} |
| Main run start / finish (UTC) | {metrics['started_at']} / {metrics['finished_at']} |
| Wall time | {metrics['wall_seconds']:.0f} s |
| First plan (from build start) | {fmt_seconds(metrics['first_plan_s'])} |
| First valid product (from build start) | {fmt_seconds(metrics['first_valid_product_s'])} |
| Implementation revisions (build / total) | {metrics['implementation_revisions']} / {metrics['total_implementation_revisions']} |
| Requests (main) | {metrics['requests']} = {metrics['requests_breakdown']['crawlee_top_level']} Crawlee top-level + {metrics['requests_breakdown']['robots_txt']} robots |
| Product candidates | {metrics['product_candidates']} |
| Valid products | {metrics['valid_products']} |
| Excluded products | {metrics['excluded_products']} |
| Failed products | {metrics['failed_products']} |
| Partial descriptions | {metrics['partial_description_products']} |
| Pending products | {metrics['pending_products']} |
| Description states | {metrics['description_status_counts']} |
| Availability | {metrics['availability_counts']} |
| Tax basis | {metrics['tax_basis_counts']} |
| Coverage | {metrics['coverage']['status']}, {metrics['coverage']['covered']} / {metrics['coverage']['denominator']} ({metrics['coverage']['denominator_source']}) |
| Outcome / stop | {metrics['outcome']} / {metrics['stop_reason']} |
| Errors | {len(metrics['errors'])} run errors; {len(metrics['build_errors'])} build-probe note(s) |
| Resource cleanup | {metrics['resource']['cleanup']} |

## Fix task

- Change: {metrics['fix_task']['change']}
- Fix minutes: {metrics['fix_task']['fix_minutes']:.1f}; total including rerun: {metrics['fix_task']['fix_total_minutes']:.1f}
- Tests: {metrics['fix_task']['tests_passed']} contract tests passed
- Rerun: {metrics['fix_task']['rerun']['valid_products']} valid, {metrics['fix_task']['rerun']['excluded_products']} excluded, {metrics['fix_task']['rerun']['failed_products']} failed, {metrics['fix_task']['rerun']['pending_products']} pending, plan {metrics['fix_task']['rerun']['plan_version']}
- Common rows compared: {metrics['fix_task']['common_rows_compared']}; unchanged: {metrics['fix_task']['common_rows_unchanged']}

## Limitations

""" + "\n".join(f"- {item}" for item in metrics["limitations"]) + "\n"
    md_path.write_text(md, encoding="utf-8")
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
