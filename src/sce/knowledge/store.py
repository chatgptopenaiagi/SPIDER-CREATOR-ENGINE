"""Bounded task-scoped retrieval without a model or vector index dependency."""

from __future__ import annotations

import json
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from sce.core.models import OperationRecord, VerificationStatus, jsonable, utc_now
from sce.knowledge.models import (KnowledgeRecord, KnowledgeRelationship, MemoryCandidate,
                                  Provenance, ProvenanceCategory, evaluate_applicability)


class KnowledgeStore:
    """Persist append-only knowledge; an amended claim needs a new record ID.

    Can share TaskStore's selected SQLite file. Historical retrieval is an
    explicit resource-scoped request; it never expands execution authority.
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
                CREATE TABLE IF NOT EXISTS knowledge_resource_scope (
                    record_id TEXT PRIMARY KEY REFERENCES knowledge_records(id),
                    resource_id TEXT NOT NULL,
                    revision TEXT
                );
                CREATE INDEX IF NOT EXISTS knowledge_resource_lookup ON knowledge_resource_scope(resource_id);
                CREATE TABLE IF NOT EXISTS knowledge_relationships (
                    id TEXT PRIMARY KEY,
                    source_record_id TEXT NOT NULL REFERENCES knowledge_records(id),
                    target_record_id TEXT NOT NULL REFERENCES knowledge_records(id),
                    task_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS knowledge_relationship_lookup ON knowledge_relationships(task_id);
                CREATE TABLE IF NOT EXISTS knowledge_scope_events (
                    id TEXT PRIMARY KEY,
                    record_id TEXT NOT NULL REFERENCES knowledge_records(id),
                    task_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                """
            )
            # Additive migration: old payloads and scopes remain unchanged.
            for record_id, payload in connection.execute(
                "SELECT id, payload FROM knowledge_records WHERE id NOT IN (SELECT record_id FROM knowledge_resource_scope)"
            ).fetchall():
                values = json.loads(payload)
                if values.get("resource_id"):
                    connection.execute("INSERT INTO knowledge_resource_scope VALUES (?, ?, ?)",
                                       (record_id, values["resource_id"], values.get("resource_revision")))

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
            if record.resource_id:
                connection.execute("INSERT INTO knowledge_resource_scope VALUES (?, ?, ?)",
                                   (record.id, record.resource_id, record.resource_revision))
        return record.id

    def get(self, record_id: str) -> KnowledgeRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM knowledge_records WHERE id=?", (record_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown knowledge record: {record_id}")
        return KnowledgeRecord.from_dict(json.loads(row[0]))

    def retrieve(self, task_id: str, query: str = "", *, resource_id: str | None = None,
                 limit: int = 8, max_chars: int = 12000) -> list[KnowledgeRecord]:
        """Return complete records inside both count and serialized character bounds.

        Query is a literal substring of the original claim (SQLite LIKE, with
        ASCII case-insensitivity and case-sensitive non-ASCII characters).
        Oversize records are omitted, never cut away from their provenance. Only
        the newest 128 matches are considered. Empty output means no qualifying
        bounded evidence, not proof that no relevant knowledge exists.
        """
        self._validate_bounds(task_id, limit, max_chars)
        if resource_id is not None and not resource_id.strip():
            raise ValueError("resource_id must be nonempty")
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT k.payload FROM knowledge_records k "
                "JOIN knowledge_task_scope s ON s.record_id=k.id "
                "WHERE s.task_id=? AND k.claim LIKE ? ESCAPE '\\' "
                "AND (? IS NULL OR k.id IN (SELECT record_id FROM knowledge_resource_scope WHERE resource_id=?)) "
                "ORDER BY k.rowid DESC LIMIT 128",
                (task_id, f"%{escaped}%", resource_id, resource_id),
            ).fetchall()
        results: list[KnowledgeRecord] = []
        used = 2  # JSON list brackets; separators counted below.
        for (payload,) in rows:
            record = KnowledgeRecord.from_dict(json.loads(payload))
            # Count restored defaults too, including migrated legacy records.
            added = len(json.dumps(jsonable(record), ensure_ascii=False, allow_nan=False)) + (2 if results else 0)
            if used + added <= max_chars:
                results.append(record)
                used += added
                if len(results) == limit:
                    break
        return results

    @staticmethod
    def _validate_bounds(task_id: str, limit: int, max_chars: int) -> None:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("Retrieval requires an explicit task_id")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if type(max_chars) is not int or not 2 <= max_chars <= 100000:
            raise ValueError("max_chars must be between 2 and 100000")

    def find_candidates(self, task_id: str, resource_id: str, query: str = "", *,
                        environment: dict[str, Any] | None = None, resource_revision: str | None = None,
                        include_history: bool = False, limit: int = 8, max_chars: int = 12000) -> list[MemoryCandidate]:
        """Opt in to cross-session resource history; return candidates, never a repair verdict."""
        self._validate_bounds(task_id, limit, max_chars)
        if not isinstance(resource_id, str) or not resource_id.strip():
            raise ValueError("Historical retrieval requires an explicit resource_id")
        if type(include_history) is not bool:
            raise ValueError("include_history must be an explicit boolean")
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT k.payload, EXISTS(SELECT 1 FROM knowledge_task_scope s WHERE s.record_id=k.id AND s.task_id=?) "
                "FROM knowledge_records k JOIN knowledge_resource_scope r ON r.record_id=k.id "
                "WHERE r.resource_id=? AND k.claim LIKE ? ESCAPE '\\' "
                "AND (? OR EXISTS(SELECT 1 FROM knowledge_task_scope s WHERE s.record_id=k.id AND s.task_id=?)) "
                "ORDER BY k.rowid DESC LIMIT 128",
                (task_id, resource_id, f"%{escaped}%", include_history, task_id),
            ).fetchall()
        results: list[MemoryCandidate] = []
        used = 2
        for payload, in_scope in rows:
            record = KnowledgeRecord.from_dict(json.loads(payload))
            candidate = MemoryCandidate(record, evaluate_applicability(record, environment, resource_revision), not bool(in_scope))
            added = len(json.dumps(jsonable(candidate), ensure_ascii=False, allow_nan=False)) + (2 if results else 0)
            if used + added <= max_chars:
                results.append(candidate)
                used += added
                if len(results) == limit:
                    break
        return results

    def reuse(self, record_id: str, task_id: str, *, actor: str, reason: str,
              environment: dict[str, Any] | None = None, resource_revision: str | None = None):
        """Associate historical information with a new task, preserving the original payload."""
        for value in (task_id, actor, reason):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Reuse requires explicit task, actor, and reason")
        assessment = evaluate_applicability(self.get(record_id), environment, resource_revision)
        event = {"actor": actor, "reason": reason, "recorded_at": utc_now(),
                 "applicability": jsonable(assessment), "environment": environment or {},
                 "resource_revision": resource_revision, "effect": "retrieval_scope_only"}
        with self._connect() as connection:
            connection.execute("INSERT OR IGNORE INTO knowledge_task_scope VALUES (?, ?)", (record_id, task_id))
            connection.execute("INSERT INTO knowledge_scope_events VALUES (?, ?, ?, ?)",
                               (str(uuid4()), record_id, task_id, json.dumps(event, ensure_ascii=False, allow_nan=False)))
        return assessment

    def scope_history(self, record_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT task_id, payload FROM knowledge_scope_events WHERE record_id=? ORDER BY rowid",
                                      (record_id,)).fetchall()
        return [{"task_id": task_id, **json.loads(payload)} for task_id, payload in rows]

    def append_relationship(self, relationship: KnowledgeRelationship) -> str:
        relationship.__post_init__()
        with self._connect() as connection:
            self._insert_relationship(connection, relationship)
        return relationship.id

    @staticmethod
    def _insert_relationship(connection: sqlite3.Connection, relationship: KnowledgeRelationship) -> None:
        for record_id in (relationship.source_record_id, relationship.target_record_id):
            if connection.execute("SELECT 1 FROM knowledge_task_scope WHERE record_id=? AND task_id=?",
                                  (record_id, relationship.task_id)).fetchone() is None:
                raise ValueError("Both relationship records must be explicitly in the task scope")
        connection.execute("INSERT INTO knowledge_relationships VALUES (?, ?, ?, ?, ?)",
                           (relationship.id, relationship.source_record_id, relationship.target_record_id,
                            relationship.task_id, json.dumps(jsonable(relationship), ensure_ascii=False, allow_nan=False)))

    def relationships(self, task_id: str, record_id: str | None = None, *, limit: int = 100) -> list[KnowledgeRelationship]:
        self._validate_bounds(task_id, limit, 100000)
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM knowledge_relationships WHERE task_id=? "
                                      "AND (? IS NULL OR source_record_id=? OR target_record_id=?) ORDER BY rowid LIMIT ?",
                                      (task_id, record_id, record_id, record_id, limit)).fetchall()
        return [KnowledgeRelationship.from_dict(json.loads(payload)) for (payload,) in rows]

    def correct(self, record_id: str, claim: str, *, task_id: str, actor: str, reason: str,
                supporting_evidence: list[dict[str, Any]] | None = None) -> KnowledgeRecord:
        """Append a human correction and its contradiction link atomically."""
        if not actor.strip() or not reason.strip():
            raise ValueError("Human corrections require an actor and reason")
        original = self.get(record_id)
        source = Provenance(source=f"knowledge:{record_id}", method=f"Human correction: {reason}", actor=actor)
        correction = KnowledgeRecord(claim=claim, provenance=[source], task_ids=[task_id], kind="correction",
                                     resource_id=original.resource_id, resource_revision=original.resource_revision,
                                     environment=dict(original.environment), applicability=dict(original.applicability),
                                     related_record_ids=[record_id], contradictory_evidence=[{"record_id": record_id, "reason": reason}],
                                     supporting_evidence=supporting_evidence or [],
                                     limitations=["Attributed human correction; independent verification is not implied."])
        relationship = KnowledgeRelationship(correction.id, record_id, "corrects", task_id, [source])
        with self._connect() as connection:
            if connection.execute("SELECT 1 FROM knowledge_task_scope WHERE record_id=? AND task_id=?", (record_id, task_id)).fetchone() is None:
                raise ValueError("Original record must be explicitly in the correction task scope")
            connection.execute("INSERT INTO knowledge_records VALUES (?, ?, ?)",
                               (correction.id, correction.claim, json.dumps(jsonable(correction), ensure_ascii=False, allow_nan=False)))
            connection.execute("INSERT INTO knowledge_task_scope VALUES (?, ?)", (correction.id, task_id))
            if correction.resource_id:
                connection.execute("INSERT INTO knowledge_resource_scope VALUES (?, ?, ?)",
                                   (correction.id, correction.resource_id, correction.resource_revision))
            self._insert_relationship(connection, relationship)
        return correction

    def record_operation(self, operation: OperationRecord, *, resource_id: str | None = None,
                         resource_revision: str | None = None, environment: dict[str, Any] | None = None) -> KnowledgeRecord:
        """Retain actual operation evidence without interpreting success as functionality."""
        operation.__post_init__()
        if not operation.task_id:
            raise ValueError("Operation knowledge requires an explicit task scope")
        # Structural discovery, copying, packaging integrity and synthesis may
        # pass their own checks without running an application acceptance test.
        # Promote only qualified functional adapters with explicit verification
        # evidence. Unknown adapters remain observations until their procedure
        # is deliberately integrated; a successful summary flag is insufficient.
        observed_tests = (
            operation.capability_id in {"application.verify", "python.build", "qasc.create_python"}
            and operation.outcome.value == "succeeded"
            and operation.verification == VerificationStatus.PASSED
            and any(item.kind == "verification" for item in operation.evidence)
        )
        record = KnowledgeRecord(
            claim=f"{operation.capability_id}: outcome={operation.outcome.value}; declared verification={operation.verification.value}",
            provenance=[Provenance(source=f"operation:{operation.id}", method="Canonical operation evidence capture",
                                   category=ProvenanceCategory.VERIFIED_TEST_EVIDENCE if observed_tests else ProvenanceCategory.OBSERVED_BEHAVIOR)],
            task_ids=[operation.task_id], resource_id=resource_id, resource_revision=resource_revision,
            supporting_evidence=[jsonable(item) for item in operation.evidence], environment=environment or {},
            limitations=["Verification scope is limited to the procedures and evidence in the operation record."],
            metadata={"operation": jsonable(operation)},
        )
        self.append(record)
        return record
