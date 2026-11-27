"""SQLite task ledger for the R06 runtime prototype."""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import (
    Batch,
    BatchFolder,
    BatchSite,
    BuildContinuation,
    BuildRecord,
    Lease,
    QualityFeedback,
    RuleActivation,
    RuleVersion,
    SiteRule,
    Task,
    WorkbenchNode,
    WorkbenchRun,
    WorkbenchTaskDef,
    WorkItem,
    json_dumps,
    json_loads,
    utc_now,
)

BATCH_FOLDER_MAX_DEPTH = 4
_UNSET = object()

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    plan_version TEXT NOT NULL,
    task_type TEXT NOT NULL,
    state TEXT NOT NULL,
    outcome TEXT,
    stop_reason TEXT,
    site_key TEXT,
    domain_key TEXT,
    market TEXT,
    rule_path TEXT,
    rule_sha256 TEXT,
    archived_at TEXT,
    batch_id TEXT,
    lease_owner TEXT,
    lease_token INTEGER NOT NULL DEFAULT 0,
    lease_expires_at REAL,
    lease_heartbeat_at REAL,
    input_json TEXT NOT NULL,
    limits_json TEXT NOT NULL,
    output_json TEXT NOT NULL,
    counters_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS batch_folders (
    folder_id TEXT PRIMARY KEY,
    parent_id TEXT,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_batch_folders_parent
    ON batch_folders(parent_id, name);

CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT,
    market TEXT,
    language TEXT,
    category TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT,
    collection_mode TEXT,
    folder_id TEXT
);

CREATE TABLE IF NOT EXISTS batch_sites (
    batch_id TEXT NOT NULL,
    site_key TEXT NOT NULL,
    domain TEXT NOT NULL,
    input_value TEXT NOT NULL,
    readiness TEXT NOT NULL,
    rule_id TEXT,
    rule_version TEXT,
    rule_path TEXT,
    task_id TEXT,
    delivery_task_id TEXT,
    build_id TEXT,
    proxy TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (batch_id, site_key)
);

CREATE INDEX IF NOT EXISTS idx_batch_sites_task
    ON batch_sites(task_id);

