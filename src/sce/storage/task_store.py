"""SQLite checkpoints for tasks, cancellation requests, and canonical records."""

from __future__ import annotations

import json
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
import sqlite3

from sce.core.models import OperationRecord, Task, jsonable, utc_now


class TaskStore:
    """Store at the explicitly selected path; errors never cause a fallback path.

    Each method opens a short-lived connection. A checkpoint writes its task and
    operation together, while a cancellation request is preserved independently.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY,
                    task_id TEXT,
                    payload TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS operations_task ON operations(task_id);
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _save_task(connection: sqlite3.Connection, task: Task) -> None:
        connection.execute(
            "INSERT INTO tasks(id, payload, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, "
            "updated_at=excluded.updated_at",
            (task.id, json.dumps(jsonable(task), allow_nan=False), utc_now()),
        )

    @staticmethod
    def _save_operation(connection: sqlite3.Connection, record: OperationRecord) -> None:
        # Records are evidence, so duplicate identifiers cannot overwrite history.
        connection.execute(
            "INSERT INTO operations(id, task_id, payload, recorded_at) VALUES (?, ?, ?, ?)",
            (record.id, record.task_id, json.dumps(jsonable(record), allow_nan=False), utc_now()),
        )

    def create_task(self, task: Task) -> None:
        """Insert a fresh task, rejecting replacement of an existing task ID."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO tasks(id, payload, updated_at) VALUES (?, ?, ?)",
                (task.id, json.dumps(jsonable(task), allow_nan=False), utc_now()),
            )

    def save_task(self, task: Task) -> None:
        with self._connect() as connection:
            self._save_task(connection, task)

    def checkpoint(self, task: Task, record: OperationRecord | None = None) -> None:
        with self._connect() as connection:
            if record is not None:
                if record.task_id != task.id:
                    raise ValueError("Operation task_id does not match checkpoint task")
                self._save_operation(connection, record)
            self._save_task(connection, task)

    def get_task(self, task_id: str) -> Task:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown task: {task_id}")
        return Task.from_dict(json.loads(row[0]))

    def list_tasks(self) -> list[Task]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM tasks ORDER BY rowid").fetchall()
        return [Task.from_dict(json.loads(row[0])) for row in rows]

    def save_operation(self, record: OperationRecord) -> None:
        with self._connect() as connection:
            self._save_operation(connection, record)

    def get_operation(self, operation_id: str) -> OperationRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM operations WHERE id=?", (operation_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown operation: {operation_id}")
        return OperationRecord.from_dict(json.loads(row[0]))

    def operations_for_task(self, task_id: str) -> list[OperationRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM operations WHERE task_id=? ORDER BY rowid", (task_id,)
            ).fetchall()
        return [OperationRecord.from_dict(json.loads(row[0])) for row in rows]

    def request_cancellation(self, task_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET cancel_requested=1, updated_at=? WHERE id=?", (utc_now(), task_id)
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Unknown task: {task_id}")

    def cancellation_requested(self, task_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT cancel_requested FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown task: {task_id}")
        return bool(row[0])
