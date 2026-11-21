"""Parallel task worker with cross-process task leases."""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scrapling.fetchers import FetcherSession

from .atomic import write_json
from .browser import BrowserConfig, BrowserFetcher
from .fetcher import DomainLimiter, HybridFetcher, ScraplingFetcher, normalize_engine
from .models import Lease, Task, utc_now
from .resources import cleanup_task_resources
from .rule import RulePackage, load_rule
from .runner import TaskRunner
from .store import LeaseLostError, TaskStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetcherContext:
    """Everything an engine needs to fetch for one leased task."""

    rule: RulePackage
    limiter: DomainLimiter
    store: TaskStore
    task: Task
    lease: Lease
    out_root: Path


FetcherFactory = Callable[[FetcherContext], Any]


def engine_plan(rule: RulePackage) -> tuple[str, dict[str, str]]:
    """Return the default engine and per-item-type overrides."""
    fetch = rule.fetch
    default = normalize_engine(str(fetch.get("default_engine", "static")))
    overrides: dict[str, str] = {}
    per_type = fetch.get("per_url_type", {})
    if isinstance(per_type, dict):
        for item_type, value in per_type.items():
            if isinstance(value, dict) and value.get("engine"):
                overrides[str(item_type)] = normalize_engine(str(value["engine"]))
    return default, overrides


def _retry_values(rule: RulePackage) -> tuple[int, int]:
    retry = rule.fetch.get("retry", {})
    return (
        max(1, int(retry.get("max_attempts", 2))),
        max(0, int(retry.get("backoff_ms", 1000))),
    )


def _make_static(context: FetcherContext) -> ScraplingFetcher:
    fetch = context.rule.fetch
    manager = FetcherSession(
        impersonate="chrome",
        timeout=float(fetch.get("timeout_ms", 45000)) / 1000,
        retries=1,
    )
    session = manager.__enter__()
    max_attempts, backoff_ms = _retry_values(context.rule)
    return ScraplingFetcher(
        session,
        limiter=context.limiter,
        timeout_ms=int(fetch.get("timeout_ms", 45000)),
        max_attempts=max_attempts,
        backoff_ms=backoff_ms,
        session_manager=manager,
    )


def _make_browser(context: FetcherContext) -> BrowserFetcher:
    max_attempts, backoff_ms = _retry_values(context.rule)
    return BrowserFetcher(
        context.store,
        task_id=context.task.task_id,
        out_root=context.out_root,
        config=BrowserConfig.from_fetch(context.rule.fetch),
        limiter=context.limiter,
        lease_token=context.lease.token,
        max_attempts=max_attempts,
        backoff_ms=backoff_ms,
    )


@contextmanager
def default_fetcher(context: FetcherContext) -> Iterator[Any]:
    default, overrides = engine_plan(context.rule)
    engines = {default, *overrides.values()}
    if engines == {"static"}:
        fetcher = _make_static(context)
        try:
            yield fetcher
        finally:
            fetcher.close()
        return
    if engines == {"browser"}:
        fetcher = _make_browser(context)
        try:
            yield fetcher
        finally:
            fetcher.close()
        return
    builders: dict[str, Callable[[], Any]] = {
        "static": lambda: _make_static(context),
        "browser": lambda: _make_browser(context),
    }
    hybrid = HybridFetcher(
        default_engine=default,
        overrides=overrides,
        builders=builders,
    )
    try:
        yield hybrid
    finally:
        hybrid.close()


