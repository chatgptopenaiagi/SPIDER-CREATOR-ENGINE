"""Observed environment facts and explicit resource budgets."""

from .environment import discover_environment
from .limits import ResourceLimits

__all__ = ["ResourceLimits", "discover_environment"]
