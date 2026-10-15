"""Portable canonical records. Unknown measurements are represented by None."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4
import math


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def identifier() -> str:
    return str(uuid4())


def _string(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


def _strings(value: Any, name: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{name} must be a list of nonempty strings")


def jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class OperationOutcome(str, Enum):
    NOT_STARTED = "not_started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    UNSUPPORTED = "unsupported"


class VerificationStatus(str, Enum):
    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


@dataclass
class Evidence:
    source: str
    detail: str
    observed_at: str = field(default_factory=utc_now)
    kind: str = "observation"

    def __post_init__(self) -> None:
        for name in ("source", "detail", "observed_at", "kind"):
            _string(getattr(self, name), f"Evidence.{name}")


@dataclass
class TimeMeasurements:
    """Seconds; setup/review/repair are subsets of assisted human active time.

    Subsets are never automatically summed into active time or machine time.
    Baseline is a human estimate/measurement with provenance, never inferred.
    """

    baseline_human_active_seconds: float | None = None
    assisted_human_active_seconds: float | None = None
    machine_execution_seconds: float | None = None
    total_elapsed_seconds: float | None = None
    setup_seconds: float | None = None
    review_seconds: float | None = None
    repair_seconds: float | None = None
    measurement_source: str | None = None

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if name.endswith("_seconds") and value is not None:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError(f"{name} must be finite, nonnegative, or unknown")
        if any(v is not None for k, v in asdict(self).items() if k.endswith("_seconds")) and not self.measurement_source:
            raise ValueError("Known timing measurements require a source")
        if self.measurement_source is not None:
            _string(self.measurement_source, "measurement_source")

    @property
    def human_time_recovered_seconds(self) -> float | None:
        if self.baseline_human_active_seconds is None or self.assisted_human_active_seconds is None:
            return None
        return self.baseline_human_active_seconds - self.assisted_human_active_seconds


@dataclass
class TaskStep:
    id: str
    capability_id: str
    inputs: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    max_attempts: int = 1
    operation_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.status = TaskStatus(self.status)
        _string(self.id, "Step.id")
        _string(self.capability_id, "Step.capability_id")
        _strings(self.dependencies, "Step.dependencies")
        _strings(self.operation_ids, "Step.operation_ids")
        if not isinstance(self.inputs, dict):
            raise ValueError("Step.inputs must be an object")
        if (type(self.max_attempts) is not int or type(self.attempts) is not int
                or not 1 <= self.max_attempts <= 10 or not 0 <= self.attempts <= self.max_attempts):
            raise ValueError("Attempt budget must be 1..10; attempts must be within budget")


@dataclass
class Task:
    objective: str
    id: str = field(default_factory=identifier)
    allowed_capabilities: list[str] = field(default_factory=list)
    steps: list[TaskStep] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    created_at: str = field(default_factory=utc_now)
    time: TimeMeasurements = field(default_factory=TimeMeasurements)
    unknowns: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.status = TaskStatus(self.status)
        _string(self.objective, "Task.objective")
        _string(self.id, "Task.id")
        _string(self.created_at, "Task.created_at")
        _strings(self.allowed_capabilities, "Task.allowed_capabilities")
        _strings(self.unknowns, "Task.unknowns")
        if not isinstance(self.steps, list) or any(not isinstance(step, TaskStep) for step in self.steps):
            raise ValueError("Task.steps must be a list of TaskStep values")
        if not isinstance(self.time, TimeMeasurements):
            raise ValueError("Task.time must contain TimeMeasurements")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        if not isinstance(data, dict) or not isinstance(data.get("steps", []), list):
            raise ValueError("Task document must be an object with a list of steps")
        values = dict(data)
        values["steps"] = [TaskStep(**step) for step in values.get("steps", [])]
        values["time"] = TimeMeasurements(**values.get("time", {}))
        return cls(**values)


@dataclass
class OperationRecord:
    capability_id: str = ""
    id: str = field(default_factory=identifier)
    task_id: str | None = None
    requested: dict[str, Any] = field(default_factory=dict)
    planned: dict[str, Any] = field(default_factory=dict)
    outcome: OperationOutcome = OperationOutcome.NOT_STARTED
    verification: VerificationStatus = VerificationStatus.NOT_RUN
    executed: list[dict[str, Any]] = field(default_factory=list)
    produced: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None

    def __post_init__(self) -> None:
        self.outcome = OperationOutcome(self.outcome)
        self.verification = VerificationStatus(self.verification)
        _string(self.id, "Operation.id")
        if not isinstance(self.capability_id, str):
            raise ValueError("Operation.capability_id must be a string")
        if self.task_id is not None:
            _string(self.task_id, "Operation.task_id")
        for name in ("requested", "planned"):
            if not isinstance(getattr(self, name), dict):
                raise ValueError(f"Operation.{name} must be an object")
        for name in ("executed", "produced"):
            value = getattr(self, name)
            if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
                raise ValueError(f"Operation.{name} must be a list of objects")
        _strings(self.unknowns, "Operation.unknowns")
        if not isinstance(self.evidence, list) or any(not isinstance(item, Evidence) for item in self.evidence):
            raise ValueError("Operation.evidence must contain Evidence values")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OperationRecord:
        values = dict(data)
        values["evidence"] = [Evidence(**item) for item in values.get("evidence", [])]
        return cls(**values)
