"""Knowledge claims retain sources, conditions, and contrary evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from sce.core.models import utc_now


@dataclass
class Provenance:
    source: str
    method: str
    observed_at: str = field(default_factory=utc_now)
    source_revision: str | None = None
    content_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.source.strip() or not self.method.strip() or not self.observed_at.strip():
            raise ValueError("Provenance requires source, observation method, and observation time")
        if self.content_sha256 is not None and (
            len(self.content_sha256) != 64 or any(character not in "0123456789abcdefABCDEF" for character in self.content_sha256)
        ):
            raise ValueError("content_sha256 must be a 64-character hexadecimal digest")


@dataclass
class KnowledgeRecord:
    claim: str
    provenance: list[Provenance]
    task_ids: list[str]
    kind: str = "observation"
    id: str = field(default_factory=lambda: str(uuid4()))
    recorded_at: str = field(default_factory=utc_now)
    supporting_evidence: list[dict[str, Any]] = field(default_factory=list)
    contradictory_evidence: list[dict[str, Any]] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    related_record_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.claim.strip():
            raise ValueError("Knowledge records require an identity and an original claim")
        if not self.provenance:
            raise ValueError("Every knowledge claim requires provenance")
        for source in self.provenance:
            if not isinstance(source, Provenance):
                raise TypeError("Knowledge provenance entries must be Provenance instances")
            source.__post_init__()
        if not self.task_ids or any(not task_id.strip() for task_id in self.task_ids):
            raise ValueError("Knowledge records require an explicit task scope")
        if self.kind not in {"observation", "project_reference", "repair_recipe", "build_configuration", "incompatibility", "artifact_reference", "failure_capsule"}:
            raise ValueError(f"Unsupported knowledge record kind: {self.kind}")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeRecord":
        values = dict(data)
        values["provenance"] = [Provenance(**source) for source in data["provenance"]]
        return cls(**values)
