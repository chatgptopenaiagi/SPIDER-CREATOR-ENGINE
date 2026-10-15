import hashlib
import json
from pathlib import Path
import sys

import pytest

from sce.adapters.qasc import PythonQASCAdapter, QASCCall, run_qasc
from sce.core.models import OperationOutcome, VerificationStatus, jsonable


ACCEPTANCE = {"cases": [{"name": "greeting", "args": ["Ada"], "stdout": "Hello Ada\n"}]}


def fingerprint(project, files):
    data = [{"path": name, "sha256": hashlib.sha256((project / name).read_bytes()).hexdigest()} for name in sorted(files)]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class FakeQASC:
    def __init__(self, *, tests=2, acceptance_passed=True, changed_acceptance=False, timeout=False):
        self.calls = []
        self.tests = tests
        self.acceptance_passed = acceptance_passed
        self.changed_acceptance = changed_acceptance
        self.timeout = timeout

    def __call__(self, argv, *, cwd, env, timeout_seconds, max_output_bytes):
        self.calls.append(argv)
        assert env["PYTHONDONTWRITEBYTECODE"] == "1"
        assert Path(env["TEMP"]).is_relative_to(cwd)
        assert argv[1:5] == ["-I", "-B", "-m", "qasc"]
        assert "--run" not in argv and "package" not in argv and "resume" not in argv
        if "create" in argv:
            name = argv[argv.index("--name") + 1]
            acceptance = json.loads(Path(argv[argv.index("--acceptance") + 1]).read_text(encoding="utf-8"))
            project = cwd / name
            (project / ".qasc").mkdir(parents=True)
            if self.timeout:
                return QASCCall(tuple(argv), interrupted=True, detail="model timeout")
            (project / "app.py").write_text('print("Hello Ada")', encoding="utf-8")
            state = {"name": name, "files": ["app.py"], "revision": "0001", "entrypoint": "app.py", "acceptance": acceptance}
            (project / ".qasc" / "state.json").write_text(json.dumps(state), encoding="utf-8")
            return QASCCall(tuple(argv), 0, json.dumps({"name": name, "status": "generated"}))
        name = argv[argv.index("test") + 1]
        project = cwd / name
        state_path = project / ".qasc" / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        verification = {"passed": True, "unit_tests_passed": True, "unit_test_count": self.tests, "independent_acceptance_passed": self.acceptance_passed, "source_unchanged": True, "source_fingerprint": fingerprint(project, state["files"]), "acceptance_cases": [{"name": case["name"], "passed": self.acceptance_passed, "mismatches": [], "receipt_id": f"case-{index}"} for index, case in enumerate(state["acceptance"]["cases"])]}
        state["last_verification"] = verification
        if self.changed_acceptance:
            state["acceptance"]["cases"][0]["stdout"] = "tampered"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        return QASCCall(tuple(argv), 0, json.dumps({"name": name, "status": "verified", "last_verification": verification, "verification_matches_current_source": True}))


def make_adapter(tmp_path, **kwargs):
    fake = FakeQASC(**kwargs)
    return PythonQASCAdapter(sys.executable, tmp_path / "builds", runner=fake), fake


def test_prepare_read_only_and_generate_does_not_verify(tmp_path):
    adapter, fake = make_adapter(tmp_path)
    plan = adapter.prepare("Create a greeting CLI", "greeting", acceptance=ACCEPTANCE)
    assert not (tmp_path / "builds").exists()
    assert not fake.calls
    record = adapter.execute(plan)
    assert record.outcome == OperationOutcome.SUCCEEDED
    assert record.verification == VerificationStatus.NOT_RUN
    assert len(fake.calls) == 1
    assert record.produced[0]["files"]
    assert adapter.report(record) is record
    json.dumps(jsonable(record))


def test_separate_verify_checks_fixed_acceptance_and_source(tmp_path):
    adapter, fake = make_adapter(tmp_path)
    plan = adapter.prepare("Create a greeting CLI", "greeting", acceptance=ACCEPTANCE)
    record = adapter.execute(plan)
    adapter.verify(plan, record, trusted_generated_source=True)
    assert record.outcome == OperationOutcome.SUCCEEDED
    assert record.verification == VerificationStatus.PASSED
    assert len(fake.calls) == 2
    assert fake.calls[-1][-4:] == ["test", "greeting", "--timeout", "30"]
    assert not any("remains unverified" in item for item in record.unknowns)


