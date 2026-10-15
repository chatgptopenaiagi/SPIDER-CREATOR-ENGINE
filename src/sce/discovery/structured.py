"""Portable discovery observations; static inspection never establishes functionality."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import tomllib
from typing import Any

from sce.core.models import Evidence, utc_now


@dataclass(frozen=True)
class DiscoveryLimits:
    max_files: int = 500
    max_file_bytes: int = 65_536
    max_source_bytes: int = 10_000_000
    max_response_bytes: int = 2_000_000
    max_requests: int = 40
    max_pages: int = 2
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        for name in ("max_files", "max_file_bytes", "max_source_bytes", "max_response_bytes", "max_requests", "max_pages"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not 0 < self.timeout_seconds <= 120:
            raise ValueError("timeout_seconds must be > 0 and <= 120")


@dataclass(frozen=True)
class SoftwareObservation:
    subject: str
    value: Any
    provenance: str
    source: str
    content_sha256: str | None = None


@dataclass
class SoftwareProject:
    resource_id: str
    source_uri: str
    name: str
    revision: str | None
    kind: str
    metadata: dict[str, Any] = field(default_factory=dict)
    observations: list[SoftwareObservation] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    discovered_at: str = field(default_factory=utc_now)


@dataclass
class DiscoveryResult:
    starting_point: dict[str, str]
    online: bool
    projects: list[SoftwareProject] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


LANGUAGES = {".py": "Python", ".cs": "C#", ".rs": "Rust", ".js": "JavaScript", ".ts": "TypeScript", ".cpp": "C++", ".c": "C", ".ps1": "PowerShell"}
MANIFESTS = {"pyproject.toml", "package.json", "requirements.txt", "cargo.toml"}
EXCLUDED_DIRECTORIES = {".git", ".venv", "venv", "node_modules", "__pycache__", ".sce", ".pytest_cache"}


def is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def selected_document(path: str) -> bool:
    """Only root project manifests and root README are admitted to text context."""
    return "/" not in path and (path.casefold() in MANIFESTS or path.casefold().startswith("readme"))


def observe_document(project: SoftwareProject, name: str, raw: bytes, source: str) -> None:
    digest = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8", errors="replace")
    project.observations.append(SoftwareObservation(name, text, "AUTHOR_DOCUMENTATION", source, digest))
    project.evidence.append(Evidence(source, f"Inspected {len(raw)} bytes; SHA-256 {digest}; declarations remain unverified", kind="static_document"))
    dependencies: list[str] = []
    systems: list[str] = []
    try:
        if name.casefold() == "pyproject.toml":
            data = tomllib.loads(text)
            package, build = data.get("project", {}), data.get("build-system", {})
            if not isinstance(package, dict) or not isinstance(build, dict):
                raise ValueError("project and build-system must be tables")
            dependencies = package.get("dependencies", [])
            if not isinstance(dependencies, list) or any(not isinstance(item, str) for item in dependencies):
                raise ValueError("project.dependencies must be strings")
            backend = build.get("build-backend")
            if backend is not None:
                if not isinstance(backend, str):
                    raise ValueError("build-backend must be a string")
                systems = [backend]
            scripts = package.get("scripts", {})
            if scripts and isinstance(scripts, dict):
                project.metadata["declared_scripts"] = scripts
        elif name.casefold() == "package.json":
            data = json.loads(text)
            if not isinstance(data, dict) or not isinstance(data.get("dependencies", {}), dict):
                raise ValueError("package metadata must be an object")
            dependencies = [f"{key}@{value}" for key, value in data.get("dependencies", {}).items()]
            systems = ["Node.js package scripts (unverified)"]
        elif name.casefold() == "cargo.toml":
            data = tomllib.loads(text)
            if not isinstance(data.get("dependencies", {}), dict):
                raise ValueError("dependencies must be a table")
            dependencies = [f"{key}: {value}" for key, value in data.get("dependencies", {}).items()]
            systems = ["Cargo (unverified)"]
        elif name.casefold() == "requirements.txt":
            dependencies = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        else:
            return
        project.metadata.setdefault("dependencies", []).extend(dependencies)
        project.metadata.setdefault("build_systems", []).extend(systems)
        project.observations.append(SoftwareObservation("declared_dependencies", dependencies, "AUTHOR_DOCUMENTATION", source, digest))
    except (ValueError, TypeError) as exc:
        project.limitations.append(f"Could not parse {name}: {exc}")


def record_structure(project: SoftwareProject, paths: list[str], source: str) -> None:
    languages = sorted({LANGUAGES[Path(path).suffix.lower()] for path in paths if Path(path).suffix.lower() in LANGUAGES})
    project.metadata.update(structure=paths, languages=languages)
    project.observations.append(SoftwareObservation("file_structure", paths, "OBSERVED_BEHAVIOR", source))
    project.observations.append(SoftwareObservation("languages_inferred_from_suffixes", languages, "OBSERVED_BEHAVIOR", source))
    project.limitations.append("Static filename and declaration observations do not prove buildability, interface compatibility, licensing permission, or application functionality")


def inspect_local(path: Path | str, *, limits: DiscoveryLimits | None = None) -> SoftwareProject:
    """Inspect an explicit local source without importing code or following links.

    The content-derived resource identity describes the bounded observed file set,
    not excluded or unread files. Moving identical observed content preserves it.
    """
    limits = limits or DiscoveryLimits()
    original = Path(path)
    if is_link(original):
        raise ValueError("Linked local discovery roots are unsupported")
    root = original.resolve(strict=True)
    project = SoftwareProject("pending", root.as_uri(), root.name, None, "local_directory" if root.is_dir() else "local_file")
    project.limitations.append("Local identity covers the bounded observed file set; it is not a Git revision or a full repository fingerprint")
    hashes: dict[str, str] = {}
    paths: list[str] = []
    total = 0

    def files():
        if root.is_file():
            yield root
            return
        directories_seen = 0
        def inaccessible(error: OSError):
            project.limitations.append(f"Directory inaccessible: {error.filename}")
        for directory, dirs, names in os.walk(root, followlinks=False, onerror=inaccessible):
            directories_seen += 1
            if directories_seen > limits.max_files:
                project.limitations.append("Directory budget reached; inventory incomplete")
                return
            kept = []
            for name in sorted(dirs):
                candidate = Path(directory) / name
                if name.casefold() in EXCLUDED_DIRECTORIES or is_link(candidate):
                    project.limitations.append(f"Excluded directory: {candidate.relative_to(root).as_posix()}")
                else:
                    kept.append(name)
            dirs[:] = kept
            for name in sorted(names):
                yield Path(directory) / name

    for candidate in files():
        if len(paths) >= limits.max_files:
            project.limitations.append("File budget reached; inventory incomplete")
            break
        relative = candidate.relative_to(root).as_posix() if root.is_dir() else candidate.name
        if is_link(candidate) or candidate.resolve() != candidate:
            project.limitations.append(f"Linked file skipped: {relative}")
            continue
        if not candidate.is_file():
            continue
        paths.append(relative)
        try:
            if candidate.stat().st_size > limits.max_source_bytes - total:
                project.limitations.append(f"Source byte budget prevents hashing: {relative}; content identity is partial")
                continue
            with candidate.open("rb") as stream:
                raw = stream.read(limits.max_source_bytes - total + 1)
            if len(raw) > limits.max_source_bytes - total:
                project.limitations.append(f"Source grew beyond byte budget: {relative}; content identity is partial")
                continue
            total += len(raw)
            hashes[relative] = hashlib.sha256(raw).hexdigest()
            if selected_document(relative):
                if len(raw) <= limits.max_file_bytes:
                    observe_document(project, relative, raw, candidate.as_uri())
                else:
                    project.limitations.append(f"Document exceeds text budget: {relative}")
        except OSError as exc:
            project.limitations.append(f"Cannot read {relative}: {type(exc).__name__}")
    fingerprint = hashlib.sha256(json.dumps({"files": paths, "content_hashes": hashes}, sort_keys=True).encode()).hexdigest()
    project.resource_id = f"local-observation:sha256:{fingerprint}"
    project.revision = f"observed-sha256:{fingerprint}"
    project.metadata["content_hashes"] = hashes
    project.metadata["bytes_hashed"] = total
    if root.is_file() and root.suffix.casefold() in {".zip", ".tar", ".gz", ".7z"}:
        project.limitations.append("Archive content is not extracted or inspected; archive extraction connector is proposed")
    record_structure(project, paths, root.as_uri())
    project.evidence.append(Evidence(root.as_uri(), f"Read-only local inspection; {len(paths)} paths observed, {len(hashes)} content hashes, {total} bytes hashed", kind="static_inspection"))
    return project
