from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sce.core.models import Evidence


@dataclass(frozen=True)
class Capability:
    id: str
    description: str
    input_schema: dict[str, str]
    output_schema: dict[str, str]
    implementation_status: str = "proposed"
    available: bool = False
    verification_evidence: list[Evidence] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id or self.implementation_status not in {"proposed", "implemented"}:
            raise ValueError("Invalid capability identity or implementation status")
        if self.implementation_status == "proposed" and self.available:
            raise ValueError("Proposed capabilities cannot be available")
        if any(t not in {"str", "bool", "int", "dict", "list"} for t in self.input_schema.values()):
            raise ValueError("Unsupported input contract type")

    def validate_inputs(self, inputs: dict[str, Any]) -> None:
        if not isinstance(inputs, dict) or set(inputs) != set(self.input_schema):
            raise ValueError(f"{self.id} requires exactly: {sorted(self.input_schema)}")
        types = {"str": str, "bool": bool, "int": int, "dict": dict, "list": list}
        for key, expected in self.input_schema.items():
            if type(inputs[key]) is not types[expected]:
                raise ValueError(f"{key} must be {expected}")


class CapabilityRegistry:
    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        if capability.id in self._capabilities:
            raise ValueError(f"Duplicate capability: {capability.id}")
        self._capabilities[capability.id] = capability

    def get(self, capability_id: str) -> Capability:
        return self._capabilities[capability_id]

    def list(self) -> list[Capability]:
        return list(self._capabilities.values())

    def validate_call(self, capability_id: str, inputs: dict[str, Any]) -> None:
        capability = self.get(capability_id)
        if capability.implementation_status != "implemented" or not capability.available:
            raise ValueError(f"Capability unavailable: {capability_id}")
        capability.validate_inputs(inputs)


def default_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(Capability(
        id="python.build", description="Build and explicitly verify controlled Python zipapp fixtures",
        input_schema={"source": "str", "output_root": "str", "trusted": "bool"},
        output_schema={"operation": "OperationRecord"},
        implementation_status="implemented", available=True,
        limitations=["Requires sce-build.json; controlled fixtures only", "Runs explicitly trusted Python code",
                     "Archive requires Python; no installation", "Verification evidence is recorded per operation"],
    ))
    registry.register(Capability(
        id="dotnet.build", description="Future replaceable .NET build adapter",
        input_schema={"source": "str", "output_root": "str"}, output_schema={"operation": "OperationRecord"},
        limitations=["Proposed only; no .NET build implementation or compatibility claim"],
    ))
    registry.register(Capability(
        id="application.synthesize", description="Future adapter-based construction of a new application",
        input_schema={"components": "list"}, output_schema={"operation": "OperationRecord"},
        limitations=["Proposed only; BUILD_ORIGINAL_PROJECT does not implement synthesis"],
    ))
    return registry
