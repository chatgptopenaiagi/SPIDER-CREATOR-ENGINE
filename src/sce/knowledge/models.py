"""Knowledge claims retain sources, conditions, and contrary evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4

from sce.core.models import utc_now


class ProvenanceCategory(str, Enum):
    AUTHOR_DOCUMENTATION = "AUTHOR_DOCUMENTATION"
    AI_INFERENCE = "AI_INFERENCE"
    OBSERVED_BEHAVIOR = "OBSERVED_BEHAVIOR"
    VERIFIED_TEST_EVIDENCE = "VERIFIED_TEST_EVIDENCE"


@dataclass
class Provenance:
    source: str
    method: str
    observed_at: str = field(default_factory=utc_now)
    source_revision: str | None = None
    content_sha256: str | None = None
    category: ProvenanceCategory = ProvenanceCategory.OBSERVED_BEHAVIOR
    actor: str | None = None

    def __post_init__(self) -> None:
        self.category = ProvenanceCategory(self.category)
        if not self.source.strip() or not self.method.strip() or not self.observed_at.strip():
            raise ValueError("Provenance requires source, observation method, and observation time")
        if self.content_sha256 is not None and (
            len(self.content_sha256) != 64 or any(character not in "0123456789abcdefABCDEF" for character in self.content_sha256)
        ):
            raise ValueError("content_sha256 must be a 64-character hexadecimal digest")
        if self.actor is not None and not self.actor.strip():
            raise ValueError("Provenance actor must be nonempty when supplied")


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
    resource_id: str | None = None
    resource_revision: str | None = None
    subject: str | None = None
    description: str | None = None
    applicability: dict[str, Any] = field(default_factory=dict)

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
        if self.kind not in {"observation", "project_reference", "repair_recipe", "build_configuration", "incompatibility", "artifact_reference", "failure_capsule", "correction", "verification", "analysis", "decision"}:
            raise ValueError(f"Unsupported knowledge record kind: {self.kind}")
        for name in ("resource_id", "resource_revision", "subject", "description"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be nonempty when supplied")
        if not isinstance(self.applicability, dict) or any(not isinstance(key, str) or not key.strip() for key in self.applicability):
            raise ValueError("Applicability must contain named environment conditions")
        if any(source.category == ProvenanceCategory.VERIFIED_TEST_EVIDENCE for source in self.provenance) and not self.supporting_evidence:
            raise ValueError("Verified test provenance requires supporting evidence")

    @property
    def known_limitations(self) -> list[str]:
        return self.limitations

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeRecord":
        values = dict(data)
        values["provenance"] = [Provenance(**source) for source in data["provenance"]]
        return cls(**values)


@dataclass
class KnowledgeRelationship:
    source_record_id: str
    target_record_id: str
    relation: str
    task_id: str
    provenance: list[Provenance]
    id: str = field(default_factory=lambda: str(uuid4()))
    recorded_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for name in ("source_record_id", "target_record_id", "task_id", "id", "recorded_at"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"Relationship requires {name}")
        if self.relation not in {"derived_from", "supports", "contradicts", "corrects", "depends_on", "uses_component", "built_from", "verified_by", "attempted_repair", "has_failure"}:
            raise ValueError(f"Unsupported knowledge relationship: {self.relation}")
        if not self.provenance or any(not isinstance(source, Provenance) for source in self.provenance):
            raise ValueError("Knowledge relationships require provenance")
        for source in self.provenance:
            source.__post_init__()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeRelationship":
        return cls(**{**data, "provenance": [Provenance(**source) for source in data["provenance"]]})


@dataclass
class ApplicabilityAssessment:
    status: str
    matched_conditions: list[str] = field(default_factory=list)
    mismatched_conditions: list[str] = field(default_factory=list)
    unknown_conditions: list[str] = field(default_factory=list)
    limitation: str = "Matching recorded conditions is a retrieval aid, not proof of compatibility or a verified repair."


@dataclass
class MemoryCandidate:
    record: KnowledgeRecord
    applicability: ApplicabilityAssessment
    historical: bool


def evaluate_applicability(record: KnowledgeRecord, environment: dict[str, Any] | None = None,
                           resource_revision: str | None = None) -> ApplicabilityAssessment:
    """Compare explicit conditions only; absent observations remain unknown."""
    conditions = dict(record.applicability)
    observed = dict(environment or {})
    if record.resource_revision is not None:
        conditions["resource_revision"] = record.resource_revision
        observed["resource_revision"] = resource_revision
    matched, mismatched, unknown = [], [], []
    for key, expected in conditions.items():
        if key not in observed or observed[key] is None or expected is None:
            unknown.append(key)
        elif observed[key] == expected:
            matched.append(key)
        else:
            mismatched.append(key)
    if not conditions:
        unknown.append("No applicability conditions were recorded")
    status = "mismatch" if mismatched else "unknown" if unknown else "matched"
    return ApplicabilityAssessment(status, matched, mismatched, unknown)
