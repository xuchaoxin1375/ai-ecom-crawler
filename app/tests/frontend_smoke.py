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
            and sites[0]["export_status"] == "complete",
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
    page.get_by_role("region", name="采集批次列表").get_by_role("button", name="新建批次").click()
    draft = page.get_by_role("dialog", name="新建采集批次")
    parse = draft.get_by_role("button", name="解析并预览")
    parse.click()
    expect(draft.get_by_text("先给批次起一个名称，再解析站点。")).to_be_visible()
    expect(draft.get_by_label("批次名称")).to_be_focused()
    draft.get_by_label("批次名称").fill(name)
    draft.get_by_label("国家", exact=True).fill("GB")
    draft.get_by_label("市场", exact=True).fill("GB")
    draft.get_by_label("站点列表").fill(f"https://{SITE}/")
    preview = post(page, parse, origin, "/api/batches", 200)
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
    page.reload(wait_until="domcontentloaded")
    page.get_by_role("link", name=name, exact=True).click()
    expect(page).to_have_url(re.compile(rf"/next/#/batches/{batch}$"))
    expect(page.get_by_role("link", name=SITE, exact=True)).to_be_visible()

    page.get_by_role("button", name="启动 1 个", exact=True).click()
    start = page.get_by_role("dialog", name="启动可采站点")
    accepted = post(
        page,
        start.get_by_role("button", name="启动 1 个", exact=True),
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
    page.get_by_role("link", name="任务详情", exact=True).click()
    expect(page).to_have_url(re.compile(rf"/next/#/tasks/{task}$"))
    expect(page.get_by_role("button", name="导出 ZIP", exact=True)).to_be_visible(timeout=25_000)
    overview = page.get_by_role("region", name="任务概览")
    expect(overview.get_by_text("有效商品", exact=True).locator("..")).to_contain_text("有效商品2")
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
    export = (
        page.locator("section")
        .filter(has=page.get_by_role("heading", name="导出与批次管理"))
        .get_by_role("button", name="导出批次 ZIP", exact=True)
    )
    with page.expect_download() as pending:
        export.click()
    download = pending.value
    check(
        download.url == f"{origin}/api/batches/{batch}/export", f"Wrong export URL: {download.url}"
    )
    target = root / "batch.zip"
    download.save_as(str(target))
    verify_zip(target, name, batch, task, fixture)
    print(
        f"Verified {batch} / {task}: persisted after reload; two GBP products in the downloaded ZIP.",
        flush=True,
    )


def browser_check(origin: str, fixture: str, root: Path) -> None:
    from patchright.sync_api import Route, sync_playwright

    problems: list[str] = []
    allowed = {urlsplit(origin).netloc, urlsplit(fixture).netloc}

    def local_only(route: Route) -> None:
        url = urlsplit(route.request.url)
        if url.scheme != "http" or url.netloc not in allowed:
            problems.append(f"External request blocked: {url.scheme}://{url.netloc}{url.path}")
            route.abort()
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
                        problems.append(f"console: {msg.text}") if msg.type == "error" else None
                    ),
                )
                page.on(
                    "response",
                    lambda res: (
                        problems.append(f"HTTP {res.status} {res.url}")
                        if res.status >= 400
                        else None
                    ),
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

    from ecom_crawler.web.app import create_app
    from tests.test_execution import fixture_server

    with fixture_server() as fixture, socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        rules = seed_rule(root, fixture)
        app = create_app(
            root / "tasks.db", root / "tasks", rules, manage_worker=True, per_domain_rps=20
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
        ECOM_BUILD_DISABLED="1",
        NO_PROXY="127.0.0.1",
    )
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
