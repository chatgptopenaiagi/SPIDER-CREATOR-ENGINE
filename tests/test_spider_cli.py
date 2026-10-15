import importlib
import json
from pathlib import Path

from sce.ai import Interpretation, ProviderError
from sce.cli.main import main, parser
from sce.core.config import Config
from sce.core.models import Evidence, OperationOutcome, OperationRecord, Task, VerificationStatus, jsonable
from sce.knowledge import KnowledgeRecord, KnowledgeStore, Provenance, ProvenanceCategory
from sce.storage import TaskStore


COMPONENTS = Path(__file__).parents[1] / "examples" / "components"


def create_args(*extra):
    return ["spider", "create", "Create a CSV report application", "--component", str(COMPONENTS / "csv_summary"),
            "--component", str(COMPONENTS / "summary_report"), "--acceptance", str(COMPONENTS / "csv_report_request.json"),
            "--name", "cli-csv-report", "--trust-source", *extra]


def seed_execution(tmp_path):
    config = Config.default(tmp_path)
    tasks = TaskStore(config.storage["TASK_DATABASE"])
    task = Task("Create a greeting application")
    tasks.create_task(task)
    operation = OperationRecord(capability_id="python.build", task_id=task.id,
        outcome=OperationOutcome.SUCCEEDED, verification=VerificationStatus.FAILED,
        evidence=[Evidence("functional-test:fixture", "Expected hello, observed goodbye", kind="verification")])
    tasks.save_operation(operation)
    knowledge = KnowledgeStore(config.storage["TASK_DATABASE"])
    knowledge.record_operation(operation, resource_id="fixture:hello")
    return config, task, operation


def test_product_parser_retains_explicit_scope_and_online_opt_in():
    arguments = parser().parse_args(create_args())
    assert len(arguments.component) == 2 and arguments.trust_source is True
    assert parser().parse_args(["discover", "objective"]).online is False
    assert parser().parse_args(["trace", "task", "--level", "3"]).level == 3
    assert parser().parse_args(["memory", "task", "--resource-id", "resource", "--include-history"]).include_history


