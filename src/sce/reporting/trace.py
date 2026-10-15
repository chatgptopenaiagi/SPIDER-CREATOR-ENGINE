"""Append-only task history with summaries, reasoning, and attributable evidence."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4
import html
import json
import re
import sqlite3

from sce.core.models import OperationOutcome, VerificationStatus, jsonable, utc_now


@dataclass
class TraceEvent:
    task_id: str
    stage: str
    status: str
    summary: str
    decision: str | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    resource_ids: list[str] = field(default_factory=list)
    operation_id: str | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    objective: str | None = None
    outcome: OperationOutcome | None = None
    verification: VerificationStatus = VerificationStatus.NOT_RUN
    selected_components: list[str] = field(default_factory=list)
    planned_actions: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid4()))
    recorded_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for name in ("task_id", "stage", "status", "summary", "id", "recorded_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Trace event requires {name}")
        if self.status not in {"planned", "executed", "verified", "failed", "not_run", "inconclusive"}:
            raise ValueError(f"Unsupported trace status: {self.status}")
        self.outcome = OperationOutcome(self.outcome) if self.outcome is not None else None
        self.verification = VerificationStatus(self.verification)
        for name in ("evidence", "artifacts", "planned_actions"):
            value = getattr(self, name)
            if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
                raise ValueError(f"Trace {name} must be a list of objects")
        for name in ("resource_ids", "unknowns", "selected_components", "errors"):
            value = getattr(self, name)
            if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
                raise ValueError(f"Trace {name} must be a list of nonempty strings")
        if self.status == "verified" and (self.verification != VerificationStatus.PASSED or not self.evidence):
            raise ValueError("Verified trace events require passed declared verification and evidence")

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "TraceEvent":
        return cls(**values)


class TraceStore:
    def __init__(self, database: str | Path):
        self.path = Path(database).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS engineering_trace (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS engineering_trace_task ON engineering_trace(task_id);
            """)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def append(self, event: TraceEvent) -> str:
        event.__post_init__()
        with self._connect() as connection:
            connection.execute("INSERT INTO engineering_trace VALUES (?, ?, ?)",
                               (event.id, event.task_id, json.dumps(jsonable(event), ensure_ascii=False, allow_nan=False)))
        return event.id

    def read(self, task_id: str, level: int = 1, *, limit: int = 1000,
             offset: int = 0) -> list[dict[str, Any]]:
        """Chronological, task-scoped pages. Level 3 exposes original event evidence."""
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("Trace reads require an explicit task_id")
        if type(level) is not int or level not in {1, 2, 3}:
            raise ValueError("Trace level must be 1, 2, or 3")
        if type(limit) is not int or not 1 <= limit <= 1000 or type(offset) is not int or offset < 0:
            raise ValueError("Trace pages require limit 1..1000 and nonnegative offset")
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM engineering_trace WHERE task_id=? ORDER BY rowid LIMIT ? OFFSET ?",
                                      (task_id, limit, offset)).fetchall()
        keys = {"id", "task_id", "stage", "status", "summary", "outcome", "verification", "recorded_at"}
        if level >= 2:
            keys |= {"objective", "decision", "resource_ids", "selected_components", "planned_actions", "operation_id", "unknowns"}
        return [values if level == 3 else {key: value for key, value in values.items() if key in keys}
                for (payload,) in rows for values in [json.loads(payload)]]

    def render(self, task_id: str, level: int = 1, format: str = "json", *,
               limit: int = 1000, offset: int = 0) -> str:
        events = self.read(task_id, level, limit=limit, offset=offset)
        payload = json.dumps({"task_id": task_id, "level": level, "offset": offset, "limit": limit,
                              "events": events}, indent=2, ensure_ascii=False, allow_nan=False)
        if format == "json":
            return payload + "\n"
        if format == "markdown":
            fence = "`" * max(3, max((len(part) for part in re.findall(r"`+", payload)), default=0) + 1)
            return f"# SCE engineering trace\n\nLevel {level}: {'What happened' if level == 1 else 'Why this route' if level == 2 else 'Supporting evidence'}\n\n{fence}json\n{payload}\n{fence}\n"
        if format == "html":
            return ('<!doctype html><html lang="en"><meta charset="utf-8"><title>SCE engineering trace</title>'
                    f'<body><h1>SCE engineering trace</h1><p>Level {level}</p><pre>{html.escape(payload)}</pre></body></html>\n')
        raise ValueError(f"Unsupported trace format: {format}")
