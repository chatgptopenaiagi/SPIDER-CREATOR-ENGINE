from pathlib import Path

import pytest

from sce.resources import ResourceLimits, discover_environment


@pytest.mark.parametrize("fields", [
    {"max_ram_bytes": -1}, {"max_gpu_bytes": True}, {"model_context_tokens": 0},
    {"max_workers": 1.5}, {"build_parallelism": False}, {"max_temp_bytes": -1},
    {"execution_timeout_seconds": float("inf")}, {"execution_timeout_seconds": float("nan")},
    {"execution_timeout_seconds": 0}, {"max_retries": 11}, {"max_retries": -1},
])
def test_invalid_limits(fields):
    with pytest.raises(ValueError):
        ResourceLimits(**fields)


def test_limits_round_trip_and_explicit_advisory_status():
    limits = ResourceLimits(max_ram_bytes=1024, max_gpu_bytes=2048, max_retries=0)
    assert ResourceLimits(**limits.as_dict()) == limits
    assert "advisory" in limits.enforcement_status()["max_ram_bytes"]
    assert "advisory" in limits.enforcement_status()["max_gpu_bytes"]
    assert "advisory" in limits.enforcement_status()["max_temp_bytes"]


def test_environment_observes_requested_storage(tmp_path):
    observed = discover_environment(tmp_path)
    assert observed["python"]["version"]
    assert observed["cpu"]["logical_count"] is None or observed["cpu"]["logical_count"] > 0
    assert observed["disk"]["path"] == str(tmp_path.resolve())
    assert observed["disk"]["total_bytes"] > 0
    assert observed["gpu"]["status"] == "not_probed"
    assert observed["observed_at"]


def test_environment_does_not_substitute_missing_destination(tmp_path):
    absent = tmp_path / "not-created"
    observed = discover_environment(absent)
    assert observed["disk"]["path"] == str(absent)
    assert observed["disk"]["error"]
    assert observed["disk"]["free_bytes"] is None
    assert not absent.exists()


def test_gpu_absence_is_unknown_not_inferred(tmp_path, monkeypatch):
    monkeypatch.setattr("sce.resources.environment.shutil.which", lambda name: None)
    observed = discover_environment(tmp_path, probe_gpu=True)
    assert observed["gpu"]["status"] == "unavailable"
    assert observed["gpu"]["devices"] == []
