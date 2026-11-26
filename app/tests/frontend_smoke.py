"""Opt-in Chromium smoke of the built React workbench and real local API."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit
from uuid import uuid4

if TYPE_CHECKING:
    from patchright.sync_api import Locator, Page

APP = Path(__file__).resolve().parents[1]
DIST = APP / "frontend-v2" / "dist" / "index.html"
SITE = "workbench-fixture.test"
TIMEOUT = 90
BUILD_SITE = "build-model-fixture.test"
TERRA = "yjwd-gpt-enterprise/gpt-6.1-terra"
DEEPSEEK = "opencode-go/deepseek-v4.1-flash"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def seed_rule(root: Path, origin: str) -> Path:
    from ecom_crawler.runtime.models import RuleVersion, SiteRule, utc_now
    from ecom_crawler.runtime.rule import load_rule
    from ecom_crawler.runtime.store import TaskStore
    from tests.test_execution import RULE_TEMPLATE

    rules = root / "rules"
    rules.mkdir()
    rule_path = rules / "fixture.yaml"
    rule_path.write_text(RULE_TEMPLATE.replace("__BASE__", origin), encoding="utf-8")
    rule = load_rule(rule_path)
    digest = hashlib.sha256(rule_path.read_bytes()).hexdigest()
    now = utc_now()
    store = TaskStore(root / "tasks.db")
    store.create_rule_version(
        RuleVersion(
            rule_id=rule.rule_id,
            rule_version=rule.rule_version,
            sha256=digest,
            path=rule_path.name,
            status="active",
            created_at=now,
            activated_at=now,
            activated_by="frontend-smoke",
        )
    )
    # Bind the synthetic public-looking site key to the loopback fixture. The
    # production importer intentionally rejects IP literals as submitted sites.
    store.upsert_site_rule(
        SiteRule(
            site_key=SITE,
            rule_id=rule.rule_id,
            rule_version=rule.rule_version,
            sha256=digest,
            path=rule_path.name,
            updated_at=now,
        )
    )
    return rules


def post(page: Page, button: Locator, origin: str, path: str, status: int) -> dict[str, Any]:
    with page.expect_response(
        lambda response: response.url == origin + path and response.request.method == "POST",
    ) as pending:
        button.click()
    response = pending.value
    check(response.status == status, f"POST {path}: {response.status} {response.text()}")
    return response.json()


def verify_zip(path: Path, name: str, batch: str, task: str, fixture: str) -> None:
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("batch.json"))
        check(
            manifest["batch"]["batch_id"] == batch and manifest["batch"]["name"] == name,
            f"Wrong batch in export: {manifest['batch']}",
        )
        sites = manifest["sites"]
        check(
            len(sites) == 1
            and sites[0]["site_key"] == SITE
            and sites[0]["task_id"] == task
            and sites[0]["export_status"] == "sample",
            f"Wrong site/task in export: {sites}",
        )
        task_path = f"sites/{SITE}"
        result = json.loads(archive.read(f"{task_path}/task-result.json"))
        check(
            result["task_id"] == task
            and result["state"] == "FINISHED"
            and result["outcome"] == "COMPLETED"
            and result["counts"]["valid_products"] == 2
            and result["counts"]["failed_products"] == 0,
            f"Wrong task result: {result}",
        )
        rows = csv.DictReader(
            io.StringIO(archive.read(f"{task_path}/products.csv").decode("utf-8-sig"))
        )
        check(
            rows.fieldnames
            == [
                "name",
                "price_amount",
                "price_currency",
                "primary_image_url",
                "description_html",
                "category",
                "brand",
                "attributes",
                "source_url",
            ],
            f"Wrong CSV header: {rows.fieldnames}",
        )
        actual = sorted(
            (r["name"], r["price_amount"], r["price_currency"], r["source_url"]) for r in rows
        )
        check(
            actual == [(f"Product {n}", "10.00", "GBP", f"{fixture}/p{n}.html") for n in (1, 2)],
            f"Wrong CSV products: {actual}",
        )


def exercise(page: Page, origin: str, fixture: str, root: Path) -> None:
    from patchright.sync_api import expect

    name = f"Workbench smoke {uuid4().hex[:10]}"
    response = page.goto(f"{origin}/", wait_until="domcontentloaded")
    check(
        response is not None and response.ok and response.request.redirected_from is not None,
        "FastAPI root did not redirect to the built workbench",
    )
    expect(page).to_have_url(re.compile(r"/next/#/batches(?:\?|$)"))
    nav = page.get_by_role("navigation", name="主导航")
    expect(nav.get_by_text("采集工作台", exact=True)).to_be_visible()
    expect(nav.get_by_text("规则与设置", exact=True)).to_be_visible()
    expect(nav.get_by_role("link", name="新建批次", exact=True)).to_have_count(0)
    expect(nav.get_by_role("link", name="采集批次", exact=True)).to_have_attribute(
        "aria-current", "page"
    )
    page.get_by_role("region", name="采集批次列表").get_by_role("button", name="新建批次").click()
    draft = page.get_by_role("dialog", name="新建采集批次")
    draft.get_by_role("button", name="保存草稿").click()
    expect(draft.get_by_text("请输入批次名称。")).to_be_visible()
    expect(draft.get_by_label("批次名称")).to_be_focused()
    draft.get_by_label("批次名称").fill(name)
    draft.get_by_label("市场", exact=True).fill("GB")
    draft.get_by_label("采集计划").select_option("sample")
    with page.expect_response(
        lambda response: response.url == f"{origin}/api/batches"
        and response.request.method == "POST" and response.status == 200
    ) as preview_response:
        draft.get_by_label("站点列表").fill(f"https://{SITE}/")
    preview = preview_response.value.json()
    check(
        preview["created"] is False and preview["preview"]["import"]["summary"]["ready"] == 1,
        f"Wrong import preview: {preview}",
    )
    before_save = page.request.get(f"{origin}/api/batches")
    check(
        before_save.ok and before_save.json()["total"] == 0, "Preview wrote a batch to the ledger"
    )
    created = post(page, draft.get_by_role("button", name="保存草稿"), origin, "/api/batches", 201)
    batch = created["batch"]["batch_id"]
    check(
        created["batch"]["name"] == name and created["import"]["summary"]["stored"] == 1,
        f"Wrong saved draft: {created}",
    )
    expect(draft).to_be_hidden()
    expect(page).to_have_url(re.compile(rf"/next/#/batches/{batch}$"))
    page.reload(wait_until="domcontentloaded")
    expect(page).to_have_url(re.compile(rf"/next/#/batches/{batch}$"))
    row_link = page.get_by_role("link", name=SITE, exact=True)
    action = page.get_by_role("button", name="启动 1 个可采站点", exact=True)
    region = page.get_by_role("region", name="站点清单", exact=True)
    for width in (1280, 1279, 768, 390, 320):
        page.set_viewport_size({"width": width, "height": 900})
        if width < 1024:
            page.wait_for_function("document.querySelector('main').getBoundingClientRect().left === 0")
        expect(row_link).to_be_in_viewport()
        scroll_width = page.evaluate("document.documentElement.scrollWidth")
        check(scroll_width <= width, f"Batch detail is {scroll_width}px wide at {width}px")
        cards = region.get_by_role("list", name="批次站点清单", exact=True)
        table = region.get_by_role("table", name="批次站点清单", exact=True)
        if cards.is_visible():
            expect(cards.get_by_role("listitem")).to_have_count(1)
        else:
            check(table.evaluate("""table => {
          const header = [...table.tHead.rows[0].cells];
          const body = [...table.tBodies[0].rows[0].cells];
          return header.every((cell, i) => {
            const a = cell.getBoundingClientRect(), b = body[i].getBoundingClientRect();
            return a.bottom <= b.top + 1 && Math.abs(a.x - b.x) <= 1
              && Math.abs(a.width - b.width) <= 1;
          });
        }"""), f"Misaligned batch table at {width}px")
        if width in (1280, 390) and (evidence := os.environ.get("ECOM_SMOKE_SCREENSHOT_DIR")):
            page.screenshot(path=str(Path(evidence) / f"batch-ready-{width}.png"), animations="disabled")
        if width == 390:
            menu = region.get_by_role("button", name=f"打开站点「{SITE}」的操作菜单")
            if table.is_visible():
                scroller = region.get_by_role("region", name="批次站点清单")
                initial_menu_x = menu.bounding_box()["x"]
                scroller.evaluate("el => { el.scrollLeft = 180; }")
                expect(menu).to_be_in_viewport()
                check(abs(menu.bounding_box()["x"] - initial_menu_x) <= 1,
                      "Site menu moved when the table was scrolled horizontally")
                scroller.evaluate("el => { el.scrollLeft = 0; }")
            menu.click()
            expect(page.get_by_role("menuitem", name="查看站点详情")).to_be_visible()
            page.keyboard.press("Escape")
            expect(menu).to_be_focused()
    page.set_viewport_size({"width": 1280, "height": 900})
    axe_script = APP / "frontend-v2" / "node_modules" / "axe-core" / "axe.min.js"
    page.add_script_tag(path=axe_script)
    violations = page.evaluate("async () => (await axe.run()).violations.map(v => v.id)", isolated_context=False)
    check(not violations, f"Batch detail axe violations: {violations}")

    search = region.get_by_role("textbox", name="搜索站点")
    filters = region.get_by_role("combobox", name="筛选站点状态")
    search.fill("workbench-fixture")
    filters.select_option("startable")
    row_link.click()
    expect(page).to_have_url(re.compile(rf"/sites/{re.escape(SITE)}$"))
    page.get_by_role("link", name=f"返回 {name}", exact=True).click()
    expect(search).to_have_value("workbench-fixture")
    expect(filters).to_have_value("startable")
    expect(row_link).to_be_focused()
    row_link.press("Enter")
    expect(page).to_have_url(re.compile(rf"/sites/{re.escape(SITE)}$"))
    page.go_back()
    expect(filters).to_have_value("startable")
    expect(row_link).to_be_focused()
    page.goto(f"{origin}/next/#/batches/{batch}/sites/{SITE}")
    page.get_by_role("link", name=f"返回 {name}", exact=True).click()
    expect(search).to_have_value("")
    expect(filters).to_have_value("all")

    more = page.get_by_role("button", name="更多批次操作")
    more.press("Enter")
    page.get_by_role("menuitem", name="归档批次…").press("Enter")
    archive = page.get_by_role("dialog", name="归档这个批次？")
    expect(archive.get_by_role("button", name="返回")).to_be_focused()
    page.keyboard.press("Escape")
    expect(archive).to_be_hidden()
    expect(more).to_be_focused()

    action.click()
    start = page.get_by_role("dialog", name="启动可采站点")
    accepted = post(
        page,
        start.get_by_role("button", name="将 1 个站点加入队列", exact=True),
        origin,
        f"/api/batches/{batch}/start",
        202,
    )
    check(
        len(accepted["accepted"]) == 1
        and not accepted["skipped"]
        and accepted["accepted"][0]["site_key"] == SITE,
        f"Wrong start result: {accepted}",
    )
    task = accepted["accepted"][0]["task_id"]
    page.get_by_role("link", name=re.compile(rf"查看任务 {re.escape(task)} 详情")).click()
    expect(page).to_have_url(re.compile(rf"/next/#/tasks/{task}$"))
    expect(page.get_by_role("button", name="导出 ZIP", exact=True)).to_be_visible(timeout=25_000)
    expect(page.get_by_role("button", name="导出 ZIP", exact=True)).to_have_count(1)
    overview = page.get_by_role("region", name="任务概览")
    expect(overview.get_by_text("有效商品", exact=True).locator("..")).to_contain_text("有效商品2")
    page.get_by_role("tab", name=re.compile("质量与验收")).click()
    expect(page.get_by_role("heading", name="结果验收", exact=True)).to_be_visible()
    page.get_by_role("tab", name=re.compile("数据明细")).click()
    expect(page.get_by_role("heading", name="CSV 表格预览", exact=True)).to_be_visible()
    page.get_by_role("tab", name=re.compile("运行明细")).click()
    expect(page.get_by_role("heading", name="任务事实", exact=True)).to_be_visible()
    page.get_by_role("tab", name=re.compile("结果")).click()
    page.set_viewport_size({"width": 390, "height": 900})
    page.wait_for_timeout(200)
    check(
        page.evaluate("document.documentElement.scrollWidth") <= 390,
        "Task detail is wider than 390px",
    )
    expect(page.get_by_role("heading", name="已采数据预览", exact=True)).to_be_visible()
    page.set_viewport_size({"width": 1280, "height": 900})
    detail = page.request.get(f"{origin}/api/tasks/{task}")
    check(detail.ok, f"Task readback failed: {detail.status}")
    payload = detail.json()
    check(
        payload["batch_id"] == batch
        and payload["state"] == "FINISHED"
        and payload["outcome"] == "COMPLETED"
        and payload["counts"]["valid_products"] == 2,
        f"Wrong task readback: {payload}",
    )

    page.get_by_role("main").locator("header").get_by_role("link", name=batch, exact=True).click()
    page.get_by_role("region", name="站点清单", exact=True).get_by_role(
        "link", name=SITE, exact=True
    ).click()
    expect(page.get_by_role("tab", name=re.compile("当前采集"))).to_be_visible()
    expect(page.get_by_role("button", name="导出当前任务 ZIP", exact=True)).to_have_count(1)
    page.get_by_role("tab", name=re.compile("规则与构建")).click()
    expect(page.get_by_role("heading", name="规则版本", exact=True)).to_be_visible()
    page.get_by_role("tab", name=re.compile("站点资料")).click()
    expect(page.get_by_text("站点 ID", exact=True)).to_be_visible()
    page.get_by_role("tab", name=re.compile("当前采集")).click()
    expect(page.get_by_text("CSV 预览和任务明细在任务详情中查看", exact=False)).to_be_visible()
    page.set_viewport_size({"width": 390, "height": 900})
    page.wait_for_timeout(200)
    check(
        page.evaluate("document.documentElement.scrollWidth") <= 390,
        "Site detail is wider than 390px",
    )
    expect(page.get_by_role("heading", name="已采数据预览", exact=True)).to_be_visible()
    if evidence := os.environ.get("ECOM_SMOKE_SCREENSHOT_DIR"):
        page.screenshot(path=str(Path(evidence) / "site-current-390.png"))
    page.set_viewport_size({"width": 1280, "height": 900})
    page.get_by_role("link", name=f"返回 {name}", exact=True).click()
    expect(page.get_by_role("button", name="导出批次 ZIP", exact=True)).to_be_visible()
    export = page.get_by_role("button", name="导出批次 ZIP", exact=True)
    expect(export).to_have_count(1)
    if evidence := os.environ.get("ECOM_SMOKE_SCREENSHOT_DIR"):
        page.screenshot(path=str(Path(evidence) / "batch-completed-1280.png"))
    with page.expect_download() as pending:
        export.click()
    download = pending.value
    check(
        download.url == f"{origin}/api/batches/{batch}/export", f"Wrong export URL: {download.url}"
    )
    target = root / "batch.zip"
    download.save_as(str(target))
    verify_zip(target, name, batch, task, fixture)
    page.get_by_role("button", name="开始正式采集…", exact=True).click()
    formal = page.get_by_role("dialog", name="开始正式采集", exact=True)
    promoted = post(
        page, formal.get_by_role("button", name="将 1 个站点加入队列", exact=True),
        origin, f"/api/batches/{batch}/start", 202,
    )
    check(promoted["batch"]["collection_mode"] == "formal", f"Trial did not promote: {promoted}")
    check(promoted["accepted"][0]["task_id"] != task, "Formal collection reused the trial task")
    print(
        f"Verified {batch} / {task}: persisted after reload; two GBP products in the downloaded ZIP.",
        flush=True,
    )

    exercise_many_sites(page, origin)


def exercise_many_sites(page: Page, origin: str) -> None:
    from patchright.sync_api import expect

    name = "多站点批次 · 返回位置"
    urls = [f"https://sample-{number:02d}.example.test/" for number in range(24)]
    seeded = page.request.post(
        f"{origin}/api/batches",
        data={"name": name, "country": "GB", "market": "GB", "sites": urls},
        headers={"Origin": origin, "X-Requested-With": "XMLHttpRequest"},
    )
    check(seeded.status == 201, f"Could not seed many-site batch: {seeded.text()}")
    batch = seeded.json()["batch"]["batch_id"]
    page.goto(f"{origin}/next/#/batches/{batch}")
    region = page.get_by_role("region", name="站点清单", exact=True)
    search = region.get_by_role("textbox", name="搜索站点")
    search.fill("not-present")
    expect(region.get_by_text("没有符合条件的站点", exact=True)).to_be_visible()
    region.get_by_role("button", name="重置筛选").click()
    expect(search).to_have_value("")
    status = region.get_by_role("combobox", name="筛选站点状态")
    status.select_option("needs")
    expect(status).to_have_value("needs")
    # Use the last rendered row, rather than relying on API row ordering.
    row = region.get_by_role("link", name=re.compile(r"sample-\d{2}\.example\.test")).last
    row.evaluate("element => element.scrollIntoView({ block: 'center', behavior: 'instant' })")
    row.focus()
    before = page.evaluate("window.scrollY")
    check(before > 0, "Many-site fixture did not require scrolling")
    row.press("Enter")
    page.get_by_role("link", name=f"返回 {name}", exact=True).click()
    expect(status).to_have_value("needs")
    expect(row).to_be_focused()
    after, max_scroll = page.evaluate("[window.scrollY, document.documentElement.scrollHeight - innerHeight]")
    expect(row).to_be_in_viewport()
    expected = min(before, max_scroll)
    check(abs(after - expected) <= 2, f"Batch scroll position changed from {before} to {after}; max {max_scroll}")
    print("Verified scroll position, filter, and row focus on the many-site batch.", flush=True)


def browser_check(origin: str, fixture: str, root: Path) -> None:
    from patchright.sync_api import Route, expect, sync_playwright

    problems: list[str] = []
    allowed = {urlsplit(origin).netloc, urlsplit(fixture).netloc}
    missing_rule_url = f"{origin}/api/sites/{BUILD_SITE}/rule"
    missing_rule_urls = {missing_rule_url} | {
        f"{origin}/api/sites/sample-{number:02d}.example.test/rule" for number in range(24)
    }

    def local_only(route: Route) -> None:
        url = urlsplit(route.request.url)
        if url.scheme != "http" or url.netloc not in allowed:
            problems.append(f"External request blocked: {url.scheme}://{url.netloc}{url.path}")
            route.abort()
        elif url.netloc == urlsplit(fixture).netloc and route.request.resource_type == "image":
            # Deliver the fixture image without relying on permissions for cross-port loopback requests.
            route.fulfill(response=route.fetch(max_redirects=0))
        else:
            route.continue_()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, timeout=15_000)
        print(f"Chromium {browser.version}; {origin}/next/#/batches (temporary)", flush=True)
        try:
            context = browser.new_context(
                viewport={"width": 1280, "height": 900}, service_workers="block"
            )
            try:
                context.route("**/*", local_only)
                page = context.new_page()
                page.set_default_timeout(8_000)
                page.on("pageerror", lambda exc: problems.append(f"pageerror: {exc}"))
                page.on(
                    "console",
                    lambda msg: (
                        problems.append(f"console: {msg.text}")
                        if msg.type == "error" and not (
                            msg.location.get("url") in missing_rule_urls and "404" in msg.text
                        ) else None
                    ),
                )
                page.on(
                    "response",
                    lambda res: (
                        problems.append(f"HTTP {res.status} {res.url}")
                        if res.status >= 400 and not (res.url in missing_rule_urls and res.status == 404)
                        else None
                    ),
                )
                context.tracing.start(screenshots=True, snapshots=True)
                try:
                    exercise(page, origin, fixture, root)
                    seeded = page.request.post(
                        f"{origin}/api/batches", data={"name": "模型池测试", "sites": [BUILD_SITE]},
                        headers={"Origin": origin, "X-Requested-With": "XMLHttpRequest"},
                    )
                    check(seeded.status == 201, f"Could not create model fixture: {seeded.text()}")
                    batch_id = seeded.json()["batch"]["batch_id"]
                    no_rule = page.request.get(missing_rule_url)
                    check(no_rule.status == 404 and no_rule.json()["error"]["code"] == "SITE_NOT_FOUND",
                          f"Unexpected response for a station with no rule or build: {no_rule.status}")
                    site_path = f"/api/batches/{batch_id}/sites/{BUILD_SITE}/build"
                    page.goto(f"{origin}/next/#/batches/{batch_id}/sites/{BUILD_SITE}")
                    page.get_by_role("button", name="启动构建", exact=True).first.click()
                    dialog = page.get_by_role("dialog", name="启动方案构建")
                    select = dialog.get_by_label("分配方式或模型")
                    expect(select).to_have_value("")
                    expect(dialog.get_by_text(re.compile(r"Terra.*尚未探测"))).to_be_visible()
                    select.select_option(TERRA)
                    level = dialog.get_by_label("思考等级")
                    expect(level).to_have_value("medium")
                    level.select_option("high")
                    health = post(
                        page, dialog.get_by_role("button", name="测试可用性"), origin,
                        "/api/builds/models/check", 200,
                    )
                    check(health["status"] == "ok", f"Fixture probe did not pass: {health}")
                    expect(dialog.get_by_text(re.compile(r"Terra.*high.*探测通过"))).to_be_visible()
                    for width in (1280, 390, 320):
                        page.set_viewport_size({"width": width, "height": 900 if width == 1280 else 700})
                        expect(dialog.get_by_role("button", name="启动构建")).to_be_in_viewport()
                        check(dialog.evaluate("el => el.scrollWidth <= el.clientWidth + 1"),
                              f"Build dialog overflows at {width}px")
                    if evidence := os.environ.get("ECOM_SMOKE_SCREENSHOT_DIR"):
                        page.screenshot(path=str(Path(evidence) / "model-dialog-320.png"))
                        page.set_viewport_size({"width": 1280, "height": 900})
                        page.screenshot(path=str(Path(evidence) / "model-dialog-1280.png"))
                    started = post(page, dialog.get_by_role("button", name="启动构建"), origin, site_path, 202)
                    check(started["build"]["model"] == {
                        "providerID": "yjwd-gpt-enterprise", "id": "gpt-6.1-terra", "variant": "high",
                    }, f"Wrong selected model: {started['build']['model']}")
                    expect(dialog).to_be_hidden()
                    print("Verified default allocation, variant selection, explicit mock probe, and model pinning.", flush=True)
                    check(not problems, "Unexpected browser errors:\n" + "\n".join(problems))
                except Exception:
                    print(f"Failed at {page.url}; browser errors: {problems}", file=sys.stderr)
                    context.tracing.stop(path=root / "trace.zip")
                    raise
                else:
                    context.tracing.stop()
            finally:
                context.close()
        finally:
            browser.close()


def run_scenario(root: Path) -> None:
    from unittest.mock import patch

    import uvicorn

    from ecom_crawler.builds import BuildManager
    from ecom_crawler.runtime.store import TaskStore
    from ecom_crawler.web.app import create_app
    from tests.test_builds import FakeBuildAdapter
    from tests.test_execution import fixture_server

    with (
        fixture_server() as fixture,
        socket.socket() as listener,
        patch("ecom_crawler.build_models.probe_chat", return_value=6),
    ):
        listener.bind(("127.0.0.1", 0))
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        rules = seed_rule(root, fixture)
        manager = BuildManager(
            TaskStore(root / "tasks.db"), root / "tasks", rules,
            adapter=FakeBuildAdapter(root, hang=True), robots_probe=lambda *_: ("fixture", []),
        )
        app = create_app(
            root / "tasks.db", root / "tasks", rules, manage_worker=True, per_domain_rps=20,
            build_manager=manager,
        )
        server = uvicorn.Server(uvicorn.Config(app, access_log=False, timeout_graceful_shutdown=5))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            until = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= until:
                    raise RuntimeError("FastAPI test server did not start")
                time.sleep(0.025)
            browser_check(origin, fixture, root)
        finally:
            server.should_exit = True
            thread.join(timeout=18)
            check(
                not thread.is_alive()
                and not any(t.name == "managed-worker" for t in threading.enumerate()),
                "FastAPI or its managed worker did not exit",
            )


def run_worker(root: Path) -> int:
    from tests.parallel_runner import wait_for_start_gate

    if not wait_for_start_gate(root / "worker.pid"):
        return 1

    if sys.platform != "win32":
        # Parent holds the pipe until completion. On EOF, exit this worker;
        # Patchright's driver then receives EOF and closes its browser group.
        def watch_parent() -> None:
            os.read(sys.stdin.fileno(), 1)
            os._exit(1)

        threading.Thread(target=watch_parent, daemon=True).start()
    scenario = root / "scenario"
    scenario.mkdir()
    run_scenario(scenario)
    (root / "complete").touch()
    return 0


def supervise(root: Path) -> None:
    from tests.parallel_runner import _Job, admit_windows_worker

    windows = sys.platform == "win32"
    scratch = root / "tmp"
    scratch.mkdir()
    env = {
        key: value
        for key, value in os.environ.items()
        if not (key.upper().endswith("_PROXY") or key.upper().startswith("ECOM_"))
    }
    env.update(
        TMP=str(scratch),
        TEMP=str(scratch),
        TMPDIR=str(scratch),
        ECOM_LEGACY_UI="off",
        ECOM_BUILD_DISABLED="0",
        ECOM_BUILD_MODEL_POOL=f"{DEEPSEEK}#high,{TERRA}#medium",
        NO_PROXY="127.0.0.1",
    )
    if screenshot_dir := os.environ.get("ECOM_SMOKE_SCREENSHOT_DIR"):
        env["ECOM_SMOKE_SCREENSHOT_DIR"] = screenshot_dir
    job = _Job() if windows else None
    worker = None
    try:
        started = time.monotonic()
        worker = subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                str(Path(__file__).resolve()),
                "--worker",
                str(root),
            ],
            env=env,
            stdin=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if windows else 0,
        )
        if job is not None:
            admit_windows_worker(job, worker, root / "worker.pid", started + 10)
        gate = worker.stdin
        if gate is None:
            raise OSError("Worker start pipe unavailable")
        gate.write(b"1")
        gate.flush()
        code = worker.wait(timeout=max(0, TIMEOUT - (time.monotonic() - started)))
        check(
            code == 0 and (root / "complete").is_file(),
            f"Browser smoke incomplete (worker exit {code})",
        )
        if job is not None:
            # Chromium helpers can still be exiting after the driver and
            # worker return. Give them a bounded graceful exit window.
            until = time.monotonic() + 5
            while job.active():
                if time.monotonic() >= until:
                    raise OSError("Browser smoke left processes behind")
                time.sleep(0.05)
        check(not any(scratch.iterdir()), "Browser smoke left temporary files behind")
    finally:
        try:
            if worker is not None and worker.stdin is not None:
                worker.stdin.close()
            if job is not None:
                job.drain()
        finally:
            # Close the kill-on-close handle before waiting, even if drain fails.
            if job is not None:
                job.close()
            if worker is not None and worker.poll() is None:
                try:
                    worker.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one Chromium smoke against FastAPI, temporary SQLite and a loopback catalog.",
        epilog=f"Build app/frontend-v2 first (npm run build). Time limit: {TIMEOUT}s. Requires the app dev environment and "
        "Patchright Chromium. Nothing is installed; failed-run diagnostics stay in the OS temp folder. "
        "Example: python -m uv run --project app --extra dev --frozen --no-sync python app/tests/frontend_smoke.py",
    )
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(APP))
    if args.worker:
        return run_worker(args.worker)
    if not DIST.is_file():
        parser.error(
            "Missing app/frontend-v2/dist/index.html; run npm run build in app/frontend-v2 first"
        )
    root = Path(tempfile.mkdtemp(prefix="ecom-frontend-smoke-"))
    started = time.monotonic()
    try:
        supervise(root)
        shutil.rmtree(root)
    except KeyboardInterrupt:
        print(f"Interrupted; diagnostics: {root}", file=sys.stderr)
        return 130
    except (OSError, subprocess.SubprocessError, AssertionError) as exc:
        print(f"Browser smoke failed: {exc}; diagnostics: {root}", file=sys.stderr)
        return 1
    print(f"Browser smoke passed; temporary directory removed ({time.monotonic() - started:.2f}s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
