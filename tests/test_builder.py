from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sys

import pytest

from sce.builders import CREATE_NEW_APPLICATION_USING_PROJECT, PythonBuildAdapter
from sce.core.models import OperationOutcome, VerificationStatus
from sce.verification import verify_process

FIXTURES = Path(__file__).resolve().parents[1] / "examples" / "fixtures"


def fixture(tmp_path, name="success"):
    source = tmp_path / "source"
    shutil.copytree(FIXTURES / name, source)
    return source


def run_fixture(tmp_path, name="success", **kwargs):
    adapter = PythonBuildAdapter(**kwargs)
    plan = adapter.prepare(fixture(tmp_path, name), tmp_path / "output", trusted=True)
    record = adapter.execute(plan)
    return adapter, plan, adapter.verify(plan, record)


def test_prepare_read_only_and_execution_separate_from_verification(tmp_path):
    source = fixture(tmp_path)
    before = {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    output = tmp_path / "output"
    adapter = PythonBuildAdapter()
    plan = adapter.prepare(source, output, trusted=True)
    assert plan.ready
    assert not output.exists()
    assert before == {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    record = adapter.execute(plan)
    assert record.outcome == OperationOutcome.SUCCEEDED
    assert record.verification == VerificationStatus.NOT_RUN
    assert len(record.produced) == 1
    assert Path(record.produced[0]["path"]).is_file()
    assert not any(item["stage"] == "verify" for item in record.executed)
    verified = adapter.verify(plan, record)
    assert verified.verification == VerificationStatus.PASSED
    assert adapter.report(verified) is verified
    assert "installed" not in json.dumps(asdict(verified)).lower()


def test_missing_dependency_stops_before_execution(tmp_path):
    adapter, plan, record = run_fixture(tmp_path, "missing_dependency")
    assert not plan.ready
    assert "missing dependency" in " ".join(plan.validation_errors)
    assert record.outcome == OperationOutcome.FAILED
    assert record.verification == VerificationStatus.NOT_RUN
    assert not record.produced
    assert not Path(plan.output_root).exists()


def test_unsupported_project_and_synthesis_are_not_claimed(tmp_path):
    adapter, plan, record = run_fixture(tmp_path, "unsupported")
    assert record.outcome == OperationOutcome.UNSUPPORTED
    synthesis = adapter.prepare(FIXTURES / "success", tmp_path / "synthesis", trusted=True, operation=CREATE_NEW_APPLICATION_USING_PROJECT)
    assert adapter.execute(synthesis).outcome == OperationOutcome.UNSUPPORTED
    assert not Path(plan.output_root).exists()


def test_exit_zero_is_not_functional_success(tmp_path):
    _, _, record = run_fixture(tmp_path, "failed_verification")
    assert record.outcome == OperationOutcome.SUCCEEDED
    assert record.verification == VerificationStatus.FAILED
    assert record.executed[-1]["exit_code"] == 0
    assert record.executed[-1]["stdout"] != record.executed[-1]["expected_stdout"]


def test_timeout_preserves_partial_artifact_evidence(tmp_path):
    _, _, record = run_fixture(tmp_path, "timeout", timeout_seconds=0.2)
    assert record.outcome == OperationOutcome.PARTIAL
    assert record.verification == VerificationStatus.INCONCLUSIVE
    assert Path(record.produced[0]["path"]).exists()
    assert "timed out" in record.executed[-1]["detail"]


def test_explicit_trust_required(tmp_path):
    adapter = PythonBuildAdapter()
    plan = adapter.prepare(FIXTURES / "success", tmp_path / "output")
    record = adapter.execute(plan)
    assert record.outcome == OperationOutcome.FAILED
    assert "trust" in " ".join(plan.validation_errors)
    assert not Path(plan.output_root).exists()


def test_changed_source_rejected(tmp_path):
    source = fixture(tmp_path)
    adapter = PythonBuildAdapter()
    plan = adapter.prepare(source, tmp_path / "output", trusted=True)
    (source / "main.py").write_text("raise RuntimeError('changed')", encoding="utf-8")
    record = adapter.execute(plan)
    assert record.outcome == OperationOutcome.FAILED
    assert "source changed" in record.evidence[0].detail
    assert not Path(plan.output_root).exists()


def test_artifact_change_rejected_before_execution(tmp_path):
    adapter = PythonBuildAdapter()
    plan = adapter.prepare(fixture(tmp_path), tmp_path / "output", trusted=True)
    record = adapter.execute(plan)
    Path(record.produced[0]["path"]).write_bytes(b"modified")
    adapter.verify(plan, record)
    assert record.verification == VerificationStatus.FAILED
    assert not any(item["stage"] == "verify" for item in record.executed)


def test_output_cannot_be_source_subdirectory(tmp_path):
    source = fixture(tmp_path)
    adapter = PythonBuildAdapter()
    plan = adapter.prepare(source, source / "output", trusted=True)
    assert not plan.ready
    assert not (source / "output").exists()


def test_existing_artifact_preserved(tmp_path):
    adapter, plan, record = run_fixture(tmp_path)
    artifact = Path(record.produced[0]["path"])
    before = artifact.read_bytes()
    repeated = adapter.execute(plan)
    assert repeated.outcome == OperationOutcome.FAILED
    assert not repeated.produced
    assert artifact.read_bytes() == before
    assert any("refusing overwrite" in evidence.detail for evidence in repeated.evidence)


def test_cancel_after_packaging_preserves_evidence(tmp_path):
    adapter = PythonBuildAdapter()
    plan = adapter.prepare(fixture(tmp_path), tmp_path / "output", trusted=True)
    record = adapter.execute(plan)
    adapter.verify(plan, record, cancelled=lambda: True)
    assert record.outcome == OperationOutcome.PARTIAL
    assert record.verification == VerificationStatus.INCONCLUSIVE
    assert Path(record.produced[0]["path"]).is_file()


def test_cancel_before_execution_does_not_write(tmp_path):
    adapter = PythonBuildAdapter()
    plan = adapter.prepare(fixture(tmp_path), tmp_path / "output", trusted=True)
    record = adapter.execute(plan, cancelled=lambda: True)
    assert record.outcome == OperationOutcome.CANCELLED
    assert not Path(plan.output_root).exists()


def test_size_limit_rejected_before_writes(tmp_path):
    adapter = PythonBuildAdapter(max_source_bytes=1)
    plan = adapter.prepare(FIXTURES / "success", tmp_path / "output", trusted=True)
    assert not plan.ready
    assert "max_source_bytes" in " ".join(plan.validation_errors)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_timeout_must_be_bounded(timeout):
    with pytest.raises(ValueError):
        PythonBuildAdapter(timeout_seconds=timeout)


def test_manifest_path_traversal_rejected(tmp_path):
    source = fixture(tmp_path)
    manifest = source / "sce-build.json"
    spec = json.loads(manifest.read_text())
    spec["name"] = "../escape"
    manifest.write_text(json.dumps(spec))
    plan = PythonBuildAdapter().prepare(source, tmp_path / "output", trusted=True)
    assert not plan.ready


def test_manifest_unknown_contract_fields_rejected(tmp_path):
    source = fixture(tmp_path)
    manifest = source / "sce-build.json"
    spec = json.loads(manifest.read_text())
    spec["install_after_build"] = True
    manifest.write_text(json.dumps(spec))
    plan = PythonBuildAdapter().prepare(source, tmp_path / "output", trusted=True)
    assert not plan.ready


def test_verification_output_evidence_is_bounded(tmp_path):
    result = verify_process(
        [sys.executable, "-I", "-c", "print('x' * 5000)"], cwd=tmp_path,
        expected_stdout="", expected_exit=0, timeout_seconds=5, max_output_bytes=100,
    )
    assert result.status == "inconclusive"
    assert "output limit" in result.detail
    assert len(result.stdout) <= 100
