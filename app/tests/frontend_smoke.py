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

if TYPE_CHECKING:
    from patchright.sync_api import Locator, Page

APP = Path(__file__).resolve().parents[1]
DIST = APP / "frontend" / "dist" / "index.html"
SITE = "workbench-fixture.test"
PENDING_SITE = "pending-workbench-fixture.test"
TIMEOUT = 90


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


def verify_zip(path: Path, task_id: str, fixture: str) -> None:
    from ecom_crawler.model import CSV_COLUMNS

    with zipfile.ZipFile(path) as archive:
        result = json.loads(archive.read("task-result.json"))
        check(
            result["task_id"] == task_id
            and result["state"] == "FINISHED"
            and result["outcome"] == "COMPLETED"
            and result["counts"]["valid_products"] == 2
            and result["counts"]["failed_products"] == 0,
            f"Wrong task result: {result}",
        )
        rows = csv.DictReader(
            io.StringIO(archive.read("products.csv").decode("utf-8-sig"))
        )
        check(rows.fieldnames == list(CSV_COLUMNS), f"Wrong CSV header: {rows.fieldnames}")
        actual = sorted(
            (row["name"], row["price_amount"], row["price_currency"], row["source_url"])
            for row in rows
        )
        check(
            actual == [(f"Product {n}", "10.00", "GBP", f"{fixture}/p{n}.html") for n in (1, 2)],
            f"Wrong CSV products: {actual}",
        )


def exercise(page: Page, origin: str, fixture: str, root: Path) -> None:
    from patchright.sync_api import expect

    response = page.goto(f"{origin}/", wait_until="domcontentloaded")
    check(response is not None and response.ok, "FastAPI root did not serve the frontend")
    expect(page).to_have_url(re.compile(r"/#/workbench(?:\?|$)"))
    nav = page.get_by_role("navigation", name="主导航")
    for label in ("任务工作台", "全部任务", "构建记录", "模型配置", "系统设置"):
        expect(nav.get_by_role("link", name=label, exact=True)).to_be_visible()
    for path in ("/#/batches", "/#/batches/legacy"):
        page.goto(f"{origin}{path}")
        expect(page).to_have_url(re.compile(r"/#/workbench(?:\?|$)"))
        expect(page.get_by_role("heading", name="任务目录", exact=True)).to_be_visible()

    page.get_by_role("button", name="新建", exact=True).click()
    page.get_by_role("menuitem", name="新建批次").click()
    dialog = page.get_by_role("dialog", name="新建批次")
    dialog.get_by_label(re.compile("批次名称")).fill("工作台冒烟批次")
    dialog.get_by_label("市场", exact=True).fill("GB")
    dialog.get_by_label("国家", exact=True).fill("GB")
    dialog.get_by_label(re.compile("站点 URL")).fill(f"https://{SITE}/\nhttps://{PENDING_SITE}/")
    with page.expect_response(
        lambda response: response.url == origin + "/api/workbench/import-batch"
        and response.request.method == "POST",
    ) as imported:
        created = post(
            page, dialog.get_by_role("button", name="创建批次并添加"), origin, "/api/batches", 201,
        )
    response = imported.value
    check(response.ok, f"Import failed: {response.status} {response.text()}")
    joined = response.json()
    check(
        joined["batch_id"] == created["batch"]["batch_id"] and joined["counts"]["added"] == 2,
        f"Expected a ready node and a pending node: {joined}",
    )
    nodes_by_name = {item["name"]: item["node_id"] for item in joined["added"]}
    check(nodes_by_name.keys() == {SITE, PENDING_SITE}, f"Unexpected imported nodes: {joined}")
    node_id = nodes_by_name[SITE]
    page.get_by_role("dialog", name="批次加入结果").get_by_role("button", name="完成").click()
    tree_panel = page.get_by_role("complementary", name="任务目录")
    start = tree_panel.get_by_role("button", name=f"启动 {SITE}", exact=True)
    expect(start).to_be_visible()
    page.reload(wait_until="domcontentloaded")
    expect(start).to_be_visible()
    expect(tree_panel.get_by_role("button", name=f"接入 {PENDING_SITE}")).to_be_visible()
    started = post(page, start, origin, f"/api/workbench/tasks/{node_id}/start", 202)
    task_id = started["task"]["task_id"]
    recent = page.get_by_role("region", name="最近任务")
    row = recent.get_by_role("row", name=re.compile(rf"运行 {re.escape(task_id)}"))
    expect(row.get_by_text("完成", exact=True)).to_be_visible(timeout=25_000)
    expect(row.get_by_role("cell", name="2 失败 0", exact=True)).to_be_visible()
    expect(row.get_by_text(f"根目录 · {task_id}", exact=True)).to_be_visible()

    detail = page.request.get(f"{origin}/api/tasks/{task_id}")
    check(detail.ok, f"Task readback failed: {detail.status} {detail.text()}")
    task = detail.json()
    check(
        task["task_id"] == task_id and task["batch_id"] == created["batch"]["batch_id"]
        and task["state"] == "FINISHED" and task["counts"]["valid_products"] == 2,
        f"Unexpected persisted task: {task}",
    )
    with page.expect_download() as downloaded:
        row.get_by_role("link", name=f"导出 {task_id}").click()
    download = downloaded.value
    check(download.suggested_filename.endswith(".zip"), "Task export did not return a ZIP")
    archive = root / "workbench-result.zip"
    download.save_as(archive)
    verify_zip(archive, task_id, fixture)
    print("Verified workbench batch import, reload, task completion and ZIP delivery.", flush=True)