class Worker:
    def __init__(
        self,
        store: TaskStore,
        *,
        out_root: str | Path,
        max_tasks: int = 2,
        max_browser_tasks: int = 1,
        per_domain_rps: float = 1.0,
        fetcher_factory: FetcherFactory = default_fetcher,
        lease_ttl_seconds: float = 30.0,
        heartbeat_interval: float | None = None,
        owner: str | None = None,
    ) -> None:
        self.store = store
        self.out_root = Path(out_root)
        self.max_tasks = max(1, max_tasks)
        self.max_browser_tasks = max(0, max_browser_tasks)
        self._browser_semaphore = (
            threading.BoundedSemaphore(self.max_browser_tasks)
            if self.max_browser_tasks > 0
            else None
        )
        self.limiter = DomainLimiter(per_domain_rps)
        self.fetcher_factory = fetcher_factory
        self.lease_ttl_seconds = max(float(lease_ttl_seconds), 0.5)
        if heartbeat_interval is None:
            heartbeat_interval = min(5.0, self.lease_ttl_seconds / 3)
        self.heartbeat_interval = max(
            0.1, min(float(heartbeat_interval), self.lease_ttl_seconds / 2)
        )
        self.owner = owner or (
            f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        )
        self._leases: dict[str, Lease] = {}
        self._lease_lock = threading.Lock()
        self._browser_slots: dict[str, str] = {}
        self._browser_slot_lock = threading.Lock()
        self.browser_slot_ttl_seconds = max(30.0, self.lease_ttl_seconds * 2)
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._next_settle = 0.0

    @property
    def active_leases(self) -> dict[str, Lease]:
        with self._lease_lock:
            return dict(self._leases)

    def run_once(self, poll_interval: float = 0.2) -> int:
        """Process queued tasks and return when the queue is empty."""
        self._start_heartbeat()
        try:
            return self._run_loop(poll_interval, exit_when_idle=True)
        finally:
            self._stop_heartbeat()

    def run_forever(
        self,
        *,
        stop_event: threading.Event | None = None,
        poll_interval: float = 0.5,
    ) -> int:
        """Keep processing queued tasks until ``stop_event`` is set.

        A stopped worker stops claiming new tasks and joins the tasks already
        running.  Use the cancel command for a task that should end early.
        """
        self._start_heartbeat()
        try:
            return self._run_loop(
                poll_interval,
                exit_when_idle=False,
                stop_event=stop_event,
            )
        finally:
            self._stop_heartbeat()

    def _start_heartbeat(self) -> None:
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="lease-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        thread = self._heartbeat_thread
        if thread is not None:
            thread.join(timeout=max(1.0, self.heartbeat_interval + 1.0))
        self._heartbeat_thread = None

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.wait(self.heartbeat_interval):
            leases = self.active_leases
            for lease in leases.values():
                try:
                    renewed = self.store.renew_lease(
                        lease, self.lease_ttl_seconds
                    )
                except Exception:
                    logger.exception(
                        "lease renewal failed for task %s", lease.task_id
                    )
                    renewed = False
                if renewed:
                    continue
                task = self.store.get_task(lease.task_id)
                with self._lease_lock:
                    self._leases.pop(lease.task_id, None)
                if task is not None and task.state in {
                    "FINISHED",
                    "CANCELLED",
                    "PAUSED",
                }:
                    continue
                logger.warning("lease lost for task %s", lease.task_id)
            with self._browser_slot_lock:
                browser_slots = list(self._browser_slots.items())
            for task_id, resource_id in browser_slots:
                if not self.store.renew_browser_slot(
                    task_id,
                    resource_id,
                    ttl_seconds=self.browser_slot_ttl_seconds,
                ):
                    logger.warning(
                        "browser slot lost for task %s (%s)", task_id, resource_id
                    )

    def _register_lease(self, lease: Lease) -> None:
        with self._lease_lock:
            self._leases[lease.task_id] = lease

    def _forget_lease(self, task_id: str) -> None:
        with self._lease_lock:
            self._leases.pop(task_id, None)

    def _release_lease(self, lease: Lease) -> None:
        self._forget_lease(lease.task_id)
        try:
            self.store.release_lease(lease)
        except Exception:
            logger.exception("could not release lease for %s", lease.task_id)

    def _maybe_settle(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now < self._next_settle:
            return
        self._next_settle = now + max(0.5, self.lease_ttl_seconds / 2)
        report = self.store.settle_expired_tasks()
        if not report["recovered"]:
            return
        logger.warning("settled expired tasks: %s", report)
        tokens = report.get("task_tokens", {})
        for task_id in report.get("task_ids", []):
            self._forget_lease(task_id)
            try:
                cleanup_task_resources(
                    self.store,
                    task_id,
                    lease_token=tokens.get(task_id),
                )
            except Exception:
                logger.exception("resource cleanup failed for task %s", task_id)

    def _run_loop(
        self,
        poll_interval: float,
        *,
        exit_when_idle: bool,
        stop_event: threading.Event | None = None,
    ) -> int:
        self.out_root.mkdir(parents=True, exist_ok=True)
        running: dict[str, threading.Thread] = {}
        started = 0
        self._maybe_settle(force=True)
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            self._maybe_settle()
            capacity = self.max_tasks - len(running)
            if capacity > 0:
                for task, lease in self.store.claim_tasks(
                    self.owner,
                    capacity,
                    self.lease_ttl_seconds,
                ):
                    self._register_lease(lease)
                    thread = threading.Thread(
                        target=self._run_task,
                        args=(task, lease),
                        name=f"task-{task.task_id}",
                        daemon=False,
                    )
                    running[task.task_id] = thread
                    thread.start()
                    started += 1

            for task_id, thread in list(running.items()):
                if not thread.is_alive():
                    thread.join()
                    running.pop(task_id, None)

            if exit_when_idle and not running:
                self._maybe_settle(force=True)
                if not self.store.list_tasks({"QUEUED"}):
                    return started
            if stop_event is not None and stop_event.is_set():
                break
            time.sleep(poll_interval)

        for thread in running.values():
            thread.join()
        return started

    @staticmethod
    def _needs_browser(rule: RulePackage) -> bool:
        if rule.kind == "hybrid":
            return True
        fetch = rule.fetch
        if fetch.get("default_engine") == "browser":
            return True
        per_type = fetch.get("per_url_type")
        if isinstance(per_type, dict):
            for settings in per_type.values():
                if isinstance(settings, dict) and settings.get("engine") == "browser":
                    return True
        return False

    def _acquire_browser_slot(self, task_id: str, lease: Lease) -> str | None:
        if self.max_browser_tasks <= 0:
            return None
        while True:
            resource_id = self.store.claim_browser_slot(
                task_id=task_id,
                lease_token=lease.token,
                limit=self.max_browser_tasks,
                ttl_seconds=self.browser_slot_ttl_seconds,
            )
            if resource_id is not None:
                with self._browser_slot_lock:
                    self._browser_slots[task_id] = resource_id
                return resource_id
            time.sleep(0.2)

    def _release_browser_slot(self, task_id: str) -> None:
        with self._browser_slot_lock:
            resource_id = self._browser_slots.pop(task_id, None)
        if resource_id is not None:
            self.store.release_browser_slot(task_id, resource_id)

    def _run_task(self, task: Task, lease: Lease) -> None:
        browser_slot = False
        try:
            rule_path = task.input.get("rule_path")
            if not rule_path:
                self._fail(task, lease, "PLAN_ERROR", "task input has no rule_path")
                return
            try:
                rule = load_rule(rule_path)
                rule.validate_task_type(task.task_type)
            except Exception as exc:  # noqa: BLE001 - task boundary
                self._fail(task, lease, "PLAN_ERROR", f"{type(exc).__name__}: {exc}")
                return
            if rule.rule_id != task.plan_id or rule.rule_version != task.plan_version:
                self._fail(
                    task,
                    lease,
                    "PLAN_ERROR",
                    "plan version mismatch: "
                    f"task={task.plan_id}@{task.plan_version} "
                    f"rule={rule.rule_id}@{rule.rule_version}",
                )
                return
            if self._browser_semaphore is not None and self._needs_browser(rule):
                self._browser_semaphore.acquire()
                browser_slot = True
                self._acquire_browser_slot(task.task_id, lease)
            try:
                context = FetcherContext(
                    rule=rule,
                    limiter=self.limiter,
                    store=self.store,
                    task=task,
                    lease=lease,
                    out_root=self.out_root,
                )
                with self.fetcher_factory(context) as fetcher:
                    runner = TaskRunner(
                        self.store,
                        rule,
                        task,
                        fetcher=fetcher,
                        out_root=self.out_root,
                        lease=lease,
                    )
                    runner.run()
            except LeaseLostError:
                logger.warning(
                    "task %s lost its lease; abandoning stale writes",
                    task.task_id,
                )
            except Exception as exc:  # noqa: BLE001 - task boundary
                self._fail(task, lease, "ENVIRONMENT_ERROR", f"{type(exc).__name__}: {exc}")
        finally:
            if browser_slot:
                self._release_browser_slot(task.task_id)
                if self._browser_semaphore is not None:
                    self._browser_semaphore.release()
            self._release_lease(lease)
            try:
                cleanup_task_resources(
                    self.store,
                    task.task_id,
                    lease_token=lease.token,
                )
            except Exception:
                logger.exception(
                    "resource cleanup failed for task %s", task.task_id
                )

    def _fail(
        self,
        task: Task,
        lease: Lease,
        reason: str,
        detail: str,
    ) -> None:
        try:
            self.store.assert_lease(lease)
        except LeaseLostError:
            logger.warning(
                "task %s lost its lease; skipping failure write", task.task_id
            )
            return
        task_dir = self.out_root / task.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "plan_id": task.plan_id,
            "plan_version": task.plan_version,
            "state": "FINISHED",
            "outcome": "FAILED",
            "stop_reason": reason,
            "stop_detail": detail,
            "failure_classes": {"transient": 0, "permanent": 0, "blocked": 0},
            "counts": {},
        }
        write_json(task_dir / "task-result.json", payload)
        try:
            self.store.update_task(
                task.task_id,
                lease=lease,
                state="FINISHED",
                outcome="FAILED",
                stop_reason=reason,
                finished_at=utc_now(),
            )
        except LeaseLostError:
            logger.warning(
                "task %s lost its lease while writing failure", task.task_id
            )
