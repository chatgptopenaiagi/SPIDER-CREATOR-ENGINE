"""End-to-end qualification of the local Spider creation route and persistent trace."""

import hashlib
import json
from pathlib import Path
import socket
import shutil
import subprocess
import sys

import pytest

from sce.core.config import Config, STORAGE_NAMES
from sce.core.models import OperationOutcome, VerificationStatus
from sce.knowledge import KnowledgeStore
from sce.reporting.trace import TraceStore
from sce.spider.engine import SpiderEngine
from sce.storage import TaskStore


COMPONENTS = Path(__file__).resolve().parents[1] / "examples" / "components"
FIXTURE = json.loads((COMPONENTS / "csv_report_request.json").read_text(encoding="utf-8"))


def plan_creation(engine, *, expected=None):
    return engine.prepare(
        "Create a useful CSV summary application by connecting inspected local components.",
        [str(COMPONENTS / "csv_summary"), str(COMPONENTS / "summary_report")],
        name="spider-csv-report", input_data=FIXTURE["input"],
        expected_output=FIXTURE["expected_output"] if expected is None else expected,
        trusted=True,
    )


def test_prepare_creates_no_storage_and_preserves_original_objective(tmp_path):
    config = Config.default(tmp_path)
    engine = SpiderEngine(config)
    before = list(tmp_path.rglob("*"))
    plan = plan_creation(engine)
    assert not plan.validation_errors
    assert list(tmp_path.rglob("*")) == before
    assert not config.storage["TASK_DATABASE"].exists()
    assert plan.task.objective.startswith("Create a useful CSV summary application")
    assert plan.task.mode == "CREATE_NEW_APPLICATION"
    assert [step.id for step in plan.task.steps] == ["discovery", "acquisition", "analysis", "synthesis", "build", "functional_verification"]


def test_controlled_csv_pipeline_creates_and_independently_runs_application(tmp_path):
    config = Config.default(tmp_path)
    engine = SpiderEngine(config)
    plan = plan_creation(engine)
    result = engine.run(plan)
    assert result["task"]["status"] == "completed", result
    assert result["functional_application_created"] is True
    assert result["human_time_recovered"] is None
    assert result["installation"] == "not_run" and result["ai_generation"] == "not_run"
    assert not result["remaining_work"]
    artifact = Path(result["artifacts"][0]["path"])
    assert artifact.is_file()
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == result["artifacts"][0]["sha256"]
    executed = subprocess.run([sys.executable, "-I", "-B", str(artifact)], input=json.dumps(FIXTURE["input"]), text=True, capture_output=True, timeout=10, check=True)
    assert json.loads(executed.stdout) == FIXTURE["expected_output"]

    operations = TaskStore(config.storage["TASK_DATABASE"]).operations_for_task(plan.task.id)
    assert len(operations) == 6
    assert all(record.outcome == OperationOutcome.SUCCEEDED and record.verification == VerificationStatus.PASSED for record in operations)
    assert operations[0].produced[0]["resource_id"]
    assert operations[1].produced[0]["content_hashes"]
    assert operations[2].produced[0]["languages"] == ["Python"]
    built = next(record for record in operations if record.capability_id == "python.build")
    functional = next(record for record in operations if record.capability_id == "application.verify")
    assert not any(event.get("stage") == "verify" for event in built.executed)
    assert any(event.get("stage") == "verify" for event in functional.executed)

    memory = KnowledgeStore(config.storage["TASK_DATABASE"])
    records = memory.retrieve(plan.task.id, limit=100, max_chars=100000)
    assert len(records) >= 6
    assert all(record.provenance for record in records)
    assert memory.relationships(plan.task.id)
    assert not memory.retrieve("unrelated-task", limit=100, max_chars=100000)
    trace = TraceStore(config.storage["TASK_DATABASE"])
    summary, detailed = trace.read(plan.task.id, level=1), trace.read(plan.task.id, level=3)
    assert len([event for event in detailed if event["status"] == "verified"]) == 6
    assert all("evidence" not in event for event in summary)
    assert all(event["evidence"] for event in detailed if event["status"] == "verified")
    assert list((config.storage["REPORT_STORAGE"] / plan.task.id).glob("trace-*.html"))


