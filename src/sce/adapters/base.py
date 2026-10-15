"""The lifecycle is explicit: preparation must never execute source code."""

from typing import Any, Protocol, TypeVar

from sce.core.models import OperationRecord

Plan = TypeVar("Plan")


class Adapter(Protocol[Plan]):
    def describe(self) -> dict[str, Any]: ...

    def prepare(self, *args: Any, **kwargs: Any) -> Plan: ...

    def execute(self, plan: Plan, **kwargs: Any) -> OperationRecord: ...

    def verify(self, plan: Plan, record: OperationRecord, **kwargs: Any) -> OperationRecord: ...

    def report(self, record: OperationRecord) -> OperationRecord: ...