CREATE TABLE IF NOT EXISTS workbench_nodes (
    node_id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL CHECK (node_type IN ('group', 'task')),
    parent_id TEXT,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workbench_nodes_parent
    ON workbench_nodes(parent_id, sort_order);

CREATE TABLE IF NOT EXISTS workbench_task_defs (
    node_id TEXT PRIMARY KEY,
    input_url TEXT NOT NULL,
    domain TEXT NOT NULL,
    site_key TEXT NOT NULL,
    batch_id TEXT,
    country TEXT,
    language TEXT,
    market TEXT,
    category TEXT,
    task_type TEXT NOT NULL DEFAULT 'product',
    collection_mode TEXT NOT NULL DEFAULT 'sample',
    rule_id TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    rule_path TEXT NOT NULL,
    limits_json TEXT NOT NULL DEFAULT '{}',
    proxy TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workbench_task_defs_batch
    ON workbench_task_defs(batch_id, site_key);

CREATE TABLE IF NOT EXISTS workbench_task_runs (
    node_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (node_id, task_id),
    UNIQUE (task_id)
);

CREATE INDEX IF NOT EXISTS idx_workbench_task_runs_node
    ON workbench_task_runs(node_id, created_at DESC);

CREATE TABLE IF NOT EXISTS workbench_recent_dismissals (
    task_id TEXT PRIMARY KEY,
    dismissed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS builds (
    build_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    site_key TEXT NOT NULL,
    state TEXT NOT NULL,
    outcome TEXT,
    workspace TEXT,
    session_id TEXT,
    model_json TEXT NOT NULL DEFAULT '{}',
    proxy TEXT,
    error TEXT,
    rule_id TEXT,
    rule_version TEXT,
    rule_path TEXT,
    mode TEXT NOT NULL DEFAULT 'build',
    feedback_id TEXT,
    request_id TEXT,
    request_json TEXT NOT NULL DEFAULT '{}',
    source_rule_version TEXT,
    source_rule_sha256 TEXT,
    target_rule_version TEXT,
    target_rule_sha256 TEXT,
    error_class TEXT,
    change_summary_json TEXT NOT NULL DEFAULT '{}',
    validation_json TEXT NOT NULL DEFAULT '{}',
    evidence_sha256 TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_builds_batch_site
    ON builds(batch_id, site_key, created_at);

CREATE TABLE IF NOT EXISTS build_continuations (
    request_id TEXT PRIMARY KEY,
    build_id TEXT NOT NULL,
    message_sha256 TEXT NOT NULL,
    message_chars INTEGER NOT NULL,
    state TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_build_continuations_build
    ON build_continuations(build_id, created_at);

CREATE TABLE IF NOT EXISTS quality_feedback (
    feedback_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    batch_id TEXT,
    site_key TEXT,
    rule_id TEXT,
    rule_version TEXT,
    rule_sha256 TEXT,
    category TEXT NOT NULL,
    samples_json TEXT NOT NULL DEFAULT '[]',
    expectation TEXT NOT NULL,
    note TEXT,
    scope TEXT NOT NULL DEFAULT 'Task-scoped review.',
    status TEXT NOT NULL,
    triage TEXT,
    triage_note TEXT,
    triage_source TEXT,
    duplicate_of TEXT,
    repair_build_id TEXT,
    rerun_task_id TEXT,
    resolution TEXT,
    resolution_note TEXT,
    created_by TEXT NOT NULL DEFAULT 'local-user',
    resolved_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT,
    request_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_quality_feedback_task
    ON quality_feedback(task_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_quality_feedback_site
    ON quality_feedback(site_key, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_quality_feedback_status
    ON quality_feedback(status, created_at DESC);

CREATE TABLE IF NOT EXISTS rule_versions (
    rule_id TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    parent_version TEXT,
    status TEXT NOT NULL,
    source_build_id TEXT,
    source_feedback_id TEXT,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    activated_by TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    notes TEXT,
    PRIMARY KEY (rule_id, rule_version)
);

CREATE INDEX IF NOT EXISTS idx_rule_versions_status
    ON rule_versions(rule_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_rule_versions_hash
    ON rule_versions(rule_id, sha256);

CREATE TABLE IF NOT EXISTS site_rules (
    site_key TEXT PRIMARY KEY,
    rule_id TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    path TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_site_rules_rule
    ON site_rules(rule_id, rule_version);

CREATE TABLE IF NOT EXISTS rule_activations (
    activation_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE,
    site_key TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    action TEXT NOT NULL,
    from_version TEXT,
    from_sha256 TEXT,
    to_version TEXT NOT NULL,
    to_sha256 TEXT NOT NULL,
    reason TEXT,
    actor TEXT NOT NULL DEFAULT 'local-user',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rule_activations_site
    ON rule_activations(site_key, created_at DESC);

CREATE TABLE IF NOT EXISTS task_items (
    task_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    item_type TEXT NOT NULL,
    url TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    stage TEXT NOT NULL,
    state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    failure_class TEXT,
    parent_url TEXT,
    discovered_from TEXT,
    result_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (task_id, item_id),
    UNIQUE (task_id, item_type, normalized_url)
);

CREATE INDEX IF NOT EXISTS idx_task_items_state
    ON task_items(task_id, item_type, state);

CREATE TABLE IF NOT EXISTS task_requests (
    request_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    request_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_resources (
    task_id TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    pid INTEGER,
    path TEXT,
    lease_token INTEGER,
    expires_at REAL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (task_id, resource_id)
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_resources_task
    ON task_resources(task_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_task_resources_browser_slot
    ON task_resources(resource_id) WHERE kind = 'browser_slot';
"""

TASK_COLUMNS = {
    "state",
    "outcome",
    "stop_reason",
    "input",
    "limits",
    "output",
    "counters",
    "started_at",
    "finished_at",
    "site_key",
    "domain_key",
    "market",
    "rule_path",
    "rule_sha256",
    "archived_at",
    "batch_id",
    "updated_at",
}


class TaskNotFoundError(ValueError):
    """Raised when a control command targets an unknown task."""


class TaskTransitionError(ValueError):
    """Raised when a control command is invalid for the task's current state."""


class RequestConflictError(ValueError):
    """Raised when an idempotency key is reused with a different request."""


class LeaseLostError(ValueError):
    """Raised when a worker tries to write after its task lease expired or moved."""


class BatchNotFoundError(ValueError):
    """Raised when a batch command targets an unknown batch."""


class BatchTransitionError(ValueError):
    """Raised when a batch command is invalid for the batch's current members."""


class BatchFolderError(ValueError):
    """Base error for invalid batch folder operations."""


class BatchFolderNotFoundError(BatchFolderError):
    """Raised when a folder operation targets an unknown folder."""


class BatchFolderNameError(BatchFolderError):
    """The folder name is empty, too long or contains invalid characters."""


class BatchFolderConflictError(BatchFolderError):
    """A sibling name conflict, cycle or depth limit blocks the operation."""


class FeedbackNotFoundError(ValueError):
    """Raised when a feedback command targets an unknown feedback record."""


class FeedbackTransitionError(ValueError):
    """Raised when a feedback action is invalid for its current status."""


class FeedbackRequestConflictError(ValueError):
    """Raised when a feedback request_id is reused with a different body."""


class BuildContinuationConflictError(ValueError):
    """Raised when a continuation request_id is reused with different content."""


class RuleVersionError(ValueError):
    """Raised when a rule version cannot be created, activated or rolled back."""

class RuleActivationConflictError(RuleVersionError):
    """Raised when a rule activation request conflicts with current state."""


class SiteRuleNotFoundError(ValueError):
    """Raised when a site has no rule pointer and no candidates."""


class RuleActivationNotFoundError(ValueError):
    """Raised when an activation audit record does not exist."""


class TaskStore:
    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = read_only
        if read_only:
            if not self.path.is_file():
                raise FileNotFoundError(
                    f"read-only task ledger does not exist: {self.path}"
                )
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self.read_only:
            # mode=ro refuses writes even if a handler forgets to check the
            # flag; query_only is a second guard on the same connection.
            connection = sqlite3.connect(
                f"{self.path.resolve().as_uri()}?mode=ro",
                uri=True,
                timeout=30,
                isolation_level=None,
            )
        else:
            connection = sqlite3.connect(
                self.path, timeout=30, isolation_level=None
            )
        connection.row_factory = sqlite3.Row
        if not self.read_only:
            connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        if self.read_only:
            connection.execute("PRAGMA query_only=ON")
        try:
            yield connection
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute("DROP INDEX IF EXISTS idx_rule_versions_one_active")
            task_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(tasks)")
            }
            if "plan_id" not in task_columns and "rule_id" in task_columns:
                connection.execute("ALTER TABLE tasks RENAME COLUMN rule_id TO plan_id")
                connection.execute(
                    "ALTER TABLE tasks RENAME COLUMN rule_version TO plan_version"
                )
            for column in (
                "site_key",
                "domain_key",
                "market",
                "rule_path",
                "rule_sha256",
                "archived_at",
                "batch_id",
            ):
                if column not in task_columns:
                    connection.execute(f"ALTER TABLE tasks ADD COLUMN {column} TEXT")
            batch_site_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(batch_sites)")
            }
            if "build_id" not in batch_site_columns:
                connection.execute("ALTER TABLE batch_sites ADD COLUMN build_id TEXT")
            if "proxy" not in batch_site_columns:
                connection.execute("ALTER TABLE batch_sites ADD COLUMN proxy TEXT")
            if "delivery_task_id" not in batch_site_columns:
                connection.execute("ALTER TABLE batch_sites ADD COLUMN delivery_task_id TEXT")
                connection.execute(
                    "UPDATE batch_sites SET delivery_task_id = task_id WHERE task_id IN "
                    "(SELECT t.task_id FROM tasks t WHERE t.state = 'FINISHED' AND t.outcome = 'COMPLETED' "
                    "AND NOT EXISTS (SELECT 1 FROM quality_feedback f WHERE f.rerun_task_id = t.task_id "
                    "AND f.status != 'RESOLVED'))"
                )
            batch_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(batches)")
            }
            if "collection_mode" not in batch_columns:
                connection.execute("ALTER TABLE batches ADD COLUMN collection_mode TEXT")
            if "folder_id" not in batch_columns:
                connection.execute("ALTER TABLE batches ADD COLUMN folder_id TEXT")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_batches_folder ON batches(folder_id)"
            )
            build_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(builds)")
            }
            if "proxy" not in build_columns:
                connection.execute("ALTER TABLE builds ADD COLUMN proxy TEXT")
            if "mode" not in build_columns:
                connection.execute(
                    "ALTER TABLE builds ADD COLUMN mode TEXT NOT NULL DEFAULT 'build'"
                )
            for column in (
                "feedback_id",
                "request_id",
                "source_rule_version",
                "source_rule_sha256",
                "target_rule_version",
                "target_rule_sha256",
                "error_class",
                "evidence_sha256",
            ):
                if column not in build_columns:
                    connection.execute(f"ALTER TABLE builds ADD COLUMN {column} TEXT")
            for column in ("request_json", "change_summary_json", "validation_json"):
                if column not in build_columns:
                    connection.execute(
                        f"ALTER TABLE builds ADD COLUMN {column} TEXT NOT NULL DEFAULT '{{}}'"
                    )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_builds_request "
                "ON builds(request_id) WHERE request_id IS NOT NULL"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_builds_feedback "
                "ON builds(feedback_id, created_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_rule_sha "
                "ON tasks(rule_sha256)"
            )
            if "lease_owner" not in task_columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN lease_owner TEXT")
            if "lease_token" not in task_columns:
                connection.execute(
                    "ALTER TABLE tasks ADD COLUMN lease_token INTEGER NOT NULL DEFAULT 0"
                )
            if "lease_expires_at" not in task_columns:
                connection.execute(
                    "ALTER TABLE tasks ADD COLUMN lease_expires_at REAL"
                )
            if "lease_heartbeat_at" not in task_columns:
                connection.execute(
                    "ALTER TABLE tasks ADD COLUMN lease_heartbeat_at REAL"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_lease "
                "ON tasks(state, lease_expires_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_batch ON tasks(batch_id)"
            )
            item_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(task_items)")
            }
            if "failure_class" not in item_columns:
                connection.execute(
                    "ALTER TABLE task_items ADD COLUMN failure_class TEXT"
                )
            resource_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(task_resources)")
            }
            if "lease_token" not in resource_columns:
                connection.execute(
                    "ALTER TABLE task_resources ADD COLUMN lease_token INTEGER"
                )
            if "expires_at" not in resource_columns:
                connection.execute(
                    "ALTER TABLE task_resources ADD COLUMN expires_at REAL"
                )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_task_resources_browser_slot "
                "ON task_resources(resource_id) WHERE kind = 'browser_slot'"
            )

    def _insert_task(self, connection: sqlite3.Connection, task: Task) -> None:
        connection.execute(
            """
            INSERT INTO tasks (
                task_id, plan_id, plan_version, task_type, state, outcome,
                stop_reason, site_key, domain_key, market, rule_path, rule_sha256,
                archived_at, batch_id, input_json, limits_json, output_json,
                counters_json, created_at, updated_at, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.task_id,
                task.plan_id,
                task.plan_version,
                task.task_type,
                task.state,
                task.outcome,
                task.stop_reason,
                task.site_key,
                task.domain_key,
                task.market,
                task.rule_path,
                task.rule_sha256,
                task.archived_at,
                task.batch_id,
                json_dumps(task.input),
                json_dumps(task.limits),
                json_dumps(task.output),
                json_dumps(task.counters),
                task.created_at,
                task.updated_at,
                task.started_at,
                task.finished_at,
            ),
        )

    def create_task(self, task: Task) -> None:
        with self._connect() as connection:
            try:
                self._insert_task(connection, task)
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"task already exists: {task.task_id}") from exc

    def create_task_idempotent(
        self,
        task: Task,
        request_id: str,
        request_json: str,
        *,
        feedback_id: str | None = None,
    ) -> tuple[Task, bool]:
        """Insert a task once per request id; return (task, created)."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT task_id, request_json FROM task_requests WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                if row is not None:
                    if str(row["request_json"]) != request_json:
                        raise RequestConflictError(
                            f"request_id {request_id} was used with a different request"
                        )
                    task_id = str(row["task_id"])
                    connection.commit()
                    existing = self.get_task(task_id)
                    if existing is None:
                        raise TaskNotFoundError(f"unknown task: {task_id}")
                    return existing, False
                self._insert_task(connection, task)
                if feedback_id is not None:
                    updated = connection.execute(
                        "UPDATE quality_feedback SET status = 'RERUN_PENDING', rerun_task_id = ?, "
                        "updated_at = ? WHERE feedback_id = ? AND status = 'AWAITING_RERUN'",
                        (task.task_id, utc_now(), feedback_id),
                    )
                    if updated.rowcount != 1:
                        raise FeedbackTransitionError("feedback no longer awaits a rerun")
                    linked = connection.execute(
                        "UPDATE batch_sites SET delivery_task_id = COALESCE(delivery_task_id, "
                        "(SELECT t.task_id FROM tasks t WHERE t.task_id = batch_sites.task_id "
                        "AND t.state = 'FINISHED' AND t.outcome = 'COMPLETED' "
                        "AND NOT EXISTS (SELECT 1 FROM quality_feedback f WHERE f.rerun_task_id = t.task_id))), "
                        "task_id = ?, updated_at = ? "
                        "WHERE batch_id = ? AND site_key = ? "
                        "AND EXISTS (SELECT 1 FROM batches WHERE batch_id = ? AND archived_at IS NULL) "
                        "AND (task_id IS NULL OR task_id IN "
                        "(SELECT task_id FROM tasks WHERE state IN ('FINISHED', 'CANCELLED')))",
                        (task.task_id, utc_now(), task.batch_id, task.site_key, task.batch_id),
                    )
                    if linked.rowcount != 1:
                        raise FeedbackTransitionError("batch target is unavailable or busy")
                connection.execute(
                    """
                    INSERT INTO task_requests (request_id, task_id, request_json, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (request_id, task.task_id, request_json, utc_now()),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise ValueError(f"task already exists: {task.task_id}") from exc
            except Exception:
                connection.rollback()
                raise
        return task, True

    def get_task_request(self, request_id: str, request_json: str) -> Task | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT task_id, request_json FROM task_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        if row is None:
            return None
        if row["request_json"] != request_json:
            raise RequestConflictError(f"request_id {request_id} was used with a different request")
        return self.get_task(row["task_id"])

    def get_task(self, task_id: str) -> Task | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        return _task_from_row(row) if row else None

    def list_tasks(self, states: set[str] | None = None) -> list[Task]:
        query = "SELECT * FROM tasks"
        params: list[Any] = []
        if states:
            placeholders = ", ".join("?" for _ in states)
            query += f" WHERE state IN ({placeholders})"
            params.extend(sorted(states))
        query += " ORDER BY created_at DESC, task_id DESC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_task_from_row(row) for row in rows]

    def update_task(
        self,
        task_id: str,
        *,
        lease: Lease | None = None,
        delivery: Task | None = None,
        **fields: Any,
    ) -> None:
        unknown = set(fields) - TASK_COLUMNS
        if unknown:
            raise ValueError(f"unknown task fields: {sorted(unknown)}")
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            column = key
            if key in {"input", "limits", "output", "counters"}:
                column = f"{key}_json"
                value = json_dumps(value)
            assignments.append(f"{column} = ?")
            values.append(value)
        if "updated_at" not in fields:
            assignments.append("updated_at = ?")
            values.append(utc_now())
        values.append(task_id)
        statement = f"UPDATE tasks SET {', '.join(assignments)} WHERE task_id = ?"
        if lease is None:
            with self._connect() as connection:
                connection.execute(statement, values)
            return
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                _require_lease(connection, lease)
                connection.execute(statement, values)
                if delivery is not None and delivery.batch_id and delivery.site_key:
                    connection.execute(
                        "UPDATE batch_sites SET delivery_task_id = ?, updated_at = ? "
                        "WHERE batch_id = ? AND site_key = ? AND task_id = ? "
                        "AND NOT EXISTS (SELECT 1 FROM quality_feedback WHERE rerun_task_id = ?) "
                        "AND (? = 1 OR delivery_task_id IS NULL)",
                        (task_id, utc_now(), delivery.batch_id, delivery.site_key, task_id,
                         task_id, int(delivery.input.get("collection_mode") != "sample")),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def claim_tasks(
        self,
        owner: str,
        limit: int,
        ttl_seconds: float,
    ) -> list[tuple[Task, Lease]]:
        """Atomically claim up to ``limit`` queued tasks for one worker.

        Call :meth:`settle_expired_tasks` first so abandoned ``RUNNING`` tasks
        are back in ``QUEUED``.  Each claim increments the task's fencing
        token, which invalidates every older lease.
        """
        if limit < 1:
            return []
        now = time.time()
        claimed_at = utc_now()
        expires_at = now + max(float(ttl_seconds), 0.1)
        claimed: list[tuple[Task, Lease]] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = connection.execute(
                    """
                    SELECT * FROM tasks
                    WHERE archived_at IS NULL
                      AND state = 'QUEUED'
                      AND (
                          lease_owner IS NULL
                          OR lease_expires_at IS NULL
                          OR lease_expires_at <= ?
                      )
                    ORDER BY created_at, task_id
                    LIMIT ?
                    """,
                    (now, limit),
                ).fetchall()
                for row in rows:
                    token = int(row["lease_token"] or 0) + 1
                    cursor = connection.execute(
                        """
                        UPDATE tasks
                        SET state = 'RUNNING',
                            lease_owner = ?,
                            lease_token = ?,
                            lease_expires_at = ?,
                            lease_heartbeat_at = ?,
                            started_at = COALESCE(started_at, ?),
                            updated_at = ?
                        WHERE task_id = ?
                          AND state = 'QUEUED'
                          AND (
                              lease_owner IS NULL
                              OR lease_expires_at IS NULL
                              OR lease_expires_at <= ?
                          )
                        """,
                        (
                            owner,
                            token,
                            expires_at,
                            now,
                            claimed_at,
                            claimed_at,
                            row["task_id"],
                            now,
                        ),
                    )
                    if cursor.rowcount != 1:
                        continue
                    fresh = connection.execute(
                        "SELECT * FROM tasks WHERE task_id = ?",
                        (row["task_id"],),
                    ).fetchone()
                    if fresh is None:
                        continue
                    claimed.append(
                        (
                            _task_from_row(fresh),
                            Lease(
                                task_id=str(row["task_id"]),
                                owner=owner,
                                token=token,
                                expires_at=expires_at,
                            ),
                        )
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return claimed

    def check_lease(self, lease: Lease) -> bool:
        with self._connect() as connection:
            return _lease_valid(connection, lease)

    def assert_lease(self, lease: Lease) -> None:
        if not self.check_lease(lease):
            raise LeaseLostError(
                f"lease for task {lease.task_id} is no longer owned by {lease.owner}"
            )

    def renew_lease(self, lease: Lease, ttl_seconds: float) -> bool:
        """Extend a lease; return False when the worker no longer owns it."""
        now = time.time()
        expires_at = now + max(float(ttl_seconds), 0.1)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET lease_expires_at = ?,
                    lease_heartbeat_at = ?
                WHERE task_id = ?
                  AND lease_owner = ?
                  AND lease_token = ?
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at > ?
                  AND state IN ('RUNNING', 'PAUSING', 'CANCELLING')
                """,
                (
                    expires_at,
                    now,
                    lease.task_id,
                    lease.owner,
                    lease.token,
                    now,
                ),
            )
            return cursor.rowcount == 1

    def release_lease(self, lease: Lease) -> None:
        """Release a lease without resetting the task's fencing token."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET lease_owner = NULL,
                    lease_expires_at = NULL,
                    lease_heartbeat_at = NULL,
                    updated_at = ?
                WHERE task_id = ?
                  AND lease_owner = ?
                  AND lease_token = ?
                """,
                (utc_now(), lease.task_id, lease.owner, lease.token),
            )

    def lease_info(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT lease_owner, lease_token, lease_expires_at, lease_heartbeat_at
                FROM tasks WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "owner": row["lease_owner"],
            "token": int(row["lease_token"] or 0),
            "expires_at": row["lease_expires_at"],
            "heartbeat_at": row["lease_heartbeat_at"],
        }

    def request_start(self, task_id: str) -> Task:
        """Move a DRAFT task to QUEUED; repeated starts are idempotent."""
        return self._transition(
            task_id,
            action="start",
            allowed={"DRAFT"},
            idempotent={"QUEUED", "RUNNING", "CANCELLED", "FINISHED"},
            target="QUEUED",
        )

    def request_pause(self, task_id: str) -> Task:
        """Request a pause.

        A queued task has no in-flight items and pauses directly.  A running
        task first moves to PAUSING and settles to PAUSED after the runner
        drains in-flight work.
        """
        return self._transition(
            task_id,
            action="pause",
            allowed={"QUEUED", "RUNNING"},
            idempotent={"PAUSING", "PAUSED"},
            target={"QUEUED": "PAUSED", "RUNNING": "PAUSING"},
        )

    def request_resume(self, task_id: str) -> Task:
        """Requeue a PAUSED task; a running or queued task is returned as-is."""
        return self._transition(
            task_id,
            action="resume",
            allowed={"PAUSED"},
            idempotent={"QUEUED", "RUNNING"},
            target="QUEUED",
        )

    def continue_task(
        self,
        task_id: str,
        *,
        limits: dict[str, Any],
        input: dict[str, Any],
        reset_navigation: bool,
    ) -> Task:
        """Requeue a budget-exhausted task in place, keeping accepted work.

        Only ``FINISHED``, unarchived tasks can continue.  The caller has
        already decided whether pending work or a discovery truncation makes a
        continuation meaningful; this method additionally requires pending
        work unless navigation items are reset.
        """
        now = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
                ).fetchone()
                if row is None:
                    raise TaskNotFoundError(f"unknown task: {task_id}")
                if row["archived_at"] is not None:
                    raise TaskTransitionError(
                        f"cannot continue archived task {task_id}"
                    )
                if row["state"] != "FINISHED":
                    raise TaskTransitionError(
                        f"cannot continue task {task_id} in state {row['state']}"
                    )
                pending = connection.execute(
                    "SELECT COUNT(*) AS count FROM task_items "
                    "WHERE task_id = ? AND state IN ('PENDING', 'IN_FLIGHT')",
                    (task_id,),
                ).fetchone()
                if int(pending["count"]) == 0 and not reset_navigation:
                    raise TaskTransitionError(
                        f"task {task_id} has no pending work to continue"
                    )
                counters = json_loads(row["counters_json"], {}) or {}
                if not isinstance(counters, dict):
                    counters = {}
                counters.pop("discovery_limit", None)
                counters["run_seconds"] = 0
                counters["continued_at"] = now
                connection.execute(
                    """
                    UPDATE tasks
                    SET state = 'QUEUED', outcome = NULL, stop_reason = NULL,
                        finished_at = NULL, limits_json = ?, input_json = ?,
                        counters_json = ?, lease_owner = NULL,
                        lease_expires_at = NULL, lease_heartbeat_at = NULL,
                        updated_at = ?
                    WHERE task_id = ?
                    """,
                    (
                        json_dumps(limits),
                        json_dumps(input),
                        json_dumps(counters),
                        now,
                        task_id,
                    ),
                )
                if reset_navigation:
                    connection.execute(
                        """
                        UPDATE task_items
                        SET state = 'PENDING', attempts = 0,
                            failure_class = NULL, updated_at = ?
                        WHERE task_id = ? AND item_type = 'navigation'
                        """,
                        (now, task_id),
                    )
                connection.execute(
                    "DELETE FROM workbench_recent_dismissals WHERE task_id = ?",
                    (task_id,),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        task = self.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(f"unknown task: {task_id}")
        return task

    def request_cancel(self, task_id: str) -> Task:
        """Cancel a task; running work first moves to CANCELLING."""
        return self._transition(
            task_id,
            action="cancel",
            allowed={"DRAFT", "QUEUED", "RUNNING", "PAUSING", "PAUSED"},
            idempotent={"CANCELLING", "CANCELLED"},
            target={"RUNNING": "CANCELLING", "PAUSING": "CANCELLING"},
            default_target="CANCELLED",
            finalize_cancel=True,
        )

    def request_archive(self, task_id: str) -> Task:
        """Hide a terminal task in the recycle area; only visibility changes."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT state, archived_at FROM tasks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                if row is None:
                    raise TaskNotFoundError(f"unknown task: {task_id}")
                if row["archived_at"] is None:
                    if row["state"] not in {"FINISHED", "CANCELLED"}:
                        raise TaskTransitionError(
                            f"cannot archive task {task_id} in state {row['state']}"
                        )
                    connection.execute(
                        "UPDATE tasks SET archived_at = ?, updated_at = ? WHERE task_id = ?",
                        (utc_now(), utc_now(), task_id),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        task = self.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(f"unknown task: {task_id}")
        return task

    def request_restore(self, task_id: str) -> Task:
        """Restore an archived task to the normal list; no re-collection."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT archived_at FROM tasks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                if row is None:
                    raise TaskNotFoundError(f"unknown task: {task_id}")
                if row["archived_at"] is not None:
                    connection.execute(
                        "UPDATE tasks SET archived_at = NULL, updated_at = ? WHERE task_id = ?",
                        (utc_now(), task_id),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        task = self.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(f"unknown task: {task_id}")
        return task

    def _transition(
        self,
        task_id: str,
        *,
        action: str,
        allowed: set[str],
        idempotent: set[str],
        target: str | dict[str, str],
        default_target: str | None = None,
        finalize_cancel: bool = False,
    ) -> Task:
        now = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT state FROM tasks WHERE task_id = ?", (task_id,)
                ).fetchone()
                if row is None:
                    raise TaskNotFoundError(f"unknown task: {task_id}")
                state = str(row["state"])
                if state in idempotent:
                    connection.commit()
                elif state not in allowed:
                    raise TaskTransitionError(
                        f"cannot {action} task {task_id} in state {state}"
                    )
                else:
                    next_state = (
                        target.get(state, default_target)
                        if isinstance(target, dict)
                        else target
                    )
                    if not next_state:
                        raise TaskTransitionError(
                            f"cannot {action} task {task_id} in state {state}"
                        )
                    fields: dict[str, Any] = {
                        "state": next_state,
                        "updated_at": now,
                    }
                    if finalize_cancel and next_state == "CANCELLED":
                        fields.update(
                            outcome="CANCELLED",
                            stop_reason="USER_CANCELLED",
                            finished_at=now,
                        )
                    assignments = ", ".join(f"{key} = ?" for key in fields)
                    connection.execute(
                        f"UPDATE tasks SET {assignments} WHERE task_id = ?",
                        [*fields.values(), task_id],
                    )
                    connection.commit()
            except Exception:
                connection.rollback()
                raise
        task = self.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(f"unknown task: {task_id}")
        return task

    def add_item(self, item: WorkItem, *, lease: Lease | None = None) -> bool:
        values = (
            item.task_id,
            item.item_id,
            item.item_type,
            item.url,
            item.normalized_url,
            item.stage,
            item.state,
            item.attempts,
            item.failure_class,
            item.parent_url,
            item.discovered_from,
            json_dumps(item.result),
            item.updated_at,
        )
        statement = """
            INSERT OR IGNORE INTO task_items (
                task_id, item_id, item_type, url, normalized_url, stage,
                state, attempts, failure_class, parent_url, discovered_from,
                result_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        if lease is None:
            with self._connect() as connection:
                cursor = connection.execute(statement, values)
                return cursor.rowcount == 1
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                _require_lease(connection, lease)
                cursor = connection.execute(statement, values)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return cursor.rowcount == 1

    def claim_items(
        self,
        task_id: str,
        limit: int,
        *,
        lease: Lease | None = None,
    ) -> list[WorkItem]:
        if limit < 1:
            return []
        claimed: list[WorkItem] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if lease is not None:
                    _require_lease(connection, lease)
                rows = connection.execute(
                    """
                    SELECT * FROM task_items
                    WHERE task_id = ? AND state = 'PENDING'
                    ORDER BY rowid
                    LIMIT ?
                    """,
                    (task_id, limit),
                ).fetchall()
                now = utc_now()
                for row in rows:
                    cursor = connection.execute(
                        """
                        UPDATE task_items
                        SET state = 'IN_FLIGHT', attempts = attempts + 1, updated_at = ?
                        WHERE task_id = ? AND item_id = ? AND state = 'PENDING'
                        """,
                        (now, task_id, row["item_id"]),
                    )
                    if cursor.rowcount == 1:
                        item = _item_from_row(row, state="IN_FLIGHT")
                        item.attempts = int(row["attempts"]) + 1
                        claimed.append(item)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return claimed

    def mark_item(
        self,
        task_id: str,
        item_id: str,
        state: str,
        result: dict[str, Any] | None = None,
        *,
        failure_class: str | None = None,
        lease: Lease | None = None,
    ) -> None:
        values = (
            state,
            failure_class,
            json_dumps(result or {}),
            utc_now(),
            task_id,
            item_id,
        )
        statement = """
            UPDATE task_items
            SET state = ?, failure_class = ?, result_json = ?, updated_at = ?
            WHERE task_id = ? AND item_id = ?
        """
        if lease is None:
            with self._connect() as connection:
                connection.execute(statement, values)
            return
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                _require_lease(connection, lease)
                connection.execute(statement, values)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def reconcile_task(
        self,
        task_id: str,
        max_attempts: int,
        *,
        lease: Lease | None = None,
    ) -> dict[str, int]:
        """Reset in-flight items after a crash; fail those out of attempts."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if lease is not None:
                    _require_lease(connection, lease)
                result = _reconcile_items(
                    connection, task_id, max_attempts, utc_now()
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return result

    def settle_expired_tasks(self) -> dict[str, Any]:
        """Settle tasks whose lease expired, leaving live leases untouched.

        ``RUNNING`` returns to ``QUEUED`` and resets in-flight items;
        ``PAUSING`` settles to ``PAUSED`` after the same reset; ``CANCELLING``
        becomes ``CANCELLED`` and rejects in-flight results.  This is the
        cross-process counterpart of the old single-worker startup recovery.
        """
        now = time.time()
        now_iso = utc_now()
        task_ids: list[str] = []
        task_tokens: dict[str, int] = {}
        requeued = 0
        paused = 0
        cancelled = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = connection.execute(
                    """
                    SELECT * FROM tasks
                    WHERE state IN ('RUNNING', 'PAUSING', 'CANCELLING')
                      AND (
                          lease_owner IS NULL
                          OR lease_expires_at IS NULL
                          OR lease_expires_at <= ?
                      )
                    """,
                    (now,),
                ).fetchall()
                for row in rows:
                    task_id = str(row["task_id"])
                    task_ids.append(task_id)
                    task_tokens[task_id] = int(row["lease_token"] or 0)
                    max_attempts = int(
                        json_loads(row["limits_json"], {}).get("max_attempts", 2)
                    )
                    if row["state"] == "RUNNING":
                        _reconcile_items(connection, task_id, max_attempts, now_iso)
                        connection.execute(
                            """
                            UPDATE tasks
                            SET state = 'QUEUED', outcome = NULL,
                                stop_reason = NULL, finished_at = NULL,
                                lease_owner = NULL, lease_expires_at = NULL,
                                lease_heartbeat_at = NULL, updated_at = ?
                            WHERE task_id = ?
                            """,
                            (now_iso, task_id),
                        )
                        requeued += 1
                    elif row["state"] == "PAUSING":
                        _reconcile_items(connection, task_id, max_attempts, now_iso)
                        connection.execute(
                            """
                            UPDATE tasks
                            SET state = 'PAUSED',
                                lease_owner = NULL, lease_expires_at = NULL,
                                lease_heartbeat_at = NULL, updated_at = ?
                            WHERE task_id = ?
                            """,
                            (now_iso, task_id),
                        )
                        paused += 1
                    else:
                        _reject_in_flight(connection, task_id, now_iso)
                        connection.execute(
                            """
                            UPDATE tasks
                            SET state = 'CANCELLED', outcome = 'CANCELLED',
                                stop_reason = 'USER_CANCELLED',
                                finished_at = ?, updated_at = ?,
                                lease_owner = NULL, lease_expires_at = NULL,
                                lease_heartbeat_at = NULL
                            WHERE task_id = ?
                            """,
                            (now_iso, now_iso, task_id),
                        )
                        cancelled += 1
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return {
            "recovered": len(task_ids),
            "requeued": requeued,
            "paused": paused,
            "cancelled": cancelled,
            "task_ids": task_ids,
            "task_tokens": task_tokens,
        }

    def recover_orphaned_tasks(self) -> dict[str, Any]:
        """Backward-compatible alias for :meth:`settle_expired_tasks`."""
        return self.settle_expired_tasks()

    def reset_in_flight(self, task_id: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE task_items
                SET state = 'PENDING', failure_class = NULL, updated_at = ?
                WHERE task_id = ? AND state = 'IN_FLIGHT'
                """,
                (utc_now(), task_id),
            )
            return cursor.rowcount

    def items(self, task_id: str, item_type: str | None = None) -> list[WorkItem]:
        query = "SELECT * FROM task_items WHERE task_id = ?"
        params: list[Any] = [task_id]
        if item_type:
            query += " AND item_type = ?"
            params.append(item_type)
        query += " ORDER BY rowid"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_item_from_row(row) for row in rows]

    def item_counts(self, task_id: str, item_type: str | None = None) -> dict[str, int]:
        query = (
            "SELECT state, COUNT(*) AS count FROM task_items WHERE task_id = ?"
        )
        params: list[Any] = [task_id]
        if item_type:
            query += " AND item_type = ?"
            params.append(item_type)
        query += " GROUP BY state"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return {row["state"]: int(row["count"]) for row in rows}

    def count_items(self, task_id: str, item_type: str | None = None) -> int:
        return sum(self.item_counts(task_id, item_type).values())

    def add_resource(
        self,
        task_id: str,
        resource_id: str,
        kind: str,
        *,
        pid: int | None = None,
        path: str | Path | None = None,
        lease_token: int | None = None,
    ) -> None:
        """Record a process or filesystem resource owned by a task.

        The browser adapter registers its process and profile directory here so
        normal completion and crash recovery can clean both up.  The optional
        lease token keeps a stale holder from deleting the resources of the
        worker that took the task over.
        """
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO task_resources (
                    task_id, resource_id, kind, pid, path, lease_token, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    resource_id,
                    kind,
                    int(pid) if pid is not None else None,
                    str(path) if path is not None else None,
                    int(lease_token) if lease_token is not None else None,
                    utc_now(),
                ),
            )

    def claim_browser_slot(
        self,
        *,
        task_id: str,
        lease_token: int,
        limit: int,
        ttl_seconds: float,
    ) -> str | None:
        """Atomically claim one of ``limit`` browser slots across workers."""
        if limit <= 0:
            return None
        now = time.time()
        expires_at = now + max(float(ttl_seconds), 1.0)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM task_resources "
                "WHERE kind = 'browser_slot' AND expires_at IS NOT NULL "
                "AND expires_at <= ?",
                (now,),
            )
            for index in range(limit):
                resource_id = f"browser-slot:{index}"
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO task_resources (
                        task_id, resource_id, kind, lease_token, expires_at, created_at
                    ) VALUES (?, ?, 'browser_slot', ?, ?, ?)
                    """,
                    (task_id, resource_id, int(lease_token), expires_at, utc_now()),
                )
                if cursor.rowcount:
                    return resource_id
        return None

    def renew_browser_slot(
        self, task_id: str, resource_id: str, *, ttl_seconds: float
    ) -> bool:
        expires_at = time.time() + max(float(ttl_seconds), 1.0)
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE task_resources SET expires_at = ? "
                "WHERE task_id = ? AND resource_id = ? AND kind = 'browser_slot'",
                (expires_at, task_id, resource_id),
            )
            return cursor.rowcount > 0

    def release_browser_slot(self, task_id: str, resource_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM task_resources "
                "WHERE task_id = ? AND resource_id = ? AND kind = 'browser_slot'",
                (task_id, resource_id),
            )

    def list_resources(
        self,
        task_id: str | None = None,
        *,
        lease_token: int | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM task_resources"
        clauses: list[str] = []
        params: list[Any] = []
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(task_id)
        if lease_token is not None:
            clauses.append("lease_token = ?")
            params.append(int(lease_token))
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at, resource_id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            {
                "task_id": row["task_id"],
                "resource_id": row["resource_id"],
                "kind": row["kind"],
                "pid": row["pid"],
                "path": row["path"],
                "lease_token": row["lease_token"],
                "expires_at": row["expires_at"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def remove_resource(self, task_id: str, resource_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM task_resources WHERE task_id = ? AND resource_id = ?",
                (task_id, resource_id),
            )

    def clear_resources(self, task_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM task_resources WHERE task_id = ?", (task_id,)
            )

    def create_batch(self, batch: Batch) -> None:
        with self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO batches (
                        batch_id, name, country, market, language, category,
                        note, created_at, updated_at, archived_at, collection_mode,
                        folder_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch.batch_id,
                        batch.name,
                        batch.country,
                        batch.market,
                        batch.language,
                        batch.category,
                        batch.note,
                        batch.created_at,
                        batch.updated_at,
                        batch.archived_at,
                        batch.collection_mode,
                        batch.folder_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"batch already exists: {batch.batch_id}") from exc

    def get_batch(self, batch_id: str) -> Batch | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
        return _batch_from_row(row) if row else None

    @staticmethod
    def _promote_batch_collection(connection: sqlite3.Connection, batch_id: str) -> None:
        cursor = connection.execute(
            "UPDATE batches SET collection_mode = 'formal', updated_at = ? "
            "WHERE batch_id = ? AND archived_at IS NULL AND collection_mode = 'sample' "
            "AND NOT EXISTS (SELECT 1 FROM tasks t WHERE t.batch_id = batches.batch_id "
            "AND t.state NOT IN ('FINISHED', 'CANCELLED')) "
            "AND NOT EXISTS (SELECT 1 FROM builds b WHERE b.batch_id = batches.batch_id "
            "AND b.state NOT IN ('FINISHED', 'CANCELLED', 'INTERRUPTED')) "
            "AND NOT EXISTS (SELECT 1 FROM batch_sites s WHERE s.batch_id = batches.batch_id "
            "AND s.readiness = 'building')",
            (utc_now(), batch_id),
        )
        if cursor.rowcount != 1:
            raise BatchTransitionError("only idle trial batches can start formal collection")

    def list_batches(self, *, include_archived: bool = False) -> list[Batch]:
        query = "SELECT * FROM batches"
        if not include_archived:
            query += " WHERE archived_at IS NULL"
        query += " ORDER BY created_at DESC, batch_id DESC"
        with self._connect() as connection:
            rows = connection.execute(query).fetchall()
        return [_batch_from_row(row) for row in rows]

    def update_batch(self, batch_id: str, **fields: Any) -> Batch:
        allowed = {"name", "country", "market", "language", "category", "note", "folder_id"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown batch fields: {sorted(unknown)}")
        assignments = [f"{key} = ?" for key in fields]
        values = list(fields.values())
        assignments.append("updated_at = ?")
        values.append(utc_now())
        values.append(batch_id)
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE batches SET {', '.join(assignments)} WHERE batch_id = ?",
                values,
            )
            if cursor.rowcount != 1:
                raise BatchNotFoundError(f"unknown batch: {batch_id}")
        batch = self.get_batch(batch_id)
        if batch is None:
            raise BatchNotFoundError(f"unknown batch: {batch_id}")
        return batch

    def list_batch_folders(self) -> list[BatchFolder]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM batch_folders ORDER BY name COLLATE NOCASE, folder_id"
            ).fetchall()
        return [_batch_folder_from_row(row) for row in rows]

    def get_batch_folder(self, folder_id: str) -> BatchFolder | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM batch_folders WHERE folder_id = ?", (folder_id,)
            ).fetchone()
        return _batch_folder_from_row(row) if row else None

    def create_batch_folder(self, folder: BatchFolder) -> BatchFolder:
        name = _normalize_batch_folder_name(folder.name)
        now = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if folder.parent_id is not None:
                    chain = _batch_folder_chain(connection, folder.parent_id)
                    if len(chain) >= BATCH_FOLDER_MAX_DEPTH:
                        raise BatchFolderConflictError(
                            f"分组最多 {BATCH_FOLDER_MAX_DEPTH} 层"
                        )
                _ensure_batch_folder_name_available(
                    connection, name, folder.parent_id, exclude_id=None
                )
                connection.execute(
                    """
                    INSERT INTO batch_folders (
                        folder_id, parent_id, name, sort_order, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        folder.folder_id,
                        folder.parent_id,
                        name,
                        folder.sort_order,
                        folder.created_at or now,
                        now,
                    ),
                )
                connection.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                connection.execute("ROLLBACK")
                raise BatchFolderConflictError("分组 ID 已存在") from exc
            except Exception:
                connection.execute("ROLLBACK")
                raise
        created = self.get_batch_folder(folder.folder_id)
        if created is None:
            raise BatchFolderNotFoundError(
                f"unknown batch folder: {folder.folder_id}"
            )
        return created

    def update_batch_folder(
        self,
        folder_id: str,
        *,
        name: Any = _UNSET,
        parent_id: Any = _UNSET,
    ) -> BatchFolder:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM batch_folders WHERE folder_id = ?", (folder_id,)
                ).fetchone()
                if row is None:
                    raise BatchFolderNotFoundError(
                        f"unknown batch folder: {folder_id}"
                    )
                if name is not _UNSET and name is None:
                    raise BatchFolderNameError("分组名称不能为空")
                next_name = (
                    row["name"]
                    if name is _UNSET
                    else _normalize_batch_folder_name(str(name))
                )
                next_parent = (
                    row["parent_id"] if parent_id is _UNSET else parent_id
                )
                if next_parent is not None:
                    if next_parent == folder_id:
                        raise BatchFolderConflictError("分组不能移动到自己下面")
                    chain = _batch_folder_chain(connection, next_parent)
                    if folder_id in chain:
                        raise BatchFolderConflictError("分组不能移动到自己的后代下面")
                    subtree_height = _batch_folder_subtree_height(
                        connection, folder_id
                    )
                    if len(chain) + subtree_height > BATCH_FOLDER_MAX_DEPTH:
                        raise BatchFolderConflictError(
                            f"分组最多 {BATCH_FOLDER_MAX_DEPTH} 层"
                        )
                _ensure_batch_folder_name_available(
                    connection,
                    next_name,
                    next_parent,
                    exclude_id=folder_id,
                )
                connection.execute(
                    "UPDATE batch_folders SET name = ?, parent_id = ?, updated_at = ? "
                    "WHERE folder_id = ?",
                    (next_name, next_parent, utc_now(), folder_id),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        updated = self.get_batch_folder(folder_id)
        if updated is None:
            raise BatchFolderNotFoundError(f"unknown batch folder: {folder_id}")
        return updated

    def delete_batch_folder(self, folder_id: str) -> dict[str, Any]:
        """Dissolve a folder without deleting batches or nested work."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM batch_folders WHERE folder_id = ?", (folder_id,)
                ).fetchone()
                if row is None:
                    raise BatchFolderNotFoundError(
                        f"unknown batch folder: {folder_id}"
                    )
                parent_id = row["parent_id"]
                conflicts = connection.execute(
                    """
                    SELECT child.name FROM batch_folders child
                    WHERE child.parent_id = ?
                      AND EXISTS (
                        SELECT 1 FROM batch_folders sibling
                        WHERE COALESCE(sibling.parent_id, '') = COALESCE(?, '')
                          AND sibling.folder_id <> ?
                          AND lower(sibling.name) = lower(child.name)
                      )
                    """,
                    (folder_id, parent_id, folder_id),
                ).fetchall()
                if conflicts:
                    names = "、".join(item["name"] for item in conflicts)
                    raise BatchFolderConflictError(
                        f"上一级已有同名分组：{names}；请先改名"
                    )
                now = utc_now()
                moved_folders = connection.execute(
                    "UPDATE batch_folders SET parent_id = ?, updated_at = ? "
                    "WHERE parent_id = ?",
                    (parent_id, now, folder_id),
                ).rowcount
                moved_batches = connection.execute(
                    "UPDATE batches SET folder_id = ?, updated_at = ? "
                    "WHERE folder_id = ?",
                    (parent_id, now, folder_id),
                ).rowcount
                connection.execute(
                    "DELETE FROM batch_folders WHERE folder_id = ?", (folder_id,)
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return {
            "folder_id": folder_id,
            "parent_id": parent_id,
            "moved_folders": moved_folders,
            "moved_batches": moved_batches,
        }

    def move_batches(
        self, batch_ids: list[str], folder_id: str | None
    ) -> int:
        unique_ids = list(dict.fromkeys(batch_ids))
        if not unique_ids:
            raise ValueError("batch_ids must not be empty")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if folder_id is not None and connection.execute(
                    "SELECT 1 FROM batch_folders WHERE folder_id = ?",
                    (folder_id,),
                ).fetchone() is None:
                    raise BatchFolderNotFoundError(
                        f"unknown batch folder: {folder_id}"
                    )
                placeholders = ",".join("?" for _ in unique_ids)
                found = {
                    row["batch_id"]
                    for row in connection.execute(
                        f"SELECT batch_id FROM batches WHERE batch_id IN ({placeholders})",
                        unique_ids,
                    ).fetchall()
                }
                missing = [batch_id for batch_id in unique_ids if batch_id not in found]
                if missing:
                    raise BatchNotFoundError(
                        f"unknown batch: {', '.join(missing)}"
                    )
                cursor = connection.execute(
                    f"UPDATE batches SET folder_id = ?, updated_at = ? "
                    f"WHERE batch_id IN ({placeholders})",
                    [folder_id, utc_now(), *unique_ids],
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return cursor.rowcount

    def list_workbench_nodes(self) -> list[WorkbenchNode]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM workbench_nodes "
                "ORDER BY parent_id, sort_order, name COLLATE NOCASE, node_id"
            ).fetchall()
        return [_workbench_node_from_row(row) for row in rows]

    def get_workbench_node(self, node_id: str) -> WorkbenchNode | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM workbench_nodes WHERE node_id = ?", (node_id,)
            ).fetchone()
        return _workbench_node_from_row(row) if row else None

    def create_workbench_group(self, node: WorkbenchNode) -> WorkbenchNode:
        if node.node_type != "group":
            raise ValueError("only group nodes can be created here")
        with self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO workbench_nodes (node_id, node_type, parent_id, name, "
                    "sort_order, created_at, updated_at) VALUES (?, 'group', ?, ?, ?, ?, ?)",
                    (
                        node.node_id,
                        node.parent_id,
                        node.name,
                        node.sort_order,
                        node.created_at,
                        node.updated_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"workbench node already exists: {node.node_id}") from exc
        created = self.get_workbench_node(node.node_id)
        if created is None:
            raise ValueError(f"unknown workbench node: {node.node_id}")
        return created

    def create_workbench_task(
        self, node: WorkbenchNode, definition: WorkbenchTaskDef
    ) -> WorkbenchNode:
        if node.node_type != "task":
            raise ValueError("task nodes require node_type=task")
        if definition.node_id != node.node_id:
            raise ValueError("task definition node_id must match the node")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "INSERT INTO workbench_nodes (node_id, node_type, parent_id, name, "
                    "sort_order, created_at, updated_at) VALUES (?, 'task', ?, ?, ?, ?, ?)",
                    (
                        node.node_id,
                        node.parent_id,
                        node.name,
                        node.sort_order,
                        node.created_at,
                        node.updated_at,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO workbench_task_defs (
                        node_id, input_url, domain, site_key, batch_id,
                        country, language, market, category, task_type,
                        collection_mode, rule_id, rule_version, rule_path,
                        limits_json, proxy, note, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        definition.node_id,
                        definition.input_url,
                        definition.domain,
                        definition.site_key,
                        definition.batch_id,
                        definition.country,
                        definition.language,
                        definition.market,
                        definition.category,
                        definition.task_type,
                        definition.collection_mode,
                        definition.rule_id,
                        definition.rule_version,
                        definition.rule_path,
                        json_dumps(definition.limits),
                        definition.proxy,
                        definition.note,
                        definition.created_at,
                        definition.updated_at,
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise ValueError(f"workbench node already exists: {node.node_id}") from exc
            except Exception:
                connection.rollback()
                raise
        created = self.get_workbench_node(node.node_id)
        if created is None:
            raise ValueError(f"unknown workbench node: {node.node_id}")
        return created

    def rename_workbench_node(
        self, node_id: str, name: str, updated_at: str
    ) -> WorkbenchNode:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT node_id FROM workbench_nodes WHERE node_id = ?", (node_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown workbench node: {node_id}")
            connection.execute(
                "UPDATE workbench_nodes SET name = ?, updated_at = ? WHERE node_id = ?",
                (name, updated_at, node_id),
            )
        updated = self.get_workbench_node(node_id)
        if updated is None:
            raise KeyError(f"unknown workbench node: {node_id}")
        return updated

    def update_workbench_task(
        self, node_id: str, updated_at: str, **fields: Any
    ) -> WorkbenchTaskDef:
        allowed = {
            "country",
            "language",
            "market",
            "category",
            "task_type",
            "collection_mode",
            "rule_id",
            "rule_version",
            "rule_path",
            "limits",
            "proxy",
            "note",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown workbench task fields: {sorted(unknown)}")
        assignments = [
            f"{'limits_json' if key == 'limits' else key} = ?" for key in fields
        ]
        values: list[Any] = []
        for key, value in fields.items():
            values.append(json_dumps(value) if key == "limits" else value)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT node_id FROM workbench_task_defs WHERE node_id = ?", (node_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown workbench task: {node_id}")
            if assignments:
                connection.execute(
                    f"UPDATE workbench_task_defs SET {', '.join(assignments)}, "
                    "updated_at = ? WHERE node_id = ?",
                    [*values, updated_at, node_id],
                )
                connection.execute(
                    "UPDATE workbench_nodes SET updated_at = ? WHERE node_id = ?",
                    (updated_at, node_id),
                )
        updated = self.get_workbench_task_def(node_id)
        if updated is None:
            raise KeyError(f"unknown workbench task: {node_id}")
        return updated

    def attach_workbench_run(
        self, node_id: str, task_id: str, created_at: str
    ) -> bool:
        """Map an existing run to a definition, rejecting cross-definition reuse."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                node = connection.execute(
                    "SELECT node_id FROM workbench_nodes WHERE node_id = ?", (node_id,)
                ).fetchone()
                definition = connection.execute(
                    "SELECT node_id FROM workbench_task_defs WHERE node_id = ?",
                    (node_id,),
                ).fetchone()
                if node is None or definition is None:
                    raise KeyError(f"unknown workbench task: {node_id}")
                task = connection.execute(
                    "SELECT task_id FROM tasks WHERE task_id = ?", (task_id,)
                ).fetchone()
                if task is None:
                    raise KeyError(f"unknown task: {task_id}")
                existing = connection.execute(
                    "SELECT node_id FROM workbench_task_runs WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                if existing is not None:
                    if str(existing["node_id"]) == node_id:
                        connection.commit()
                        return False
                    raise ValueError(
                        f"task is already attached to {existing['node_id']}"
                    )
                connection.execute(
                    "INSERT INTO workbench_task_runs (node_id, task_id, created_at) "
                    "VALUES (?, ?, ?)",
                    (node_id, task_id, created_at),
                )
                connection.execute(
                    "UPDATE workbench_nodes SET updated_at = ? WHERE node_id = ?",
                    (created_at, node_id),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return True

    def move_workbench_node(
        self,
        node_id: str,
        parent_id: str | None,
        after_node_id: str | None,
        updated_at: str,
        before_node_id: str | None = None,
    ) -> WorkbenchNode:
        if after_node_id is not None and before_node_id is not None:
            raise ValueError("after_node_id and before_node_id are mutually exclusive")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                node = connection.execute(
                    "SELECT node_id, node_type, parent_id FROM workbench_nodes "
                    "WHERE node_id = ?",
                    (node_id,),
                ).fetchone()
                if node is None:
                    raise KeyError(f"unknown workbench node: {node_id}")
                if parent_id == node_id:
                    raise ValueError("a node cannot be moved into itself")
                if parent_id is not None:
                    parent = connection.execute(
                        "SELECT node_id, node_type, parent_id FROM workbench_nodes "
                        "WHERE node_id = ?",
                        (parent_id,),
                    ).fetchone()
                    if parent is None:
                        raise ValueError(f"unknown workbench parent: {parent_id}")
                    if parent["node_type"] != "group":
                        raise ValueError("workbench parent must be a group")
                    cursor: str | None = parent_id
                    seen: set[str] = set()
                    while cursor is not None:
                        if cursor == node_id:
                            raise ValueError("a node cannot be moved into its descendant")
                        if cursor in seen:
                            break
                        seen.add(cursor)
                        row = connection.execute(
                            "SELECT parent_id FROM workbench_nodes WHERE node_id = ?",
                            (cursor,),
                        ).fetchone()
                        cursor = row["parent_id"] if row else None
                sibling_rows = connection.execute(
                    "SELECT node_id FROM workbench_nodes "
                    "WHERE parent_id IS ? AND node_id != ? "
                    "ORDER BY sort_order, name COLLATE NOCASE, node_id",
                    (parent_id, node_id),
                ).fetchall()
                sibling_ids = [str(row["node_id"]) for row in sibling_rows]
                if after_node_id is not None:
                    if after_node_id == node_id:
                        raise ValueError("after_node_id must not be the moved node")
                    if after_node_id not in sibling_ids:
                        raise ValueError(
                            "after_node_id must be a child of the target parent"
                        )
                    index = sibling_ids.index(after_node_id) + 1
                elif before_node_id is not None:
                    if before_node_id == node_id:
                        raise ValueError("before_node_id must not be the moved node")
                    if before_node_id not in sibling_ids:
                        raise ValueError(
                            "before_node_id must be a child of the target parent"
                        )
                    index = sibling_ids.index(before_node_id)
                else:
                    index = len(sibling_ids)
                sibling_ids.insert(index, node_id)
                for order, sibling_id in enumerate(sibling_ids):
                    connection.execute(
                        "UPDATE workbench_nodes SET parent_id = ?, sort_order = ?, "
                        "updated_at = ? WHERE node_id = ?",
                        (parent_id, order, updated_at, sibling_id),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        moved = self.get_workbench_node(node_id)
        if moved is None:
            raise KeyError(f"unknown workbench node: {node_id}")
        return moved

    def dissolve_workbench_group(self, node_id: str, updated_at: str) -> int:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                group = connection.execute(
                    "SELECT node_id, node_type, parent_id, sort_order FROM workbench_nodes "
                    "WHERE node_id = ?",
                    (node_id,),
                ).fetchone()
                if group is None:
                    raise KeyError(f"unknown workbench node: {node_id}")
                if group["node_type"] != "group":
                    raise ValueError("only groups can be dissolved")
                parent_id = group["parent_id"]
                sibling_rows = connection.execute(
                    "SELECT node_id FROM workbench_nodes WHERE parent_id IS ? "
                    "ORDER BY sort_order, name COLLATE NOCASE, node_id",
                    (parent_id,),
                ).fetchall()
                sibling_ids = [str(row["node_id"]) for row in sibling_rows]
                group_index = sibling_ids.index(node_id)
                child_rows = connection.execute(
                    "SELECT node_id FROM workbench_nodes WHERE parent_id = ? "
                    "ORDER BY sort_order, name COLLATE NOCASE, node_id",
                    (node_id,),
                ).fetchall()
                child_ids = [str(row["node_id"]) for row in child_rows]
                remaining = [item for item in sibling_ids if item != node_id]
                combined = (
                    remaining[:group_index] + child_ids + remaining[group_index:]
                )
                for order, item_id in enumerate(combined):
                    if item_id in child_ids:
                        connection.execute(
                            "UPDATE workbench_nodes SET parent_id = ?, sort_order = ?, "
                            "updated_at = ? WHERE node_id = ?",
                            (parent_id, order, updated_at, item_id),
                        )
                    else:
                        connection.execute(
                            "UPDATE workbench_nodes SET sort_order = ? WHERE node_id = ?",
                            (order, item_id),
                        )
                connection.execute(
                    "DELETE FROM workbench_nodes WHERE node_id = ?", (node_id,)
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return len(child_ids)

    def list_workbench_task_defs(self) -> list[WorkbenchTaskDef]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM workbench_task_defs ORDER BY created_at, node_id"
            ).fetchall()
        return [_workbench_task_def_from_row(row) for row in rows]

    def get_workbench_task_def(self, node_id: str) -> WorkbenchTaskDef | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM workbench_task_defs WHERE node_id = ?", (node_id,)
            ).fetchone()
        return _workbench_task_def_from_row(row) if row else None

    def list_workbench_task_runs(self) -> list[WorkbenchRun]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM workbench_task_runs ORDER BY created_at, task_id"
            ).fetchall()
        return [
            WorkbenchRun(
                node_id=row["node_id"],
                task_id=row["task_id"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def create_workbench_run(
        self,
        task: Task,
        *,
        node_id: str,
        request_id: str,
        request_json: str,
    ) -> tuple[Task, bool]:
        """Insert a task run and its workbench definition mapping atomically."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT task_id, request_json FROM task_requests WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                if row is not None:
                    if str(row["request_json"]) != request_json:
                        raise RequestConflictError(
                            f"request_id {request_id} was used with a different request"
                        )
                    connection.commit()
                    existing = self.get_task(str(row["task_id"]))
                    if existing is None:
                        raise TaskNotFoundError(f"unknown task: {row['task_id']}")
                    return existing, False
                self._insert_task(connection, task)
                connection.execute(
                    "INSERT INTO task_requests (request_id, task_id, request_json, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (request_id, task.task_id, request_json, utc_now()),
                )
                connection.execute(
                    "INSERT INTO workbench_task_runs (node_id, task_id, created_at) "
                    "VALUES (?, ?, ?)",
                    (node_id, task.task_id, utc_now()),
                )
                if task.batch_id and task.site_key:
                    site = connection.execute(
                        "SELECT 1 FROM batch_sites WHERE batch_id = ? AND site_key = ?",
                        (task.batch_id, task.site_key),
                    ).fetchone()
                    if site is not None:
                        linked = connection.execute(
                            "UPDATE batch_sites SET task_id = ?, updated_at = ? "
                            "WHERE batch_id = ? AND site_key = ? AND "
                            "(task_id IS NULL OR task_id IN "
                            "(SELECT task_id FROM tasks WHERE state IN ('FINISHED', 'CANCELLED')))",
                            (task.task_id, utc_now(), task.batch_id, task.site_key),
                        )
                        if linked.rowcount != 1:
                            raise BatchTransitionError(
                                "batch target is unavailable or busy"
                            )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise ValueError(f"task already exists: {task.task_id}") from exc
            except Exception:
                connection.rollback()
                raise
        return task, True

    def list_workbench_dismissals(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT task_id FROM workbench_recent_dismissals"
            ).fetchall()
        return {str(row["task_id"]) for row in rows}

    def dismiss_workbench_runs(self, task_ids: list[str]) -> int:
        unique_ids = list(dict.fromkeys(str(task_id) for task_id in task_ids))
        if not unique_ids:
            return 0
        now = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for task_id in unique_ids:
                    connection.execute(
                        "INSERT OR IGNORE INTO workbench_recent_dismissals "
                        "(task_id, dismissed_at) VALUES (?, ?)",
                        (task_id, now),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return len(unique_ids)

    def restore_workbench_runs(self, task_ids: list[str]) -> int:
        unique_ids = list(dict.fromkeys(str(task_id) for task_id in task_ids))
        if not unique_ids:
            return 0
        placeholders = ", ".join("?" for _ in unique_ids)
        with self._connect() as connection:
            cursor = connection.execute(
                f"DELETE FROM workbench_recent_dismissals WHERE task_id IN ({placeholders})",
                unique_ids,
            )
        return cursor.rowcount

    def batch_tree_signals(self) -> dict[str, dict[str, int]]:
        """Return lightweight per-batch signals for the directory tree.

        The tree must not reuse the full batch payload: doing so would read
        sites, tasks and result summaries for every batch.  These signals are
        operational hints only; the batch table and detail remain authoritative.
        """
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    bs.batch_id,
                    COALESCE(SUM(CASE WHEN t.state IN
                        ('RUNNING', 'PAUSING', 'CANCELLING') THEN 1 ELSE 0 END), 0)
                        AS running,
                    COALESCE(SUM(CASE WHEN t.state = 'FINISHED'
                        AND t.outcome = 'FAILED' THEN 1 ELSE 0 END), 0)
                        AS failed,
                    COALESCE(SUM(CASE WHEN bs.readiness = 'needs_onboarding'
                        THEN 1 ELSE 0 END), 0)
                        AS needs_onboarding
                FROM batch_sites bs
                LEFT JOIN tasks t ON t.task_id = bs.task_id
                GROUP BY bs.batch_id
                """
            ).fetchall()
        return {
            row["batch_id"]: {
                "running": int(row["running"]),
                "failed": int(row["failed"]),
                "needs_onboarding": int(row["needs_onboarding"]),
            }
            for row in rows
        }

    def add_batch_sites(self, sites: list[BatchSite]) -> int:
        """Insert site rows, skipping keys that already exist in the batch."""
        inserted = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for site in sites:
                    cursor = connection.execute(
                        """
                        INSERT OR IGNORE INTO batch_sites (
                            batch_id, site_key, domain, input_value, readiness,
                            rule_id, rule_version, rule_path, task_id, build_id,
                            proxy, note, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            site.batch_id,
                            site.site_key,
                            site.domain,
                            site.input_value,
                            site.readiness,
                            site.rule_id,
                            site.rule_version,
                            site.rule_path,
                            site.task_id,
                            site.build_id,
                            site.proxy,
                            site.note,
                            site.created_at,
                            site.updated_at,
                        ),
                    )
                    inserted += cursor.rowcount
                if inserted:
                    batch_ids = {site.batch_id for site in sites}
                    for batch_id in batch_ids:
                        connection.execute(
                            "UPDATE batches SET updated_at = ? WHERE batch_id = ?",
                            (utc_now(), batch_id),
                        )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return inserted

    def list_batch_sites(self, batch_id: str) -> list[BatchSite]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM batch_sites WHERE batch_id = ? "
                "ORDER BY created_at, rowid",
                (batch_id,),
            ).fetchall()
        return [_batch_site_from_row(row) for row in rows]

    def get_batch_site(self, batch_id: str, site_key: str) -> BatchSite | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM batch_sites WHERE batch_id = ? AND site_key = ?",
                (batch_id, site_key),
            ).fetchone()
        return _batch_site_from_row(row) if row else None

    def update_batch_site(
        self, batch_id: str, site_key: str, **fields: Any
    ) -> BatchSite:
        allowed = {
            "domain",
            "input_value",
            "readiness",
            "rule_id",
            "rule_version",
            "rule_path",
            "task_id",
            "build_id",
            "proxy",
            "note",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown batch site fields: {sorted(unknown)}")
        assignments = [f"{key} = ?" for key in fields]
        values = list(fields.values())
        assignments.append("updated_at = ?")
        values.append(utc_now())
        values.extend([batch_id, site_key])
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE batch_sites SET {', '.join(assignments)} "
                "WHERE batch_id = ? AND site_key = ?",
                values,
            )
            if cursor.rowcount != 1:
                raise BatchNotFoundError(
                    f"unknown batch site: {batch_id}/{site_key}"
                )
        site = self.get_batch_site(batch_id, site_key)
        if site is None:
            raise BatchNotFoundError(f"unknown batch site: {batch_id}/{site_key}")
        return site

    def create_task_for_site(
        self,
        task: Task,
        *,
        site_key: str,
        expected_task_id: str | None = None,
        promote_trial: bool = False,
        onboarding_build_id: str | None = None,
    ) -> bool:
        """Create a task and link it to a batch site in one transaction.

        Returns ``False`` when the site already has a task, which makes a
        repeated batch start idempotent even with concurrent callers. Pass
        ``expected_task_id`` to replace that specific terminal task link.
        """
        if not task.batch_id:
            raise ValueError("task.batch_id is required for batch starts")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if promote_trial:
                    self._promote_batch_collection(connection, task.batch_id)
                row = connection.execute(
                    "SELECT bs.task_id, t.state, b.collection_mode FROM batch_sites bs "
                    "JOIN batches b ON b.batch_id = bs.batch_id AND b.archived_at IS NULL "
                    "LEFT JOIN tasks t ON t.task_id = bs.task_id "
                    "WHERE bs.batch_id = ? AND bs.site_key = ?",
                    (task.batch_id, site_key),
                ).fetchone()
                if row is None:
                    raise BatchNotFoundError(
                        f"unknown batch site: {task.batch_id}/{site_key}"
                    )
                if row["collection_mode"] != task.input.get("collection_mode"):
                    connection.rollback()
                    return False
                if row["task_id"] != expected_task_id or row["state"] not in {
                    "FINISHED", "CANCELLED", None,
                }:
                    connection.rollback()
                    return False
                if onboarding_build_id and connection.execute(
                    "SELECT 1 FROM batch_sites s JOIN builds b ON b.build_id = s.build_id "
                    "AND b.batch_id = s.batch_id AND b.site_key = s.site_key "
                    "JOIN site_rules r ON r.site_key = s.site_key "
                    "WHERE s.batch_id = ? AND s.site_key = ? AND b.build_id = ? "
                    "AND b.state = 'VALIDATING' "
                    "AND r.rule_id = ? AND r.rule_version = ? AND r.sha256 = ? "
                    "AND json_extract(b.request_json, '$.auto_collect') = 1 "
                    "AND COALESCE(json_extract(b.request_json, '$.batch_cancel_requested'), 0) = 0",
                    (task.batch_id, site_key, onboarding_build_id,
                     task.plan_id, task.plan_version, task.rule_sha256),
                ).fetchone() is None:
                    connection.rollback()
                    return False
                self._insert_task(connection, task)
                connection.execute(
                    "UPDATE batch_sites SET task_id = ?, updated_at = ? "
                    "WHERE batch_id = ? AND site_key = ?",
                    (task.task_id, utc_now(), task.batch_id, site_key),
                )
                connection.execute(
                    "UPDATE batches SET updated_at = ? WHERE batch_id = ?",
                    (utc_now(), task.batch_id),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return True

    def list_batch_tasks(self, batch_id: str) -> list[Task]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE batch_id = ? ORDER BY created_at, task_id",
                (batch_id,),
            ).fetchall()
        return [_task_from_row(row) for row in rows]

    def read_batch_snapshot(self, batch_id: str) -> tuple[Batch, list[BatchSite], list[Task]]:
        with self._connect() as connection:
            connection.execute("BEGIN")
            batch = connection.execute(
                "SELECT * FROM batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            if batch is None:
                raise BatchNotFoundError(f"unknown batch: {batch_id}")
            sites = connection.execute(
                "SELECT * FROM batch_sites WHERE batch_id = ? ORDER BY created_at, rowid",
                (batch_id,),
            ).fetchall()
            tasks = connection.execute(
                "SELECT * FROM tasks WHERE batch_id = ? ORDER BY created_at, task_id",
                (batch_id,),
            ).fetchall()
        return _batch_from_row(batch), list(map(_batch_site_from_row, sites)), list(map(_task_from_row, tasks))

    def request_cancel_batch_onboarding(self, batch_id: str) -> list[str]:
        """Fence automatic collection and cancel all queued onboarding together."""
        now = utc_now()
        with self._connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            builds = connection.execute(
                """
                UPDATE builds
                SET request_json = json_set(request_json, '$.batch_cancel_requested', json('true')),
                    outcome = CASE WHEN state = 'QUEUED' THEN 'cancelled' ELSE outcome END,
                    finished_at = CASE WHEN state = 'QUEUED' THEN ? ELSE finished_at END,
                    state = CASE WHEN state = 'QUEUED' THEN 'CANCELLED' ELSE state END,
                    updated_at = ?
                WHERE batch_id = ? AND state NOT IN ('FINISHED', 'CANCELLED')
                    AND json_extract(request_json, '$.auto_collect') = 1
                    AND COALESCE(json_extract(request_json, '$.batch_cancel_requested'), 0) = 0
                    AND EXISTS (
                        SELECT 1 FROM batches WHERE batch_id = builds.batch_id AND archived_at IS NULL
                    )
                RETURNING build_id, site_key, state
                """,
                (now, now, batch_id),
            ).fetchall()
            connection.executemany(
                """
                UPDATE batch_sites SET readiness = 'needs_onboarding', note = ?, updated_at = ?
                WHERE batch_id = ? AND site_key = ? AND build_id = ? AND readiness = 'building'
                """,
                [
                    ("接入已取消，可重新开始", now, batch_id, row["site_key"], row["build_id"])
                    for row in builds if row["state"] == "CANCELLED"
                ],
            )
        return [row["build_id"] for row in builds]

    def claim_queued_build(self, build_id: str) -> BuildRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "UPDATE builds SET state = 'CREATED', updated_at = ? "
                "WHERE build_id = ? AND state = 'QUEUED' RETURNING *",
                (utc_now(), build_id),
            ).fetchone()
        return _build_from_row(row) if row else None

    def claim_build_validation(self, build_id: str) -> bool:
        with self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE builds SET state = 'VALIDATING', updated_at = ?
                WHERE build_id = ? AND state IN ('CREATED', 'RUNNING', 'PAUSING', 'PAUSED')
                    AND COALESCE(json_extract(request_json, '$.batch_cancel_requested'), 0) = 0
                """,
                (utc_now(), build_id),
            )
        return updated.rowcount == 1

    def create_build(
        self, build: BuildRecord, *, promote_trial: bool = False,
        queued_site_note: str | None = None,
    ) -> None:
        with self._connect() as connection, connection:
            try:
                if promote_trial or queued_site_note is not None:
                    connection.execute("BEGIN IMMEDIATE")
                if promote_trial:
                    self._promote_batch_collection(connection, build.batch_id)
                connection.execute(
                    """
                    INSERT INTO builds (
                        build_id, batch_id, site_key, state, outcome, workspace,
                        session_id, model_json, proxy, error, rule_id, rule_version,
                        rule_path, mode, feedback_id, request_id, request_json,
                        source_rule_version, source_rule_sha256,
                        target_rule_version, target_rule_sha256, error_class,
                        change_summary_json, validation_json, evidence_sha256,
                        created_at, updated_at, started_at, finished_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        build.build_id,
                        build.batch_id,
                        build.site_key,
                        build.state,
                        build.outcome,
                        build.workspace,
                        build.session_id,
                        json_dumps(build.model or {}),
                        build.proxy,
                        build.error,
                        build.rule_id,
                        build.rule_version,
                        build.rule_path,
                        build.mode,
                        build.feedback_id,
                        build.request_id,
                        json_dumps(build.request or {}),
                        build.source_rule_version,
                        build.source_rule_sha256,
                        build.target_rule_version,
                        build.target_rule_sha256,
                        build.error_class,
                        json_dumps(build.change_summary or {}),
                        json_dumps(build.validation or {}),
                        build.evidence_sha256,
                        build.created_at,
                        build.updated_at,
                        build.started_at,
                        build.finished_at,
                    ),
                )
                if queued_site_note is not None:
                    linked = connection.execute(
                        """
                        UPDATE batch_sites SET readiness = 'building', build_id = ?,
                            proxy = ?, note = ?, updated_at = ?
                        WHERE batch_id = ? AND site_key = ?
                            AND EXISTS (SELECT 1 FROM batches WHERE batch_id = ?
                                AND archived_at IS NULL)
                        """,
                        (
                            build.build_id, build.proxy, queued_site_note, utc_now(),
                            build.batch_id, build.site_key, build.batch_id,
                        ),
                    )
                    if linked.rowcount != 1:
                        raise BatchNotFoundError(f"batch target is unavailable: {build.site_key}")
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"build already exists: {build.build_id}") from exc

    def get_build_by_request_id(self, request_id: str) -> BuildRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM builds WHERE request_id = ?", (request_id,)
            ).fetchone()
        return _build_from_row(row) if row else None

    def get_build(self, build_id: str) -> BuildRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM builds WHERE build_id = ?", (build_id,)
            ).fetchone()
        return _build_from_row(row) if row else None

    def get_build_continuation(
        self, request_id: str
    ) -> BuildContinuation | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM build_continuations WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        return _build_continuation_from_row(row) if row else None

    def list_build_continuations(
        self, build_id: str, *, limit: int = 20
    ) -> list[BuildContinuation]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM build_continuations
                WHERE build_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (build_id, max(1, int(limit))),
            ).fetchall()
        return [_build_continuation_from_row(row) for row in rows]

    def create_build_continuation(
        self, continuation: BuildContinuation
    ) -> BuildContinuation:
        with self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO build_continuations (
                        request_id, build_id, message_sha256, message_chars,
                        state, error, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        continuation.request_id,
                        continuation.build_id,
                        continuation.message_sha256,
                        continuation.message_chars,
                        continuation.state,
                        continuation.error,
                        continuation.created_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                existing = self.get_build_continuation(
                    continuation.request_id
                )
                if existing and (
                    existing.build_id == continuation.build_id
                    and existing.message_sha256 == continuation.message_sha256
                ):
                    return existing
                raise BuildContinuationConflictError(
                    f"continuation request_id already used: "
                    f"{continuation.request_id}"
                ) from exc
        created = self.get_build_continuation(continuation.request_id)
        if created is None:
            raise ValueError("build continuation insert was not visible")
        return created

    def update_build_continuation(
        self,
        request_id: str,
        *,
        state: str,
        error: str | None = None,
    ) -> BuildContinuation:
        if state not in {"ACCEPTED", "FAILED"}:
            raise ValueError(f"unsupported continuation state: {state!r}")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE build_continuations
                SET state = ?, error = ?
                WHERE request_id = ?
                """,
                (state, error, request_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"unknown build continuation: {request_id}")
        updated = self.get_build_continuation(request_id)
        if updated is None:
            raise ValueError(f"unknown build continuation: {request_id}")
        return updated

    def list_builds(
        self,
        *,
        batch_id: str | None = None,
        site_key: str | None = None,
        feedback_id: str | None = None,
        states: set[str] | None = None,
        limit: int | None = 50,
        oldest_first: bool = False,
    ) -> list[BuildRecord]:
        query = "SELECT * FROM builds"
        clauses: list[str] = []
        values: list[Any] = []
        if batch_id is not None:
            clauses.append("batch_id = ?")
            values.append(batch_id)
        if site_key is not None:
            clauses.append("site_key = ?")
            values.append(site_key)
        if feedback_id is not None:
            clauses.append("feedback_id = ?")
            values.append(feedback_id)
        if states:
            placeholders = ", ".join("?" for _ in states)
            clauses.append(f"state IN ({placeholders})")
            values.extend(sorted(states))
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        if oldest_first:
            query += " ORDER BY rowid ASC"
        else:
            query += " ORDER BY created_at DESC, rowid DESC"
        if limit is not None:
            query += " LIMIT ?"
            values.append(max(1, int(limit)))
        with self._connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [_build_from_row(row) for row in rows]

    def last_balanced_build_model(self) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT model_json FROM builds "
                "WHERE json_extract(request_json, '$.model_selection') = 'balanced' "
                "ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        model = json_loads(row[0], {}) if row else {}
        if model.get("providerID") and model.get("id"):
            return f"{model['providerID']}/{model['id']}"
        return None

    def get_setting(self, key: str) -> str | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT value FROM app_settings WHERE key = ?", (key,)
                ).fetchone()
        except sqlite3.OperationalError as exc:
            # A read-only preview may open a ledger created before app_settings
            # existed; an absent table means no override, not a failed read.
            if "no such table" in str(exc):
                return None
            raise
        return str(row["value"]) if row is not None else None

    def set_setting(self, key: str, value: str) -> None:
        if self.read_only:
            raise RuntimeError("task ledger is read-only")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value = excluded.value, updated_at = excluded.updated_at",
                (key, value, utc_now()),
            )

    def delete_setting(self, key: str) -> None:
        if self.read_only:
            raise RuntimeError("task ledger is read-only")
        with self._connect() as connection:
            connection.execute("DELETE FROM app_settings WHERE key = ?", (key,))

    def latest_build_for_site(
        self, batch_id: str, site_key: str
    ) -> BuildRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM builds WHERE batch_id = ? AND site_key = ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (batch_id, site_key),
            ).fetchone()
        return _build_from_row(row) if row else None

    def update_build(self, build_id: str, **fields: Any) -> BuildRecord:
        allowed = {
            "state",
            "outcome",
            "workspace",
            "session_id",
            "model",
            "proxy",
            "error",
            "rule_id",
            "rule_version",
            "rule_path",
            "feedback_id",
            "request_id",
            "request",
            "source_rule_version",
            "source_rule_sha256",
            "target_rule_version",
            "target_rule_sha256",
            "error_class",
            "change_summary",
            "validation",
            "evidence_sha256",
            "started_at",
            "finished_at",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown build fields: {sorted(unknown)}")
        values: list[Any] = []
        assignments: list[str] = []
        for key, value in fields.items():
            if key == "model":
                assignments.append("model_json = ?")
                values.append(json_dumps(value or {}))
            elif key in {"change_summary", "validation"}:
                assignments.append(f"{key}_json = ?")
                values.append(json_dumps(value or {}))
            elif key == "request":
                assignments.append("request_json = ?")
                values.append(json_dumps(value or {}))
            else:
                assignments.append(f"{key} = ?")
                values.append(value)
        assignments.append("updated_at = ?")
        values.append(utc_now())
        values.append(build_id)
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE builds SET {', '.join(assignments)} WHERE build_id = ?",
                values,
            )
            if cursor.rowcount != 1:
                raise ValueError(f"unknown build: {build_id}")
        build = self.get_build(build_id)
        if build is None:
            raise ValueError(f"unknown build: {build_id}")
        return build

    def request_archive_batch(self, batch_id: str) -> Batch:
        """Hide a terminal batch; running members must finish or cancel first."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT archived_at FROM batches WHERE batch_id = ?",
                    (batch_id,),
                ).fetchone()
                if row is None:
                    raise BatchNotFoundError(f"unknown batch: {batch_id}")
                active = connection.execute(
                    "SELECT 1 FROM batch_sites bs JOIN tasks t ON t.task_id = bs.task_id "
                    "WHERE bs.batch_id = ? AND t.state NOT IN ('FINISHED', 'CANCELLED') "
                    "LIMIT 1",
                    (batch_id,),
                ).fetchone()
                if active is not None:
                    raise BatchTransitionError(
                        f"cannot archive batch {batch_id} while a member task is active"
                    )
                if row["archived_at"] is None:
                    connection.execute(
                        "UPDATE batches SET archived_at = ?, updated_at = ? "
                        "WHERE batch_id = ?",
                        (utc_now(), utc_now(), batch_id),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        batch = self.get_batch(batch_id)
        if batch is None:
            raise BatchNotFoundError(f"unknown batch: {batch_id}")
        return batch

    def request_restore_batch(self, batch_id: str) -> Batch:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE batches SET archived_at = NULL, updated_at = ? WHERE batch_id = ?",
                (utc_now(), batch_id),
            )
            if cursor.rowcount != 1:
                raise BatchNotFoundError(f"unknown batch: {batch_id}")
        batch = self.get_batch(batch_id)
        if batch is None:
            raise BatchNotFoundError(f"unknown batch: {batch_id}")
        return batch

    def create_feedback(
        self, feedback: QualityFeedback
    ) -> tuple[QualityFeedback, bool]:
        """Insert feedback once per request_id and return (record, created)."""
        with self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO quality_feedback (
                        feedback_id, request_id, task_id, batch_id, site_key,
                        rule_id, rule_version, rule_sha256, category, samples_json,
                        expectation, note, scope, status, triage, triage_note,
                        triage_source, duplicate_of, repair_build_id, rerun_task_id,
                        resolution, resolution_note, created_by, resolved_by,
                        created_at, updated_at, closed_at, request_json
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        feedback.feedback_id,
                        feedback.request_id,
                        feedback.task_id,
                        feedback.batch_id,
                        feedback.site_key,
                        feedback.rule_id,
                        feedback.rule_version,
                        feedback.rule_sha256,
                        feedback.category,
                        json_dumps(feedback.samples),
                        feedback.expectation,
                        feedback.note,
                        feedback.scope,
                        feedback.status,
                        feedback.triage,
                        feedback.triage_note,
                        feedback.triage_source,
                        feedback.duplicate_of,
                        feedback.repair_build_id,
                        feedback.rerun_task_id,
                        feedback.resolution,
                        feedback.resolution_note,
                        feedback.created_by,
                        feedback.resolved_by,
                        feedback.created_at,
                        feedback.updated_at,
                        feedback.closed_at,
                        feedback.request_json,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT * FROM quality_feedback WHERE request_id = ?",
                    (feedback.request_id,),
                ).fetchone()
                if row is None:
                    raise
                existing = _feedback_from_row(row)
                if existing.request_json != feedback.request_json:
                    raise FeedbackRequestConflictError(
                        f"request_id {feedback.request_id!r} was used with a different body"
                    )
                return existing, False
        return feedback, True

    def get_feedback(self, feedback_id: str) -> QualityFeedback | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM quality_feedback WHERE feedback_id = ?",
                (feedback_id,),
            ).fetchone()
        return _feedback_from_row(row) if row else None

    def list_feedback(
        self,
        *,
        task_id: str | None = None,
        batch_id: str | None = None,
        site_key: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[QualityFeedback], int]:
        clauses: list[str] = []
        values: list[Any] = []
        for column, value in (
            ("task_id", task_id),
            ("batch_id", batch_id),
            ("site_key", site_key),
            ("status", status),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                values.append(value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM quality_feedback{where}", values
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT * FROM quality_feedback{where}
                ORDER BY created_at DESC, feedback_id DESC
                LIMIT ? OFFSET ?
                """,
                (*values, max(1, int(limit)), max(0, int(offset))),
            ).fetchall()
        return [_feedback_from_row(row) for row in rows], total

    def create_rule_version(self, version: RuleVersion) -> RuleVersion:
        with self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO rule_versions (
                        rule_id, rule_version, sha256, parent_version, status,
                        source_build_id, source_feedback_id, path, created_at,
                        activated_at, activated_by, reviewed_by, reviewed_at, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version.rule_id,
                        version.rule_version,
                        version.sha256,
                        version.parent_version,
                        version.status,
                        version.source_build_id,
                        version.source_feedback_id,
                        version.path,
                        version.created_at,
                        version.activated_at,
                        version.activated_by,
                        version.reviewed_by,
                        version.reviewed_at,
                        version.notes,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                existing = self.get_rule_version(version.rule_id, version.rule_version)
                if existing and existing.sha256 == version.sha256:
                    return existing
                raise RuleVersionError(
                    f"rule version already exists with different content: "
                    f"{version.rule_id}@{version.rule_version}"
                ) from exc
        created = self.get_rule_version(version.rule_id, version.rule_version)
        if created is None:
            raise RuleVersionError("rule version insert was not visible")
        return created

    def get_rule_version(
        self, rule_id: str, rule_version: str
    ) -> RuleVersion | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM rule_versions WHERE rule_id = ? AND rule_version = ?",
                (rule_id, rule_version),
            ).fetchone()
        return _rule_version_from_row(row) if row else None

    def list_rule_versions(
        self,
        rule_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RuleVersion], int]:
        where = " WHERE rule_id = ?"
        values: list[Any] = [rule_id]
        if status:
            where += " AND status = ?"
            values.append(status)
        with self._connect() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM rule_versions{where}", values
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT * FROM rule_versions{where}
                ORDER BY created_at DESC, rule_version DESC
                LIMIT ? OFFSET ?
                """,
                (*values, max(1, int(limit)), max(0, int(offset))),
            ).fetchall()
        return [_rule_version_from_row(row) for row in rows], total

    def get_site_rule(self, site_key: str) -> SiteRule | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM site_rules WHERE site_key = ?", (site_key,)
            ).fetchone()
        return _site_rule_from_row(row) if row else None

    def bind_verified_site_rule(self, rule: SiteRule) -> SiteRule | None:
        with self._connect() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM site_rules WHERE site_key = ?", (rule.site_key,)
            ).fetchone()
            if current is not None:
                return _site_rule_from_row(current)
            connection.execute(
                """
                INSERT INTO rule_versions (
                    rule_id, rule_version, sha256, path, status, created_at,
                    activated_at, activated_by
                ) VALUES (?, ?, ?, ?, 'active', ?, ?, 'legacy-migration')
                ON CONFLICT(rule_id, rule_version) DO NOTHING
                """,
                (rule.rule_id, rule.rule_version, rule.sha256, rule.path, rule.updated_at, rule.updated_at),
            )
            version = connection.execute(
                "SELECT sha256, status FROM rule_versions WHERE rule_id = ? AND rule_version = ?",
                (rule.rule_id, rule.rule_version),
            ).fetchone()
            if version["status"] != "active" or version["sha256"] != rule.sha256:
                return None
            connection.execute(
                """
                INSERT INTO site_rules (site_key, rule_id, rule_version, sha256, path, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (rule.site_key, rule.rule_id, rule.rule_version, rule.sha256, rule.path, rule.updated_at),
            )
        return rule

    def upsert_site_rule(self, site_rule: SiteRule) -> SiteRule:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO site_rules (
                    site_key, rule_id, rule_version, sha256, path, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_key) DO UPDATE SET
                    rule_id = excluded.rule_id,
                    rule_version = excluded.rule_version,
                    sha256 = excluded.sha256,
                    path = excluded.path,
                    updated_at = excluded.updated_at
                """,
                (
                    site_rule.site_key,
                    site_rule.rule_id,
                    site_rule.rule_version,
                    site_rule.sha256,
                    site_rule.path,
                    site_rule.updated_at,
                ),
            )
        stored = self.get_site_rule(site_rule.site_key)
        if stored is None:
            raise RuleVersionError("site rule pointer was not written")
        return stored

    def latest_batch_site_rule(self, site_key: str) -> BatchSite | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM batch_sites
                WHERE site_key = ? AND rule_id IS NOT NULL AND rule_version IS NOT NULL
                ORDER BY updated_at DESC, batch_id DESC LIMIT 1
                """,
                (site_key,),
            ).fetchone()
        return _batch_site_from_row(row) if row else None

    def list_site_batch_sites(self, site_key: str) -> list[BatchSite]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM batch_sites WHERE site_key = ? ORDER BY updated_at DESC",
                (site_key,),
            ).fetchall()
        return [_batch_site_from_row(row) for row in rows]

    def list_candidate_rules(self, rule_id: str, site_key: str) -> list[RuleVersion]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT r.* FROM rule_versions r
                JOIN builds b ON b.build_id = r.source_build_id
                WHERE r.rule_id = ? AND r.status = 'candidate' AND b.site_key = ?
                ORDER BY r.created_at DESC, r.rule_version DESC LIMIT 200
                """,
                (rule_id, site_key),
            ).fetchall()
        return [_rule_version_from_row(row) for row in rows]

    @staticmethod
    def _find_rollback_rule(
        connection: sqlite3.Connection, current: SiteRule, version: str | None,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT r.* FROM rule_activations a
            JOIN rule_versions r ON r.rule_id = a.rule_id
                AND r.rule_version = a.from_version AND r.sha256 = a.from_sha256
            WHERE a.site_key = ? AND a.rule_id = ? AND r.rule_version != ?
              AND r.status IN ('active', 'superseded')
              AND (? IS NULL OR r.rule_version = ?)
            ORDER BY a.rowid DESC LIMIT 1
            """,
            (current.site_key, current.rule_id, current.rule_version, version, version),
        ).fetchone()

    def find_rollback_rule(
        self, current: SiteRule, version: str | None = None,
    ) -> RuleVersion | None:
        with self._connect() as connection:
            row = self._find_rollback_rule(connection, current, version)
        return _rule_version_from_row(row) if row else None

    def get_activation_by_request(
        self, request_id: str
    ) -> RuleActivation | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM rule_activations WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        return _rule_activation_from_row(row) if row else None

    def activate_rule(
        self,
        *,
        site_key: str,
        rule_id: str,
        rule_version: str,
        sha256: str,
        expected_active_version: str | None = None,
        expected_active_sha256: str | None = None,
        feedback_id: str | None = None,
        request_id: str,
        reason: str | None = None,
        actor: str = "local-user",
        action: str = "activate",
    ) -> tuple[SiteRule, RuleActivation]:
        if action not in {"activate", "rollback"}:
            raise RuleVersionError(f"unsupported rule action: {action}")
        now = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                target_row = connection.execute(
                    "SELECT * FROM rule_versions WHERE rule_id = ? AND rule_version = ?",
                    (rule_id, rule_version),
                ).fetchone()
                if target_row is None:
                    raise RuleVersionError(
                        f"unknown rule version: {rule_id}@{rule_version}"
                    )
                target = _rule_version_from_row(target_row)
                if target.sha256 != sha256:
                    raise RuleVersionError(
                        f"rule hash mismatch: {rule_id}@{rule_version}"
                    )
                if action == "activate" and target.status != "candidate":
                    raise RuleVersionError(
                        f"rule {rule_id}@{rule_version} is {target.status}, "
                        "expected candidate"
                    )
                current_row = connection.execute(
                    "SELECT * FROM site_rules WHERE site_key = ?", (site_key,)
                ).fetchone()
                current = _site_rule_from_row(current_row) if current_row else None
                if expected_active_version is not None and (
                    current is None or current.rule_version != expected_active_version
                ):
                    raise RuleActivationConflictError(
                        "expected active version does not match current pointer"
                    )
                if expected_active_sha256 is not None and (
                    current is None or current.sha256 != expected_active_sha256
                ):
                    raise RuleActivationConflictError(
                        "expected active hash does not match current pointer"
                    )
                if current is not None and current.rule_id != rule_id:
                    raise RuleVersionError(
                        f"site rule_id mismatch: {current.rule_id} != {rule_id}"
                    )
                if action == "rollback":
                    if current is None or self._find_rollback_rule(connection, current, rule_version) is None:
                        raise RuleVersionError("rollback target was not used by this site")
                else:
                    if target.source_build_id and connection.execute(
                        "SELECT 1 FROM builds WHERE build_id = ? AND site_key = ?",
                        (target.source_build_id, site_key),
                    ).fetchone() is None:
                        raise RuleVersionError("candidate belongs to another site")
                    if target.parent_version and (
                        current is None or current.rule_version != target.parent_version
                    ):
                        raise RuleActivationConflictError(
                            "candidate was validated against a different active version"
                        )
                if current is not None:
                    connection.execute(
                        """
                        UPDATE rule_versions SET status = 'superseded'
                        WHERE rule_id = ? AND rule_version = ? AND status = 'active'
                        AND NOT EXISTS (
                            SELECT 1 FROM site_rules s
                            WHERE s.rule_id = rule_versions.rule_id
                            AND s.rule_version = rule_versions.rule_version AND s.site_key != ?
                        )
                        """,
                        (current.rule_id, current.rule_version, site_key),
                    )
                connection.execute(
                    """
                    UPDATE rule_versions
                    SET status = 'active',
                        activated_at = CASE WHEN status = 'active' THEN activated_at ELSE ? END,
                        activated_by = CASE WHEN status = 'active' THEN activated_by ELSE ? END
                    WHERE rule_id = ? AND rule_version = ?
                    """,
                    (now, actor, rule_id, rule_version),
                )
                connection.execute(
                    """
                    INSERT INTO site_rules (
                        site_key, rule_id, rule_version, sha256, path, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(site_key) DO UPDATE SET
                        rule_id = excluded.rule_id,
                        rule_version = excluded.rule_version,
                        sha256 = excluded.sha256,
                        path = excluded.path,
                        updated_at = excluded.updated_at
                    """,
                    (site_key, rule_id, rule_version, sha256, target.path, now),
                )
                connection.execute(
                    """
                    UPDATE batch_sites
                    SET rule_id = ?, rule_version = ?, rule_path = ?,
                        note = CASE
                            WHEN note LIKE '候选方案：%'
                              OR note LIKE '已激活方案：%' THEN ?
                            ELSE note END,
                        readiness = CASE
                            WHEN readiness IN ('needs_onboarding', 'building')
                            THEN 'ready' ELSE readiness END,
                        updated_at = ?
                    WHERE site_key = ?
                    """,
                    (
                        rule_id,
                        rule_version,
                        target.path,
                        f"已激活方案：{rule_id}@{rule_version}",
                        now,
                        site_key,
                    ),
                )
                linked_feedback = (feedback_id or target.source_feedback_id) if action == "activate" else None
                if linked_feedback:
                    feedback = connection.execute(
                        "SELECT * FROM quality_feedback WHERE feedback_id = ?",
                        (linked_feedback,),
                    ).fetchone()
                    if feedback is not None:
                        if feedback["site_key"] != site_key:
                            raise RuleVersionError(
                                "feedback does not belong to the activated site"
                            )
                        if feedback["status"] == "AWAITING_ACTIVATION":
                            connection.execute(
                                """
                                UPDATE quality_feedback
                                SET status = 'AWAITING_RERUN', updated_at = ?
                                WHERE feedback_id = ?
                                """,
                                (now, linked_feedback),
                            )
                activation = RuleActivation(
                    activation_id=f"act-{uuid.uuid4().hex[:12]}",
                    request_id=request_id,
                    site_key=site_key,
                    rule_id=rule_id,
                    action=action,
                    from_version=current.rule_version if current else None,
                    from_sha256=current.sha256 if current else None,
                    to_version=rule_version,
                    to_sha256=sha256,
                    reason=reason,
                    actor=actor,
                    created_at=now,
                )
                connection.execute(
                    """
                    INSERT INTO rule_activations (
                        activation_id, request_id, site_key, rule_id, action,
                        from_version, from_sha256, to_version, to_sha256,
                        reason, actor, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        activation.activation_id,
                        activation.request_id,
                        activation.site_key,
                        activation.rule_id,
                        activation.action,
                        activation.from_version,
                        activation.from_sha256,
                        activation.to_version,
                        activation.to_sha256,
                        activation.reason,
                        activation.actor,
                        activation.created_at,
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise RuleActivationConflictError(
                    "activation request already exists or rule state conflicts"
                ) from exc
            except Exception:
                connection.rollback()
                raise
        site_rule = self.get_site_rule(site_key)
        if site_rule is None:
            raise RuleVersionError("site rule pointer was not written")
        return site_rule, activation

    def reject_rule_version(
        self,
        rule_id: str,
        rule_version: str,
        *,
        reason: str | None = None,
        feedback_id: str | None = None,
        retry: bool = False,
        actor: str = "local-user",
    ) -> RuleVersion:
        now = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute(
                    """
                    UPDATE rule_versions SET status = 'rejected'
                    WHERE rule_id = ? AND rule_version = ? AND status = 'candidate'
                    """,
                    (rule_id, rule_version),
                )
                if cursor.rowcount != 1:
                    raise RuleVersionError(
                        f"rule {rule_id}@{rule_version} is not a candidate"
                    )
                if feedback_id:
                    feedback = connection.execute(
                        "SELECT * FROM quality_feedback WHERE feedback_id = ?",
                        (feedback_id,),
                    ).fetchone()
                    if feedback is None:
                        raise RuleVersionError(f"unknown feedback: {feedback_id}")
                    if feedback["status"] != "AWAITING_ACTIVATION":
                        raise RuleVersionError(
                            "feedback is not awaiting activation"
                        )
                    next_status = "TRIAGED" if retry else "WONTFIX"
                    connection.execute(
                        """
                        UPDATE quality_feedback
                        SET status = ?, resolution = ?, resolution_note = ?,
                            resolved_by = ?, closed_at = ?, updated_at = ?
                        WHERE feedback_id = ?
                        """,
                        (
                            next_status,
                            None if retry else "WONTFIX",
                            reason,
                            None if retry else actor,
                            None if retry else now,
                            now,
                            feedback_id,
                        ),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        updated = self.get_rule_version(rule_id, rule_version)
        if updated is None:
            raise RuleVersionError("rule version not found after reject")
        return updated

    def update_feedback(self, feedback_id: str, **fields: Any) -> QualityFeedback:
        allowed = {
            "status",
            "triage",
            "triage_note",
            "triage_source",
            "repair_build_id",
            "rerun_task_id",
            "resolution",
            "resolution_note",
            "resolved_by",
            "closed_at",
            "updated_at",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown feedback fields: {sorted(unknown)}")
        fields.setdefault("updated_at", utc_now())
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE quality_feedback SET {assignments} WHERE feedback_id = ?",
                (*fields.values(), feedback_id),
            )
            if cursor.rowcount != 1:
                raise FeedbackNotFoundError(f"unknown feedback: {feedback_id}")
        feedback = self.get_feedback(feedback_id)
        if feedback is None:
            raise FeedbackNotFoundError(f"unknown feedback: {feedback_id}")
        return feedback

    def adopt_feedback_result(
        self, feedback: QualityFeedback, *, note: str | None, actor: str
    ) -> QualityFeedback:
        now = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = connection.execute(
                "SELECT state, outcome FROM tasks t WHERE task_id = ? AND batch_id = ? AND site_key = ? "
                "AND NOT EXISTS (SELECT 1 FROM site_rules s WHERE s.site_key = t.site_key "
                "AND (s.rule_id != t.plan_id OR s.rule_version != t.plan_version OR s.sha256 != t.rule_sha256))",
                (feedback.rerun_task_id, feedback.batch_id, feedback.site_key),
            ).fetchone()
            if task is None or task["state"] != "FINISHED" or task["outcome"] != "COMPLETED":
                raise FeedbackTransitionError("rerun must complete successfully before adoption")
            adopted = connection.execute(
                "UPDATE batch_sites SET delivery_task_id = ?, updated_at = ? "
                "WHERE batch_id = ? AND site_key = ? AND task_id = ? "
                "AND EXISTS (SELECT 1 FROM batches WHERE batch_id = ? AND archived_at IS NULL)",
                (feedback.rerun_task_id, now, feedback.batch_id, feedback.site_key,
                 feedback.rerun_task_id, feedback.batch_id),
            )
            if adopted.rowcount != 1:
                raise FeedbackTransitionError("rerun is no longer the current batch target task")
            closed = connection.execute(
                "UPDATE quality_feedback SET status = 'RESOLVED', resolution = 'RESOLVED', "
                "resolution_note = ?, resolved_by = ?, closed_at = ?, updated_at = ? "
                "WHERE feedback_id = ? AND status = 'RERUN_PENDING' AND rerun_task_id = ?",
                (note, actor, now, now, feedback.feedback_id, feedback.rerun_task_id),
            )
            if closed.rowcount != 1:
                raise FeedbackTransitionError("feedback no longer awaits review")
            connection.commit()
        updated = self.get_feedback(feedback.feedback_id)
        assert updated is not None
        return updated

    def triage_feedback(
        self,
        feedback_id: str,
        *,
        triage: str,
        note: str | None = None,
        duplicate_of: str | None = None,
        actor: str = "local-user",
        triage_source: str = "api",
    ) -> QualityFeedback:
        now = utc_now()
        if triage == "DUPLICATE":
            status = "WONTFIX"
            resolution = "DUPLICATE"
            resolved_by = actor
            closed_at = now
        else:
            status = "TRIAGED"
            resolution = None
            resolved_by = None
            closed_at = None
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE quality_feedback
                SET status = ?, triage = ?, triage_note = ?, triage_source = ?,
                    duplicate_of = ?, resolution = ?, resolved_by = ?,
                    closed_at = ?, updated_at = ?
                WHERE feedback_id = ? AND status IN ('OPEN', 'TRIAGED')
                """,
                (
                    status,
                    triage,
                    note,
                    triage_source,
                    duplicate_of if triage == "DUPLICATE" else None,
                    resolution,
                    resolved_by,
                    closed_at,
                    now,
                    feedback_id,
                ),
            )
            if cursor.rowcount != 1:
                exists = connection.execute(
                    "SELECT 1 FROM quality_feedback WHERE feedback_id = ?",
                    (feedback_id,),
                ).fetchone()
                if exists is None:
                    raise FeedbackNotFoundError(f"unknown feedback: {feedback_id}")
                raise FeedbackTransitionError(
                    f"feedback {feedback_id} is not open for triage"
                )
        feedback = self.get_feedback(feedback_id)
        if feedback is None:
            raise FeedbackNotFoundError(f"unknown feedback: {feedback_id}")
        return feedback


def _feedback_from_row(row: sqlite3.Row) -> QualityFeedback:
    samples = json_loads(row["samples_json"], [])
    if not isinstance(samples, list):
        samples = []
    return QualityFeedback(
        feedback_id=row["feedback_id"],
        request_id=row["request_id"],
        task_id=row["task_id"],
        batch_id=row["batch_id"],
        site_key=row["site_key"],
        rule_id=row["rule_id"],
        rule_version=row["rule_version"],
        rule_sha256=row["rule_sha256"],
        category=row["category"],
        samples=[str(value) for value in samples],
        expectation=row["expectation"],
        note=row["note"],
        scope=row["scope"],
        status=row["status"],
        triage=row["triage"],
        triage_note=row["triage_note"],
        triage_source=row["triage_source"],
        duplicate_of=row["duplicate_of"],
        repair_build_id=row["repair_build_id"],
        rerun_task_id=row["rerun_task_id"],
        resolution=row["resolution"],
        resolution_note=row["resolution_note"],
        created_by=row["created_by"],
        resolved_by=row["resolved_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        closed_at=row["closed_at"],
        request_json=row["request_json"],
    )


def _lease_valid(
    connection: sqlite3.Connection,
    lease: Lease,
    now: float | None = None,
) -> bool:
    current = time.time() if now is None else now
    row = connection.execute(
        """
        SELECT 1 FROM tasks
        WHERE task_id = ?
          AND lease_owner = ?
          AND lease_token = ?
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at > ?
        """,
        (lease.task_id, lease.owner, lease.token, current),
    ).fetchone()
    return row is not None


def _require_lease(
    connection: sqlite3.Connection,
    lease: Lease,
    now: float | None = None,
) -> None:
    if not _lease_valid(connection, lease, now):
        raise LeaseLostError(
            f"lease for task {lease.task_id} is no longer owned by {lease.owner}"
        )


def _reconcile_items(
    connection: sqlite3.Connection,
    task_id: str,
    max_attempts: int,
    now: str,
) -> dict[str, int]:
    max_attempts = max(int(max_attempts), 1)
    rows = connection.execute(
        """
        SELECT * FROM task_items
        WHERE task_id = ? AND state = 'IN_FLIGHT'
        """,
        (task_id,),
    ).fetchall()
    reset = 0
    failed = 0
    for row in rows:
        attempts = int(row["attempts"])
        if attempts >= max_attempts:
            result = {
                "reason": "attempts_exhausted",
                "failure_class": "transient",
                "attempts": attempts,
            }
            connection.execute(
                """
                UPDATE task_items
                SET state = 'FAILED', failure_class = 'transient',
                    result_json = ?, updated_at = ?
                WHERE task_id = ? AND item_id = ?
                """,
                (json_dumps(result), now, task_id, row["item_id"]),
            )
            failed += 1
        else:
            connection.execute(
                """
                UPDATE task_items
                SET state = 'PENDING', failure_class = NULL,
                    updated_at = ?
                WHERE task_id = ? AND item_id = ?
                """,
                (now, task_id, row["item_id"]),
            )
            reset += 1
    return {"in_flight": len(rows), "reset": reset, "failed": failed}


def _reject_in_flight(
    connection: sqlite3.Connection,
    task_id: str,
    now: str,
) -> int:
    result = {"reason": "task_cancelled", "failure_class": "blocked"}
    cursor = connection.execute(
        """
        UPDATE task_items
        SET state = 'FAILED', failure_class = 'blocked',
            result_json = ?, updated_at = ?
        WHERE task_id = ? AND state = 'IN_FLIGHT'
        """,
        (json_dumps(result), now, task_id),
    )
    return cursor.rowcount


def _normalize_batch_folder_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise BatchFolderNameError("分组名称不能为空")
    if len(value) > 80:
        raise BatchFolderNameError("分组名称不能超过 80 个字符")
    if "/" in value:
        raise BatchFolderNameError("分组名称不能包含 /")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise BatchFolderNameError("分组名称不能包含控制字符")
    return value


def _batch_folder_chain(
    connection: sqlite3.Connection, folder_id: str
) -> list[str]:
    chain: list[str] = []
    current: str | None = folder_id
    while current is not None:
        row = connection.execute(
            "SELECT parent_id FROM batch_folders WHERE folder_id = ?", (current,)
        ).fetchone()
        if row is None:
            raise BatchFolderNotFoundError(f"unknown batch folder: {current}")
        chain.append(current)
        current = row["parent_id"]
        if len(chain) > BATCH_FOLDER_MAX_DEPTH + 1:
            raise BatchFolderConflictError(
                f"分组最多 {BATCH_FOLDER_MAX_DEPTH} 层"
            )
    return chain


def _batch_folder_subtree_height(
    connection: sqlite3.Connection, folder_id: str
) -> int:
    height = 0
    stack: list[tuple[str, int]] = [(folder_id, 1)]
    while stack:
        current, level = stack.pop()
        height = max(height, level)
        if height > BATCH_FOLDER_MAX_DEPTH:
            raise BatchFolderConflictError(
                f"分组最多 {BATCH_FOLDER_MAX_DEPTH} 层"
            )
        children = connection.execute(
            "SELECT folder_id FROM batch_folders WHERE parent_id = ?", (current,)
        ).fetchall()
        stack.extend((child["folder_id"], level + 1) for child in children)
    return height


def _ensure_batch_folder_name_available(
    connection: sqlite3.Connection,
    name: str,
    parent_id: str | None,
    *,
    exclude_id: str | None,
) -> None:
    row = connection.execute(
        """
        SELECT folder_id FROM batch_folders
        WHERE COALESCE(parent_id, '') = COALESCE(?, '')
          AND lower(name) = lower(?)
          AND folder_id <> ?
        """,
        (parent_id, name, exclude_id or ""),
    ).fetchone()
    if row is not None:
        raise BatchFolderConflictError(f"同级已存在分组：{name}")


def _batch_folder_from_row(row: sqlite3.Row) -> BatchFolder:
    return BatchFolder(
        folder_id=row["folder_id"],
        name=row["name"],
        parent_id=row["parent_id"],
        sort_order=row["sort_order"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _workbench_node_from_row(row: sqlite3.Row) -> WorkbenchNode:
    return WorkbenchNode(
        node_id=row["node_id"],
        node_type=row["node_type"],
        name=row["name"],
        parent_id=row["parent_id"],
        sort_order=int(row["sort_order"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _workbench_task_def_from_row(row: sqlite3.Row) -> WorkbenchTaskDef:
    return WorkbenchTaskDef(
        node_id=row["node_id"],
        input_url=row["input_url"],
        domain=row["domain"],
        site_key=row["site_key"],
        batch_id=row["batch_id"],
        country=row["country"],
        language=row["language"],
        market=row["market"],
        category=row["category"],
        task_type=row["task_type"],
        collection_mode=row["collection_mode"],
        rule_id=row["rule_id"],
        rule_version=row["rule_version"],
        rule_path=row["rule_path"],
        limits=json_loads(row["limits_json"], {}),
        proxy=row["proxy"],
        note=row["note"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _batch_from_row(row: sqlite3.Row) -> Batch:
    return Batch(
        batch_id=row["batch_id"],
        name=row["name"],
        country=row["country"],
        market=row["market"],
        language=row["language"],
        category=row["category"],
        note=row["note"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        archived_at=row["archived_at"],
        collection_mode=dict(row).get("collection_mode"),
        folder_id=dict(row).get("folder_id"),
    )


def _batch_site_from_row(row: sqlite3.Row) -> BatchSite:
    return BatchSite(
        batch_id=row["batch_id"],
        site_key=row["site_key"],
        domain=row["domain"],
        input_value=row["input_value"],
        readiness=row["readiness"],
        rule_id=row["rule_id"],
        rule_version=row["rule_version"],
        rule_path=row["rule_path"],
        task_id=row["task_id"],
        delivery_task_id=dict(row).get("delivery_task_id"),
        build_id=row["build_id"],
        proxy=row["proxy"],
        note=row["note"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _build_from_row(row: sqlite3.Row) -> BuildRecord:
    return BuildRecord(
        build_id=row["build_id"],
        batch_id=row["batch_id"],
        site_key=row["site_key"],
        state=row["state"],
        outcome=row["outcome"],
        workspace=row["workspace"],
        session_id=row["session_id"],
        model=json_loads(row["model_json"], {}) or None,
        proxy=row["proxy"],
        error=row["error"],
        rule_id=row["rule_id"],
        rule_version=row["rule_version"],
        rule_path=row["rule_path"],
        mode=row["mode"],
        feedback_id=row["feedback_id"],
        request_id=row["request_id"],
        request=json_loads(row["request_json"], {}),
        source_rule_version=row["source_rule_version"],
        source_rule_sha256=row["source_rule_sha256"],
        target_rule_version=row["target_rule_version"],
        target_rule_sha256=row["target_rule_sha256"],
        error_class=row["error_class"],
        change_summary=json_loads(row["change_summary_json"], {}),
        validation=json_loads(row["validation_json"], {}),
        evidence_sha256=row["evidence_sha256"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _build_continuation_from_row(row: sqlite3.Row) -> BuildContinuation:
    return BuildContinuation(
        request_id=row["request_id"],
        build_id=row["build_id"],
        message_sha256=row["message_sha256"],
        message_chars=row["message_chars"],
        state=row["state"],
        error=row["error"],
        created_at=row["created_at"],
    )


def _task_from_row(row: sqlite3.Row) -> Task:
    return Task(
        task_id=row["task_id"],
        plan_id=row["plan_id"],
        plan_version=row["plan_version"],
        task_type=row["task_type"],
        state=row["state"],
        outcome=row["outcome"],
        stop_reason=row["stop_reason"],
        input=json_loads(row["input_json"], {}),
        limits=json_loads(row["limits_json"], {}),
        output=json_loads(row["output_json"], {}),
        counters=json_loads(row["counters_json"], {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        site_key=row["site_key"],
        domain_key=row["domain_key"],
        market=row["market"],
        rule_path=row["rule_path"],
        rule_sha256=row["rule_sha256"],
        archived_at=row["archived_at"],
        batch_id=row["batch_id"],
        lease_owner=row["lease_owner"],
        lease_token=int(row["lease_token"] or 0),
        lease_expires_at=row["lease_expires_at"],
        lease_heartbeat_at=row["lease_heartbeat_at"],
    )


def _rule_version_from_row(row: sqlite3.Row) -> RuleVersion:
    return RuleVersion(
        rule_id=row["rule_id"],
        rule_version=row["rule_version"],
        sha256=row["sha256"],
        parent_version=row["parent_version"],
        status=row["status"],
        source_build_id=row["source_build_id"],
        source_feedback_id=row["source_feedback_id"],
        path=row["path"],
        created_at=row["created_at"],
        activated_at=row["activated_at"],
        activated_by=row["activated_by"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"],
        notes=row["notes"],
    )


def _site_rule_from_row(row: sqlite3.Row) -> SiteRule:
    return SiteRule(
        site_key=row["site_key"],
        rule_id=row["rule_id"],
        rule_version=row["rule_version"],
        sha256=row["sha256"],
        path=row["path"],
        updated_at=row["updated_at"],
    )


def _rule_activation_from_row(row: sqlite3.Row) -> RuleActivation:
    return RuleActivation(
        activation_id=row["activation_id"],
        request_id=row["request_id"],
        site_key=row["site_key"],
        rule_id=row["rule_id"],
        action=row["action"],
        from_version=row["from_version"],
        from_sha256=row["from_sha256"],
        to_version=row["to_version"],
        to_sha256=row["to_sha256"],
        reason=row["reason"],
        actor=row["actor"],
        created_at=row["created_at"],
    )


def _item_from_row(row: sqlite3.Row, *, state: str | None = None) -> WorkItem:
    return WorkItem(
        task_id=row["task_id"],
        item_id=row["item_id"],
        item_type=row["item_type"],
        url=row["url"],
        normalized_url=row["normalized_url"],
        stage=row["stage"],
        state=state or row["state"],
        attempts=int(row["attempts"]),
        failure_class=row["failure_class"],
        parent_url=row["parent_url"],
        discovered_from=row["discovered_from"],
        result=json_loads(row["result_json"], {}),
        updated_at=row["updated_at"],
    )
