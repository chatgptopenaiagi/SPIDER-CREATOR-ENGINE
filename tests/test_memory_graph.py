import json
import sqlite3

import pytest

from sce.core.models import Evidence, OperationOutcome, OperationRecord, VerificationStatus, jsonable
from sce.knowledge import (KnowledgeRecord, KnowledgeRelationship, KnowledgeStore, Provenance,
                           ProvenanceCategory, evaluate_applicability)
from sce.recovery import FailureCapsule
from sce.reporting.trace import TraceEvent, TraceStore


def claim(text="Package includes runtime data", task="old-task", **kwargs):
    return KnowledgeRecord(text, [Provenance("fixture://package", "inspection")], [task],
                           resource_id="fixture-package", **kwargs)


def test_categories_roundtrip_without_promoting_ai_inference(tmp_path):
    store = KnowledgeStore(tmp_path / "memory.sqlite3")
    record = claim()
    record.provenance = [Provenance("local-model:proposal", "proposal", category="AI_INFERENCE")]
    store.append(record)
    assert store.get(record.id).provenance[0].category is ProvenanceCategory.AI_INFERENCE
    assert not store.get(record.id).supporting_evidence
    with pytest.raises(ValueError, match="supporting evidence"):
        KnowledgeRecord("Works", [Provenance("test", "run", category="VERIFIED_TEST_EVIDENCE")], ["task"])


def test_legacy_database_migration_preserves_original_payload(tmp_path):
    database = tmp_path / "old.sqlite3"
    old = {"claim": "Historical source inspection", "provenance": [{"source": "fixture", "method": "read"}],
           "task_ids": ["old-task"], "id": "old-record"}
    with sqlite3.connect(database) as connection:
        connection.executescript("CREATE TABLE knowledge_records(id TEXT PRIMARY KEY, claim TEXT, payload TEXT);"
                                 "CREATE TABLE knowledge_task_scope(record_id TEXT, task_id TEXT, PRIMARY KEY(record_id,task_id));")
        connection.execute("INSERT INTO knowledge_records VALUES (?, ?, ?)", (old["id"], old["claim"], json.dumps(old)))
        connection.execute("INSERT INTO knowledge_task_scope VALUES (?, ?)", (old["id"], "old-task"))
    store = KnowledgeStore(database)
    assert store.get("old-record").resource_id is None
    assert store.retrieve("old-task")[0].claim == old["claim"]
    assert store.retrieve("new-task") == []
    with sqlite3.connect(database) as connection:
        assert json.loads(connection.execute("SELECT payload FROM knowledge_records").fetchone()[0]) == old


def test_historical_lookup_is_explicit_resource_scoped_and_bounded(tmp_path):
    store = KnowledgeStore(tmp_path / "memory.sqlite3")
    record = claim(applicability={"python": "3.11"}, resource_revision="abc")
    store.append(record)
    assert store.find_candidates("new-task", "fixture-package") == []
    assert store.find_candidates("new-task", "another-resource", include_history=True) == []
    candidates = store.find_candidates("new-task", "fixture-package", include_history=True,
                                       environment={"python": "3.11"}, resource_revision="abc")
    assert len(candidates) == 1
    assert candidates[0].historical is True
    assert candidates[0].applicability.status == "matched"
    assert candidates[0].record == record
    assert store.retrieve("new-task") == []
    size = len(json.dumps(jsonable(candidates), ensure_ascii=False))
    assert store.find_candidates("new-task", "fixture-package", include_history=True,
                                 environment={"python": "3.11"}, resource_revision="abc", max_chars=size - 1) == []


@pytest.mark.parametrize("kwargs,status", [
    ({}, "unknown"),
    ({"environment": {"python": "3.11"}}, "unknown"),
    ({"environment": {"python": "3.11"}, "resource_revision": "abc"}, "matched"),
    ({"environment": {"python": "3.12"}, "resource_revision": "abc"}, "mismatch"),
    ({"environment": {"python": "3.11"}, "resource_revision": "def"}, "mismatch"),
])
def test_applicability_requires_observed_conditions_and_revision(kwargs, status):
    record = claim(applicability={"python": "3.11"}, resource_revision="abc")
    assert evaluate_applicability(record, **kwargs).status == status
    assert evaluate_applicability(claim()).status == "unknown"


