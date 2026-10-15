"""Bounded task-scoped retrieval without a model or vector index dependency."""

from __future__ import annotations

import json
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
import sqlite3

from sce.core.models import jsonable
from sce.knowledge.models import KnowledgeRecord


class KnowledgeStore:
    """Persist append-only knowledge; an amended claim needs a new record ID.

    Can share TaskStore's selected SQLite file. This is lexical retrieval of
    explicitly associated records, not a similarity or cross-project engine.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_records (
                    id TEXT PRIMARY KEY,
                    claim TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_task_scope (
                    record_id TEXT NOT NULL REFERENCES knowledge_records(id),
                    task_id TEXT NOT NULL,
                    PRIMARY KEY(record_id, task_id)
                );
                CREATE INDEX IF NOT EXISTS knowledge_task_lookup ON knowledge_task_scope(task_id);
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def append(self, record: KnowledgeRecord) -> str:
        record.__post_init__()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO knowledge_records(id, claim, payload) VALUES (?, ?, ?)",
                (record.id, record.claim, json.dumps(jsonable(record), ensure_ascii=False, allow_nan=False)),
            )
            connection.executemany(
                "INSERT INTO knowledge_task_scope(record_id, task_id) VALUES (?, ?)",
                [(record.id, task_id) for task_id in dict.fromkeys(record.task_ids)],
            )
        return record.id

    def get(self, record_id: str) -> KnowledgeRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM knowledge_records WHERE id=?", (record_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown knowledge record: {record_id}")
        return KnowledgeRecord.from_dict(json.loads(row[0]))

    def retrieve(self, task_id: str, query: str = "", *, limit: int = 8, max_chars: int = 12000) -> list[KnowledgeRecord]:
        """Return complete records inside both count and serialized character bounds.

        Query is a literal substring of the original claim (SQLite LIKE, with
        ASCII case-insensitivity and case-sensitive non-ASCII characters).
        Oversize records are omitted, never cut away from their provenance. Only
        the newest 128 matches are considered. Empty output means no qualifying
        bounded evidence, not proof that no relevant knowledge exists.
        """
        if not task_id.strip():
            raise ValueError("Retrieval requires an explicit task_id")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if type(max_chars) is not int or not 2 <= max_chars <= 100000:
            raise ValueError("max_chars must be between 2 and 100000")
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT k.payload FROM knowledge_records k "
                "JOIN knowledge_task_scope s ON s.record_id=k.id "
                "WHERE s.task_id=? AND k.claim LIKE ? ESCAPE '\\' "
                "ORDER BY k.rowid DESC LIMIT 128",
                (task_id, f"%{escaped}%"),
            ).fetchall()
        results: list[KnowledgeRecord] = []
        used = 2  # JSON list brackets; separators counted below.
        for (payload,) in rows:
            added = len(payload) + (2 if results else 0)
            if used + added <= max_chars:
                results.append(KnowledgeRecord.from_dict(json.loads(payload)))
                used += added
                if len(results) == limit:
                    break
        return results
