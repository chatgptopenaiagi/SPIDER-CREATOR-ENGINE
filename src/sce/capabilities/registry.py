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
    implementation: str | None = None
    required_tools: list[str] = field(default_factory=list)
    expected_effects: list[str] = field(default_factory=list)
    execution_limits: dict[str, Any] = field(default_factory=dict)
    verification_method: str | None = None
    tested: bool = False
    verified_functional: bool = False

    def __post_init__(self) -> None:
        if not self.id or self.implementation_status not in {"proposed", "implemented"}:
            raise ValueError("Invalid capability identity or implementation status")
        if self.implementation_status == "proposed" and self.available:
            raise ValueError("Proposed capabilities cannot be available")
        if (self.tested or self.verified_functional) and (self.implementation_status != "implemented" or not self.verification_evidence):
            raise ValueError("Tested or functionally verified capability states require implementation and evidence")
        if self.verified_functional and not self.tested:
            raise ValueError("Functional verification requires tested state")
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
        id="python.build", description="Build and explicitly verify declared Python zipapp applications",
        input_schema={"source": "str", "output_root": "str", "trusted": "bool"},
        output_schema={"operation": "OperationRecord"},
        implementation_status="implemented", available=True,
        implementation="sce.builders.PythonBuildAdapter", required_tools=["Python 3.11+"],
        expected_effects=["Creates a Python archive in the selected artifact directory"],
        verification_method="Artifact hash and independently declared stdout/exit checks",
        limitations=["Requires a declared sce-build.json interface; fixture and synthesis matrix qualified", "Runs explicitly trusted Python code",
                     "Archive requires Python; no installation", "Verification evidence is recorded per operation"],
    ))
    registry.register(Capability(
        id="dotnet.build", description="Future replaceable .NET build adapter",
        input_schema={"source": "str", "output_root": "str"}, output_schema={"operation": "OperationRecord"},
        limitations=["Proposed only; no .NET build implementation or compatibility claim"],
    ))
    registry.register(Capability(
        id="application.synthesize", description="Create a Python application connecting inspected JSON-callable components",
        input_schema={"request": "dict"}, output_schema={"operation": "OperationRecord"},
        implementation_status="implemented", available=True, implementation="sce.synthesis.PythonSynthesisAdapter",
        required_tools=["Python 3.11+"], expected_effects=["Creates a new isolated application source tree"],
        execution_limits={"max_components": 8}, verification_method="Source construction integrity; independent functionality is a separate stage",
        limitations=["Declared synchronous Python callable interfaces; no general application generation claim"],
    ))
    for identity, description, implementation, effects, method in (
        ("spider.discover", "Inspect explicit local resources or bounded public GitHub metadata", "sce.discovery.SpiderDiscovery", ["Reads selected sources; optional public HTTP"], "Attributable structured metadata and revision/content evidence"),
        ("resource.acquire_local", "Acquire bounded local resources with content integrity", "sce.acquisition.LocalAcquirer", ["Copies snapshots into selected resource library"], "SHA-256 inventory match"),
        ("project.analyze", "Bounded static source and dependency observations", "sce.analysis.analyze_local", ["Reads source metadata without importing it"], "Readability and metadata evidence; no buildability inference"),
        ("application.verify", "Run declared functional acceptance for a built Python application", "sce.builders.PythonBuildAdapter.verify", ["Executes explicitly trusted application"], "Pinned artifact identity plus exact output and exit"),
    ):
        registry.register(Capability(identity, description, {"request": "dict"}, {"operation": "OperationRecord"},
            implementation_status="implemented", available=True, implementation=implementation,
            expected_effects=effects, verification_method=method,
            limitations=["Status and evidence apply to the declared operation scope, not universal compatibility"]))
    registry.register(Capability(
        id="qasc.create_python", description="Generate Python through an explicitly configured independent QASC installation",
        input_schema={"request": "dict"}, output_schema={"operation": "OperationRecord"},
        implementation_status="implemented", available=False, implementation="sce.adapters.qasc.PythonQASCAdapter",
        required_tools=["Explicit installed QASC 0.1.0 interpreter", "Available configured local model"],
        expected_effects=["Creates source in configured BUILD_WORKSPACES", "Separate trusted verification executes generated source"],
        verification_method="Retained independent acceptance, nonzero unit tests, unchanged source fingerprint",
        limitations=["Optional adapter: availability requires an explicit interpreter and live model check", "No automatic recovery, packaging or installation; capability definition grants no execution authority"],
    ))
    return registry