def test_explicit_reuse_preserves_payload_and_audits_actor_and_conditions(tmp_path):
    database = tmp_path / "memory.sqlite3"
    store = KnowledgeStore(database)
    original = claim(applicability={"platform": "windows"})
    store.append(original)
    assessment = store.reuse(original.id, "new-task", actor="engineer:alice", reason="Compare missing data symptom",
                            environment={"platform": "linux"})
    assert assessment.status == "mismatch"
    restored = KnowledgeStore(database)
    assert restored.get(original.id) == original
    assert restored.retrieve("new-task", resource_id="fixture-package") == [original]
    assert restored.find_candidates("new-task", "fixture-package")[0].historical is False
    audit = restored.scope_history(original.id)
    assert audit[0]["actor"] == "engineer:alice"
    assert audit[0]["applicability"]["status"] == "mismatch"
    assert audit[0]["effect"] == "retrieval_scope_only"


def test_human_correction_preserves_claim_and_attributable_relationship(tmp_path):
    store = KnowledgeStore(tmp_path / "memory.sqlite3")
    original = claim("Runtime data is packaged")
    store.append(original)
    correction = store.correct(original.id, "Runtime data was omitted", task_id="old-task",
                               actor="human:alice", reason="Inspected wheel contents",
                               supporting_evidence=[{"archive_member": "data.json", "present": False}])
    assert store.get(original.id) == original
    assert correction.provenance[0].actor == "human:alice"
    assert correction.contradictory_evidence[0]["record_id"] == original.id
    relationships = store.relationships("old-task", original.id)
    assert len(relationships) == 1
    assert relationships[0].source_record_id == correction.id
    assert relationships[0].target_record_id == original.id
    assert relationships[0].relation == "corrects"
    assert store.relationships("another-task") == []
    with pytest.raises(sqlite3.IntegrityError):
        store.append_relationship(relationships[0])


def test_correction_and_relationship_cannot_bypass_task_scope(tmp_path):
    store = KnowledgeStore(tmp_path / "memory.sqlite3")
    first = claim()
    second = claim(task="other-task")
    store.append(first)
    store.append(second)
    with pytest.raises(ValueError, match="task scope"):
        store.append_relationship(KnowledgeRelationship(first.id, second.id, "contradicts", "old-task", first.provenance))
    with pytest.raises(ValueError, match="task scope"):
        store.correct(first.id, "Correction", task_id="other-task", actor="human", reason="Review")
    assert len(store.retrieve("other-task")) == 1
    assert store.get(first.id) == first


def test_verified_operation_capture_preserves_verification_scope(tmp_path):
    store = KnowledgeStore(tmp_path / "memory.sqlite3")
    operation = OperationRecord(capability_id="python.build", task_id="task", outcome=OperationOutcome.SUCCEEDED,
                                verification=VerificationStatus.NOT_RUN, produced=[{"path": "app.pyz"}])
    record = store.record_operation(operation, resource_id="fixture-package")
    assert "declared verification=not_run" in record.claim
    assert record.provenance[0].category is ProvenanceCategory.OBSERVED_BEHAVIOR
    assert record.metadata["operation"]["produced"] == [{"path": "app.pyz"}]
    operation.verification = VerificationStatus.PASSED
    operation.evidence = [Evidence("functional-test:1", "Expected output matched", kind="verification")]
    verified = store.record_operation(operation, resource_id="fixture-package")
    assert verified.provenance[0].category is ProvenanceCategory.VERIFIED_TEST_EVIDENCE
    assert "limited" in verified.limitations[0]


@pytest.mark.parametrize("capability,kind", [
    ("spider.discover", "static_inspection"),
    ("project.analyze", "static_analysis"),
    ("application.synthesize", "verification"),
    ("resource.acquire_local", "verification"),
    ("python.build", "package_integrity"),
    ("application.verify", "observation"),
    ("future.unknown_adapter", "verification"),
])
def test_structural_success_and_unknown_adapters_do_not_gain_test_provenance(tmp_path, capability, kind):
    store = KnowledgeStore(tmp_path / "memory.sqlite3")
    operation = OperationRecord(capability_id=capability, task_id="task", outcome=OperationOutcome.SUCCEEDED,
                                verification=VerificationStatus.PASSED,
                                evidence=[Evidence("fixture://observation", "Declared structural check passed", kind=kind)])
    record = store.record_operation(operation)
    restored = KnowledgeStore(store.path).get(record.id)
    assert restored.provenance[0].category is ProvenanceCategory.OBSERVED_BEHAVIOR
    assert restored.metadata["operation"]["verification"] == "passed"
    assert restored.supporting_evidence[0]["kind"] == kind


