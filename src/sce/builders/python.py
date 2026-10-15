"""A deliberately narrow, evidence-producing Python zipapp builder."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any, Callable
import zipapp

from sce.core.models import Evidence, OperationOutcome, OperationRecord, VerificationStatus, jsonable
from sce.verification import verify_process

BUILD_ORIGINAL_PROJECT = "BUILD_ORIGINAL_PROJECT"
CREATE_NEW_APPLICATION_USING_PROJECT = "CREATE_NEW_APPLICATION_USING_PROJECT"
CAPABILITY_ID = "python.build"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class SourceFile:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class BuildPlan:
    source: str
    output_root: str
    operation: str
    trusted: bool
    task_id: str | None
    artifact_name: str = ""
    entry_point: str = ""
    required_modules: tuple[str, ...] = ()
    verification_args: tuple[str, ...] = ()
    expected_stdout: str = ""
    expected_exit: int = 0
    files: tuple[SourceFile, ...] = ()
    validation_errors: tuple[str, ...] = ()
    unsupported: bool = False

    @property
    def ready(self) -> bool:
        return not self.unsupported and not self.validation_errors


class PythonBuildAdapter:
    def __init__(self, timeout_seconds: float = 30, max_source_bytes: int = 10_000_000):
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        if max_source_bytes <= 0:
            raise ValueError("max_source_bytes must be positive")
        self.timeout_seconds = timeout_seconds
        self.max_source_bytes = max_source_bytes

    def describe(self) -> dict[str, Any]:
        return {
            "capability_id": CAPABILITY_ID,
            "operations": [BUILD_ORIGINAL_PROJECT],
            "unsupported_operations": [CREATE_NEW_APPLICATION_USING_PROJECT],
            "input_contract": "trusted source directory containing sce-build.json format sce.zipapp.v1",
            "output_contract": "one .pyz artifact with SHA-256; no installation",
            "requirements": ["Python 3.11+", "explicit source trust", "separate writable output directory"],
            "verification": "explicitly declared exact stdout and exit code",
            "limitations": [
                "Controlled zipapp fixtures only; no general pyproject/wheel/native-extension builds",
                "required_modules checks module availability, not version compatibility",
                "Verification executes trusted source without an OS sandbox",
                "Timeout controls the direct verification process only",
                "No dependency installation, packaging installer, or installation capability",
            ],
        }

    def _snapshot(self, source: Path) -> tuple[SourceFile, ...]:
        if not source.is_dir():
            raise ValueError("source is not a directory")
        files: list[SourceFile] = []
        total = 0
        for path in sorted(source.rglob("*")):
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise ValueError(f"source contains unsupported link: {path.relative_to(source)}")
            if not path.is_file():
                continue
            size = path.stat().st_size
            total += size
            if total > self.max_source_bytes:
                raise ValueError("source exceeds max_source_bytes")
            files.append(SourceFile(path.relative_to(source).as_posix(), _hash(path), size))
        return tuple(files)

    def prepare(
        self, source: Path | str, output_root: Path | str, *, trusted: bool = False,
        operation: str = BUILD_ORIGINAL_PROJECT, task_id: str | None = None,
    ) -> BuildPlan:
        """Read and validate only. Never create directories or execute project code."""
        source_path, output_path = Path(source).resolve(), Path(output_root).resolve()
        base = dict(source=str(source_path), output_root=str(output_path), operation=operation, trusted=trusted, task_id=task_id)
        if operation != BUILD_ORIGINAL_PROJECT:
            return BuildPlan(**base, unsupported=True, validation_errors=(f"unsupported operation: {operation}",))
        if not (source_path / "sce-build.json").is_file():
            return BuildPlan(**base, unsupported=True, validation_errors=("missing controlled sce-build.json manifest",))
        errors: list[str] = []
        if not trusted:
            errors.append("explicit trust authorization is required before building or running this source")
        if output_path == source_path or source_path in output_path.parents:
            errors.append("output root must be outside the source directory")
        try:
            files = self._snapshot(source_path)
            spec = json.loads((source_path / "sce-build.json").read_text(encoding="utf-8"))
            if not isinstance(spec, dict) or spec.get("format") != "sce.zipapp.v1":
                return BuildPlan(**base, unsupported=True, validation_errors=("unsupported manifest format",))
            allowed = {"format", "name", "entry_point", "required_modules", "verification"}
            if set(spec) - allowed:
                raise ValueError("manifest has unknown fields")
            name = spec.get("name", "")
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
                raise ValueError("name must be a safe filename of 1-64 characters")
            entry = spec.get("entry_point", "")
            if not isinstance(entry, str) or not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", entry):
                raise ValueError("entry_point must have module:function form")
            if (source_path / "__main__.py").exists():
                raise ValueError("source __main__.py is not supported with a declared entry_point")
            if (output_path / f"{name}.pyz").exists():
                errors.append("artifact already exists; use a fresh output directory")
            modules = spec.get("required_modules", [])
            if not isinstance(modules, list) or any(not isinstance(m, str) or not re.fullmatch(r"[A-Za-z_]\w*", m) for m in modules):
                raise ValueError("required_modules must be a list of top-level Python module names")
            for module in modules:
                if importlib.util.find_spec(module) is None:
                    errors.append(f"missing dependency module: {module}")
            verification = spec.get("verification")
            if not isinstance(verification, dict) or set(verification) != {"args", "expected_stdout", "expected_exit"}:
                raise ValueError("verification must declare args, expected_stdout, and expected_exit")
            args, stdout, code = verification["args"], verification["expected_stdout"], verification["expected_exit"]
            if not isinstance(args, list) or any(not isinstance(arg, str) or "\0" in arg for arg in args):
                raise ValueError("verification args must be strings without NUL")
            if not isinstance(stdout, str) or type(code) is not int or not 0 <= code <= 255:
                raise ValueError("verification requires string expected_stdout and integer expected_exit in 0..255")
            return BuildPlan(
                **base, artifact_name=f"{name}.pyz", entry_point=entry, required_modules=tuple(modules),
                verification_args=tuple(args), expected_stdout=stdout, expected_exit=code,
                files=files, validation_errors=tuple(errors),
            )
        except (OSError, ValueError, TypeError) as exc:
            return BuildPlan(**base, validation_errors=tuple(errors + [str(exc)]))

    def execute(self, plan: BuildPlan, *, cancelled: Callable[[], bool] | None = None) -> OperationRecord:
        record = OperationRecord(
            task_id=plan.task_id, capability_id=CAPABILITY_ID,
            requested={"operation": plan.operation, "source": plan.source, "trusted": plan.trusted},
            planned=asdict(plan), started_at=_now(),
        )
        if plan.unsupported:
            record.outcome = OperationOutcome("unsupported")
        elif not plan.ready:
            record.outcome = OperationOutcome("failed")
        elif cancelled and cancelled():
            record.outcome = OperationOutcome("cancelled")
            record.unknowns.append("build cancelled before packaging")
        else:
            source, output = Path(plan.source), Path(plan.output_root)
            artifact = output / plan.artifact_name
            created_artifact = False
            try:
                if not plan.trusted:
                    raise ValueError("plan has no trust authorization")
                if output.resolve() != output or source.resolve() != source:
                    raise ValueError("prepared filesystem location changed")
                if self._snapshot(source) != plan.files:
                    raise ValueError("source changed since PREPARE; prepare again")
                if artifact.exists():
                    raise ValueError("artifact already exists; refusing overwrite")
                output.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix="sce-build-", dir=output) as temporary:
                    stage = Path(temporary) / "source"
                    stage.mkdir()
                    for item in plan.files:
                        if cancelled and cancelled():
                            record.outcome = OperationOutcome("cancelled")
                            record.unknowns.append("build cancelled while staging")
                            record.finished_at = _now()
                            return record
                        destination = stage / item.path
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source / item.path, destination)
                    if self._snapshot(stage) != plan.files:
                        raise ValueError("source changed during staging; prepare again")
                    staged_artifact = Path(temporary) / plan.artifact_name
                    zipapp.create_archive(stage, target=staged_artifact, main=plan.entry_point, compressed=True)
                    with artifact.open("xb") as target:
                        created_artifact = True
                        with staged_artifact.open("rb") as content:
                            shutil.copyfileobj(content, target)
                record.executed.append({"stage": "execute", "operation": "zipapp.create_archive", "entry_point": plan.entry_point})
                record.produced.append({"kind": "python_zipapp", "path": str(artifact), "sha256": _hash(artifact), "size": artifact.stat().st_size})
                record.evidence.append(Evidence(source=str(artifact), detail="package created and SHA-256 recorded; functionality remains unverified", kind="artifact"))
                record.outcome = OperationOutcome("succeeded")
            except (OSError, ValueError, zipapp.ZipAppError) as exc:
                record.outcome = OperationOutcome("partial" if created_artifact else "failed")
                if created_artifact and artifact.is_file():
                    record.produced.append({"kind": "partial_artifact", "path": str(artifact), "sha256": _hash(artifact)})
                record.evidence.append(Evidence(source="python.zipapp.execute", detail=str(exc), kind="error"))
        for error in plan.validation_errors:
            record.evidence.append(Evidence(source="python.zipapp.prepare", detail=error, kind="validation"))
        record.finished_at = _now()
        return record

    def verify(self, plan: BuildPlan, record: OperationRecord, *, cancelled: Callable[[], bool] | None = None) -> OperationRecord:
        if (record.capability_id != CAPABILITY_ID or record.task_id != plan.task_id
                or jsonable(record.planned) != jsonable(asdict(plan))):
            record.verification = VerificationStatus("failed")
            record.evidence.append(Evidence(
                source="python.zipapp.verify", kind="error",
                detail="Verification plan or operation identity does not match the recorded execution plan",
            ))
            record.finished_at = _now()
            return record
        if record.outcome != OperationOutcome("succeeded"):
            record.unknowns.append("functional verification was not run because packaging did not succeed")
            return record
        if not plan.trusted:
            raise ValueError("verification requires explicit source trust")
        artifact = Path(plan.output_root) / plan.artifact_name
        expected_artifacts = [item for item in record.produced if item.get("kind") == "python_zipapp" and item.get("path") == str(artifact)]
        try:
            artifact_matches = (artifact.is_file() and len(expected_artifacts) == 1
                                and _hash(artifact) == expected_artifacts[0].get("sha256"))
        except OSError as exc:
            record.outcome = OperationOutcome("partial")
            record.verification = VerificationStatus("inconclusive")
            record.evidence.append(Evidence(source=str(artifact), kind="error",
                                            detail=f"Could not read artifact identity before verification: {exc}"))
            record.unknowns.append("Artifact identity could not be established; functional verification was not run")
            record.finished_at = _now()
            return record
        if not artifact_matches:
            record.verification = VerificationStatus("failed")
            record.evidence.append(Evidence(source=str(artifact), detail="artifact missing or changed before verification", kind="verification"))
            record.finished_at = _now()
            return record
        result = verify_process(
            [sys.executable, "-I", str(artifact), *plan.verification_args], cwd=Path(plan.output_root),
            expected_stdout=plan.expected_stdout, expected_exit=plan.expected_exit,
            timeout_seconds=self.timeout_seconds, cancelled=cancelled,
        )
        record.executed.append({"stage": "verify", **asdict(result)})
        record.verification = VerificationStatus(result.status)
        record.evidence.append(Evidence(source="python.zipapp.verify", detail=result.detail, kind="verification"))
        if result.status == "inconclusive":
            record.outcome = OperationOutcome("partial")
            record.unknowns.append("artifact exists, but declared functional verification did not complete")
        record.unknowns.extend([
            "Installation was not requested, performed, or verified",
            "Declared fixture check does not establish general application correctness",
        ])
        record.finished_at = _now()
        return record

    def report(self, record: OperationRecord) -> OperationRecord:
        """Return the canonical evidence record; renderers decide its presentation."""
        return record
