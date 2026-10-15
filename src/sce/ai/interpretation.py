"""Model interpretations of observed evidence are attributable inference, not actions."""

from dataclasses import dataclass
import json


class InterpretationError(ValueError):
    """The response does not meet the bounded interpretation contract."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise InterpretationError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise InterpretationError(f"Non-finite JSON constant: {value}")


@dataclass(frozen=True)
class Interpretation:
    summary: str
    unknowns: tuple[str, ...]
    suggested_next_checks: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.summary, str) or not self.summary.strip() or len(self.summary) > 8192:
            raise InterpretationError("summary must contain 1..8192 characters")
        for name in ("unknowns", "suggested_next_checks"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or len(values) > 16 or any(
                not isinstance(value, str) or not value.strip() or len(value) > 2048 for value in values
            ):
                raise InterpretationError(f"{name} must contain at most 16 nonempty strings of at most 2048 characters")

    @property
    def provenance(self) -> str:
        return "AI_INFERENCE"

    @property
    def execution_authority(self) -> bool:
        return False

    @classmethod
    def from_json(cls, raw: str, *, max_chars: int = 32768) -> "Interpretation":
        if type(max_chars) is not int or max_chars <= 0:
            raise ValueError("Interpretation character limit must be a positive integer")
        if not isinstance(raw, str) or len(raw) > max_chars:
            raise InterpretationError("Interpretation exceeds the configured character budget")
        try:
            data = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
        except (json.JSONDecodeError, RecursionError) as error:
            raise InterpretationError("Model interpretation must be a single strict JSON object") from error
        if not isinstance(data, dict) or set(data) != {"summary", "unknowns", "suggested_next_checks"}:
            raise InterpretationError("Interpretation must contain exactly summary, unknowns, and suggested_next_checks")
        for name in ("unknowns", "suggested_next_checks"):
            if not isinstance(data[name], list):
                raise InterpretationError(f"{name} must be an array")
        return cls(data["summary"], tuple(data["unknowns"]), tuple(data["suggested_next_checks"]))

    def as_dict(self) -> dict:
        return {"summary": self.summary, "unknowns": list(self.unknowns),
                "suggested_next_checks": list(self.suggested_next_checks)}
