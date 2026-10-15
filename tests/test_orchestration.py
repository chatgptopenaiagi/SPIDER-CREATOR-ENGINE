import sqlite3

import pytest

from sce.core.models import Evidence, OperationOutcome, OperationRecord, Task, TaskStatus, TaskStep, VerificationStatus
from sce.orchestration import Orchestrator, TaskValidationError, validate_task
from sce.storage.task_store import TaskStore


def make_task(*steps):
    return Task(objective="Build a controlled fixture", allowed_capabilities=["fixture.build"], steps=list(steps))


def step(identifier, dependencies=None, max_attempts=1):
    return TaskStep(id=identifier, capability_id="fixture.build", dependencies=dependencies or [], max_attempts=max_attempts)


def success(task_step):
    return OperationRecord(
        capability_id=task_step.capability_id, outcome=OperationOutcome.SUCCEEDED,
        verification=VerificationStatus.PASSED,
        evidence=[Evidence(source="fixture-test", detail="Expected fixture output matched")],
    )


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "selected" / "tasks.sqlite3")


def test_dependency_order_persists_serializable_verified_results(store):
    task = make_task(step("second", ["first"]), step("first"))
    calls = []

    def execute(task_step):
        checkpoint = store.get_task(task.id)
        assert next(item for item in checkpoint.steps if item.id == task_step.id).status == TaskStatus.RUNNING
        calls.append(task_step.id)
        return success(task_step)

    result = Orchestrator(store, execute).run(task)
    assert calls == ["first", "second"]
    assert result.status == TaskStatus.COMPLETED
    assert store.get_task(task.id) == result
    assert len(store.operations_for_task(task.id)) == 2
    for operation in store.operations_for_task(task.id):
        assert store.get_operation(operation.id) == operation
        assert operation.task_id == task.id


@pytest.mark.parametrize("steps", [
    [step("a", ["b"]), step("b", ["a"])],
    [step("a", ["missing"])],
    [step("a"), step("a")],
    [step("a", ["a"])],
    [step("a"), step("b", ["a", "a"])],
    [],
])
def test_invalid_graph_never_executes_or_persists(store, steps):
    with pytest.raises(TaskValidationError):
        Orchestrator(store, lambda _: pytest.fail("Invalid task must not execute")).run(make_task(*steps))
    assert store.list_tasks() == []


def test_allowlist_blocks_model_or_other_capability_expansion(store):
    task = make_task(TaskStep(id="outside", capability_id="install.arbitrary"))
    with pytest.raises(TaskValidationError, match="outside task scope"):
        Orchestrator(store, lambda _: pytest.fail("Forbidden capability must not execute")).run(task)
    assert store.list_tasks() == []


def test_retry_requires_explicit_safety_and_stays_bounded(store):
    calls = []

    def execute(task_step):
        calls.append(task_step.attempts)
        return OperationRecord(capability_id=task_step.capability_id, outcome=OperationOutcome.FAILED, planned={"retry_safe": True})

    result = Orchestrator(store, execute).run(make_task(step("retry", max_attempts=3)))
    assert calls == [1, 2, 3]
    assert result.status == TaskStatus.FAILED
    assert len(store.operations_for_task(result.id)) == 3


def test_failed_execution_without_retry_safety_is_not_repeated(store):
    calls = []

    def execute(task_step):
        calls.append(task_step.id)
        return OperationRecord(capability_id=task_step.capability_id, outcome=OperationOutcome.FAILED)

    result = Orchestrator(store, execute).run(make_task(step("unsafe", max_attempts=3)))
    assert calls == ["unsafe"]
    assert result.steps[0].attempts == 1


def test_failed_dependency_blocks_dependents_but_independent_work_finishes(store):
    calls = []

    def execute(task_step):
        calls.append(task_step.id)
        if task_step.id == "first":
            return OperationRecord(capability_id=task_step.capability_id, outcome=OperationOutcome.FAILED)
        return success(task_step)

    result = Orchestrator(store, execute).run(make_task(step("first"), step("dependent", ["first"]), step("independent")))
    assert calls == ["first", "independent"]
    assert result.status == TaskStatus.FAILED
    assert result.steps[1].status == TaskStatus.BLOCKED
    assert result.steps[2].status == TaskStatus.COMPLETED


@pytest.mark.parametrize("verification, expected", [
    (VerificationStatus.NOT_RUN, TaskStatus.BLOCKED),
    (VerificationStatus.INCONCLUSIVE, TaskStatus.BLOCKED),
    (VerificationStatus.FAILED, TaskStatus.FAILED),
])
def test_successful_execution_does_not_imply_verified_completion(store, verification, expected):
    def execute(task_step):
        return OperationRecord(capability_id=task_step.capability_id, outcome=OperationOutcome.SUCCEEDED, verification=verification)

    result = Orchestrator(store, execute).run(make_task(step("first")))
    assert result.status == expected
    assert store.operations_for_task(result.id)[0].outcome == OperationOutcome.SUCCEEDED


def test_exception_is_preserved_as_partial_and_never_automatically_retried(store):
    calls = []

    def execute(task_step):
        calls.append(task_step.id)
        raise RuntimeError("Lost confirmation after write")

    result = Orchestrator(store, execute).run(make_task(step("ambiguous", max_attempts=3)))
    assert calls == ["ambiguous"]
    assert result.status == TaskStatus.BLOCKED
    record = store.operations_for_task(result.id)[0]
    assert record.outcome == OperationOutcome.PARTIAL
    assert record.verification == VerificationStatus.INCONCLUSIVE
    assert "Lost confirmation after write" in record.unknowns[0]


