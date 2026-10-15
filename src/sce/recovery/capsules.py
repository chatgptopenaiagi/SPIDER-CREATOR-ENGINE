"""Reusable failure records explicitly remain unresolved engineering evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from sce.core.models import jsonable, utc_now
from sce.knowledge.models import KnowledgeRecord, Provenance


@dataclass
class RepairAttempt:
    description: str
    outcome: str = "unknown"
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.description.strip():
            raise ValueError("Repair attempt requires a description")
        if self.outcome not in {"unknown", "failed", "partial", "observed_success"}:
            raise ValueError("Unsupported repair attempt outcome")


@dataclass
class FailureCapsule:
    project_identity: str
    provenance: list[Provenance]
    relevant_errors: list[str]
    id: str = field(default_factory=lambda: str(uuid4()))
    source_revision: str | None = None
    environment: dict[str, Any] = field(default_factory=dict)
    reproduction_instructions: list[str] = field(default_factory=list)
    attempted_repairs: list[RepairAttempt] = field(default_factory=list)
    partial_artifacts: list[dict[str, Any]] = field(default_factory=list)
    unresolved_hypotheses: list[str] = field(default_factory=list)
    suggested_next_checks: list[str] = field(default_factory=list)
    supporting_evidence: list[dict[str, Any]] = field(default_factory=list)
    contradictory_evidence: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    state: str = field(default="unresolved", init=False)

    def __post_init__(self) -> None:
        if not self.project_identity.strip() or not self.id.strip():
            raise ValueError("Failure capsule requires project and failure identities")
        if not self.provenance:
            raise ValueError("Failure capsule requires provenance")
        for source in self.provenance:
            source.__post_init__()
        if not self.relevant_errors or any(not error.strip() for error in self.relevant_errors):
            raise ValueError("Failure capsule requires observed error information")

    def to_knowledge_record(self, task_ids: list[str]) -> KnowledgeRecord:
        self.__post_init__()
        if self.state != "unresolved":
            raise ValueError("A failure capsule does not establish resolution")
        return KnowledgeRecord(
            id=self.id, kind="failure_capsule", task_ids=task_ids,
            claim=f"Unresolved failure for {self.project_identity}: {self.relevant_errors[0]}",
            provenance=self.provenance, environment=self.environment,
            supporting_evidence=self.supporting_evidence,
            contradictory_evidence=self.contradictory_evidence,
            limitations=[*self.limitations, "Historical observations do not establish future applicability or resolution."],
            metadata={"capsule": jsonable(self)},
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FailureCapsule":
        values = dict(data)
        if values.pop("state", "unresolved") != "unresolved":
            raise ValueError("A failure capsule does not establish resolution")
        values["provenance"] = [Provenance(**source) for source in data["provenance"]]
        values["attempted_repairs"] = [RepairAttempt(**attempt) for attempt in data.get("attempted_repairs", [])]
        return cls(**values)