@pytest.mark.parametrize("kwargs", [{"tests": 0}, {"tests": True}, {"acceptance_passed": False}, {"changed_acceptance": True}])
def test_exit_zero_is_insufficient_for_verification(tmp_path, kwargs):
    adapter, _ = make_adapter(tmp_path, **kwargs)
    plan = adapter.prepare("Create a greeting CLI", "greeting", acceptance=ACCEPTANCE)
    record = adapter.execute(plan)
    adapter.verify(plan, record, trusted_generated_source=True)
    assert record.outcome == OperationOutcome.SUCCEEDED
    assert record.verification == VerificationStatus.FAILED


def test_generated_source_requires_explicit_trust(tmp_path):
    adapter, fake = make_adapter(tmp_path)
    plan = adapter.prepare("Create a greeting CLI", "greeting", acceptance=ACCEPTANCE)
    record = adapter.execute(plan)
    with pytest.raises(ValueError, match="trust"):
        adapter.verify(plan, record)
    assert len(fake.calls) == 1
    assert record.verification == VerificationStatus.NOT_RUN


def test_changed_source_prevents_verification_execution(tmp_path):
    adapter, fake = make_adapter(tmp_path)
    plan = adapter.prepare("Create a greeting CLI", "greeting", acceptance=ACCEPTANCE)
    record = adapter.execute(plan)
    (Path(plan.project) / "app.py").write_text("changed")
    adapter.verify(plan, record, trusted_generated_source=True)
    assert record.verification == VerificationStatus.FAILED
    assert len(fake.calls) == 1


def test_timeout_preserves_partial_project_without_success_claim(tmp_path):
    adapter, _ = make_adapter(tmp_path, timeout=True)
    plan = adapter.prepare("Create a greeting CLI", "greeting", acceptance=ACCEPTANCE)
    record = adapter.execute(plan)
    assert record.outcome == OperationOutcome.PARTIAL
    assert record.verification == VerificationStatus.NOT_RUN
    assert Path(plan.project).is_dir()
    assert record.produced[0]["kind"] == "partial_qasc_project"


def test_workspace_scope_and_existing_project_are_enforced(tmp_path):
    adapter, fake = make_adapter(tmp_path)
    with pytest.raises(ValueError, match="BUILD_WORKSPACES"):
        adapter.prepare("Create a CLI", "sample", workspace=tmp_path / "elsewhere", acceptance=ACCEPTANCE)
    plan = adapter.prepare("Create a CLI", "sample", acceptance=ACCEPTANCE)
    Path(plan.project).mkdir(parents=True)
    record = adapter.execute(plan)
    assert record.outcome != OperationOutcome.SUCCEEDED
    assert not fake.calls
    with pytest.raises(ValueError, match="already exists"):
        adapter.prepare("Create a CLI", "sample", acceptance=ACCEPTANCE)


@pytest.mark.parametrize("acceptance", [{}, {"cases": []}, {"cases": [{"stdout": 3}]}, {"cases": [{"stdout": "", "command": "run anything"}]}, {"cases": [{"name": "duplicate", "stdout": ""}, {"name": "duplicate", "stdout": ""}]}])
def test_invalid_acceptance_rejected_without_execution(tmp_path, acceptance):
    adapter, fake = make_adapter(tmp_path)
    with pytest.raises(ValueError):
        adapter.prepare("Create a CLI", "sample", acceptance=acceptance)
    assert not fake.calls


def test_record_plan_mismatch_prevents_verify(tmp_path):
    adapter, fake = make_adapter(tmp_path)
    plan = adapter.prepare("Create a CLI", "sample", acceptance=ACCEPTANCE)
    record = adapter.execute(plan)
    record.planned["objective"] = "Different objective"
    adapter.verify(plan, record, trusted_generated_source=True)
    assert record.verification == VerificationStatus.FAILED
    assert len(fake.calls) == 1


def test_actual_process_runner_captures_bounded_output(tmp_path):
    import os
    env = os.environ.copy()
    env["TEMP"] = str(tmp_path)
    call = run_qasc([sys.executable, "-I", "-B", "-c", "print('ok')"], cwd=tmp_path, env=env, timeout_seconds=3, max_output_bytes=100)
    assert call.exit_code == 0 and call.stdout.strip() == "ok" and not call.interrupted
    call = run_qasc([sys.executable, "-I", "-B", "-c", "print('x'*10000)"], cwd=tmp_path, env=env, timeout_seconds=3, max_output_bytes=100)
    assert call.interrupted and len(call.stdout.encode()) <= 100
    call = run_qasc([sys.executable, "-I", "-B", "-c", "import time; time.sleep(5)"], cwd=tmp_path, env=env, timeout_seconds=0.05, max_output_bytes=100)
    assert call.interrupted and "timeout" in call.detail
