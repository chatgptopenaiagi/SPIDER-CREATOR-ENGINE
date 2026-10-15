import json
import hashlib
import os
from pathlib import Path

import pytest

from sce.acquisition import LocalAcquirer
from sce.analysis import analyze_local
from sce.discovery import LocalDiscovery


def test_local_discovery_and_acquisition_identity_evidence(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "__main__.py").write_text('print("local fixture")')
    candidates = LocalDiscovery([source]).discover("source")
    assert candidates[0].source_uri == source.as_uri()
    acquirer = LocalAcquirer()
    library = tmp_path / "library"
    plan = acquirer.prepare(source, library)
    assert not library.exists()  # PREPARE performs no transfer.
    record = acquirer.execute(plan)
    assert record.transfer_status == "completed"
    assert record.identity == plan.identity
    assert record.source_revision is None
    assert record.unknowns and record.evidence
    assert json.loads((plan.destination / "resource.json").read_text())["identity"] == plan.identity
    analysis = analyze_local(Path(record.location))
    assert analysis["languages"] == ["Python"]
    assert analysis["entry_points"] == ["__main__.py"]


def test_changed_sources_and_budgets_rejected(tmp_path):
    source = tmp_path / "file.txt"
    source.write_text("before")
    acquirer = LocalAcquirer()
    plan = acquirer.prepare(source, tmp_path / "library")
    source.write_text("after")
    with pytest.raises(ValueError, match="changed"):
        acquirer.execute(plan)
    assert not plan.destination.exists()
    with pytest.raises(ValueError, match="budget"):
        LocalAcquirer(max_bytes=1).prepare(source, tmp_path / "library")


def test_single_file_acquisition_and_bounded_analysis(tmp_path):
    source = tmp_path / "app.py"
    source.write_text('print("ok")')
    acquirer = LocalAcquirer()
    record = acquirer.execute(acquirer.prepare(source, tmp_path / "lib"))
    assert record.transfer_status == "completed"
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.py").write_text("")
    (project / "b.rs").write_text("")
    report = analyze_local(project, max_files=1)
    assert len(report["structure"]) == 1
    assert any("incomplete" in item for item in report["unknowns"])


@pytest.mark.parametrize("metadata", [
    'project = "invalid table"',
    'build-system = "invalid table"',
    '[project]\ndependencies = "not an array"',
    '[project]\ndependencies = [42]',
    '[build-system]\nbuild-backend = 42',
])
def test_malformed_python_metadata_preserves_unknowns(tmp_path, metadata):
    (tmp_path / "pyproject.toml").write_text(metadata)
    report = analyze_local(tmp_path)
    assert report["dependencies"] == []
    assert any("Could not parse" in item for item in report["unknowns"])


def make_directory_link(link, target):
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory link creation not available: {exc}")


def test_analysis_prunes_linked_directories(tmp_path):
    source, outside = tmp_path / "source", tmp_path / "outside"
    source.mkdir()
    outside.mkdir()
    (source / "local.py").write_text("")
    (outside / "external.rs").write_text("")
    make_directory_link(source / "linked", outside)
    report = analyze_local(source)
    assert report["structure"] == ["local.py"]
    assert report["languages"] == ["Python"]
    assert any("Linked directory skipped" in item for item in report["unknowns"])


@pytest.mark.parametrize("redirect", ["source", "destination"])
def test_acquisition_rejects_redirected_prepared_locations(tmp_path, redirect):
    source = tmp_path / "source"
    source.mkdir()
    (source / "item.txt").write_text("same bytes")
    library = tmp_path / "library"
    library.mkdir()
    acquirer = LocalAcquirer()
    plan = acquirer.prepare(source, library)
    original = source if redirect == "source" else library
    moved = tmp_path / f"moved-{redirect}"
    original.rename(moved)
    make_directory_link(original, moved)
    with pytest.raises(ValueError, match="location changed"):
        acquirer.execute(plan)
    assert not (moved / plan.identity).exists()


def test_partial_acquisition_distinguishes_actual_and_expected_hashes(tmp_path, monkeypatch):
    source = tmp_path / "file.txt"
    source.write_text("original")
    acquirer = LocalAcquirer()
    plan = acquirer.prepare(source, tmp_path / "library")
    inventory = acquirer._inventory

    def mutate_after_source_inventory(path):
        result = inventory(path)
        if path == source:
            source.write_text("changed during acquisition")
        return result

    monkeypatch.setattr(acquirer, "_inventory", mutate_after_source_inventory)
    record = acquirer.execute(plan)
    assert record.transfer_status == "partial"
    assert record.expected_content_hashes == plan.content_hashes
    assert record.content_hashes != record.expected_content_hashes
    copied = Path(record.location) / source.name
    assert record.content_hashes[source.name] == hashlib.sha256(copied.read_bytes()).hexdigest()


def test_copy_never_includes_files_added_after_snapshot(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "planned.txt").write_text("planned")
    acquirer = LocalAcquirer()
    plan = acquirer.prepare(source, tmp_path / "library")
    inventory = acquirer._inventory

    def add_after_source_inventory(path):
        result = inventory(path)
        if path == source:
            (source / "new.txt").write_text("outside planned snapshot")
        return result

    monkeypatch.setattr(acquirer, "_inventory", add_after_source_inventory)
    record = acquirer.execute(plan)
    assert record.transfer_status == "completed"
    assert sorted(path.name for path in Path(record.location).iterdir()) == ["planned.txt"]
