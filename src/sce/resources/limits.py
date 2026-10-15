"""Resource configuration; observations are never substituted for enforcement."""

from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class ResourceLimits:
    max_ram_bytes: int | None = None
    max_gpu_bytes: int | None = None
    model_context_tokens: int = 8192
    max_workers: int = 1
    build_parallelism: int = 1
    max_temp_bytes: int = 1024**3
    execution_timeout_seconds: float = 120.0
    max_retries: int = 1

    def __post_init__(self) -> None:
        for name in ("max_ram_bytes", "max_gpu_bytes"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(f"{name} must be a positive integer or null")
        for name in ("model_context_tokens", "max_workers", "build_parallelism", "max_temp_bytes"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.max_retries) is not int or not 0 <= self.max_retries <= 10:
            raise ValueError("max_retries must be an integer between 0 and 10")
        if (isinstance(self.execution_timeout_seconds, bool)
                or not isinstance(self.execution_timeout_seconds, (int, float))
                or not math.isfinite(self.execution_timeout_seconds)
                or self.execution_timeout_seconds <= 0):
            raise ValueError("execution_timeout_seconds must be finite and positive")

    def as_dict(self) -> dict:
        return asdict(self)

    def enforcement_status(self) -> dict[str, str]:
        return {
            "max_ram_bytes": "advisory: no operating-system memory isolation",
            "max_gpu_bytes": "advisory: no GPU allocation isolation or offload configuration",
            "model_context_tokens": "AI request budget; actual tokenization belongs to the provider",
            "max_workers": "orchestrator scheduling limit; no global process isolation",
            "build_parallelism": "adapter-specific; only effective when a builder consumes it",
            "max_temp_bytes": "advisory: no filesystem quota enforcement",
            "execution_timeout_seconds": "adapter-specific timeout; no guarantee for detached child processes",
            "max_retries": "orchestrator retry limit; zero disables automatic recovery",
        }