def test_resume_interrupted_step_blocks_side_effect_replay(store):
    task = make_task(step("interrupted"), step("dependent", ["interrupted"]))
    task.status = TaskStatus.RUNNING
    task.steps[0].status = TaskStatus.RUNNING
    task.steps[0].attempts = 1
    store.save_task(task)
    result = Orchestrator(store, lambda _: pytest.fail("Ambiguous work must not replay")).resume(task.id)
    assert result.status == TaskStatus.BLOCKED
    assert all(item.status == TaskStatus.BLOCKED for item in result.steps)
    assert "reconciliation" in result.unknowns[0]


def test_resume_safe_checkpoint_does_not_repeat_completed_work(store):
    task = make_task(step("complete"), step("next", ["complete"]))
    task.status = TaskStatus.RUNNING
    task.steps[0].status = TaskStatus.COMPLETED
    task.steps[0].attempts = 1
    record = success(task.steps[0])
    record.task_id = task.id
    task.steps[0].operation_ids.append(record.id)
    store.checkpoint(task, record)
    calls = []

    def execute(task_step):
        calls.append(task_step.id)
        return success(task_step)

    result = Orchestrator(store, execute).resume(task.id)
    assert result.status == TaskStatus.COMPLETED
    assert calls == ["next"]


@pytest.mark.parametrize("evidence_state", ["missing_reference", "missing_record", "wrong_task", "unverified", "failed"])
def test_resume_reconciles_completed_steps_with_stored_operation_evidence(store, evidence_state):
    task = make_task(step("claims_complete"), step("next", ["claims_complete"]))
    task.status = TaskStatus.RUNNING
    task.steps[0].status = TaskStatus.COMPLETED
    task.steps[0].attempts = 1
    if evidence_state != "missing_reference":
        record = success(task.steps[0])
        record.task_id = "another-task" if evidence_state == "wrong_task" else task.id
        if evidence_state == "unverified":
            record.verification = VerificationStatus.NOT_RUN
        if evidence_state == "failed":
            record.outcome = OperationOutcome.FAILED
        task.steps[0].operation_ids.append(record.id)
        if evidence_state != "missing_record":
            store.save_operation(record)
    store.save_task(task)
    result = Orchestrator(store, lambda _: pytest.fail("Invalid checkpoints must not run")).resume(task.id)
    assert result.status == TaskStatus.BLOCKED
    assert all(item.status == TaskStatus.BLOCKED for item in result.steps)
    assert "evidence requires reconciliation" in result.unknowns[0]


def test_declared_allowlist_must_be_a_list_not_a_substring_container():
    with pytest.raises(ValueError):
        Task.from_dict({
            "objective": "Reject malformed allowlist", "allowed_capabilities": "prefixfixture.buildsuffix",
            "steps": [{"id": "first", "capability_id": "fixture.build"}],
        })


def test_cancellation_survives_checkpoint_and_stops_between_steps(store):
    task = make_task(step("first"), step("second", ["first"]))
    calls = []

    def execute(task_step):
        calls.append(task_step.id)
        store.request_cancellation(task.id)
        return success(task_step)

    result = Orchestrator(store, execute).run(task)
    assert calls == ["first"]
    assert result.status == TaskStatus.CANCELLED
    assert result.steps[0].status == TaskStatus.COMPLETED
    assert result.steps[1].status == TaskStatus.CANCELLED
    assert store.cancellation_requested(task.id)


def test_existing_task_and_operation_evidence_cannot_be_replaced(store):
    task = make_task(step("first"))
    completed = Orchestrator(store, success).run(task)
    with pytest.raises(sqlite3.IntegrityError):
        Orchestrator(store, success).run(Task.from_dict({
            "id": task.id, "objective": "replacement", "allowed_capabilities": ["fixture.build"],
            "steps": [{"id": "replacement", "capability_id": "fixture.build"}],
        }))
    record = store.operations_for_task(task.id)[0]
    with pytest.raises(sqlite3.IntegrityError):
        store.save_operation(record)
    assert store.get_task(task.id) == completed


def test_checkpoint_rolls_back_task_if_operation_write_fails(store):
    task = make_task(step("first"))
    store.save_task(task)
    record = success(task.steps[0])
    record.task_id = task.id
    store.save_operation(record)
    task.status = TaskStatus.COMPLETED
    with pytest.raises(sqlite3.IntegrityError):
        store.checkpoint(task, record)
    assert store.get_task(task.id).status == TaskStatus.PENDING


def test_missing_records_and_cancellation_targets_are_explicit(store):
    for method in (store.get_task, store.get_operation, store.request_cancellation, store.cancellation_requested):
        with pytest.raises(KeyError):
            method("missing")


def test_retry_budget_type_and_recorded_attempt_bounds():
    task = make_task(step("first"))
    task.steps[0].max_attempts = True
    with pytest.raises(TaskValidationError):
        validate_task(task)
    task.steps[0].max_attempts = 1
    task.steps[0].attempts = 2
    with pytest.raises(TaskValidationError):
        validate_task(task)
