"""Availability and historical qualification are independent execution facts."""

import pytest

from sce.capabilities import Capability, CapabilityRegistry, default_registry
from sce.core.models import Evidence


EVIDENCE = [Evidence("fixture://acceptance/run-1", "Observed exact output for declared fixture", kind="verification")]


@pytest.mark.parametrize("settings", [
    {"available": True},
    {"tested": True, "verification_evidence": EVIDENCE},
    {"implementation_status": "implemented", "tested": True},
    {"implementation_status": "implemented", "verified_functional": True, "verification_evidence": EVIDENCE},
    {"implementation_status": "implemented", "tested": True, "verified_functional": True},
])
def test_capability_qualification_requires_implementation_tests_and_evidence(settings):
    with pytest.raises(ValueError):
        Capability("fixture.execute", "Declared fixture", {}, {}, **settings)


def test_available_implementation_does_not_automatically_gain_tested_or_verified_status():
    capability = Capability("fixture.execute", "Declared fixture", {"source": "str"}, {},
                            implementation_status="implemented", available=True)
    registry = CapabilityRegistry()
    registry.register(capability)
    registry.validate_call("fixture.execute", {"source": "selected source"})
    assert capability.tested is False
    assert capability.verified_functional is False
    assert not capability.verification_evidence


def test_historical_functional_evidence_does_not_make_unavailable_adapter_callable():
    capability = Capability("fixture.execute", "Previously qualified fixture", {}, {},
                            implementation_status="implemented", available=False,
                            tested=True, verified_functional=True, verification_evidence=EVIDENCE)
    registry = CapabilityRegistry()
    registry.register(capability)
    assert registry.get(capability.id).verified_functional is True
    with pytest.raises(ValueError, match="unavailable"):
        registry.validate_call(capability.id, {})


def test_default_registry_keeps_optional_tools_and_proposals_unavailable():
    registry = default_registry()
    proposed = registry.get("dotnet.build")
    optional = registry.get("qasc.create_python")
    assert proposed.implementation_status == "proposed" and not proposed.available
    assert optional.implementation_status == "implemented" and not optional.available
    assert all(not item.tested and not item.verified_functional for item in registry.list())
    with pytest.raises(ValueError, match="unavailable"):
        registry.validate_call("qasc.create_python", {"request": {"objective": "Create a CLI"}})
