"""Check the real D08 preview through the browser UI.

Requires the real preview server (``run_real_preview.py``) on port 8775. It
exercises the real finished task and one additional real task for
create/start/pause/resume/cancel, archive/restore, export and the
missing-task error message. Screenshots are saved next to this script.
"""

from __future__ import annotations

import json
import re
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from patchright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8775"
ROOT = Path(__file__).resolve().parent


def api(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    tasks = api("/api/tasks?include_archived=true")["items"]
    finished = next(
        task
        for task in tasks
        if task["state"] == "FINISHED"
        and task["counts"].get("valid_products", 0) >= 6
    )
    finished_id = finished["task_id"]
    checks: dict[str, object] = {
        "finished_task": finished_id,
        "finished_counts": finished["counts"],
        "finished_quality_exceptions": len(finished.get("quality_exceptions") or []),
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{BASE}/#/tasks", wait_until="networkidle")
        page.wait_for_selector("#task-rows tr")
        list_text = page.locator("main").inner_text()
        checks["purpose_banner"] = "内部技术控制台" in list_text and "非业务工作台" in list_text
        checks["real_task_in_list"] = finished_id in list_text
        checks["real_counts_in_list"] = "有效商品 6" in list_text
        page.screenshot(path=str(ROOT / "real-list-1280.png"))

        page.goto(f"{BASE}/#/tasks/{finished_id}", wait_until="networkidle")
        page.wait_for_selector("#detail-counts")
        page.wait_for_selector("#item-rows tr")
        detail_text = page.locator("#detail-view").inner_text()
        checks["real_detail_counts"] = "有效商品" in detail_text and "6" in detail_text
        checks["real_quality"] = "质量异常" in detail_text
        checks["real_product"] = "Poussette" in detail_text
        checks["field_sources"] = "字段来源" in detail_text
        page.locator("#item-rows").scroll_into_view_if_needed()
        page.screenshot(path=str(ROOT / "real-items-1280.png"))

        page.locator('[data-action="archive"]').click()
        expect(page.locator('[data-action="restore"]')).to_be_visible(timeout=10000)
        page.locator('[data-action="restore"]').click()
        expect(page.locator('[data-action="archive"]')).to_be_visible(timeout=10000)
        checks["archive_restore"] = True

        with page.expect_download() as download_info:
            page.locator("#export-link").click()
        download = download_info.value
        export_path = Path(tempfile.mkdtemp(prefix="d08-export-")) / download.suggested_filename
        download.save_as(str(export_path))
        with zipfile.ZipFile(export_path) as archive:
            names = archive.namelist()
        checks["export"] = "products.csv" in names and "task-result.json" in names

        page.goto(f"{BASE}/#/tasks", wait_until="networkidle")
        page.click("details.create-panel > summary")
        page.select_option("#rule-select", index=0)
        page.fill("#create-max-products", "30")
        page.fill("#create-max-urls", "30")
        page.fill("#create-max-seconds", "180")
        page.click("#create-submit")
        page.wait_for_url(re.compile(r"#/tasks/web-"), timeout=30000)
        new_task_id = page.url.rsplit("/", 1)[-1]
        checks["created_task"] = new_task_id
        expect(page.locator('[data-action="pause"]')).to_be_visible(timeout=30000)
        page.locator('[data-action="pause"]').click()
        expect(page.locator("#detail-meta")).to_contain_text("已暂停", timeout=30000)
        checks["pause"] = True
        expect(page.locator('[data-action="resume"]')).to_be_visible(timeout=30000)
        page.locator('[data-action="resume"]').click()
        expect(page.locator("#detail-meta")).to_contain_text("运行中", timeout=30000)
        checks["resume"] = True
        page.on("dialog", lambda dialog: dialog.accept())
        page.locator('[data-action="cancel"]').click()
        expect(page.locator("#detail-meta")).to_contain_text("已取消", timeout=30000)
        checks["cancel"] = True
        page.screenshot(path=str(ROOT / "real-controls-1280.png"))

        page.goto(f"{BASE}/#/tasks/does-not-exist", wait_until="networkidle")
        expect(page.locator("#detail-status")).to_contain_text("读取失败", timeout=10000)
        checks["missing_task_error"] = True

        browser.close()

    print(json.dumps(checks, ensure_ascii=False, indent=2))
    (ROOT / "evidence.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