def test_spider_cli_prepare_has_no_storage_side_effects(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(create_args("--prepare-only")) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["validation_errors"] == []
    assert plan["task"]["objective"] == "Create a CSV report application"
    assert list(tmp_path.iterdir()) == []


def test_discovery_memory_and_trace_commands_preserve_sources(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["discover", str(COMPONENTS / "csv_summary")]) == 0
    discovery = json.loads(capsys.readouterr().out)
    task_id = discovery["task_id"]
    project = discovery["discovery"]["projects"][0]
    assert project["resource_id"].startswith("local-observation:")
    assert project["metadata"]["languages"] == ["Python"]
    assert main(["memory", task_id, "--resource-id", project["resource_id"]]) == 0
    candidates = json.loads(capsys.readouterr().out)
    assert candidates and all(not value["historical"] for value in candidates)
    assert all(value["record"]["provenance"] for value in candidates)
    assert main(["trace", task_id, "--level", "1"]) == 0
    basic = json.loads(capsys.readouterr().out)["events"][0]
    assert "evidence" not in basic
    assert basic["outcome"] == "succeeded"
    assert main(["trace", task_id, "--level", "3", "--format", "json"]) == 0
    detailed = json.loads(capsys.readouterr().out)["events"][0]
    assert detailed["evidence"] and detailed["operation_id"] == discovery["operation_id"]


def test_spider_cli_creates_functional_application_and_preserves_its_trace(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(create_args()) == 0, capsys.readouterr()
    result = json.loads(capsys.readouterr().out)
    assert result["functional_application_created"] is True
    assert result["installation"] == "not_run"
    assert result["human_time_recovered"] is None
    assert Path(result["artifacts"][0]["path"]).is_file()
    task_id = result["task"]["id"]
    tasks = TaskStore(Config.default(tmp_path).storage["TASK_DATABASE"])
    operations = tasks.operations_for_task(task_id)
    assert len(operations) == 6
    functional = [record for record in operations if record.capability_id == "application.verify"][0]
    assert functional.verification is VerificationStatus.PASSED
    assert functional.evidence
    assert main(["trace", task_id, "--level", "2", "--format", "markdown"]) == 0
    assert "Connect declared Python JSON callables" in capsys.readouterr().out
    assert main(["memory", task_id]) == 0
    assert json.loads(capsys.readouterr().out)


def test_cli_discovery_is_offline_by_default_and_history_requires_resource(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["discover", "https://github.com/example/project"]) == 1
    discovery = json.loads(capsys.readouterr().out)
    assert "offline mode" in discovery["discovery"]["errors"][0]
    assert main(["memory", discovery["task_id"], "--include-history"]) == 2
    assert "resource identity" in capsys.readouterr().err


def test_ai_interpret_cli_receives_evidence_and_only_appends_ai_inference(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config, task, operation = seed_execution(tmp_path)
    contexts = []

    class FakeInterpreter:
        def interpret(self, context):
            contexts.append(context)
            return Interpretation("Build succeeded; functional verification failed.", ("Cause remains unknown",), ("Inspect preserved output",))

    cli = importlib.import_module("sce.cli.main")
    monkeypatch.setattr(cli, "_provider", lambda _: FakeInterpreter())
    assert main(["ai-interpret", task.id]) == 0
    response = json.loads(capsys.readouterr().out)
    assert response["executed_suggestions"] is False
    assert len(contexts) == 1 and contexts[0].objective == task.objective
    supplied = "\n".join(contexts[0].records)
    assert operation.id in supplied
    assert "Expected hello, observed goodbye" in supplied
    saved = KnowledgeStore(config.storage["TASK_DATABASE"]).get(response["knowledge_record_id"])
    assert saved.provenance[0].category is ProvenanceCategory.AI_INFERENCE
    assert "not verification" in saved.limitations[0]
    tasks = TaskStore(config.storage["TASK_DATABASE"])
    assert tasks.operations_for_task(task.id) == [operation]
    assert tasks.get_task(task.id) == task


def test_ai_interpret_failure_does_not_add_an_inference_claim(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config, task, _ = seed_execution(tmp_path)
    store = KnowledgeStore(config.storage["TASK_DATABASE"])
    before = store.retrieve(task.id)

    class UnavailableInterpreter:
        def interpret(self, context):
            raise ProviderError("Local provider unavailable")

    monkeypatch.setattr(importlib.import_module("sce.cli.main"), "_provider", lambda _: UnavailableInterpreter())
    assert main(["ai-interpret", task.id]) == 2
    assert "unavailable" in capsys.readouterr().err
    assert store.retrieve(task.id) == before


def test_cli_historical_memory_is_explicit_and_does_not_associate_automatically(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config, old_task, _ = seed_execution(tmp_path)
    new_task = Task("Compare a later greeting failure")
    TaskStore(config.storage["TASK_DATABASE"]).create_task(new_task)
    assert main(["memory", new_task.id, "--resource-id", "fixture:hello"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert main(["memory", new_task.id, "--resource-id", "fixture:hello", "--include-history"]) == 0
    candidates = json.loads(capsys.readouterr().out)
    assert candidates[0]["historical"] is True
    assert candidates[0]["applicability"]["status"] == "unknown"
    assert KnowledgeStore(config.storage["TASK_DATABASE"]).retrieve(new_task.id) == []


def test_ai_interpret_requires_actual_operations_not_only_model_claims(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config = Config.default(tmp_path)
    task = Task("Interpret actual evidence")
    TaskStore(config.storage["TASK_DATABASE"]).create_task(task)
    memory = KnowledgeStore(config.storage["TASK_DATABASE"])
    memory.append(KnowledgeRecord("Earlier model says it works", [Provenance("model", "inference", category="AI_INFERENCE")], [task.id]))
    called = []
    monkeypatch.setattr(importlib.import_module("sce.cli.main"), "_provider", lambda _: called.append(True))
    assert main(["ai-interpret", task.id]) == 2
    assert "actual recorded operations" in capsys.readouterr().err
    assert called == []
    assert len(memory.retrieve(task.id)) == 1


def test_repeated_interpretation_retains_original_evidence_instead_of_previous_inferences(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config, task, operation = seed_execution(tmp_path)
    memory = KnowledgeStore(config.storage["TASK_DATABASE"])
    for number in range(8):
        memory.append(KnowledgeRecord(f"UNSUPPORTED_PRIOR_AI_CLAIM_{number}",
                      [Provenance("model", "inference", category="AI_INFERENCE")], [task.id]))
    contexts = []

    class Interpreter:
        def interpret(self, context):
            contexts.append(context)
            return Interpretation("The declared check failed.", (), ())

    monkeypatch.setattr(importlib.import_module("sce.cli.main"), "_provider", lambda _: Interpreter())
    assert main(["ai-interpret", task.id]) == 0
    capsys.readouterr()
    supplied = "\n".join(contexts[0].records)
    assert operation.id in supplied
    assert "UNSUPPORTED_PRIOR_AI_CLAIM" not in supplied


def qasc_arguments(tmp_path, *extra):
    acceptance = tmp_path / "qasc-acceptance.json"
    acceptance.write_text(json.dumps({"cases": [{"name": "greeting", "args": [], "stdout": "hello\n", "exit_code": 0}]}))
    return ["create-ai", "Create a greeting application", "--qasc-python", str(tmp_path / "fake-qasc-python.exe"),
            "--name", "greeting-app", "--acceptance", str(acceptance), *extra]


def test_interpretation_context_keeps_runtime_receipts_and_chronological_artifact_identity(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config = Config.default(tmp_path)
    task = Task("Interpret generation and later functional checks")
    tasks = TaskStore(config.storage["TASK_DATABASE"])
    tasks.create_task(task)
    artifact = {"kind": "generated_python_project", "path": "fixture-project", "source_fingerprint": "a" * 64}
    generation = OperationRecord(capability_id="qasc.create_python", task_id=task.id,
        outcome=OperationOutcome.SUCCEEDED, verification=VerificationStatus.NOT_RUN,
        started_at="2026-10-15T10:00:00+00:00", finished_at="2026-10-15T10:01:00+00:00",
        produced=[artifact], unknowns=["Functionality remains unverified until separate VERIFY"])
    verified = OperationRecord(capability_id="qasc.create_python", task_id=task.id,
        outcome=OperationOutcome.SUCCEEDED, verification=VerificationStatus.PASSED,
        started_at="2026-10-15T10:02:00+00:00", finished_at="2026-10-15T10:03:00+00:00",
        produced=[artifact], evidence=[Evidence("fixture-tests", "Declared acceptance passed", kind="verification")],
        executed=[{"stage": "verify", "argv": ["python", "-m", "qasc", "test", "fixture-project"],
                   "exit_code": 0, "stdout": "hello\n", "stderr": "", "timed_out": False, "interrupted": False}])
    tasks.save_operation(generation)
    tasks.save_operation(verified)
    contexts = []

    class Interpreter:
        def interpret(self, context):
            contexts.append(context)
            return Interpretation("Later checks passed for the same artifact.", (), ())

    monkeypatch.setattr(importlib.import_module("sce.cli.main"), "_provider", lambda _: Interpreter())
    assert main(["ai-interpret", task.id]) == 0
    capsys.readouterr()
    records = [json.loads(record) for record in contexts[0].records]
    assert [record["operation_id"] for record in records] == [verified.id, generation.id]
    assert records[0]["operation_order"] > records[1]["operation_order"]
    assert records[0]["started_at"] == verified.started_at
    assert records[1]["finished_at"] == generation.finished_at
    receipt = records[0]["executed"][0]
    assert receipt["stdout"] == "hello\n" and receipt["exit_code"] == 0
    assert receipt["argv"][-2:] == ["test", "fixture-project"]
    assert receipt["timed_out"] is False and receipt["interrupted"] is False
    assert records[0]["artifact_identities"] == records[1]["artifact_identities"] == [artifact]
    assert records[1]["verification"] == "not_run" and records[1]["unknowns"] == generation.unknowns
    assert "same artifact and check scope" in records[0]["scope"]
    assert tasks.operations_for_task(task.id) == [generation, verified]


def test_interpretation_execution_excerpts_are_bounded_and_mark_truncation(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config, task, _ = seed_execution(tmp_path)
    tasks = TaskStore(config.storage["TASK_DATABASE"])
    operation = OperationRecord(capability_id="application.verify", task_id=task.id,
        executed=[{"stage": "verify", "argv": ["python", "argument" * 40], "stdout": "x" * 5000,
                   "stderr": "y" * 5000, "exit_code": index, "timed_out": True} for index in range(5)])
    tasks.save_operation(operation)
    contexts = []

    class Interpreter:
        def interpret(self, context):
            contexts.append(context)
            return Interpretation("Recorded execution timed out.", (), ())

    monkeypatch.setattr(importlib.import_module("sce.cli.main"), "_provider", lambda _: Interpreter())
    assert main(["ai-interpret", task.id]) == 0
    capsys.readouterr()
    records = [json.loads(record) for record in contexts[0].records]
    record = next(item for item in records if item["operation_id"] == operation.id)
    assert [receipt["exit_code"] for receipt in record["executed"]] == [2, 3, 4]
    for receipt in record["executed"]:
        assert len(receipt["stdout"]) == len(receipt["stderr"]) == 500
        assert receipt["stdout_truncated"] is True and receipt["stderr_truncated"] is True
        assert all(len(arg) <= 200 for arg in receipt["argv"])
        assert receipt["argv_is_excerpt"] is True
    assert sum(map(len, contexts[0].records)) <= config.ai.max_context_chars
    from sce.ai.provider import INTERPRETATION_PROMPT
    serialized = json.dumps({"objective": contexts[0].objective, "records": list(contexts[0].records)}, ensure_ascii=False)
    assert len(serialized) <= config.ai.max_context_chars
    assert (len(serialized.encode("utf-8")) + len(INTERPRETATION_PROMPT.encode("utf-8")) + 128
            + config.ai.max_response_tokens <= config.resources.model_context_tokens)


def fake_qasc(monkeypatch, *, generation=OperationOutcome.SUCCEEDED, verification=VerificationStatus.PASSED):
    calls = []

    class Adapter:
        def __init__(self, *args, **kwargs):
            calls.append("initialize")

        def prepare(self, objective, name, *, acceptance, task_id):
            calls.append("prepare")
            return {"task_id": task_id, "objective": objective, "name": name, "acceptance": acceptance}

        def execute(self, plan):
            calls.append("execute")
            return OperationRecord(capability_id="qasc.create_python", task_id=plan["task_id"],
                requested={"objective": plan["objective"]}, outcome=generation,
                evidence=[Evidence("mock:qasc", "Generated source" if generation == OperationOutcome.SUCCEEDED else "Observed generation failure",
                                   kind="observation" if generation == OperationOutcome.SUCCEEDED else "error")],
                produced=[{"kind": "generated_source", "path": "mock-source-only"}])

        def verify(self, plan, record, *, trusted_generated_source):
            assert trusted_generated_source is True
            calls.append("verify")
            record.verification = verification
            record.evidence.append(Evidence("mock:qasc-test", f"Declared check {verification.value}", kind="verification"))
            return record

    monkeypatch.setattr(importlib.import_module("sce.adapters.qasc"), "PythonQASCAdapter", Adapter)
    return calls


def test_create_ai_prepare_and_trust_boundaries(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    calls = fake_qasc(monkeypatch)
    assert main(qasc_arguments(tmp_path, "--verify")) == 2
    assert "trust-generated-source" in capsys.readouterr().err
    assert calls == [] and not (tmp_path / ".sce").exists()
    assert main(qasc_arguments(tmp_path, "--prepare-only")) == 0
    assert json.loads(capsys.readouterr().out)["name"] == "greeting-app"
    assert calls == ["initialize", "prepare"]
    assert not (tmp_path / ".sce").exists()


def test_create_ai_generation_only_persists_unverified_output_without_executing_it(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    calls = fake_qasc(monkeypatch)
    assert main(qasc_arguments(tmp_path)) == 0, capsys.readouterr()
    response = json.loads(capsys.readouterr().out)
    assert calls == ["initialize", "prepare", "execute"]
    assert response["operation"]["verification"] == "not_run"
    tasks = TaskStore(Config.default(tmp_path).storage["TASK_DATABASE"])
    assert len(tasks.operations_for_task(response["task_id"])) == 1
    assert tasks.get_task(response["task_id"]).status.value == "blocked"


def test_create_ai_verification_preserves_generation_and_separate_verified_record(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    calls = fake_qasc(monkeypatch)
    assert main(qasc_arguments(tmp_path, "--verify", "--trust-generated-source")) == 0
    response = json.loads(capsys.readouterr().out)
    assert calls == ["initialize", "prepare", "execute", "verify"]
    tasks = TaskStore(Config.default(tmp_path).storage["TASK_DATABASE"])
    operations = tasks.operations_for_task(response["task_id"])
    assert len(operations) == 2 and operations[0].id != operations[1].id
    assert operations[0].verification is VerificationStatus.NOT_RUN
    assert operations[1].verification is VerificationStatus.PASSED
    assert tasks.get_task(response["task_id"]).status.value == "completed"


def test_create_ai_generation_failure_preserves_capsule_and_does_not_verify(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    calls = fake_qasc(monkeypatch, generation=OperationOutcome.FAILED)
    assert main(qasc_arguments(tmp_path, "--verify", "--trust-generated-source")) == 1
    response = json.loads(capsys.readouterr().out)
    assert "verify" not in calls
    database = Config.default(tmp_path).storage["TASK_DATABASE"]
    task = TaskStore(database).get_task(response["task_id"])
    assert task.status.value == "failed"
    capsules = [record for record in KnowledgeStore(database).retrieve(task.id) if record.kind == "failure_capsule"]
    assert len(capsules) == 1
    assert capsules[0].metadata["capsule"]["original_objective"] == task.objective
    assert capsules[0].metadata["capsule"]["partial_artifacts"]


def test_create_ai_failed_functional_check_is_not_successful_creation(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    fake_qasc(monkeypatch, verification=VerificationStatus.FAILED)
    assert main(qasc_arguments(tmp_path, "--verify", "--trust-generated-source")) == 1, capsys.readouterr()
    response = json.loads(capsys.readouterr().out)
    assert response["operation"]["outcome"] == "succeeded"
    assert response["operation"]["verification"] == "failed"
    tasks = TaskStore(Config.default(tmp_path).storage["TASK_DATABASE"])
    assert len(tasks.operations_for_task(response["task_id"])) == 2
    assert tasks.get_task(response["task_id"]).status.value == "failed"
