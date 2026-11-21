"""Parallel task worker for the runtime prototype."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from scrapling.fetchers import FetcherSession

from .atomic import write_json
from .fetcher import DomainLimiter, ScraplingFetcher
from .models import Task
from .rule import RulePackage, load_rule
from .runner import TaskRunner
from .store import TaskStore

FetcherFactory = Callable[[RulePackage, DomainLimiter], Any]

logger = logging.getLogger(__name__)


@contextmanager
def default_fetcher(
    rule: RulePackage, limiter: DomainLimiter
) -> Iterator[ScraplingFetcher]:
    fetch = rule.fetch
    with FetcherSession(
        impersonate="chrome",
        timeout=float(fetch.get("timeout_ms", 45000)) / 1000,
        retries=1,
    ) as session:
        yield ScraplingFetcher(
            session,
            limiter=limiter,
            timeout_ms=int(fetch.get("timeout_ms", 45000)),
            max_attempts=int(fetch.get("retry", {}).get("max_attempts", 2)),
            backoff_ms=int(fetch.get("retry", {}).get("backoff_ms", 1000)),
        )


class Worker:
    def __init__(
        self,
        store: TaskStore,
        *,
        out_root: str | Path,
        max_tasks: int = 2,
        per_domain_rps: float = 1.0,
        fetcher_factory: FetcherFactory = default_fetcher,
    ) -> None:
        self.store = store
        self.out_root = Path(out_root)
        self.max_tasks = max(1, max_tasks)
        self.limiter = DomainLimiter(per_domain_rps)
        self.fetcher_factory = fetcher_factory
        self._recovered = False

    def run_once(self, poll_interval: float = 0.2) -> int:
        """Process queued tasks and return when the queue is empty."""
        self._recover_once()
        return self._run_loop(poll_interval, exit_when_idle=True)

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
        self._recover_once()
        return self._run_loop(
            poll_interval,
            exit_when_idle=False,
            stop_event=stop_event,
        )

    def _recover_once(self) -> None:
        if self._recovered:
            return
        recovery = self.store.recover_orphaned_tasks()
        if recovery["recovered"]:
            logger.warning("recovered orphaned tasks: %s", recovery)
        self._recovered = True

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
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            for task in self.store.list_tasks({"QUEUED"}):
                if len(running) >= self.max_tasks:
                    break
                if task.task_id in running:
                    continue
                thread = threading.Thread(
                    target=self._run_task,
                    args=(task,),
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

            if exit_when_idle and not running and not self.store.list_tasks({"QUEUED"}):
                return started
            if stop_event is not None and stop_event.is_set():
                break
            time.sleep(poll_interval)

        for thread in running.values():
            thread.join()
        return started

    def _run_task(self, task: Task) -> None:
        rule_path = task.input.get("rule_path")
        if not rule_path:
            self._fail(task, "PLAN_ERROR", "task input has no rule_path")
            return
        try:
            rule = load_rule(rule_path)
            rule.validate_task_type(task.task_type)
        except Exception as exc:  # noqa: BLE001 - task boundary
            self._fail(task, "PLAN_ERROR", f"{type(exc).__name__}: {exc}")
            return
        if rule.rule_id != task.plan_id or rule.rule_version != task.plan_version:
            self._fail(
                task,
                "PLAN_ERROR",
                "plan version mismatch: "
                f"task={task.plan_id}@{task.plan_version} "
                f"rule={rule.rule_id}@{rule.rule_version}",
            )
            return
        try:
            with self.fetcher_factory(rule, self.limiter) as fetcher:
                runner = TaskRunner(
                    self.store,
                    rule,
                    task,
                    fetcher=fetcher,
                    out_root=self.out_root,
                )
                runner.run()
        except Exception as exc:  # noqa: BLE001 - task boundary
            self._fail(task, "ENVIRONMENT_ERROR", f"{type(exc).__name__}: {exc}")

    def _fail(self, task: Task, reason: str, detail: str) -> None:
        from .models import utc_now

        self.store.update_task(
            task.task_id,
            state="FINISHED",
            outcome="FAILED",
            stop_reason=reason,
            finished_at=utc_now(),
        )
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
