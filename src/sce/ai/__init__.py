"""Bounded local model proposals and mandatory host-side validation."""

from .proposals import CapabilityAction, ExactInputScope, Proposal, ProposalError, validate_proposal
from .interpretation import Interpretation, InterpretationError
from .provider import AIInterpreter, AIProvider, LocalAIConfig, LoopbackAIProvider, ModelAvailability, ProviderError, TaskContext

__all__ = ["AIInterpreter", "AIProvider", "Interpretation", "InterpretationError", "CapabilityAction", "ExactInputScope", "LocalAIConfig", "LoopbackAIProvider", "ModelAvailability",
           "Proposal", "ProposalError", "ProviderError", "TaskContext", "validate_proposal"]
