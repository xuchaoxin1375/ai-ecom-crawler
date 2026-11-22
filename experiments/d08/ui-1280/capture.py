"""Capture the D08 list/create/detail pages at the 1280 desktop spec.

The task ledger is synthetic and local; no site is fetched and no worker runs.
Run with the app environment:

    app/.venv/Scripts/python.exe experiments/d08/ui-1280/capture.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from ecom_crawler.runtime.models import Task, WorkItem
from ecom_crawler.runtime.store import TaskStore

ROOT = Path(__file__).resolve().parent
PORT = 8773
RULES_DIR = Path("experiments/d03/familidoo").resolve()


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def seed(db: Path, out_root: Path) -> list[str]:
    store = TaskStore(db)
    plan = {"plan_id": "familidoo-fr-d03", "plan_version": "2026.11.21-1"}

    def task(
        task_id: str,
        state: str,
        *,
        outcome: str | None = None,
        stop_reason: str | None = None,
        archived: bool = False,
    ) -> Task:
        value = Task(
            task_id=task_id,
            task_type="product",
            state=state,
            outcome=outcome,
            stop_reason=stop_reason,
            site_key="familidoo.fr",
            domain_key="familidoo.fr",
            market="FR",
            rule_path=str(RULES_DIR / "familidoo-d03.yaml"),
            input={"rule_path": str(RULES_DIR / "familidoo-d03.yaml")},
            limits={"max_products": 6, "max_urls": 20, "max_seconds": 180},
            counters={},
            created_at=now(),
            updated_at=now(),
            started_at=now(),
            finished_at=now() if state in {"FINISHED", "CANCELLED"} else None,
            **plan,
        )
        store.create_task(value)
        if archived:
            store.request_archive(task_id)
        return value

    task("ui-draft", "DRAFT")
    task("ui-queued", "QUEUED")
    task("ui-paused", "PAUSED")
    task(
        "ui-finished",
        "FINISHED",
        outcome="COMPLETED",
        stop_reason="NATURAL_END",
    )
    task(
        "ui-cancelled",
        "CANCELLED",
        outcome="CANCELLED",
        stop_reason="USER_CANCELLED",
    )
    task(
        "ui-archived",
        "FINISHED",
        outcome="COMPLETED",
        stop_reason="NATURAL_END",
        archived=True,
    )

    product_rows = [
        ("ui-finished", "p1", "DONE", "Product one"),
        ("ui-finished", "p2", "DONE", "Product two"),
        ("ui-paused", "p3", "DONE", "Paused product"),
        ("ui-cancelled", "p4", "FAILED", "Cancelled product"),
        ("ui-archived", "p5", "DONE", "Archived product"),
    ]
    for task_id, item_id, state, title in product_rows:
        if state == "DONE":
            product = {
                "name": title,
                "price_amount": 19.99,
                "price_currency": "EUR",
                "description_status": "PARTIAL" if item_id == "p1" else "COMPLETE",
                "partial_reason": "specifications omitted" if item_id == "p1" else None,
                "missing_reasons": {"brand": "NOT_PROVIDED"} if item_id == "p1" else {},
                "field_sources": {
                    "name": "h1_itemprop",
                    "price.amount": "meta_price_pair",
                    "price.currency": "meta_price_pair",
                    "description_html": "description_container",
                    "source_url": "canonical",
                },
            }
            result = {
                "name": title,
                "status": "valid",
                "price_amount": 19.99,
                "price_currency": "EUR",
                "product": product,
            }
        else:
            result = {
                "status": "failed",
                "reason": "validation_error",
                "failure_class": "permanent",
            }
        store.add_item(
            WorkItem(
                task_id=task_id,
                item_id=item_id,
                item_type="product",
                url=f"https://www.familidoo.fr/fr/example-{item_id}.html",
                normalized_url=f"https://www.familidoo.fr/fr/example-{item_id}.html",
                stage="fetch",
                state=state,
                failure_class="permanent" if state == "FAILED" else None,
                result=result,
            )
        )
    store.add_item(
        WorkItem(
            task_id="ui-finished",
            item_id="n1",
            item_type="navigation",
            url="https://www.familidoo.fr/fr/",
            normalized_url="https://www.familidoo.fr/fr/",
            stage="discover",
            state="DONE",
        )
    )

    results = {
        "ui-finished": {
            "counts": {
                "navigation_urls": 1,
                "discovered_urls": 3,
                "pending_navigation_entries": 0,
                "product_candidates": 2,
                "pending_products": 0,
                "in_flight_products": 0,
                "processed_products": 2,
                "valid_products": 2,
                "excluded_products": 0,
                "failed_products": 0,
                "partial_description_products": 1,
            },
            "coverage": {"status": "KNOWN", "denominator": 2, "covered": 2},
            "stop_reason": "NATURAL_END",
            "quality_exceptions": [
                {
                    "source_url": "https://www.familidoo.fr/fr/example-p1.html",
                    "description_status": "partial",
                    "partial_reason": "specifications omitted",
                    "missing_reasons": {"brand": "NOT_PROVIDED"},
                }
            ],
        },
        "ui-paused": {
            "counts": {
                "navigation_urls": 1,
                "discovered_urls": 1,
                "pending_navigation_entries": 1,
                "product_candidates": 3,
                "pending_products": 2,
                "in_flight_products": 0,
                "processed_products": 1,
                "valid_products": 1,
                "excluded_products": 0,
                "failed_products": 0,
                "partial_description_products": 0,
            },
            "coverage": {"status": "UNKNOWN"},
            "stop_reason": None,
            "quality_exceptions": [],
        },
        "ui-cancelled": {
            "counts": {
                "navigation_urls": 1,
                "discovered_urls": 1,
                "pending_navigation_entries": 0,
                "product_candidates": 2,
                "pending_products": 1,
                "in_flight_products": 0,
                "processed_products": 1,
                "valid_products": 0,
                "excluded_products": 0,
                "failed_products": 1,
                "partial_description_products": 0,
            },
            "coverage": {"status": "UNKNOWN"},
            "stop_reason": "USER_CANCELLED",
            "quality_exceptions": [],
        },
        "ui-archived": {
            "counts": {
                "navigation_urls": 1,
                "discovered_urls": 1,
                "pending_navigation_entries": 0,
                "product_candidates": 1,
                "pending_products": 0,
                "in_flight_products": 0,
                "processed_products": 1,
                "valid_products": 1,
                "excluded_products": 0,
                "failed_products": 0,
                "partial_description_products": 0,
            },
            "coverage": {"status": "KNOWN", "denominator": 1, "covered": 1},
            "stop_reason": "NATURAL_END",
            "quality_exceptions": [],
        },
    }
    for task_id, payload in results.items():
        target = out_root / task_id
        target.mkdir(parents=True, exist_ok=True)
        (target / "task-result.json").write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "task_type": "product",
                    "plan_id": plan["plan_id"],
                    "plan_version": plan["plan_version"],
                    "state": "FINISHED",
                    **payload,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return sorted(result for result in results)


def wait_ready(url: str, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:  # noqa: BLE001 - readiness loop
            time.sleep(0.2)
    raise RuntimeError("serve did not become ready")


def main() -> int:
    temporary = tempfile.TemporaryDirectory()
    root = Path(temporary.name)
    db = root / "tasks.db"
    out_root = root / "tasks"
    out_root.mkdir()
    seed(db, out_root)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ecom_crawler",
            "serve",
            "--db",
            str(db),
            "--out-root",
            str(out_root),
            "--rules-dir",
            str(RULES_DIR),
            "--no-worker",
            "--port",
            str(PORT),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        cwd=Path.cwd(),
    )
    try:
        wait_ready(f"http://127.0.0.1:{PORT}")
        from patchright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(f"http://127.0.0.1:{PORT}/#/tasks", wait_until="networkidle")
            page.wait_for_selector("#task-rows tr")
            page.screenshot(path=str(ROOT / "list-1280.png"), full_page=False)
            list_overflow = page.evaluate(
                "document.documentElement.scrollWidth > window.innerWidth"
            )
            rows = page.locator("#task-rows tr").count()
            list_text = page.locator("main").inner_text()

            page.click("details.create-panel > summary")
            page.screenshot(path=str(ROOT / "create-1280.png"), full_page=False)
            create_overflow = page.evaluate(
                "document.documentElement.scrollWidth > window.innerWidth"
            )
            create_text = page.locator("main").inner_text()

            page.goto(
                f"http://127.0.0.1:{PORT}/#/tasks/ui-finished",
                wait_until="networkidle",
            )
            page.wait_for_selector("#detail-counts")
            page.screenshot(path=str(ROOT / "detail-1280.png"), full_page=False)
            detail_overflow = page.evaluate(
                "document.documentElement.scrollWidth > window.innerWidth"
            )
            detail_text = page.locator("main").inner_text()
            page.locator("#item-rows tr").first.wait_for()
            sources = page.locator(".sources summary").first
            if sources.count():
                sources.click()
            page.locator("#item-rows").scroll_into_view_if_needed()
            page.screenshot(
                path=str(ROOT / "detail-items-1280.png"),
                full_page=False,
            )
            items_text = page.locator("#detail-view").inner_text()
            sources_open = page.locator(".sources[open]").count() > 0

            browser.close()
        evidence = {
            "viewport": "1280x900",
            "list_rows": rows,
            "list_overflow": list_overflow,
            "create_overflow": create_overflow,
            "detail_overflow": detail_overflow,
            "list_contains": {
                "coverage": "覆盖 已知" in list_text,
                "stop": "停止：自然结束" in list_text,
                "quality_badge": "质量异常 1" in list_text,
            },
            "create_contains": {
                "market_from_rule": "由规则包确定" in create_text,
            },
            "detail_contains": {
                "controls": "归档" in detail_text or "取消任务" in detail_text,
                "export": "导出" in detail_text,
                "quality": "质量异常" in detail_text,
                "quality_formatted": "描述状态：部分" in detail_text
                and "缺失字段：品牌" in detail_text,
                "quality_no_raw_json": "source_url" not in detail_text,
                "counts": "有效商品" in detail_text,
                "secondary_counts": "已处理商品" in detail_text,
                "product_preview": "描述：部分" in detail_text,
                "field_sources": "字段来源" in detail_text,
            },
            "items_contains": {
                "name": "Product one" in items_text,
                "price": "19.99 EUR" in items_text,
                "description": "描述：部分" in items_text,
                "sources_expanded": sources_open,
            },
            "screenshots": [
                "list-1280.png",
                "create-1280.png",
                "detail-1280.png",
                "detail-items-1280.png",
            ],
        }
        (ROOT / "evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