def browser_check(origin: str, fixture: str, root: Path) -> None:
    from patchright.sync_api import Route, sync_playwright

    problems: list[str] = []
    allowed = {urlsplit(origin).netloc, urlsplit(fixture).netloc}

    def local_only(route: Route) -> None:
        url = urlsplit(route.request.url)
        if url.scheme != "http" or url.netloc not in allowed:
            problems.append(f"External request blocked: {url.scheme}://{url.netloc}{url.path}")
            route.abort()
        elif url.netloc == urlsplit(fixture).netloc and route.request.resource_type == "image":
            # Deliver local images without relying on cross-port browser permissions.
            route.fulfill(response=route.fetch(max_redirects=0))
        else:
            route.continue_()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, timeout=15_000)
        print(f"Chromium {browser.version}; {origin}/#/workbench (temporary)", flush=True)
        try:
            context = browser.new_context(
                viewport={"width": 1280, "height": 900}, service_workers="block"
            )
            try:
                context.route("**/*", local_only)
                page = context.new_page()
                page.set_default_timeout(8_000)
                page.on("pageerror", lambda exc: problems.append(f"pageerror: {exc}"))
                # Patchright can suppress console events. Capture app errors in the page.
                page.expose_function("reportSmokeConsoleError", lambda message: problems.append(message))
                page.add_init_script(
                    """{
                        const original = console.error;
                        console.error = (...args) => {
                            void window.reportSmokeConsoleError(`console: ${args.map(String).join(" ")}`);
                            original.apply(console, args);
                        };
                    }""",
                )
                page.on(
                    "response",
                    lambda res: problems.append(f"HTTP {res.status} {res.url}") if res.status >= 400 else None,
                )
                page.on(
                    "requestfailed",
                    lambda request: problems.append(f"Request failed: {request.failure} {request.url}")
                    if request.failure != "net::ERR_ABORTED" else None,
                )
                context.tracing.start(screenshots=True, snapshots=True)
                try:
                    exercise(page, origin, fixture, root)
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
    import uvicorn

    from ecom_crawler.builds import BuildManager
    from ecom_crawler.runtime.store import TaskStore
    from ecom_crawler.web.app import create_app
    from tests.test_builds import FakeBuildAdapter
    from tests.test_execution import fixture_server

    with fixture_server() as fixture, socket.socket() as listener:
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
        ECOM_BUILD_DISABLED="0",
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
        epilog=f"Build app/frontend first (npm run build). Time limit: {TIMEOUT}s. Requires the app dev environment and "
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
            "Missing app/frontend/dist/index.html; run npm run build in app/frontend first"
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
