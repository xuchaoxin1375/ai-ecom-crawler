"""Single-process execution entry for a declarative rule package.

This is the D04 v0 bridge: the ported R06 runtime performs discovery, static
fetch and extraction; the D02 pipeline owns the final CSV/task result.  The
first version is intentionally single-process and static-only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .bridge import convert_task_to_run_dir
from .model import ContractError, ExportResult
from .pipeline import export_run
from .runtime.models import Task
from .runtime.rule import load_rule
from .runtime.store import TaskStore
from .runtime.worker import Worker


@dataclass(frozen=True)
class ExecutionResult:
    task_id: str
    task_result: dict[str, Any]
    out_dir: Path
    app_export: ExportResult | None = None
    export_dir: Path | None = None


def _archive_input(
    *,
    mode: str | None,
    root: str | Path | None,
    sample_limit: int,
    max_bytes: int | None,
    reuse: bool,
    offline: bool,
) -> dict[str, Any] | None:
    if mode is None and not reuse and not offline:
        return None
    payload: dict[str, Any] = {
        "mode": mode or ("full" if offline else "off"),
        "sample_limit": max(1, int(sample_limit)),
        "reuse": bool(reuse),
        "offline": bool(offline),
    }
    if root is not None:
        payload["root"] = str(root)
    if max_bytes is not None:
        payload["max_bytes"] = max(0, int(max_bytes))
    return payload


def build_task(
    *,
    rule_path: Path,
    task_id: str,
    task_type: str,
    max_urls: int | None,
    max_products: int | None,
    max_seconds: int | None,
    max_attempts: int,
    proxy: str | None = None,
    archive_mode: str | None = None,
    archive_root: str | Path | None = None,
    archive_sample_limit: int = 20,
    archive_max_bytes: int | None = None,
    archive_reuse: bool = False,
    offline: bool = False,
) -> Task:
    rule_path = Path(rule_path).resolve()
    if not rule_path.is_file():
        raise ContractError(f"rule package not found: {rule_path}")
    rule = load_rule(rule_path)
    rule.validate_task_type(task_type)
    if task_type not in {"product", "discovery"}:
        raise ContractError(f"unsupported task_type: {task_type}")
    task_input = {"rule_path": str(rule_path)}
    if proxy:
        task_input["proxy"] = proxy
    archive = _archive_input(
        mode=archive_mode,
        root=archive_root,
        sample_limit=archive_sample_limit,
        max_bytes=archive_max_bytes,
        reuse=archive_reuse,
        offline=offline,
    )
    if archive is not None:
        task_input["archive"] = archive
    return Task(
        task_id=task_id,
        plan_id=rule.rule_id,
        plan_version=rule.rule_version,
        task_type=task_type,
        state="DRAFT",
        input=task_input,
        limits={
            "max_urls": max_urls,
            "max_products": max_products,
            "max_seconds": max_seconds,
            "max_attempts": max_attempts,
            "retry_backoff_ms": 1000,
            "concurrency": {"navigation": 1, "product": 1},
        },
        output={
            "url_list": True,
            "product_csv": task_type == "product",
        },
        site_key=str(rule.site.get("name") or urlparse(rule.entry_url).hostname or rule.rule_id),
        domain_key=urlparse(rule.entry_url).hostname or "",
        market=str(rule.site.get("market")) if rule.site.get("market") else None,
        rule_path=str(rule_path),
        rule_sha256=hashlib.sha256(rule_path.read_bytes()).hexdigest(),
    )


def submit_task(
    *,
    rule_path: Path,
    db_path: Path,
    task_id: str,
    task_type: str = "product",
    max_urls: int = 100,
    max_products: int = 20,
    max_seconds: int = 180,
    max_attempts: int = 2,
    proxy: str | None = None,
    archive_mode: str | None = None,
    archive_root: str | Path | None = None,
    archive_sample_limit: int = 20,
    archive_max_bytes: int | None = None,
    archive_reuse: bool = False,
    offline: bool = False,
) -> Task:
    """Create a QUEUED task without executing it."""
    task = build_task(
        rule_path=rule_path,
        task_id=task_id,
        task_type=task_type,
        max_urls=max_urls,
        max_products=max_products,
        max_seconds=max_seconds,
        max_attempts=max_attempts,
        proxy=proxy,
        archive_mode=archive_mode,
        archive_root=archive_root,
        archive_sample_limit=archive_sample_limit,
        archive_max_bytes=archive_max_bytes,
        archive_reuse=archive_reuse,
        offline=offline,
    )
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = TaskStore(db_path)
    if store.get_task(task_id) is not None:
        raise ContractError(f"task already exists: {task_id}")
    store.create_task(task)
    return store.request_start(task_id)


def run_task(
    *,
    rule_path: Path,
    db_path: Path,
    out_root: Path,
    task_id: str,
    task_type: str = "product",
    max_urls: int = 100,
    max_products: int = 20,
    max_seconds: int = 180,
    max_attempts: int = 2,
    per_domain_rps: float = 1.0,
    proxy: str | None = None,
    archive_mode: str | None = None,
    archive_root: str | Path | None = None,
    archive_sample_limit: int = 20,
    archive_max_bytes: int | None = None,
    archive_reuse: bool = False,
    offline: bool = False,
) -> tuple[dict[str, Any], Path]:
    """Create and run one task, returning its result and task directory."""
    task = build_task(
        rule_path=rule_path,
        task_id=task_id,
        task_type=task_type,
        max_urls=max_urls,
        max_products=max_products,
        max_seconds=max_seconds,
        max_attempts=max_attempts,
        proxy=proxy,
        archive_mode=archive_mode,
        archive_root=archive_root,
        archive_sample_limit=archive_sample_limit,
        archive_max_bytes=archive_max_bytes,
        archive_reuse=archive_reuse,
        offline=offline,
    )
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    store = TaskStore(db_path)
    if store.get_task(task_id) is not None:
        raise ContractError(f"task already exists: {task_id}")
    store.create_task(task)
    store.request_start(task_id)

    worker = Worker(
        store,
        out_root=out_root,
        max_tasks=1,
        per_domain_rps=per_domain_rps,
        proxy=proxy,
    )
    worker.run_once()
    task_dir = out_root / task_id
    result_path = task_dir / "task-result.json"
    if not result_path.is_file():
        stored = store.get_task(task_id)
        state = stored.state if stored is not None else "UNKNOWN"
        if state == "PAUSED":
            raise ContractError(
                f"task {task_id} is PAUSED; run 'worker' after 'resume' to continue"
            )
        raise ContractError(f"task {task_id} finished without task-result.json (state={state})")
    return json.loads(result_path.read_text(encoding="utf-8")), task_dir


def run_and_export(
    *,
    rule_path: Path,
    db_path: Path,
    out_root: Path,
    task_id: str,
    task_type: str = "product",
    max_urls: int = 100,
    max_products: int = 20,
    max_seconds: int = 180,
    max_attempts: int = 2,
    per_domain_rps: float = 1.0,
    export_dir: Path | None = None,
    partial_reason: str | None = None,
    proxy: str | None = None,
    archive_mode: str | None = None,
    archive_root: str | Path | None = None,
    archive_sample_limit: int = 20,
    archive_max_bytes: int | None = None,
    archive_reuse: bool = False,
    offline: bool = False,
) -> ExecutionResult:
    """Run one task and, for product tasks, export the D02 outputs."""
    task_result, task_dir = run_task(
        rule_path=rule_path,
        db_path=db_path,
        out_root=out_root,
        task_id=task_id,
        task_type=task_type,
        max_urls=max_urls,
        max_products=max_products,
        max_seconds=max_seconds,
        max_attempts=max_attempts,
        per_domain_rps=per_domain_rps,
        proxy=proxy,
        archive_mode=archive_mode,
        archive_root=archive_root,
        archive_sample_limit=archive_sample_limit,
        archive_max_bytes=archive_max_bytes,
        archive_reuse=archive_reuse,
        offline=offline,
    )
    if task_type != "product":
        return ExecutionResult(
            task_id=task_id,
            task_result=task_result,
            out_dir=task_dir,
        )
    if int(task_result.get("counts", {}).get("valid_products", 0)) == 0:
        return ExecutionResult(
            task_id=task_id,
            task_result=task_result,
            out_dir=task_dir,
        )

    app_run = task_dir / "app-run"
    convert_task_to_run_dir(
        task_dir / "task-result.json",
        task_dir / "products.jsonl",
        app_run,
        partial_reason=partial_reason,
    )
    target = Path(export_dir) if export_dir is not None else task_dir / "export"
    app_export = export_run(app_run, target, force=True)
    return ExecutionResult(
        task_id=task_id,
        task_result=task_result,
        out_dir=task_dir,
        app_export=app_export,
        export_dir=target,
    )
