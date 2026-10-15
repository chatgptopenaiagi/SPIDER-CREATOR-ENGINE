import json
from pathlib import Path
import subprocess
import sys

from sce.cli.main import main
from sce import __version__

FIXTURES = Path(__file__).parents[1] / "examples" / "fixtures"


def test_installed_module_entry_point():
    result = subprocess.run([sys.executable, "-m", "sce", "--version"], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert f"SCE {__version__}" in result.stdout


def test_cli_prepare_is_read_only(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    result = main(["build", str(FIXTURES / "success"), "--output", str(tmp_path / "out"),
                   "--trust-source", "--prepare-only"])
    assert result == 0, capsys.readouterr()
    assert list(tmp_path.iterdir()) == []


def test_cli_build_report_and_task(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    result = main(["build", str(FIXTURES / "success"), "--output", str(tmp_path / "out"), "--trust-source", "--verify"])
    assert result == 0, capsys.readouterr()
    record = json.loads(capsys.readouterr().out)
    assert record["outcome"] == "succeeded" and record["verification"] == "passed"
    assert main(["report", record["id"], "--format", "html"]) == 0
    assert "<!doctype html>" in capsys.readouterr().out
    task_file = tmp_path / "task.json"
    task_file.write_text(json.dumps({"objective": "Verify fixture", "allowed_capabilities": ["python.build"],
        "steps": [{"id": "build", "capability_id": "python.build", "inputs": {
            "source": str(FIXTURES / "success"), "output_root": str(tmp_path / "task-out"), "trusted": True}}]}))
    assert main(["task", "run", str(task_file)]) == 2
    capsys.readouterr()
    assert main(["task", "run", str(task_file), "--trust-source"]) == 0
    task = json.loads(capsys.readouterr().out)
    assert task["status"] == "completed"
