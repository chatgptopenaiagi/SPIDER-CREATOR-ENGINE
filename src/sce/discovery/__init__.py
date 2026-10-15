"""Local-first software discovery; legacy LocalDiscovery remains compatible."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .spider import SpiderDiscovery, StartingPoint
from .structured import DiscoveryLimits, DiscoveryResult, SoftwareObservation, SoftwareProject, inspect_local


@dataclass(frozen=True)
class DiscoveredResource:
    source_uri: str
    name: str
    kind: str
    observations: tuple[str, ...]


class DiscoveryProvider(Protocol):
    def discover(self, query: str, *, limit: int = 20) -> list[DiscoveredResource]: ...


class LocalDiscovery:
    """Explicit paths only; no recursive disk crawler or network requests."""

    def __init__(self, roots: list[Path]):
        self.roots = roots

    def discover(self, query: str = "", *, limit: int = 20) -> list[DiscoveredResource]:
        if not 1 <= limit <= 100:
            raise ValueError("Discovery limit must be 1..100")
        results = []
        for root in self.roots:
            path = root.resolve(strict=True)
            if query.casefold() not in path.name.casefold():
                continue
            results.append(DiscoveredResource(path.as_uri(), path.name,
                                             "directory" if path.is_dir() else "file",
                                             ("Local path exists; contents not executed",)))
            if len(results) == limit:
                break
        return results
