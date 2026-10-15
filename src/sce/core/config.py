"""Strict explicit storage configuration; relative paths use the config directory."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import tempfile
import tomllib

from sce.resources import ResourceLimits


STORAGE_NAMES = (
    "TASK_DATABASE", "RESOURCE_LIBRARY", "DOWNLOAD_CACHE", "BUILD_WORKSPACES",
    "DEPENDENCY_ENVIRONMENTS", "ARTIFACT_STORAGE", "MODEL_STORAGE", "MODEL_CACHE",
    "INDEX_STORAGE", "TEMP_STORAGE", "LOG_STORAGE", "REPORT_STORAGE", "INSTALLATION_DESTINATIONS",
)


@dataclass(frozen=True)
class AIConfig:
    endpoint: str = "http://127.0.0.1:8080"
    model: str = "qwen3-coder-local"
    max_context_chars: int = 12000
    max_response_tokens: int = 512
    timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        if not self.model or self.max_context_chars < 1 or self.max_response_tokens < 1:
            raise ValueError("AI model and positive context/output budgets are required")
        import math
        if isinstance(self.timeout_seconds, bool) or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("AI timeout must be finite and positive")


@dataclass(frozen=True)
class Config:
    storage: dict[str, Path]
    resources: ResourceLimits = field(default_factory=ResourceLimits)
    ai: AIConfig = field(default_factory=AIConfig)

    def __post_init__(self) -> None:
        if set(self.storage) != set(STORAGE_NAMES):
            raise ValueError("All named storage paths must be configured; unknown paths are rejected")
        for name, path in self.storage.items():
            if not path.is_absolute():
                raise ValueError(f"{name} must resolve to an absolute path")
        if self.ai.max_response_tokens >= self.resources.model_context_tokens:
            raise ValueError("AI response budget must leave space for input context")

    @classmethod
    def default(cls, root: Path) -> Config:
        root = root.resolve() / ".sce"
        paths = {name: root / name.lower() for name in STORAGE_NAMES}
        paths["TASK_DATABASE"] = root / "tasks.sqlite3"
        return cls(paths)

    @classmethod
    def load(cls, filename: Path) -> Config:
        filename = filename.resolve(strict=True)
        with filename.open("rb") as stream:
            raw = tomllib.load(stream)
        if set(raw) - {"storage", "resources", "ai"}:
            raise ValueError("Unknown configuration section")
        defaults = cls.default(filename.parent)
        given = raw.get("storage", {})
        if set(given) - set(STORAGE_NAMES):
            raise ValueError("Unknown storage name")
        paths = dict(defaults.storage)
        for name, value in given.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty path")
            path = Path(value).expanduser()
            paths[name] = (path if path.is_absolute() else filename.parent / path).resolve()
        return cls(paths, ResourceLimits(**raw.get("resources", {})), AIConfig(**raw.get("ai", {})))

    def initialize_storage(self) -> None:
        """Explicit write operation. Fail at the selected path without fallback."""
        for name, path in self.storage.items():
            directory = path.parent if name == "TASK_DATABASE" else path
            if name == "TASK_DATABASE" and path.exists() and not path.is_file():
                raise ValueError(f"TASK_DATABASE is not a file: {path}")
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix=".sce-write-check-", dir=directory):
                pass
            if not os.access(directory, os.W_OK):
                raise PermissionError(f"Storage destination is not writable: {directory}")
