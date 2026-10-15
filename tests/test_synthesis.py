from dataclasses import asdict, replace
import json
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from sce.builders.python import CREATE_NEW_APPLICATION_USING_PROJECT, PythonBuildAdapter
from sce.core.models import OperationRecord, jsonable
from sce.synthesis import ComponentSpec, PythonSynthesisAdapter


COMPONENTS = Path(__file__).resolve().parents[1] / "examples" / "components"
FIXTURE = json.loads((COMPONENTS / "csv_report_request.json").read_text(encoding="utf-8"))


def prepare(tmp_path, *, expected=None, trusted=True, name="csv-report"):
    adapter = PythonSynthesisAdapter()
    plan = adapter.prepare([COMPONENTS / "csv_summary", COMPONENTS / "summary_report"],
                           tmp_path / "application", name=name, input_data=FIXTURE["input"],
                           expected_output=FIXTURE["expected_output"] if expected is None else expected,
                           trusted=trusted, task_id="synthesis-test")
    return adapter, plan


def build(tmp_path, plan):
    adapter = PythonBuildAdapter()
    build_plan = adapter.prepare(plan.workspace, tmp_path / "artifacts", trusted=True, task_id=plan.task_id)
    return adapter.verify(build_plan, adapter.execute(build_plan))


def test_prepare_is_read_only_and_snapshots_selected_sources(tmp_path):
    before = sorted(str(path) for path in tmp_path.rglob("*"))
    adapter, plan = prepare(tmp_path)
    assert plan.ready, plan.validation_errors
    assert sorted(str(path) for path in tmp_path.rglob("*")) == before
    assert plan.operation == CREATE_NEW_APPLICATION_USING_PROJECT
    assert len(plan.components) == 2
    assert plan.components[0].files[0].path == "csv_tools.py"
    assert len(plan.components[0].files[0].sha256) == 64
    assert adapter.describe()["operations"] == [CREATE_NEW_APPLICATION_USING_PROJECT]


def test_two_components_create_build_and_verify_useful_application(tmp_path):
    adapter, plan = prepare(tmp_path)
    record = adapter.execute(plan)
    assert record.outcome.value == "succeeded", record.evidence
    assert record.verification.value == "not_run"
    assert adapter.verify(plan, record).verification.value == "passed"
    assert any("not functionality" in evidence.detail for evidence in record.evidence)
    built = build(tmp_path, plan)
    assert built.outcome.value == "succeeded"
    assert built.verification.value == "passed", built.evidence
    assert record.requested["operation"] != built.requested["operation"]
    artifact = next(item["path"] for item in built.produced if item["kind"] == "python_zipapp")
    result = subprocess.run([sys.executable, "-I", artifact], input=json.dumps(FIXTURE["input"]),
                            text=True, capture_output=True, timeout=10, check=True)
    assert json.loads(result.stdout) == FIXTURE["expected_output"]
    assert (Path(plan.workspace) / "_sce_parts/p0/csv_tools.py").read_bytes() == (COMPONENTS / "csv_summary/csv_tools.py").read_bytes()
    provenance = json.loads((Path(plan.workspace) / "sce-provenance.json").read_text())
    assert len(provenance["components"]) == 2
    assert provenance["functional_verification"] == "NOT_RUN"
    assert OperationRecord.from_dict(json.loads(json.dumps(jsonable(record)))).outcome == record.outcome
    assert adapter.report(record) is record


def test_independent_wrong_acceptance_fails_despite_successful_build(tmp_path):
    adapter, plan = prepare(tmp_path, expected={"row_count": 900})
    assert adapter.execute(plan).outcome.value == "succeeded"
    built = build(tmp_path, plan)
    assert built.outcome.value == "succeeded"
    assert built.verification.value == "failed"


