"""Capture the batch workbench prototype at 1280 and basic 768 widths.

The prototype is static and uses mock data. This script starts a local
http.server, opens the pages with Patchright, and writes screenshots plus a
small evidence JSON. It does not touch the application backend.

Run with the app environment:

    app/.venv/Scripts/python.exe experiments/d08/batch-workbench-prototype/capture.py
"""

from __future__ import annotations

import functools
import json
import threading
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = 8780
BASE = f"http://127.0.0.1:{PORT}"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def serve() -> ThreadingHTTPServer:
    handler = functools.partial(QuietHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def wait_ready() -> None:
    for _ in range(50):
        try:
            with urllib.request.urlopen(f"{BASE}/index.html", timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:  # noqa: BLE001 - readiness loop
            pass
    raise RuntimeError("prototype server did not become ready")


def main() -> int:
    server = serve()
    screens = ROOT / "screens"
    screens.mkdir(exist_ok=True)
    errors: list[str] = []
    try:
        wait_ready()
        from patchright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)

            page.goto(f"{BASE}/#/batches", wait_until="networkidle")
            page.wait_for_selector("table tbody tr")
            list_rows = page.locator("table tbody tr").count()
            list_text = page.locator("main").inner_text()
            list_overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
            page.screenshot(path=str(screens / "batches-1280.png"))

            page.goto(f"{BASE}/#/batches/fr-handmade-2026-11", wait_until="networkidle")
            page.wait_for_selector("table tbody tr")
            batch_rows = page.locator("table tbody tr").count()
            batch_text = page.locator("main").inner_text()
            batch_overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
            page.screenshot(path=str(screens / "batch-1280.png"))

            page.goto(
                f"{BASE}/#/batches/fr-handmade-2026-11/sites/maison-lin.fr",
                wait_until="networkidle",
            )
            page.wait_for_selector("text=质量异常")
            site_text = page.locator("main").inner_text()
            page.screenshot(path=str(screens / "site-1280.png"))
            page.click('[data-action="item-tab"][data-value="url"]')
            page.wait_for_selector("text=类型")
            url_tab_text = page.locator("main").inner_text()
            page.screenshot(path=str(screens / "site-url-tab-1280.png"))

            page.goto(f"{BASE}/#/batches/new", wait_until="networkidle")
            new_batch_has_rule_select = page.locator("#rule-select").count() > 0
            page.fill("#wizard-name", "法国手工纺织 2026-12")
            page.click('[data-action="wizard-next"]')
            page.wait_for_selector("#wizard-sites")
            page.screenshot(path=str(screens / "new-batch-import-1280.png"))
            page.click('[data-action="wizard-next"]')
            page.wait_for_selector("text=匹配预览")
            new_batch_text = page.locator("main").inner_text()
            page.screenshot(path=str(screens / "new-batch-preview-1280.png"))
            page.click('[data-action="wizard-save"][data-start="false"]')
            page.wait_for_selector("h1:has-text('法国手工纺织 2026-12')")
            new_batch_saved = "法国手工纺织 2026-12" in page.locator("main").inner_text()
            page.screenshot(path=str(screens / "new-batch-saved-1280.png"))

            page.set_viewport_size({"width": 768, "height": 900})
            page.goto(f"{BASE}/#/batches/fr-handmade-2026-11", wait_until="networkidle")
            page.wait_for_selector("table tbody tr")
            narrow_overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
            page.screenshot(path=str(screens / "batch-768.png"))

            browser.close()

        evidence = {
            "viewport": "1280x900 / 768x900",
            "batch_rows": list_rows,
            "batch_detail_rows": batch_rows,
            "overflow": {
                "batch_list_1280": list_overflow,
                "batch_detail_1280": batch_overflow,
                "batch_detail_768": narrow_overflow,
            },
            "contains": {
                "workflow_copy": "把一批站点组织成一个采集项目" in list_text,
                "needs_onboarding": "待接入" in batch_text,
                "partial_start": "不阻塞可采站点" in batch_text,
                "quality_formatted": "描述状态" in site_text and "缺失字段" in site_text,
                "create_starts_with_batch": not new_batch_has_rule_select,
                "preview_shows_readiness": "可采" in new_batch_text and "待接入" in new_batch_text,
                "new_batch_saved": new_batch_saved,
                "url_tab_switches": "网址" in url_tab_text and "类型" in url_tab_text,
            },
            "console_errors": errors,
            "screenshots": sorted(path.name for path in screens.glob("*.png")),
        }
        (ROOT / "evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        return 0
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
