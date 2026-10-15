from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from sce.core.models import Evidence, jsonable


@dataclass
class ResourceRecord:
    identity: str
    source_uri: str
    source_revision: str | None
    content_hashes: dict[str, str]
    location: str
    transfer_status: str
    evidence: list[Evidence] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    expected_content_hashes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AcquisitionPlan:
    identity: str
    source: Path
    destination: Path
    content_hashes: dict[str, str]
    source_revision: str | None = None


class AcquisitionProvider(Protocol):
    def prepare(self, source: Path, library: Path, *, source_revision: str | None = None) -> AcquisitionPlan: ...
    def execute(self, plan: AcquisitionPlan) -> ResourceRecord: ...


class LocalAcquirer:
    def __init__(self, *, max_bytes: int = 10_000_000, max_files: int = 1000):
        if max_bytes < 1 or max_files < 1:
            raise ValueError("Acquisition budgets must be positive")
        self.max_bytes = max_bytes
        self.max_files = max_files

    def _inventory(self, source: Path) -> dict[str, str]:
        def regular_files():
            if source.is_symlink() or getattr(source, "is_junction", lambda: False)():
                raise ValueError(f"Linked resource root is unsupported: {source}")
            if source.is_file():
                yield source
                return
            directories_seen = 0
            def inaccessible(error):
                raise error
            for root, directories, filenames in os.walk(source, followlinks=False, onerror=inaccessible):
                directories_seen += 1
                if directories_seen > self.max_files:
                    raise ValueError("Acquisition exceeds configured directory budget")
                for name in directories:
                    path = Path(root) / name
                    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                        raise ValueError(f"Linked resources are unsupported: {path}")
                for name in sorted(filenames):
                    yield Path(root) / name
        files = regular_files()
        hashes = {}
        total = 0
        for path in files:
            if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                raise ValueError(f"Linked resources are unsupported: {path}")
            if not path.is_file():
                continue
            total += path.stat().st_size
            if total > self.max_bytes or len(hashes) >= self.max_files:
                raise ValueError("Acquisition exceeds configured source budget")
            relative = path.name if source.is_file() else path.relative_to(source).as_posix()
            with path.open("rb") as stream:
                hashes[relative] = hashlib.file_digest(stream, "sha256").hexdigest()
        if not hashes:
            raise ValueError("Resource contains no regular files")
        return hashes

    def prepare(self, source: Path, library: Path, *, source_revision: str | None = None) -> AcquisitionPlan:
        if source.is_symlink() or getattr(source, "is_junction", lambda: False)():
            raise ValueError("Linked resource roots are unsupported")
        source = source.resolve(strict=True)
        library = library.resolve()
        if library == source or library.is_relative_to(source):
            raise ValueError("Library must be outside acquired source")
        identity = str(uuid4())
        return AcquisitionPlan(identity, source, library / identity, self._inventory(source), source_revision)

    def execute(self, plan: AcquisitionPlan) -> ResourceRecord:
        if plan.source.resolve(strict=True) != plan.source or plan.destination.resolve() != plan.destination:
            raise ValueError("Prepared source or destination location changed")
        if self._inventory(plan.source) != plan.content_hashes:
            raise ValueError("Source changed after preparation")
        plan.destination.mkdir(parents=True, exist_ok=False)
        record = ResourceRecord(plan.identity, plan.source.as_uri(), plan.source_revision,
                                {}, str(plan.destination / "content"), "partial",
                                expected_content_hashes=dict(plan.content_hashes))
        if plan.source_revision is None:
            record.unknowns.append("Source revision unknown; content hashes identify this observation")
        try:
            content = plan.destination / "content"
            content.mkdir()
            copied_bytes = 0
            for relative in plan.content_hashes:
                origin = plan.source / relative if plan.source.is_dir() else plan.source
                if origin.resolve(strict=True) != origin:
                    raise ValueError("Prepared source file location changed")
                target = content / relative
                if not target.resolve().is_relative_to(content):
                    raise ValueError("Invalid relative resource path")
                target.parent.mkdir(parents=True, exist_ok=True)
                with origin.open("rb") as incoming, target.open("xb") as outgoing:
                    while block := incoming.read(min(1024 * 1024, self.max_bytes - copied_bytes + 1)):
                        copied_bytes += len(block)
                        if copied_bytes > self.max_bytes:
                            raise ValueError("Source grew beyond configured transfer budget")
                        outgoing.write(block)
            record.content_hashes = self._inventory(content)
            if record.content_hashes != plan.content_hashes:
                raise ValueError("Acquired content differs from prepared source")
            record.transfer_status = "completed"
            record.evidence.append(Evidence(plan.source.as_uri(), "Copied content SHA-256 matches prepared inventory"))
        except (OSError, ValueError) as exc:
            record.unknowns.append(f"Partial transfer preserved for inspection: {exc}")
            try:
                record.content_hashes = self._inventory(plan.destination / "content")
            except (OSError, ValueError):
                record.unknowns.append("Actual partial content hashes could not be completely inventoried")
        (plan.destination / "resource.json").write_text(json.dumps(jsonable(record), indent=2), encoding="utf-8")
        return record