def test_explicit_inspected_interface_needs_no_manifest_and_never_runs_during_prepare(tmp_path):
    source = tmp_path / "plain_source"
    source.mkdir()
    marker = tmp_path / "would_run"
    (source / "plain.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\ndef run(value):\n    return value\n")
    (source / "unselected.py").write_text("raise RuntimeError('must not copy')\n")
    spec = ComponentSpec(str(source), "plain:run", ("plain.py",), resource_id="resource:plain", resource_revision="commit:one")
    adapter = PythonSynthesisAdapter()
    plan = adapter.prepare([spec], tmp_path / "new_app", name="plain-app", input_data={"hello": "world"},
                           expected_output={"hello": "world"}, trusted=True)
    assert plan.ready
    assert not marker.exists()
    record = adapter.execute(plan)
    assert record.outcome.value == "succeeded", record.evidence
    assert not marker.exists()
    assert not (Path(plan.workspace) / "_sce_parts/p0/unselected.py").exists()
    assert plan.components[0].resource_id == "resource:plain"
    assert plan.components[0].resource_revision == "commit:one"


def test_source_drift_refuses_execution_before_creating_workspace(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    module = source / "tool.py"
    module.write_text("def run(value):\n    return value\n")
    adapter = PythonSynthesisAdapter()
    plan = adapter.prepare([ComponentSpec(str(source), "tool:run", ("tool.py",))],
                           tmp_path / "app", name="app", input_data={}, expected_output={}, trusted=True)
    module.write_text("def run(value):\n    return {'changed': True}\n")
    record = adapter.execute(plan)
    assert record.outcome.value == "failed"
    assert not Path(plan.workspace).exists()
    assert "changed" in record.evidence[-1].detail


def test_manifest_drift_refuses_execution(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "tool.py").write_text("def run(value):\n    return value\n")
    manifest = source / "sce-component.json"
    manifest.write_text(json.dumps({"format": "sce.python-component.v1", "interface": "tool:run", "source_files": ["tool.py"]}))
    adapter = PythonSynthesisAdapter()
    plan = adapter.prepare([source], tmp_path / "app", name="app", input_data={}, expected_output={}, trusted=True)
    manifest.write_text(manifest.read_text() + " ")
    assert adapter.execute(plan).outcome.value == "failed"
    assert not Path(plan.workspace).exists()


def test_trust_is_explicit_and_existing_destinations_are_preserved(tmp_path):
    adapter, plan = prepare(tmp_path, trusted=False)
    assert not plan.ready
    assert adapter.execute(plan).outcome.value == "failed"
    assert not Path(plan.workspace).exists()
    adapter, plan = prepare(tmp_path)
    Path(plan.workspace).mkdir()
    marker = Path(plan.workspace) / "keep.txt"
    marker.write_text("existing human work")
    assert adapter.execute(plan).outcome.value == "failed"
    assert marker.read_text() == "existing human work"


@pytest.mark.parametrize("interface,files", [
    ("tool:missing", ("tool.py",)),
    ("tool:run", ("../tool.py",)),
    ("tool:run", ("tool.py", "TOOL.py")),
    ("tool.run", ("tool.py",)),
    ("tool:run", ("missing.py",)),
])
def test_bad_interfaces_and_paths_are_reported(tmp_path, interface, files):
    source = tmp_path / "source"
    source.mkdir()
    (source / "tool.py").write_text("def run(value):\n    return value\n")
    adapter = PythonSynthesisAdapter()
    plan = adapter.prepare([ComponentSpec(str(source), interface, files)], tmp_path / "app",
                           name="app", input_data={}, expected_output={}, trusted=True)
    assert not plan.ready
    assert plan.validation_errors
    assert not (tmp_path / "app").exists()


def test_declared_missing_dependency_is_a_build_failure(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "tool.py").write_text("def run(value):\n    return value\n")
    adapter = PythonSynthesisAdapter()
    plan = adapter.prepare([ComponentSpec(str(source), "tool:run", ("tool.py",),
                                         ("sce_dependency_that_does_not_exist_9261",))],
                           tmp_path / "app", name="app", input_data={}, expected_output={}, trusted=True)
    assert adapter.execute(plan).outcome.value == "succeeded"
    built = build(tmp_path, plan)
    assert built.outcome.value == "failed"
    assert built.verification.value == "not_run"
    assert any("missing dependency" in item.detail for item in built.evidence)


def test_tampered_generated_plan_is_rejected(tmp_path):
    adapter, plan = prepare(tmp_path)
    forged = replace(plan, generated_files=plan.generated_files + (replace(plan.generated_files[0], path="../escape.py"),))
    assert adapter.execute(forged).outcome.value == "failed"
    assert not (tmp_path / "escape.py").exists()
    assert not Path(plan.workspace).exists()


def test_construction_integrity_detects_modified_artifact(tmp_path):
    adapter, plan = prepare(tmp_path)
    record = adapter.execute(plan)
    (Path(plan.workspace) / "sce_bridge.py").write_text("changed")
    assert adapter.verify(plan, record).verification.value == "failed"


def test_verification_rejects_mismatched_plan(tmp_path):
    adapter, plan = prepare(tmp_path)
    record = adapter.execute(plan)
    assert adapter.verify(replace(plan, task_id="other-task"), record).verification.value == "failed"


def test_cancellation_preserves_partial_artifacts_without_claiming_success(tmp_path):
    adapter, plan = prepare(tmp_path)
    checks = iter([False, False, True])
    record = adapter.execute(plan, cancelled=lambda: next(checks))
    assert record.outcome.value == "cancelled"
    assert any(item["kind"] == "application_source" for item in record.produced)
    assert adapter.verify(plan, record).verification.value == "not_run"
    assert Path(plan.workspace).is_dir()


def test_write_failure_records_partial_workspace_for_inspection(tmp_path, monkeypatch):
    adapter, plan = prepare(tmp_path)
    original_open = Path.open
    def fail_bridge(path, mode="r", *args, **kwargs):
        if path == Path(plan.workspace) / "sce_bridge.py" and mode == "xb":
            raise OSError("controlled destination write failure")
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", fail_bridge)
    record = adapter.execute(plan)
    assert record.outcome.value == "partial"
    assert any(item["kind"] == "partial_application_workspace" and item["path"] == plan.workspace for item in record.produced)
    assert adapter.verify(plan, record).verification.value == "not_run"


def test_package_relative_imports_are_supported(tmp_path):
    source = tmp_path / "source"
    (source / "pkg").mkdir(parents=True)
    (source / "pkg/__init__.py").write_text("")
    (source / "pkg/helper.py").write_text("def double(number):\n    return number * 2\n")
    (source / "pkg/entry.py").write_text("from .helper import double\ndef run(value):\n    return {'number': double(value['number'])}\n")
    adapter = PythonSynthesisAdapter()
    spec = ComponentSpec(str(source), "pkg.entry:run", ("pkg/__init__.py", "pkg/helper.py", "pkg/entry.py"))
    plan = adapter.prepare([spec], tmp_path / "app", name="double", input_data={"number": 21},
                           expected_output={"number": 42}, trusted=True)
    assert plan.ready, plan.validation_errors
    assert adapter.execute(plan).outcome.value == "succeeded"
    assert build(tmp_path, plan).verification.value == "passed"


def test_json_boundary_failure_does_not_become_functional_success(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "tool.py").write_text("def run(value):\n    return {1, 2, 3}\n")
    adapter = PythonSynthesisAdapter()
    plan = adapter.prepare([ComponentSpec(str(source), "tool:run", ("tool.py",))],
                           tmp_path / "app", name="app", input_data={}, expected_output={}, trusted=True)
    assert adapter.execute(plan).outcome.value == "succeeded"
    built = build(tmp_path, plan)
    assert built.outcome.value == "succeeded"
    assert built.verification.value == "failed"


def test_same_module_name_in_separate_components_keeps_interfaces_isolated(tmp_path):
    specs = []
    for index in (1, 2):
        root = tmp_path / f"component{index}"
        root.mkdir()
        (root / "tool.py").write_text(f"def run(value):\n    return {{'number': value['number'] + {index}}}\n")
        specs.append(ComponentSpec(str(root), "tool:run", ("tool.py",)))
    adapter = PythonSynthesisAdapter()
    plan = adapter.prepare(specs, tmp_path / "app", name="isolated", input_data={"number": 10},
                           expected_output={"number": 13}, trusted=True)
    assert adapter.execute(plan).outcome.value == "succeeded"
    assert build(tmp_path, plan).verification.value == "passed"


def test_final_component_can_return_a_json_array(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "tool.py").write_text("def run(value):\n    return [value['number'], value['number'] * 2]\n")
    adapter = PythonSynthesisAdapter()
    plan = adapter.prepare([ComponentSpec(str(source), "tool:run", ("tool.py",))],
                           tmp_path / "app", name="app", input_data={"number": 3}, expected_output=[3, 6], trusted=True)
    assert adapter.execute(plan).outcome.value == "succeeded"
    assert build(tmp_path, plan).verification.value == "passed"


@pytest.mark.parametrize("include_runtime_resource,expected_verification", [(False, "failed"), (True, "passed")])
def test_runtime_resources_must_be_explicitly_selected(tmp_path, include_runtime_resource, expected_verification):
    source = tmp_path / "source"
    source.mkdir()
    (source / "tool.py").write_text(
        "from importlib.resources import files\n"
        "def run(value):\n"
        "    return {'message': files(__package__).joinpath('message.txt').read_text().strip()}\n"
    )
    (source / "message.txt").write_text("Reusable runtime resource\n")
    selected = ("tool.py", "message.txt") if include_runtime_resource else ("tool.py",)
    adapter = PythonSynthesisAdapter()
    plan = adapter.prepare([ComponentSpec(str(source), "tool:run", selected)],
                           tmp_path / "app", name="app", input_data={},
                           expected_output={"message": "Reusable runtime resource"}, trusted=True)
    assert adapter.execute(plan).outcome.value == "succeeded"
    assert build(tmp_path, plan).verification.value == expected_verification


def test_budget_and_nonfinite_values_are_rejected_before_writing(tmp_path):
    adapter = PythonSynthesisAdapter(max_source_bytes=5)
    plan = adapter.prepare([COMPONENTS / "csv_summary"], tmp_path / "app", name="app",
                           input_data={}, expected_output={}, trusted=True)
    assert not plan.ready
    adapter = PythonSynthesisAdapter()
    plan = adapter.prepare([COMPONENTS / "csv_summary"], tmp_path / "app", name="app",
                           input_data={"value": float("nan")}, expected_output={}, trusted=True)
    assert not plan.ready
    assert not (tmp_path / "app").exists()


def test_content_identity_is_independent_of_location(tmp_path):
    roots = [tmp_path / "first", tmp_path / "second"]
    adapter = PythonSynthesisAdapter()
    plans = []
    for root in roots:
        root.mkdir()
        (root / "tool.py").write_text("def run(value):\n    return value\n")
        plans.append(adapter.prepare([ComponentSpec(str(root), "tool:run", ("tool.py",))],
                     tmp_path / (root.name + "-application"), name="app", input_data={}, expected_output={}, trusted=True))
    assert plans[0].components[0].resource_id == plans[1].components[0].resource_id


def test_local_synthesis_never_opens_a_socket(tmp_path, monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("Network access is forbidden in this local synthesis test")
    monkeypatch.setattr(socket, "socket", deny)
    adapter, plan = prepare(tmp_path)
    record = adapter.verify(plan, adapter.execute(plan))
    assert record.verification.value == "passed"
    # This guard applies to this process only; it is not a disconnected-OS test.
