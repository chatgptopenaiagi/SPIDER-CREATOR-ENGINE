"""Untrusted model output becomes a proposal, never execution authority."""

from copy import deepcopy
from dataclasses import dataclass
import json
import re
from typing import Callable, Mapping, Protocol, Sequence


class ProposalError(ValueError):
    """The model response or proposed action does not meet the host contract."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProposalError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ProposalError(f"Non-finite JSON constant: {value}")


@dataclass(frozen=True)
class CapabilityAction:
    capability_id: str
    inputs: dict


@dataclass(frozen=True)
class Proposal:
    actions: tuple[CapabilityAction, ...]
    rationale: str

    @classmethod
    def from_json(cls, raw: str, *, max_chars: int = 32768, max_actions: int = 8) -> "Proposal":
        if type(max_chars) is not int or max_chars <= 0 or type(max_actions) is not int or max_actions <= 0:
            raise ValueError("Proposal limits must be positive integers")
        if not isinstance(raw, str) or len(raw) > max_chars:
            raise ProposalError("Proposal exceeds the configured character budget")
        try:
            data = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
        except (json.JSONDecodeError, RecursionError) as error:
            raise ProposalError("Model response must be a single strict JSON object") from error
        if not isinstance(data, dict) or set(data) != {"actions", "rationale"}:
            raise ProposalError("Proposal must contain exactly actions and rationale")
        if not isinstance(data["rationale"], str) or len(data["rationale"]) > 4096:
            raise ProposalError("rationale must be a string of at most 4096 characters")
        if not isinstance(data["actions"], list) or len(data["actions"]) > max_actions:
            raise ProposalError("actions must be an array within the configured action budget")
        actions = []
        for action in data["actions"]:
            if not isinstance(action, dict) or set(action) != {"capability_id", "inputs"}:
                raise ProposalError("Each action must contain exactly capability_id and inputs")
            identifier = action["capability_id"]
            if not isinstance(identifier, str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.-]{0,127}", identifier):
                raise ProposalError("Invalid capability identifier")
            if not isinstance(action["inputs"], dict):
                raise ProposalError("Action inputs must be an object")
            actions.append(CapabilityAction(identifier, action["inputs"]))
        return cls(tuple(actions), data["rationale"])

    def as_dict(self) -> dict:
        return {"actions": [{"capability_id": action.capability_id, "inputs": deepcopy(action.inputs)}
                            for action in self.actions], "rationale": self.rationale}


class CapabilityValidator(Protocol):
    def validate_call(self, capability_id: str, inputs: dict) -> None: ...


class ExactInputScope:
    """Authorize only complete input sets already approved by the host task.

    Equality deliberately covers every field, including source paths, output
    destinations, trust flags, and generated source. The model cannot add an
    authorized destination or change a false trust flag to true.
    """

    def __init__(self, approved_inputs: Mapping[str, Sequence[Mapping]]):
        self._approved = deepcopy(dict(approved_inputs))

    def __call__(self, capability_id: str, inputs: Mapping) -> None:
        if not any(dict(inputs) == candidate for candidate in self._approved.get(capability_id, ())):
            raise ValueError("Inputs do not match a host-approved task action")


def validate_proposal(
    proposal: Proposal,
    registry: CapabilityValidator,
    allowed_capabilities: set[str] | frozenset[str],
    validate_task_inputs: Callable[[str, Mapping], None],
) -> Proposal:
    """Validate availability, exact contracts, and host-defined task scope.

    The required task validator must reject paths, source content, revisions, or
    destinations outside the human-authorized task. It returns None on success
    and raises on failure. This function does not run any proposed operation.
    Callers must validate again at dispatch if registry, scope, or inputs change.
    """
    if not callable(validate_task_inputs):
        raise ProposalError("Task-scoped input validation is required")
    # Round-trip to check manually constructed proposals and detach mutable input.
    try:
        validated = Proposal.from_json(json.dumps(proposal.as_dict(), allow_nan=False))
    except (ValueError, TypeError, AttributeError) as error:
        raise ProposalError(f"Invalid proposal: {error}") from error
    for action in validated.actions:
        if action.capability_id not in allowed_capabilities:
            raise ProposalError(f"Capability outside task scope: {action.capability_id}")
        try:
            registry.validate_call(action.capability_id, action.inputs)
            # A separate copy prevents a scope validator from mutating the validated call.
            decision = validate_task_inputs(action.capability_id, deepcopy(action.inputs))
            if decision is not None:
                raise ValueError("Task input validator must return None or raise")
        except (KeyError, ValueError, TypeError) as error:
            raise ProposalError(f"Rejected {action.capability_id}: {error}") from error
    return validated