def test_wrong_acceptance_retains_artifact_and_reusable_failure_capsule(tmp_path):
    config = Config.default(tmp_path)
    engine = SpiderEngine(config)
    plan = plan_creation(engine, expected={"deliberately_wrong": True})
    result = engine.run(plan)
    assert result["task"]["status"] == "failed"
    assert result["functional_application_created"] is False
    assert result["remaining_work"] == ["functional_verification"]
    assert Path(result["artifacts"][0]["path"]).is_file()
    records = TaskStore(config.storage["TASK_DATABASE"]).operations_for_task(plan.task.id)
    assert records[-2].capability_id == "python.build"
    assert records[-2].verification == VerificationStatus.PASSED
    assert records[-1].outcome == OperationOutcome.SUCCEEDED
    assert records[-1].verification == VerificationStatus.FAILED
    memory = KnowledgeStore(config.storage["TASK_DATABASE"])
    capsules = [record for record in memory.retrieve(plan.task.id, limit=100, max_chars=100000) if record.kind == "failure_capsule"]
    assert len(capsules) == 1
    assert capsules[0].supporting_evidence
    assert capsules[0].provenance and capsules[0].limitations
    assert any(event["status"] == "failed" and event["stage"] == "functional_verification" for event in TraceStore(config.storage["TASK_DATABASE"]).read(plan.task.id, level=3))


def test_completed_resume_does_not_repeat_operations_or_rewrite_artifact(tmp_path, monkeypatch):
    config = Config.default(tmp_path)
    engine = SpiderEngine(config)
    result = engine.run(plan_creation(engine))
    task_id = result["task"]["id"]
    artifact = Path(result["artifacts"][0]["path"])
    before = artifact.stat().st_mtime_ns
    operations_before = TaskStore(config.storage["TASK_DATABASE"]).operations_for_task(task_id)
    trace_before = TraceStore(config.storage["TASK_DATABASE"]).read(task_id, level=3)

    def no_repeat(*args, **kwargs):
        pytest.fail("Completed task repeated discovery")
    monkeypatch.setattr("sce.spider.engine.inspect_local", no_repeat)
    resumed = SpiderEngine(config).resume(task_id, trusted=True)
    operations_after = TaskStore(config.storage["TASK_DATABASE"]).operations_for_task(task_id)
    assert resumed["task"]["status"] == "completed"
    assert resumed["operation_ids"] == result["operation_ids"]
    assert [record.id for record in operations_after] == [record.id for record in operations_before]
    assert artifact.stat().st_mtime_ns == before
    assert TraceStore(config.storage["TASK_DATABASE"]).read(task_id, level=3) == trace_before


def test_resolved_storage_profile_routes_outputs_and_refuses_changed_profile(tmp_path):
    paths = {name: tmp_path / f"volume-{index}" / name.lower() for index, name in enumerate(STORAGE_NAMES)}
    paths["TASK_DATABASE"] = tmp_path / "database-volume" / "state.sqlite3"
    config = Config(paths)
    engine = SpiderEngine(config)
    result = engine.run(plan_creation(engine))
    assert result["functional_application_created"] is True
    assert Path(result["application_source"]).is_relative_to(paths["BUILD_WORKSPACES"])
    assert all(Path(item["path"]).is_relative_to(paths["ARTIFACT_STORAGE"]) for item in result["artifacts"])
    assert list(paths["RESOURCE_LIBRARY"].glob("*/resource.json"))
    assert list(paths["REPORT_STORAGE"].glob("*/result-*.json"))
    assert paths["TASK_DATABASE"].is_file()
    assert paths["TEMP_STORAGE"].is_dir()
    assert not (tmp_path / ".sce").exists()
    changed = dict(paths)
    changed["ARTIFACT_STORAGE"] = tmp_path / "different-artifacts"
    with pytest.raises(ValueError, match="Storage profile changed"):
        SpiderEngine(Config(changed)).resume(result["task"]["id"], trusted=True)


