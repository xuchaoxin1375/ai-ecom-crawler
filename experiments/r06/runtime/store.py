"""SQLite task ledger for the R06 runtime prototype."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import Task, WorkItem, json_dumps, json_loads, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    plan_version TEXT NOT NULL,
    task_type TEXT NOT NULL,
    state TEXT NOT NULL,
    outcome TEXT,
    stop_reason TEXT,
    input_json TEXT NOT NULL,
    limits_json TEXT NOT NULL,
    output_json TEXT NOT NULL,
    counters_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

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
    "updated_at",
}


class TaskStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            task_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(tasks)")
            }
            if "plan_id" not in task_columns and "rule_id" in task_columns:
                connection.execute("ALTER TABLE tasks RENAME COLUMN rule_id TO plan_id")
                connection.execute(
                    "ALTER TABLE tasks RENAME COLUMN rule_version TO plan_version"
                )
            item_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(task_items)")
            }
            if "failure_class" not in item_columns:
                connection.execute(
                    "ALTER TABLE task_items ADD COLUMN failure_class TEXT"
                )

    def create_task(self, task: Task) -> None:
        with self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id, plan_id, plan_version, task_type, state, outcome,
                        stop_reason, input_json, limits_json, output_json,
                        counters_json, created_at, updated_at, started_at, finished_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task.task_id,
                        task.plan_id,
                        task.plan_version,
                        task.task_type,
                        task.state,
                        task.outcome,
                        task.stop_reason,
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
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"task already exists: {task.task_id}") from exc

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

    def update_task(self, task_id: str, **fields: Any) -> None:
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
        with self._connect() as connection:
            connection.execute(
                f"UPDATE tasks SET {', '.join(assignments)} WHERE task_id = ?",
                values,
            )

    def add_item(self, item: WorkItem) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO task_items (
                    task_id, item_id, item_type, url, normalized_url, stage,
                    state, attempts, failure_class, parent_url, discovered_from,
                    result_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
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
                ),
            )
            return cursor.rowcount == 1

    def claim_items(self, task_id: str, limit: int) -> list[WorkItem]:
        if limit < 1:
            return []
        claimed: list[WorkItem] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
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
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE task_items
                SET state = ?, failure_class = ?, result_json = ?, updated_at = ?
                WHERE task_id = ? AND item_id = ?
                """,
                (
                    state,
                    failure_class,
                    json_dumps(result or {}),
                    utc_now(),
                    task_id,
                    item_id,
                ),
            )

    def reconcile_task(self, task_id: str, max_attempts: int) -> dict[str, int]:
        """Reset in-flight items after a crash; fail those out of attempts."""
        max_attempts = max(int(max_attempts), 1)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = connection.execute(
                    """
                    SELECT * FROM task_items
                    WHERE task_id = ? AND state = 'IN_FLIGHT'
                    """,
                    (task_id,),
                ).fetchall()
                reset = 0
                failed = 0
                now = utc_now()
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
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return {"in_flight": len(rows), "reset": reset, "failed": failed}

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
