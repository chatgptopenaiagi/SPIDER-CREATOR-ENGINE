"""A deliberately sequential foundation with conservative recovery semantics."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from sce.core.models import (
    OperationOutcome,
    OperationRecord,
    Task,
    TaskStatus,
    TaskStep,
    VerificationStatus,
    utc_now,
)
from sce.storage.task_store import TaskStore


class TaskValidationError(ValueError):
    """A task violates its declared scope or dependency contract."""


def validate_task(task: Task) -> None:
    """Validate task scope and a directed acyclic graph before any execution."""
    if not task.id or not task.objective.strip():
        raise TaskValidationError("Task identity and objective are required")
    if not task.steps:
        raise TaskValidationError("At least one explicit task step is required")
    identifiers = [step.id for step in task.steps]
    if any(not item for item in identifiers) or len(set(identifiers)) != len(identifiers):
        raise TaskValidationError("Step identifiers must be nonempty and unique")
    known = set(identifiers)
    for step in task.steps:
        if step.capability_id not in task.allowed_capabilities:
            raise TaskValidationError(f"Capability outside task scope: {step.capability_id}")
        if not isinstance(step.max_attempts, int) or isinstance(step.max_attempts, bool) or not 1 <= step.max_attempts <= 10:
            raise TaskValidationError("max_attempts must be an integer between 1 and 10")
        if step.attempts < 0 or step.attempts > step.max_attempts:
            raise TaskValidationError("Recorded attempt count exceeds its declared bound")
        if len(set(step.dependencies)) != len(step.dependencies):
            raise TaskValidationError(f"Duplicate dependency in step {step.id}")
        if any(dependency not in known for dependency in step.dependencies):
            raise TaskValidationError(f"Unknown dependency in step {step.id}")
    pending = {step.id: set(step.dependencies) for step in task.steps}
    while pending:
        ready = {identifier for identifier, dependencies in pending.items() if not dependencies}
        if not ready:
            raise TaskValidationError("Task dependency graph contains a cycle")
        pending = {identifier: dependencies - ready for identifier, dependencies in pending.items() if identifier not in ready}


class Orchestrator:
    """Run a validated DAG through an injected capability executor.

    Cooperative cancellation occurs between operations. This class does not kill
    active subprocesses. One caller owns a task at a time; distributed workers and
    concurrent execution of the same task are outside this milestone's contract.
    """

    def __init__(self, store: TaskStore, executor: Callable[[TaskStep], OperationRecord]):
        self.store = store
        self.executor = executor

    def run(self, task: Task) -> Task:
        validate_task(task)
        if task.status != TaskStatus.PENDING or any(
            step.status != TaskStatus.PENDING or step.attempts or step.operation_ids for step in task.steps
        ):
            raise TaskValidationError("run requires a fresh task; use resume for a saved checkpoint")
        self.store.create_task(task)
        return self._execute(task)

    def resume(self, task_id: str) -> Task:
        task = self.store.get_task(task_id)
        validate_task(task)
        missing_evidence = []
        for step in task.steps:
            if step.status != TaskStatus.COMPLETED:
                continue
            try:
                record = self.store.get_operation(step.operation_ids[-1])
                if (record.task_id != task.id or record.capability_id != step.capability_id
                        or record.outcome != OperationOutcome.SUCCEEDED
                        or record.verification != VerificationStatus.PASSED):
                    missing_evidence.append(step)
            except (IndexError, KeyError):
                missing_evidence.append(step)
        interrupted = [step for step in task.steps if step.status == TaskStatus.RUNNING]
        if interrupted or missing_evidence:
            for step in missing_evidence:
                step.status = TaskStatus.BLOCKED
                task.unknowns.append(
                    f"Step {step.id} has no matching successful, verified operation checkpoint; evidence requires reconciliation."
                )
            for step in interrupted:
                step.status = TaskStatus.BLOCKED
                task.unknowns.append(
                    f"Step {step.id} was interrupted during execution; side effects require reconciliation before retry."
                )
            self._block_dependents(task)
            task.status = TaskStatus.BLOCKED
            self.store.checkpoint(task)
            return task
        if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED}:
            return task
        return self._execute(task)

    @staticmethod
    def _block_dependents(task: Task) -> None:
        steps = {step.id: step for step in task.steps}
        changed = True
        while changed:
            changed = False
            for step in task.steps:
                if step.status == TaskStatus.PENDING and any(
                    steps[dependency].status in {TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED}
                    for dependency in step.dependencies
                ):
                    step.status = TaskStatus.BLOCKED
                    changed = True

    def _execute(self, task: Task) -> Task:
        task.status = TaskStatus.RUNNING
        self.store.checkpoint(task)
        steps = {step.id: step for step in task.steps}
        while True:
            if self.store.cancellation_requested(task.id):
                for step in task.steps:
                    if step.status == TaskStatus.PENDING:
                        step.status = TaskStatus.CANCELLED
                task.status = TaskStatus.CANCELLED
                self.store.checkpoint(task)
                return task
            self._block_dependents(task)
            ready = next((step for step in task.steps if step.status == TaskStatus.PENDING and all(
                steps[dependency].status == TaskStatus.COMPLETED for dependency in step.dependencies
            )), None)
            if ready is None:
                break
            if ready.attempts >= ready.max_attempts:
                ready.status = TaskStatus.FAILED
                task.unknowns.append(f"Step {ready.id} exhausted its declared attempts.")
                self.store.checkpoint(task)
                continue
            ready.status = TaskStatus.RUNNING
            ready.attempts += 1
            self.store.checkpoint(task)  # Persist intent before invoking side effects.
            started_at = utc_now()
            try:
                record = self.executor(ready)
                if not isinstance(record, OperationRecord):
                    raise TypeError("Executor must return OperationRecord")
                if record.task_id not in {None, task.id} or record.capability_id != ready.capability_id:
                    raise ValueError("Executor returned a record outside this task step")
                record.task_id = task.id
            except Exception as exc:
                # An exception does not establish whether execution had side effects.
                record = OperationRecord(
                    id=str(uuid4()), task_id=task.id, capability_id=ready.capability_id,
                    requested=dict(ready.inputs), planned={"step_id": ready.id},
                    outcome=OperationOutcome.PARTIAL, verification=VerificationStatus.INCONCLUSIVE,
                    unknowns=[f"Executor raised {type(exc).__name__}: {exc}; side effects are unknown."],
                    started_at=started_at, finished_at=utc_now(),
                )
            ready.operation_ids.append(record.id)
            if record.outcome == OperationOutcome.SUCCEEDED and record.verification == VerificationStatus.PASSED:
                ready.status = TaskStatus.COMPLETED
            elif record.outcome == OperationOutcome.CANCELLED:
                ready.status = TaskStatus.CANCELLED
            elif record.outcome == OperationOutcome.PARTIAL:
                ready.status = TaskStatus.BLOCKED
                task.unknowns.append(f"Step {ready.id} has partial execution requiring reconciliation.")
            elif record.outcome == OperationOutcome.SUCCEEDED and record.verification != VerificationStatus.FAILED:
                ready.status = TaskStatus.BLOCKED
                task.unknowns.append(f"Step {ready.id} executed successfully but verification is {record.verification.value}.")
            elif record.outcome == OperationOutcome.FAILED and record.planned.get("retry_safe") is True and ready.attempts < ready.max_attempts:
                ready.status = TaskStatus.PENDING
            else:
                ready.status = TaskStatus.FAILED
            self.store.checkpoint(task, record)
        if all(step.status == TaskStatus.COMPLETED for step in task.steps):
            task.status = TaskStatus.COMPLETED
        elif any(step.status == TaskStatus.FAILED for step in task.steps):
            task.status = TaskStatus.FAILED
        elif any(step.status == TaskStatus.CANCELLED for step in task.steps):
            task.status = TaskStatus.CANCELLED
        else:
            task.status = TaskStatus.BLOCKED
        self.store.checkpoint(task)
        return task
