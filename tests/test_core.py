import json
from pathlib import Path

import pytest

from sce.capabilities import Capability, CapabilityRegistry, default_registry
from sce.core.config import Config, STORAGE_NAMES
from sce.core.models import Evidence, OperationRecord, Task, TaskStep, TimeMeasurements, jsonable
from sce.reporting import render_report, write_report


def test_task_round_trip_and_unknown_time():
    task = Task("Create useful software", allowed_capabilities=["python.build"],
                steps=[TaskStep("a", "python.build")])
    assert Task.from_dict(json.loads(json.dumps(jsonable(task)))) == task
    assert task.time.human_time_recovered_seconds is None


@pytest.mark.parametrize("change", [
    {"allowed_capabilities": "python.build"}, {"objective": 12}, {"steps": {}},
    {"unknowns": "not a list"}, {"steps": [{"id": "s", "capability_id": "x", "inputs": []}]},
    {"steps": [{"id": "s", "capability_id": "x", "max_attempts": True}]},
])
def test_malformed_task_documents_rejected(change):
    with pytest.raises((ValueError, TypeError)):
        Task.from_dict({"objective": "A valid goal", **change})


def test_negative_recovery_visible_and_invalid_measurements_rejected():
    time = TimeMeasurements(baseline_human_active_seconds=20, assisted_human_active_seconds=30,
                            machine_execution_seconds=90, measurement_source="manual stopwatch")
    assert time.human_time_recovered_seconds == -10
    with pytest.raises(ValueError):
        TimeMeasurements(baseline_human_active_seconds=1)
    for value in [-1, float("nan"), float("inf"), True]:
        with pytest.raises(ValueError):
            TimeMeasurements(setup_seconds=value, measurement_source="test")


def test_registry_proposals_are_not_executable_or_verified():
    registry = default_registry()
    assert not registry.get("python.build").verification_evidence
    with pytest.raises(ValueError, match="unavailable"):
        registry.validate_call("dotnet.build", {"source": "x", "output_root": "y"})
    with pytest.raises(ValueError):
        registry.validate_call("python.build", {"source": "x", "output_root": "y", "trusted": True, "command": "extra"})
    with pytest.raises(ValueError):
        registry.register(registry.get("python.build"))
    with pytest.raises(ValueError):
        Capability("x", "proposed", {}, {}, available=True)


def test_config_paths_independent_read_only_and_no_fallback(tmp_path):
    path = tmp_path / "sce.toml"
    path.write_text('[storage]\nARTIFACT_STORAGE = "chosen"\n', encoding="utf-8")
    config = Config.load(path)
    assert set(config.storage) == set(STORAGE_NAMES)
    assert config.storage["ARTIFACT_STORAGE"] == tmp_path / "chosen"
    assert not (tmp_path / "chosen").exists()
    (tmp_path / "chosen").write_text("not a directory")
    with pytest.raises(FileExistsError):
        config.initialize_storage()
    assert (tmp_path / "chosen").read_text() == "not a directory"


def test_config_unknown_settings_rejected(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text('[storage]\nARTIFACT_STORGE="oops"')
    with pytest.raises(ValueError, match="Unknown storage"):
        Config.load(path)


def test_canonical_reports_preserve_separate_outcomes_and_escape_html(tmp_path):
    record = OperationRecord(capability_id="fixture", outcome="succeeded", verification="failed",
                             evidence=[Evidence("test", "<script>alert('x')</script>```")])
    assert OperationRecord.from_dict(json.loads(render_report(record))) == record
    assert "<script>" not in render_report(record, "html")
    assert "&lt;script&gt;" in render_report(record, "html")
    assert "````json" in render_report(record, "markdown")
    destination = tmp_path / "operation.json"
    write_report(record, destination)
    with pytest.raises(FileExistsError):
        write_report(record, destination)