@pytest.mark.parametrize("capability", ["python.build", "application.verify", "qasc.create_python"])
def test_qualified_functional_evidence_gains_scoped_test_provenance(tmp_path, capability):
    store = KnowledgeStore(tmp_path / "memory.sqlite3")
    operation = OperationRecord(capability_id=capability, task_id="task", outcome=OperationOutcome.SUCCEEDED,
                                verification=VerificationStatus.PASSED,
                                evidence=[Evidence("fixture://acceptance", "Exact independently supplied stdout and exit matched", kind="verification")])
    record = store.record_operation(operation)
    assert store.get(record.id).provenance[0].category is ProvenanceCategory.VERIFIED_TEST_EVIDENCE
    assert record.metadata["operation"]["capability_id"] == capability


@pytest.mark.parametrize("outcome,verification", [("succeeded", "failed"), ("succeeded", "not_run"), ("partial", "passed")])
def test_incomplete_or_failed_checks_are_observations(tmp_path, outcome, verification):
    operation = OperationRecord(capability_id="application.verify", task_id="task", outcome=outcome, verification=verification,
                                evidence=[Evidence("fixture://acceptance", "Recorded attempt", kind="verification")])
    record = KnowledgeStore(tmp_path / "memory.sqlite3").record_operation(operation)
    assert record.provenance[0].category is ProvenanceCategory.OBSERVED_BEHAVIOR


def test_failure_capsule_retains_objective_inputs_versions_and_signature():
    capsule = FailureCapsule("fixture-package", [Provenance("build:1", "stderr")], ["Missing data.json"],
                             original_objective="Create an offline greeting app", failed_operation="package",
                             relevant_inputs={"source": "fixture"}, software_versions={"python": "3.11"},
                             error_signature="FileNotFoundError:data.json")
    restored = FailureCapsule.from_dict(jsonable(capsule))
    assert restored == capsule
    record = restored.to_knowledge_record(["task"])
    assert record.resource_id == "fixture-package"
    assert record.metadata["capsule"]["state"] == "unresolved"
    assert record.metadata["capsule"]["error_signature"] == "FileNotFoundError:data.json"


def test_trace_three_levels_keep_execution_separate_from_verification(tmp_path):
    database = tmp_path / "memory.sqlite3"
    store = TraceStore(database)
    event = TraceEvent("task", "build", "executed", "Built fixture", decision="Use standard library zipapp",
                       objective="Create a useful offline application", resource_ids=["fixture-package"],
                       outcome=OperationOutcome.SUCCEEDED, artifacts=[{"path": "app.pyz"}],
                       evidence=[{"process": "build", "returncode": 0}], unknowns=["Functional test has not run"])
    store.append(event)
    restored = TraceStore(database)
    first = restored.read("task", level=1)[0]
    assert first["outcome"] == "succeeded" and first["verification"] == "not_run"
    assert "decision" not in first and "evidence" not in first
    assert restored.read("task", level=2)[0]["decision"] == event.decision
    assert "evidence" not in restored.read("task", level=2)[0]
    assert restored.read("task", level=3)[0] == jsonable(event)
    assert restored.read("other-task") == []
    with pytest.raises(sqlite3.IntegrityError):
        restored.append(event)


def test_trace_validated_verification_and_rendering(tmp_path):
    with pytest.raises(ValueError, match="evidence"):
        TraceEvent("task", "verification", "verified", "Works", verification=VerificationStatus.PASSED)
    store = TraceStore(tmp_path / "trace.sqlite3")
    event = TraceEvent("task", "functional_verification", "verified", "<script>```fixture passed</script>",
                       verification=VerificationStatus.PASSED, evidence=[{"expected": "hello", "actual": "hello"}])
    store.append(event)
    assert json.loads(store.render("task", level=3))["events"][0] == jsonable(event)
    assert "````json" in store.render("task", format="markdown")
    assert "&lt;script&gt;" in store.render("task", format="html")
    with pytest.raises(ValueError):
        store.render("task", format="unsupported")


def test_trace_chronological_pagination_and_validation(tmp_path):
    store = TraceStore(tmp_path / "trace.sqlite3")
    for number in range(3):
        store.append(TraceEvent("task", "discovery", "planned", str(number)))
    assert [event["summary"] for event in store.read("task", offset=1, limit=1)] == ["1"]
    for kwargs in ({"level": 0}, {"level": True}, {"limit": 0}, {"offset": -1}):
        with pytest.raises(ValueError):
            store.read("task", **kwargs)


@pytest.mark.parametrize("kwargs", [
    {"task_id": "", "resource_id": "resource"},
    {"task_id": "task", "resource_id": ""},
    {"task_id": "task", "resource_id": "resource", "include_history": "yes"},
    {"task_id": "task", "resource_id": "resource", "max_chars": 1},
])
def test_candidate_scope_and_budget_validation(tmp_path, kwargs):
    with pytest.raises(ValueError):
        KnowledgeStore(tmp_path / "memory.sqlite3").find_candidates(**kwargs)
