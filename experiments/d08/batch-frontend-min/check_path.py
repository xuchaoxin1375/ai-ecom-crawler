"""Smoke the built batch frontend through FastAPI and a real ledger.

Start a local serve first, for example:

    app/.venv/Scripts/python.exe -m ecom_crawler serve \
      --db /path/to/tasks.db --out-root /path/to/tasks \
      --rules-dir experiments/d03/familidoo --no-worker --port 8776

Then:

    app/.venv/Scripts/python.exe experiments/d08/batch-frontend-min/check_path.py \
      --base http://127.0.0.1:8776
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from patchright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8776")
    parser.add_argument("--screenshot", default=str(ROOT / "batch-minimal-path.png"))
    args = parser.parse_args()
    base = args.base.rstrip("/")

    errors: list[str] = []
    checks: dict[str, object] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.on(
            "console",
            lambda message: errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"{base}/batch/", wait_until="networkidle")
        page.wait_for_selector("#app")
        page.wait_for_selector("text=采集批次")
        text = page.locator("main").inner_text()
        checks["health_rendered"] = "ok" in text and (
            "托管 worker" in text or "外部 worker" in text
        )
        checks["real_task_rows"] = page.locator(".table-wrap tbody tr").count() > 0
        checks["fastapi_batch_hosted"] = "技术最小路径" in text

        link = page.locator(".table-wrap a").first
        checks["task_link_present"] = link.count() == 1
        if link.count():
            link.click()
            page.wait_for_selector("text=批次详情（占位）")
            checks["hash_route"] = "批次详情（占位）" in page.locator(
                "main"
            ).inner_text()
        page.screenshot(path=args.screenshot)
        browser.close()

    checks["console_errors"] = errors
    checks["screenshot"] = Path(args.screenshot).name
    (ROOT / "evidence.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0 if all(
        checks[key]
        for key in (
            "health_rendered",
            "real_task_rows",
            "fastapi_batch_hosted",
            "task_link_present",
            "hash_route",
        )
    ) and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
