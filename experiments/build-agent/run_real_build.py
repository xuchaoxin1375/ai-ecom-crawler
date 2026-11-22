"""Run a real OpenCode build through the batch-site workflow.

The script exercises the same path a user takes in the workbench:

1. create a batch from a site URL;
2. start a build for the unmatched site;
3. wait for the agent and host validation;
4. start the batch and wait for the managed worker;
5. copy a small, reviewable evidence set.

The model is called for real and may incur provider charges.  Defaults are
deliberately small: one site, three products, one build.  Override the model or
budgets with the CLI flags; the script never writes provider credentials.

Run with the app environment:

    python -m uv run --project app python experiments/build-agent/run_real_build.py --help
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ecom_crawler.builds import BuildManager
from ecom_crawler.harness.trace import render_trace_markdown
from ecom_crawler.runtime.store import TaskStore
from ecom_crawler.web.app import create_app
from fastapi.testclient import TestClient

HEADERS = {
    "Host": "127.0.0.1:8765",
    "Origin": "http://127.0.0.1:8765",
    "X-Requested-With": "XMLHttpRequest",
}

VISIBLE_EVENTS = {
    "tool_started",
    "tool_finished",
    "phase_changed",
    "permission_requested",
    "permission_replied",
    "dependency_requested",
    "dependency_available",
    "dependency_installed",
    "dependency_approval_required",
    "dependency_denied",
    "dependency_failed",
    "finished",
    "error",
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _event_text(event: dict[str, Any]) -> str:
    data = event.get("data") or {}
    kind = event.get("type")
    if kind == "tool_started":
        return f"tool_started {data.get('tool') or ''}".strip()
    if kind == "tool_finished":
        return f"tool_finished {data.get('tool') or ''} {data.get('status') or ''}".strip()
    if kind == "phase_changed":
        return f"phase {data.get('phase') or ''}".strip()
    if kind.startswith("dependency_"):
        return f"{kind} {data.get('name') or ''} {data.get('status') or ''}".strip()
    if kind == "permission_requested":
        return f"permission {data.get('action') or ''}".strip()
    if kind == "finished":
        return f"finished {data.get('outcome') or ''}".strip()
    if kind == "error":
        return f"error {data.get('error') or data.get('message') or ''}".strip()
    return str(kind)


def _wait_build(
    client: TestClient,
    build_id: str,
    *,
    timeout: float,
    poll: float = 2.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    seen_events = 0
    last_state = ""
    last_note = 0.0
    while time.monotonic() < deadline:
        response = client.get(f"/api/builds/{build_id}")
        if response.status_code != 200:
            raise RuntimeError(
                f"build status failed: HTTP {response.status_code} {response.text[:500]}"
            )
        build = response.json()["build"]
        if build["state"] != last_state:
            print(
                f"[{_now()}] build {build_id}: {build['state']}"
                + (f"/{build['outcome']}" if build.get("outcome") else "")
            )
            last_state = build["state"]
        events = build.get("events") or []
        for event in events[seen_events:]:
            if event.get("type") in VISIBLE_EVENTS:
                print(f"[{_now()}]   {_event_text(event)}")
        seen_events = len(events)
        if build["state"] in {"FINISHED", "CANCELLED"}:
            return build
        if time.monotonic() - last_note >= 15:
            elapsed = build.get("elapsed_seconds")
            if elapsed is not None:
                print(f"[{_now()}]   waiting; elapsed {round(elapsed)}s")
            last_note = time.monotonic()
        time.sleep(poll)
    raise TimeoutError(f"build {build_id} did not finish within {timeout:.0f}s")


def _wait_task(
    client: TestClient,
    task_id: str,
    *,
    timeout: float,
    poll: float = 2.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_state = ""
    while time.monotonic() < deadline:
        response = client.get(f"/api/tasks/{task_id}")
        if response.status_code != 200:
            raise RuntimeError(
                f"task status failed: HTTP {response.status_code} {response.text[:500]}"
            )
        task = response.json()
        if task["state"] != last_state:
            counts = task.get("counts") or {}
            print(
                f"[{_now()}] task {task_id}: {task['state']} "
                f"valid={counts.get('valid_products', 0)} "
                f"failed={counts.get('failed_products', 0)} "
                f"excluded={counts.get('excluded_products', 0)}"
            )
            last_state = task["state"]
        if task["state"] in {"FINISHED", "CANCELLED"}:
            return task
        time.sleep(poll)
    raise TimeoutError(f"task {task_id} did not finish within {timeout:.0f}s")


def _copy_evidence(
    evidence_dir: Path,
    *,
    batch: dict[str, Any],
    build: dict[str, Any],
    task: dict[str, Any] | None,
    rules_dir: Path,
    out_root: Path,
    export_zip: bytes | None,
    site_url: str,
    include_reasoning: bool = False,
) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    rule = build.get("rule") or {}
    if rule.get("path"):
        source = rules_dir / str(rule["path"])
        if source.is_file():
            shutil.copyfile(source, evidence_dir / "rule.yaml")

    workspace = Path(str(build.get("workspace") or ""))
    trace_path = workspace / "out" / "trace.json"
    if trace_path.is_file():
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        if not include_reasoning:
            trace["reasoning"] = []
            trace["reasoning_retained"] = False
            trace["counts"]["reasoning_parts"] = 0
            trace["counts"]["reasoning_chars"] = 0
        (evidence_dir / "trace.json").write_text(
            json.dumps(trace, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (evidence_dir / "trace.md").write_text(
            render_trace_markdown(trace),
            encoding="utf-8",
        )
    session_path = workspace / "out" / "session.ndjson"
    if session_path.is_file():
        (evidence_dir / "session.ndjson").write_text(
            "".join(
                line
                for line in session_path.read_text(encoding="utf-8").splitlines(True)
                if include_reasoning
                or '"type": "reasoning"' not in line
                and '"type":"reasoning"' not in line
            ),
            encoding="utf-8",
        )
    notes_path = workspace / "out" / "evidence" / "build-notes.md"
    if notes_path.is_file():
        shutil.copyfile(notes_path, evidence_dir / "build-notes.md")

    sanitized_events = [
        {
            "type": event.get("type"),
            "source_type": event.get("source_type"),
            "created_at": event.get("created_at"),
            "data": {
                key: value
                for key, value in (event.get("data") or {}).items()
                if key
                in {
                    "tool",
                    "status",
                    "phase",
                    "outcome",
                    "error",
                    "message",
                    "name",
                    "version",
                    "action",
                    "reply",
                }
            },
        }
        for event in (build.get("events") or [])
        if event.get("type") in VISIBLE_EVENTS
    ]
    _json(
        evidence_dir / "build.json",
        {
            "build_id": build.get("build_id"),
            "state": build.get("state"),
            "outcome": build.get("outcome"),
            "error": build.get("error"),
            "model": build.get("model"),
            "proxy": build.get("proxy"),
            "proxy_configured": build.get("proxy_configured"),
            "rule": build.get("rule"),
            "created_at": build.get("created_at"),
            "started_at": build.get("started_at"),
            "finished_at": build.get("finished_at"),
            "elapsed_seconds": build.get("elapsed_seconds"),
            "events": sanitized_events,
        },
    )
    _json(
        evidence_dir / "batch.json",
        {
            "batch_id": batch.get("batch_id"),
            "name": batch.get("name"),
            "status": batch.get("status"),
            "counts": batch.get("counts"),
            "valid_products": batch.get("valid_products"),
            "failed_products": batch.get("failed_products"),
            "sites": batch.get("sites"),
        },
    )
    if task is not None:
        _json(evidence_dir / "task.json", task)
        if export_zip:
            (evidence_dir / "task-export.zip").write_bytes(export_zip)
        task_id = str(task.get("task_id") or "")
        run_dir = out_root / task_id
        export_dir = run_dir / "export"
        for name in ("products.csv", "task-result.json", "urls.csv"):
            source = export_dir / name
            if not source.is_file():
                source = run_dir / name
            if source.is_file():
                shutil.copyfile(source, evidence_dir / name)
    (evidence_dir / "README.md").write_text(
        "\n".join(
            [
                "# 构建 Agent 真实站点验证",
                "",
                f"- 时间：{_now()}",
                f"- 站点：`{site_url}`",
                f"- 批次：`{batch.get('batch_id')}`，状态 `{batch.get('status')}`",
                (
                    f"- 构建：`{build.get('build_id')}`，状态 `{build.get('state')}`，"
                    f"结果 `{build.get('outcome')}`"
                ),
                f"- 模型：`{json.dumps(build.get('model'), ensure_ascii=False)}`",
                f"- 出口：`{build.get('proxy') or '直连'}`",
                f"- 规则：`{json.dumps(build.get('rule'), ensure_ascii=False)}`",
                (
                    f"- 任务：`{(task or {}).get('task_id') or '-'}`，"
                    f"状态 `{(task or {}).get('state') or '-'}`，"
                    f"结果 `{(task or {}).get('outcome') or '-'}`"
                ),
                "",
                (
                    "本目录只保留规则、构建摘要、任务结果和 9 列 CSV；不保存会话原文、"
                    "模型推理或整页 HTML。单次运行不等于全站或长期稳定性结论。"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a real build-agent workflow for one batch site: import, build, "
            "host validation, batch start and task export."
        )
    )
    parser.add_argument(
        "--site-url",
        default="https://www.sixmoondesigns.com/collections/ultralight-backpacks",
        help="entry URL imported into the batch",
    )
    parser.add_argument("--market", default="US", help="batch market hint")
    parser.add_argument("--language", default="en-US", help="batch language hint")
    parser.add_argument("--batch-name", default="Build agent smoke", help="batch name")
    parser.add_argument("--max-products", type=int, default=3, help="build and task product budget")
    parser.add_argument("--build-seconds", type=int, default=900, help="agent wall-clock budget")
    parser.add_argument(
        "--validation-seconds",
        type=int,
        default=180,
        help="host validation task budget",
    )
    parser.add_argument("--task-seconds", type=int, default=180, help="task wall-clock budget")
    parser.add_argument("--build-timeout", type=int, default=1200, help="polling timeout for the build")
    parser.add_argument(
        "--model-provider",
        default=os.environ.get("ECOM_BUILD_MODEL_PROVIDER", "opencode-go"),
        help="model providerID (empty disables the explicit model)",
    )
    parser.add_argument(
        "--model-id",
        default=os.environ.get("ECOM_BUILD_MODEL_ID", "deepseek-v4.1-flash"),
        help="model id",
    )
    parser.add_argument(
        "--model-variant",
        default=os.environ.get("ECOM_BUILD_MODEL_VARIANT", "high"),
        help="model variant, if supported",
    )
    parser.add_argument(
        "--proxy",
        default=os.environ.get("ECOM_FETCH_PROXY"),
        help="HTTP(S)/socks5 egress proxy for the build and task fetches",
    )
    parser.add_argument(
        "--capture-reasoning",
        action="store_true",
        help="request reasoning capture for the build (requires service-side capture)",
    )
    parser.add_argument(
        "--include-reasoning",
        action="store_true",
        help="copy captured reasoning into the evidence directory (local review only)",
    )
    parser.add_argument("--work-root", type=Path, default=None, help="task/build output root")
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path("experiments/build-agent/real-model-latest"),
        help="where to copy the review evidence",
    )
    parser.add_argument("--keep-work", action="store_true", help="keep the full work root")
    args = parser.parse_args(argv)

    temporary = None
    if args.work_root is None:
        temporary = tempfile.TemporaryDirectory(prefix="ecom-build-agent-")
        work_root = Path(temporary.name)
    else:
        work_root = args.work_root.resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    rules_dir = work_root / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    out_root = work_root / "out"
    db_path = work_root / "tasks.db"

    model = None
    if args.model_provider and args.model_id:
        model = {"providerID": args.model_provider, "id": args.model_id}
        if args.model_variant:
            model["variant"] = args.model_variant

    manager = BuildManager(
        store=TaskStore(db_path),
        out_root=out_root,
        rules_dir=rules_dir,
        model=model,
        max_seconds=args.build_seconds,
        validation_seconds=args.validation_seconds,
        max_products=args.max_products,
        capture_reasoning=args.capture_reasoning,
    )
    app = create_app(
        db_path,
        out_root,
        rules_dir,
        manage_worker=True,
        max_tasks=1,
        max_browser_tasks=1,
        build_manager=manager,
        proxy=args.proxy,
    )

    try:
        with TestClient(app, headers=HEADERS) as client:
            health = client.get("/api/health")
            if health.status_code != 200:
                raise RuntimeError(f"health failed: {health.text[:500]}")
            created = client.post(
                "/api/batches",
                json={
                    "name": args.batch_name,
                    "market": args.market,
                    "language": args.language,
                    "sites_text": args.site_url,
                },
            )
            if created.status_code != 201:
                raise RuntimeError(f"batch create failed: {created.text[:1000]}")
            batch = created.json()["batch"]
            batch_id = batch["batch_id"]
            detail = client.get(f"/api/batches/{batch_id}").json()
            sites = detail.get("sites") or []
            if not sites:
                raise RuntimeError("batch import produced no sites")
            site = sites[0]
            print(
                f"[{_now()}] batch {batch_id}: site={site['site_key']} "
                f"readiness={site['readiness']}"
            )
            if site["readiness"] != "needs_onboarding":
                raise RuntimeError(
                    f"expected needs_onboarding, got {site['readiness']}: {site.get('note')}"
                )

            started = client.post(
                f"/api/batches/{batch_id}/sites/{site['site_key']}/build",
                json={
                    "max_products": args.max_products,
                    "max_seconds": args.build_seconds,
                    "proxy": args.proxy,
                    "capture_reasoning": args.capture_reasoning,
                },
            )
            if started.status_code != 202:
                raise RuntimeError(f"build start failed: {started.text[:1000]}")
            build_id = started.json()["build"]["build_id"]
            print(f"[{_now()}] build {build_id} accepted; model={model}")

            build = _wait_build(
                client,
                build_id,
                timeout=args.build_timeout,
            )
            detail = client.get(f"/api/batches/{batch_id}").json()
            site = next(
                item for item in detail["sites"] if item["site_key"] == site["site_key"]
            )
            print(
                f"[{_now()}] build finished: state={build['state']} "
                f"outcome={build['outcome']} site_readiness={site['readiness']}"
            )
            if build["state"] != "FINISHED" or build["outcome"] != "succeeded":
                _copy_evidence(
                    args.evidence_dir,
                    batch=detail,
                    build=build,
                    task=None,
                    rules_dir=rules_dir,
                    out_root=out_root,
                    export_zip=None,
                    site_url=args.site_url,
                    include_reasoning=args.include_reasoning,
                )
                print(f"evidence: {args.evidence_dir}")
                return 1

            started_task = client.post(
                f"/api/batches/{batch_id}/start",
                json={
                    "limits": {
                        "max_urls": max(10, args.max_products * 3),
                        "max_products": args.max_products,
                        "max_seconds": args.task_seconds,
                        "max_attempts": 2,
                    }
                },
            )
            if started_task.status_code != 202:
                raise RuntimeError(f"batch start failed: {started_task.text[:1000]}")
            accepted = started_task.json().get("accepted") or []
            if not accepted:
                raise RuntimeError(f"batch start accepted no site: {started_task.text[:1000]}")
            task_id = accepted[0]["task_id"]
            print(f"[{_now()}] task {task_id} accepted")

            task = _wait_task(client, task_id, timeout=args.task_seconds + 120)
            export = client.get(f"/api/tasks/{task_id}/export?partial=true")
            export_zip = export.content if export.status_code == 200 else None
            detail = client.get(f"/api/batches/{batch_id}").json()
            _copy_evidence(
                args.evidence_dir,
                batch=detail,
                build=build,
                task=task,
                rules_dir=rules_dir,
                out_root=out_root,
                export_zip=export_zip,
                site_url=args.site_url,
                include_reasoning=args.include_reasoning,
            )
            counts = task.get("counts") or {}
            print(
                f"[{_now()}] done: task={task_id} state={task['state']} "
                f"outcome={task['outcome']} valid={counts.get('valid_products', 0)} "
                f"failed={counts.get('failed_products', 0)}"
            )
            print(f"evidence: {args.evidence_dir}")
            return 0 if task["outcome"] in {"COMPLETED", "PARTIAL"} else 1
    finally:
        if temporary is not None and not args.keep_work:
            temporary.cleanup()
        elif args.work_root is not None:
            print(f"work root: {work_root}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130) from None
