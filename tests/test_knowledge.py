import json
import sqlite3

import pytest

from sce.core.models import jsonable
from sce.knowledge import KnowledgeRecord, KnowledgeStore, Provenance
from sce.recovery import FailureCapsule, RepairAttempt
from sce.storage.task_store import TaskStore


def observation(claim="Fixture build completed", task_ids=None, **kwargs):
    return KnowledgeRecord(
        claim=claim, provenance=[Provenance(source="fixture://controlled/build", method="test observation", source_revision="fixture-v1")],
        task_ids=task_ids or ["task-one"], **kwargs,
    )


def test_claims_require_provenance_and_explicit_scope():
    with pytest.raises(ValueError, match="provenance"):
        KnowledgeRecord(claim="Speculative claim", provenance=[], task_ids=["task-one"])
    with pytest.raises(ValueError, match="task scope"):
        KnowledgeRecord(claim="Unscoped claim", provenance=[Provenance(source="local fixture", method="inspection")], task_ids=[])
    with pytest.raises(ValueError):
        Provenance(source="", method="inspection")
    with pytest.raises(ValueError, match="digest"):
        Provenance(source="local fixture", method="inspection", content_sha256="not-a-sha256")


def test_roundtrip_keeps_original_observation_evidence_and_limitations(tmp_path):
    database = tmp_path / "shared.sqlite3"
    TaskStore(database)
    store = KnowledgeStore(database)
    record = observation(
        supporting_evidence=[{"operation_id": "build-one", "result": "passed"}],
        contradictory_evidence=[{"operation_id": "build-two", "result": "failed"}],
        environment={"python": "controlled fixture runtime"},
        limitations=["Only tested on the controlled fixture"],
    )
    assert store.append(record) == record.id
    assert KnowledgeStore(database).get(record.id) == record
    assert store.retrieve("task-one") == [record]
    with pytest.raises(sqlite3.IntegrityError):
        store.append(record)


def test_task_scoped_retrieval_cannot_leak_another_task(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")
    first = observation("Known build", ["task-one"])
    second = observation("Other build", ["task-two"])
    store.append(first)
    store.append(second)
    assert store.retrieve("task-one", "BUILD") == [first]
    assert store.retrieve("task-two") == [second]
    assert store.retrieve("missing") == []
    with pytest.raises(ValueError):
        store.retrieve("")


def test_literal_query_does_not_expand_sql_wildcards(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")
    literal = observation("Build is 50%_complete")
    store.append(literal)
    store.append(observation("Build is 50 percent complete"))
    assert store.retrieve("task-one", "%_") == [literal]


def test_count_and_character_bounds_preserve_complete_provenance(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")
    small = observation("Small observation")
    store.append(small)
    store.append(observation("Large observation: " + "x" * 15000))
    bounded = store.retrieve("task-one", limit=1, max_chars=2000)
    assert bounded == [small]
    assert len(json.dumps(jsonable(bounded), ensure_ascii=False)) <= 2000
    assert store.retrieve("task-one", max_chars=2) == []
    for kwargs in ({"limit": 0}, {"limit": 101}, {"max_chars": 100001}, {"max_chars": True}):
        with pytest.raises(ValueError):
            store.retrieve("task-one", **kwargs)


def test_amendment_appends_a_new_linked_claim_instead_of_erasing_history(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")
    first = observation("Hypothesis: dependency X is absent")
    store.append(first)
    correction = observation("Dependency X is installed; investigate API mismatch", related_record_ids=[first.id], contradictory_evidence=[{"record_id": first.id}])
    store.append(correction)
    assert store.get(first.id) == first
    assert store.retrieve("task-one") == [correction, first]


def test_failure_capsule_persists_without_implying_resolution(tmp_path):
    provenance = [Provenance(source="fixture://build/failure", method="captured exception")]
    capsule = FailureCapsule(
        project_identity="fixture-project", provenance=provenance,
        relevant_errors=["ModuleNotFoundError: optional_example"], source_revision=None,
        environment={"operating_system": "controlled test environment"},
        reproduction_instructions=["Execute controlled fixture in isolated interpreter"],
        attempted_repairs=[RepairAttempt(description="Inspected declared dependencies", outcome="observed_success")],
        unresolved_hypotheses=["Dependency may be undeclared"], suggested_next_checks=["Compare project dependency metadata"],
        partial_artifacts=[{"path": "fixture-output.zip", "verification": "not_run"}],
    )
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")
    store.append(capsule.to_knowledge_record(["task-one"]))
    saved = store.get(capsule.id)
    restored = FailureCapsule.from_dict(saved.metadata["capsule"])
    assert restored == capsule
    assert restored.state == "unresolved"
    assert restored.source_revision is None
    assert saved.kind == "failure_capsule"
    assert "Unresolved failure" in saved.claim
    with pytest.raises(ValueError, match="resolution"):
        FailureCapsule.from_dict({**jsonable(capsule), "state": "solved"})


def test_missing_knowledge_record_is_explicit(tmp_path):
    with pytest.raises(KeyError):
        KnowledgeStore(tmp_path / "knowledge.sqlite3").get("missing")
