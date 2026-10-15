import json
import os
import subprocess
import sys

from sce.ai import Interpretation
from sce.ai.provider import INTERPRETATION_PROMPT
from sce.cli.main import main
from sce.core.config import Config
from sce.core.models import Evidence, OperationRecord, OperationOutcome, Task, VerificationStatus
from sce.storage import TaskStore


def test_redirected_windows_style_legacy_encoding_keeps_unicode_json(tmp_path):
    environment = {**os.environ, "PYTHONIOENCODING": "ascii"}
    objective = "温度 → Fahrenheit"
    result = subprocess.run([sys.executable, "-m", "sce", "task", "create", objective],
        cwd=tmp_path, env=environment, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert json.loads(result.stdout.decode("utf-8"))["objective"] == objective


def test_interpretation_includes_runtime_receipts_chronology_and_fits_wire_budget(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config = Config.default(tmp_path)
    store = TaskStore(config.storage["TASK_DATABASE"])
    task = Task("Inspect the actual Celsius conversion evidence")
    store.create_task(task)
    for index in range(6):
        record = OperationRecord(capability_id="application.verify", task_id=task.id,
            outcome=OperationOutcome.SUCCEEDED, verification=VerificationStatus.PASSED,
            started_at=f"2026-10-15T13:00:0{index}+00:00", finished_at=f"2026-10-15T13:01:0{index}+00:00",
            executed=[{"stage": "verify", "argv": ["python", "main.py", "25"], "stdout": "77.0\n", "stderr": "", "exit_code": 0}],
            evidence=[Evidence("captured subprocess", "Observed exact output: " + "温度" * 400, kind="verification")],
            produced=[{"path": "main.py", "sha256": "a" * 64}])
        store.save_operation(record)
    captured = []

    class Provider:
        def interpret(self, context):
            captured.append(context)
            return Interpretation("Recorded checks passed within their declared scope.", (), ())

    import importlib
    monkeypatch.setattr(importlib.import_module("sce.cli.main"), "_provider", lambda config: Provider())
    assert main(["ai-interpret", task.id]) == 0, capsys.readouterr()
    context, = captured
    payload = json.dumps({"objective": context.objective, "records": list(context.records)}, ensure_ascii=False)
    assert len(payload) <= config.ai.max_context_chars
    assert len(payload.encode("utf-8")) + len(INTERPRETATION_PROMPT.encode("utf-8")) + 128 + config.ai.max_response_tokens <= config.resources.model_context_tokens
    newest = json.loads(context.records[0])
    assert newest["operation_order"] == 5
    assert newest["started_at"] == "2026-10-15T13:00:05+00:00"
    assert newest["finished_at"] == "2026-10-15T13:01:05+00:00"
    assert newest["executed"][0]["stdout"] == "77.0\n"
    assert newest["executed"][0]["exit_code"] == 0
    assert newest["artifact_identities"][0]["sha256"] == "a" * 64
    assert "same artifact" in newest["scope"]
    assert len(store.operations_for_task(task.id)) == 6