def test_local_pipeline_does_not_attempt_network(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Local Spider pipeline attempted a network connection")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    result = SpiderEngine(Config.default(tmp_path)).run(plan_creation(SpiderEngine(Config.default(tmp_path))))
    assert result["functional_application_created"] is True


def copied_components(tmp_path):
    copied = tmp_path / "selected-sources"
    shutil.copytree(COMPONENTS, copied)
    return copied


@pytest.mark.parametrize("relative", ["csv_tools.py", "sce-component.json"])
def test_source_or_manifest_drift_after_prepare_is_rejected(tmp_path, relative):
    sources = copied_components(tmp_path)
    config = Config.default(tmp_path / "engine")
    engine = SpiderEngine(config)
    plan = engine.prepare("Connect the reviewed source revisions", [str(sources / "csv_summary"), str(sources / "summary_report")], name="drift-check", input_data=FIXTURE["input"], expected_output=FIXTURE["expected_output"], trusted=True)
    changed = sources / "csv_summary" / relative
    changed.write_bytes(changed.read_bytes() + b"\n")
    result = engine.run(plan)
    assert result["functional_application_created"] is False
    assert not Path(result["application_source"]).exists()
    records = TaskStore(config.storage["TASK_DATABASE"]).operations_for_task(plan.task.id)
    assert records[0].verification != VerificationStatus.PASSED
    assert all(record.capability_id not in {"application.synthesize", "python.build", "application.verify"} for record in records)


def test_source_changed_after_discovery_is_not_given_stale_revision(tmp_path, monkeypatch):
    sources = copied_components(tmp_path)
    config = Config.default(tmp_path / "engine")
    engine = SpiderEngine(config)
    plan = engine.prepare("Keep discovery and acquisition revisions consistent", [str(sources / "csv_summary"), str(sources / "summary_report")], name="revision-check", input_data=FIXTURE["input"], expected_output=FIXTURE["expected_output"], trusted=True)
    checkpoint = TaskStore.checkpoint
    mutated = []

    def change_after_discovery(store, task, operation=None):
        result = checkpoint(store, task, operation)
        if operation is not None and operation.capability_id == "spider.discover" and not mutated:
            changed = sources / "csv_summary" / "csv_tools.py"
            changed.write_bytes(changed.read_bytes() + b"\n# Changed after discovery\n")
            mutated.append(True)
        return result
    monkeypatch.setattr(TaskStore, "checkpoint", change_after_discovery)
    result = engine.run(plan)
    assert mutated
    assert result["functional_application_created"] is False
    records = TaskStore(config.storage["TASK_DATABASE"]).operations_for_task(plan.task.id)
    assert records[0].verification == VerificationStatus.PASSED
    assert records[-1].capability_id == "resource.acquire_local"
    assert records[-1].verification != VerificationStatus.PASSED
    assert not result["artifacts"]


def test_tampered_generated_acceptance_is_rejected_before_build(tmp_path, monkeypatch):
    config = Config.default(tmp_path)
    engine = SpiderEngine(config)
    plan = plan_creation(engine)
    checkpoint = TaskStore.checkpoint
    mutated = []

    def change_after_synthesis(store, task, operation=None):
        result = checkpoint(store, task, operation)
        if operation is not None and operation.capability_id == "application.synthesize" and not mutated:
            manifest = Path(plan.task.steps[0].inputs["request"]["workspace"]) / "sce-build.json"
            specification = json.loads(manifest.read_text(encoding="utf-8"))
            specification["verification"]["expected_stdout"] = "replacement acceptance must not be authorized\n"
            manifest.write_text(json.dumps(specification), encoding="utf-8")
            mutated.append(True)
        return result
    monkeypatch.setattr(TaskStore, "checkpoint", change_after_synthesis)
    result = engine.run(plan)
    assert mutated
    assert result["functional_application_created"] is False
    assert not result["artifacts"]
    records = TaskStore(config.storage["TASK_DATABASE"]).operations_for_task(plan.task.id)
    assert records[-1].capability_id == "python.build"
    assert records[-1].outcome != OperationOutcome.SUCCEEDED


@pytest.mark.parametrize("mutation", ["acceptance", "objective", "verification_stage"])
def test_changed_prepared_task_scope_requires_new_plan(tmp_path, mutation):
    config = Config.default(tmp_path)
    engine = SpiderEngine(config)
    plan = plan_creation(engine)
    if mutation == "acceptance":
        plan.task.steps[0].inputs["request"]["expected_output"] = {"different": "acceptance"}
    elif mutation == "objective":
        plan.task.objective = "A different requested application"
    else:
        plan.task.steps.pop()
    with pytest.raises(ValueError, match="scope changed"):
        engine.run(plan)
    assert not config.storage["TASK_DATABASE"].exists()
    assert not config.storage["BUILD_WORKSPACES"].exists()


def test_explicit_manifest_file_paths_create_application_and_remain_bound_after_prepare(tmp_path):
    sources = copied_components(tmp_path)
    manifests = [str(sources / "csv_summary" / "sce-component.json"), str(sources / "summary_report" / "sce-component.json")]
    config = Config.default(tmp_path / "engine")
    engine = SpiderEngine(config)
    plan = engine.prepare("Use the specifically selected manifest interfaces", manifests, name="manifest-route", input_data=FIXTURE["input"], expected_output=FIXTURE["expected_output"], trusted=True)
    assert not plan.validation_errors
    result = engine.run(plan)
    assert result["functional_application_created"] is True
    artifact = Path(result["artifacts"][0]["path"])
    run = subprocess.run([sys.executable, "-I", "-B", str(artifact)], input=json.dumps(FIXTURE["input"]), text=True, capture_output=True, timeout=10, check=True)
    assert json.loads(run.stdout) == FIXTURE["expected_output"]
    second = engine.prepare("Preserve the selected manifest revision", manifests, name="changed-manifest", input_data=FIXTURE["input"], expected_output=FIXTURE["expected_output"], trusted=True)
    changed_manifest = Path(manifests[0])
    changed_manifest.write_bytes(changed_manifest.read_bytes() + b"\n")
    rejected = engine.run(second)
    assert rejected["functional_application_created"] is False
    assert not Path(rejected["application_source"]).exists()
    operations = TaskStore(config.storage["TASK_DATABASE"]).operations_for_task(second.task.id)
    assert operations[0].capability_id == "spider.discover"
    assert operations[0].verification != VerificationStatus.PASSED


@pytest.mark.parametrize("change,expected_status", [("delete", "unavailable"), ("modify", "changed")])
def test_resume_reports_current_artifact_integrity_without_rewriting_history(tmp_path, monkeypatch, change, expected_status):
    config = Config.default(tmp_path)
    engine = SpiderEngine(config)
    original = engine.run(plan_creation(engine))
    task_id = original["task"]["id"]
    artifact = Path(original["artifacts"][0]["path"])
    assert original["current_artifact_integrity"] == [{"path": str(artifact), "status": "matched"}]
    operations_before = TaskStore(config.storage["TASK_DATABASE"]).operations_for_task(task_id)
    if change == "delete":
        artifact.unlink()
    else:
        artifact.write_bytes(b"human replacement must not be overwritten")

    def no_rebuild(*args, **kwargs):
        pytest.fail("Resume attempted to rebuild a historically completed operation")
    monkeypatch.setattr("sce.spider.engine.PythonBuildAdapter.execute", no_rebuild)
    resumed = SpiderEngine(config).resume(task_id, trusted=True)
    assert resumed["task"]["status"] == "completed"
    assert resumed["functional_application_created"] is True  # Historical, explicitly qualified below.
    assert "execution time" in resumed["verification_basis"]
    assert resumed["current_artifact_integrity"] == [{"path": str(artifact), "status": expected_status}]
    operations_after = TaskStore(config.storage["TASK_DATABASE"]).operations_for_task(task_id)
    assert [record.id for record in operations_before] == [record.id for record in operations_after]
    assert resumed["operation_ids"] == original["operation_ids"]
    if change == "delete":
        assert not artifact.exists()
    else:
        assert artifact.read_bytes() == b"human replacement must not be overwritten"
