"""Verify the QUEUED / worker status UI on the synthetic read-only preview.

Run the synthetic preview on port 8776, create and start one task through the
API, then run this script. It checks that the page explains the external
worker mode and the queue reason instead of leaving the user guessing.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from patchright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8776"
ROOT = Path(__file__).resolve().parent


def api(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    tasks = api("/api/tasks?include_archived=true")["items"]
    queued = next(task for task in tasks if task["state"] == "QUEUED")
    task_id = queued["task_id"]
    checks: dict[str, object] = {"queued_task": task_id}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{BASE}/#/tasks", wait_until="networkidle")
        page.wait_for_selector("#service-status")
        service_text = page.locator("#service-status").inner_text()
        list_text = page.locator("main").inner_text()
        checks["external_worker_shown"] = "外部 worker" in service_text
        checks["queued_count_shown"] = "个排队" in list_text
        checks["queued_task_shown"] = task_id in list_text

        page.goto(f"{BASE}/#/tasks/{task_id}", wait_until="networkidle")
        page.wait_for_selector("#detail-queue:not([hidden])")
        queue_text = page.locator("#detail-queue").inner_text()
        checks["queue_reason"] = "外部 worker" in queue_text and "排队" in queue_text
        page.screenshot(path=str(ROOT / "queue-state-1280.png"))
        browser.close()

    print(json.dumps(checks, ensure_ascii=False, indent=2))
    (ROOT / "queue-evidence.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
