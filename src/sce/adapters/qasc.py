"""Thin CLI bridge to an independently installed QASC; generation is not execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import time
from typing import Callable
from urllib.parse import urlsplit

from sce.core.models import Evidence, OperationOutcome, OperationRecord, VerificationStatus, identifier, jsonable, utc_now


CAPABILITY_ID = "qasc.create_python"


@dataclass(frozen=True)
class QASCCall:
    argv: tuple[str, ...]
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    interrupted: bool = False
    detail: str = ""
    elapsed_seconds: float = 0.0


def run_qasc(argv: list[str], *, cwd: Path, env: dict[str, str], timeout_seconds: float, max_output_bytes: int) -> QASCCall:
    """Bound captured output and direct-process duration; this is not a sandbox."""
    started = time.monotonic()
    try:
        with tempfile.TemporaryFile(dir=env["TEMP"]) as output, tempfile.TemporaryFile(dir=env["TEMP"]) as errors:
            process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=errors, shell=False)
            detail = ""
            try:
                while process.poll() is None:
                    if time.monotonic() - started >= timeout_seconds:
                        detail = "QASC direct-process timeout reached"
                    elif os.fstat(output.fileno()).st_size + os.fstat(errors.fileno()).st_size > max_output_bytes:
                        detail = "QASC output budget exceeded"
                    if detail:
                        process.kill()
                        process.wait(timeout=5)
                        break
                    time.sleep(0.02)
                if os.fstat(output.fileno()).st_size + os.fstat(errors.fileno()).st_size > max_output_bytes:
                    detail = detail or "QASC output budget exceeded"
                output.seek(0)
                errors.seek(0)
                stdout = output.read(max_output_bytes).decode("utf-8", errors="replace")
                stderr = errors.read(max_output_bytes).decode("utf-8", errors="replace")
                return QASCCall(tuple(argv), process.returncode, stdout, stderr, bool(detail), detail, time.monotonic() - started)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return QASCCall(tuple(argv), interrupted=True, detail=f"QASC invocation failed: {type(exc).__name__}: {exc}", elapsed_seconds=time.monotonic() - started)


def _hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _acceptance(value: dict) -> str:
    if not isinstance(value, dict) or set(value) - {"cases", "provenance"}:
        raise ValueError("acceptance must contain independently supplied cases")
    cases = value.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 40:
        raise ValueError("acceptance needs 1..40 cases")
    normalized = []
    for index, item in enumerate(cases):
        if not isinstance(item, dict) or set(item) - {"name", "args", "stdin", "stdout", "stderr", "exit_code"}:
            raise ValueError("invalid acceptance case fields")
        case = dict(item)
        case.setdefault("name", f"case-{index + 1}")
        case.setdefault("args", [])
        case.setdefault("exit_code", 0)
        if not isinstance(case.get("stdout"), str) or type(case["exit_code"]) is not int:
            raise ValueError("acceptance requires exact stdout and integer exit_code")
        if not isinstance(case["args"], list) or any(not isinstance(arg, str) or "\0" in arg for arg in case["args"]):
            raise ValueError("acceptance args must be strings without NUL")
        if any(key in case and (not isinstance(case[key], str) or "\0" in case[key]) for key in ("name", "stdin", "stdout", "stderr")):
            raise ValueError("acceptance text must be strings without NUL")
        normalized.append(case)
    if len({case["name"] for case in normalized}) != len(normalized):
        raise ValueError("acceptance case names must be unique")
    result = json.dumps({"cases": normalized, "provenance": "operator_supplied_verification"}, sort_keys=True, ensure_ascii=False)
    if len(result.encode("utf-8")) > 32_000:
        raise ValueError("acceptance exceeds 32 KB")
    return result


@dataclass(frozen=True)
class QASCPlan:
    id: str
    objective: str
    name: str
    workspace: str
    project: str
    interpreter: str
    interpreter_sha256: str
    endpoint: str
    model: str | None
    acceptance_json: str
    task_id: str | None = None


class PythonQASCAdapter:
    def __init__(self, python_executable: Path | str, build_workspaces: Path | str, *, endpoint: str = "http://127.0.0.1:8080", model: str | None = None, model_timeout_seconds: float = 180, timeout_seconds: float = 240, max_tokens: int = 3000, max_output_bytes: int = 1_000_000, runner: Callable = run_qasc):
        for value in (model_timeout_seconds, timeout_seconds):
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 < value <= 3600:
                raise ValueError("QASC timeouts must be finite and in (0, 3600]")
        if type(max_tokens) is not int or not 1 <= max_tokens <= 16384 or type(max_output_bytes) is not int or max_output_bytes < 1:
            raise ValueError("Invalid QASC output/token budget")
        endpoint_parts = urlsplit(endpoint)
        if endpoint_parts.scheme not in {"http", "https"} or not endpoint_parts.hostname or endpoint_parts.username or endpoint_parts.password or endpoint_parts.query or endpoint_parts.fragment:
            raise ValueError("QASC endpoint must be an HTTP(S) URL without credentials, query or fragment")
        if model is not None and (not isinstance(model, str) or not model or "\0" in model):
            raise ValueError("model must be a nonempty string without NUL")
        self.python = Path(python_executable).resolve()
        self.workspaces = Path(build_workspaces).resolve()
        self.endpoint, self.model = endpoint, model
        self.model_timeout_seconds, self.timeout_seconds = model_timeout_seconds, timeout_seconds
        self.max_tokens, self.max_output_bytes, self.runner = max_tokens, max_output_bytes, runner

    def describe(self) -> dict:
        return {"capability_id": CAPABILITY_ID, "operations": ["CREATE_NEW_APPLICATION"], "implementation": "installed QASC Python CLI adapter", "input_contract": "objective, fresh project name, configured SCE build workspace, fixed external acceptance cases", "output_contract": "generated source and QASC state; canonical SCE evidence record", "requirements": ["explicit QASC Python interpreter with installed qasc", "reachable configured model for generation", "explicit generated-source trust for verification"], "verification": "separate qasc test; nonzero unit tests, unchanged source fingerprint, retained external acceptance and matching case results", "limitations": ["QASC generation creates files but does not imply functional verification", "No automatic repair, packaging, installation, dependency installation or QASC environment modification", "Executes trusted generated source with current user permissions; no OS sandbox", "SCE timeout controls the direct QASC process, not arbitrary descendants", "QASC API compatibility qualified for inspected 0.1.0 CLI only"]}

    def prepare(self, objective: str, name: str, *, workspace: Path | str | None = None, acceptance: dict, task_id: str | None = None) -> QASCPlan:
        if not isinstance(objective, str) or not objective.strip() or "\0" in objective or len(objective) > 12_000:
            raise ValueError("objective must be 1..12000 characters without NUL")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name):
            raise ValueError("name must match [a-z][a-z0-9-]{0,63}")
        destination = Path(workspace).resolve() if workspace is not None else self.workspaces / "qasc"
        if not destination.is_relative_to(self.workspaces):
            raise ValueError("QASC workspace must be inside configured BUILD_WORKSPACES")
        if not self.python.is_file():
            raise ValueError("Configured QASC interpreter is unavailable")
        project = destination / name
        if project.exists():
            raise ValueError("QASC project already exists; choose a fresh name")
        return QASCPlan(identifier(), objective, name, str(destination), str(project), str(self.python), _hash(self.python), self.endpoint, self.model, _acceptance(acceptance), task_id)

    def _check_plan(self, plan: QASCPlan) -> None:
        if plan.interpreter != str(self.python) or plan.endpoint != self.endpoint or plan.model != self.model:
            raise ValueError("QASC plan does not match configured adapter")
        if Path(plan.workspace).resolve() != Path(plan.workspace) or not Path(plan.workspace).is_relative_to(self.workspaces) or Path(plan.project) != Path(plan.workspace) / plan.name:
            raise ValueError("Prepared QASC workspace location changed or escaped configured storage")
        if self.workspaces.resolve() != self.workspaces or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", plan.name):
            raise ValueError("Prepared QASC storage or project name changed")
        if Path(plan.project).resolve() != Path(plan.project):
            raise ValueError("Prepared QASC project location changed")
        if _hash(self.python) != plan.interpreter_sha256:
            raise ValueError("QASC interpreter changed since PREPARE")
        if _acceptance(json.loads(plan.acceptance_json)) != plan.acceptance_json:
            raise ValueError("Invalid prepared acceptance specification")

    def _control(self, plan: QASCPlan) -> Path:
        if not re.fullmatch(r"[a-f0-9-]{36}", plan.id):
            raise ValueError("Invalid QASC plan identifier")
        control = Path(plan.workspace) / ".sce-qasc" / plan.id
        if control.resolve() != control:
            raise ValueError("QASC control directory location changed")
        return control

    def _invoke(self, plan: QASCPlan, command: list[str]) -> QASCCall:
        control = self._control(plan)
        temporary = control / "tmp"
        if temporary.resolve() != temporary:
            raise ValueError("QASC temporary directory location changed")
        temporary.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8", TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary))
        argv = [plan.interpreter, "-I", "-B", "-m", "qasc", "--projects-dir", plan.workspace, "--endpoint", plan.endpoint, "--model-timeout", str(self.model_timeout_seconds), "--max-tokens", str(self.max_tokens)]
        if plan.model:
            argv.extend(["--model", plan.model])
        return self.runner([*argv, *command], cwd=Path(plan.workspace), env=env, timeout_seconds=self.timeout_seconds, max_output_bytes=self.max_output_bytes)

    def _state(self, plan: QASCPlan) -> dict:
        path = Path(plan.project) / ".qasc" / "state.json"
        if path.resolve() != path or path.stat().st_size > 2_000_000:
            raise ValueError("QASC state path or size is outside contract")
        with path.open("rb") as source:
            raw = source.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("QASC state grew beyond size contract")
        state = json.loads(raw)
        if not isinstance(state, dict) or state.get("name") != plan.name or state.get("acceptance") != json.loads(plan.acceptance_json):
            raise ValueError("QASC project identity or external acceptance changed")
        return state

    def _snapshot(self, plan: QASCPlan, state: dict) -> tuple[dict[str, str], str]:
        names = state.get("files")
        if not isinstance(names, list) or not 1 <= len(names) <= 40 or any(not isinstance(name, str) for name in names) or len(set(names)) != len(names):
            raise ValueError("QASC did not produce a valid managed file inventory")
        hashes, total = {}, 0
        for name in sorted(names):
            relative = PurePosixPath(name)
            if relative.is_absolute() or any(part in {".", ".."} or part.startswith(".") for part in relative.parts) or "\\" in name or ":" in name or not relative.parts:
                raise ValueError("Unsafe QASC managed source path")
            path = Path(plan.project).joinpath(*relative.parts)
            if path.resolve() != path or not path.is_file():
                raise ValueError("QASC source location changed or source is missing")
            if path.stat().st_size > 1_000_000 - total:
                raise ValueError("Generated source exceeds SCE inspection budget")
            with path.open("rb") as source:
                raw = source.read(1_000_000 - total + 1)
            total += len(raw)
            if total > 1_000_000:
                raise ValueError("Generated source grew beyond SCE inspection budget")
            hashes[name] = hashlib.sha256(raw).hexdigest()
        data = [{"path": name, "sha256": digest} for name, digest in hashes.items()]
        fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        return hashes, fingerprint

    @staticmethod
    def _summary(call: QASCCall) -> dict:
        if call.interrupted:
            raise ValueError(call.detail or "QASC execution incomplete")
        payload = json.loads(call.stdout)
        if not isinstance(payload, dict):
            raise ValueError("QASC output was not a structured status object")
        return payload

    def execute(self, plan: QASCPlan) -> OperationRecord:
        record = OperationRecord(capability_id=CAPABILITY_ID, task_id=plan.task_id, requested={"objective": plan.objective, "operation": "CREATE_NEW_APPLICATION"}, planned=asdict(plan), started_at=utc_now())
        invoked = False
        try:
            self._check_plan(plan)
            if Path(plan.project).exists():
                raise ValueError("QASC project already exists; refusing overwrite")
            control = self._control(plan)
            control.mkdir(parents=True, exist_ok=False)
            request_file, acceptance_file = control / "request.txt", control / "acceptance.json"
            request_file.write_text(plan.objective, encoding="utf-8")
            acceptance_file.write_text(plan.acceptance_json, encoding="utf-8")
            invoked = True
            call = self._invoke(plan, ["create", "--name", plan.name, "--request-file", str(request_file), "--acceptance", str(acceptance_file), "--max-corrections", "0"])
            record.executed.append({"stage": "generate", **asdict(call)})
            summary = self._summary(call)
            if call.exit_code != 0 or summary.get("status") != "generated" or summary.get("name") != plan.name:
                raise ValueError("QASC generation did not return generated project status")
            state = self._state(plan)
            hashes, fingerprint = self._snapshot(plan, state)
            record.produced.append({"kind": "generated_python_project", "path": plan.project, "files": hashes, "source_fingerprint": fingerprint, "revision": state.get("revision"), "entrypoint": state.get("entrypoint")})
            record.evidence.append(Evidence(str(Path(plan.project) / ".qasc" / "state.json"), "QASC generated source exists; acceptance retained and file hashes observed; no source execution requested", kind="artifact"))
            record.outcome = OperationOutcome.SUCCEEDED
        except (OSError, ValueError, TypeError) as exc:
            partial = invoked and Path(plan.project).exists()
            record.outcome = OperationOutcome.PARTIAL if partial else OperationOutcome.FAILED
            record.evidence.append(Evidence("qasc.create", str(exc), kind="error"))
            if partial:
                record.produced.append({"kind": "partial_qasc_project", "path": plan.project})
        record.unknowns.extend(["Generated application functionality remains unverified until separate VERIFY", "No packaging, installation, or dependency installation was requested"])
        record.finished_at = utc_now()
        return record

    def verify(self, plan: QASCPlan, record: OperationRecord, *, trusted_generated_source: bool = False) -> OperationRecord:
        if not trusted_generated_source:
            raise ValueError("Explicit generated-source trust is required for QASC verification")
        try:
            if record.capability_id != CAPABILITY_ID or record.task_id != plan.task_id or jsonable(record.planned) != jsonable(asdict(plan)):
                raise ValueError("QASC verification plan does not match execution record")
            if record.outcome != OperationOutcome.SUCCEEDED:
                record.unknowns.append("Verification not run because source generation did not succeed")
                return record
            self._check_plan(plan)
            state = self._state(plan)
            hashes, before = self._snapshot(plan, state)
            artifacts = [item for item in record.produced if item.get("kind") == "generated_python_project" and item.get("path") == plan.project]
            if len(artifacts) != 1 or artifacts[0].get("files") != hashes or artifacts[0].get("source_fingerprint") != before:
                raise ValueError("Generated source changed after execution; review and create a new verification plan")
            call = self._invoke(plan, ["test", plan.name, "--timeout", str(min(30, self.timeout_seconds))])
            record.executed.append({"stage": "verify", **asdict(call)})
            if call.interrupted:
                record.verification = VerificationStatus.INCONCLUSIVE
                record.evidence.append(Evidence("qasc.test", call.detail, kind="verification"))
                return record
            summary = self._summary(call)
            state = self._state(plan)
            _, after = self._snapshot(plan, state)
            verification = state.get("last_verification")
            if not isinstance(verification, dict):
                raise ValueError("QASC supplied no actual verification record")
            expected_cases = json.loads(plan.acceptance_json)["cases"]
            cases = verification.get("acceptance_cases")
            cases_match = isinstance(cases, list) and len(cases) == len(expected_cases) and all(isinstance(actual, dict) and actual.get("name") == expected["name"] and actual.get("passed") is True and actual.get("mismatches") == [] and isinstance(actual.get("receipt_id"), str) for actual, expected in zip(cases, expected_cases))
            passed = (call.exit_code == 0 and summary.get("name") == plan.name and summary.get("status") == "verified" and summary.get("verification_matches_current_source") is True and summary.get("last_verification") == verification and verification.get("passed") is True and verification.get("unit_tests_passed") is True and type(verification.get("unit_test_count")) is int and verification["unit_test_count"] > 0 and verification.get("independent_acceptance_passed") is True and verification.get("source_unchanged") is True and verification.get("source_fingerprint") == after == before and cases_match)
            record.verification = VerificationStatus.PASSED if passed else VerificationStatus.FAILED
            record.evidence.append(Evidence(str(Path(plan.project) / ".qasc" / "state.json"), json.dumps({"verification": verification, "sce_fingerprint": after, "fixed_acceptance_retained": True, "passed": passed}), kind="verification"))
            if passed:
                record.unknowns = [item for item in record.unknowns if not item.startswith("Generated application functionality remains")]
            record.unknowns.append("Checks cover supplied acceptance cases and generated tests; they do not establish general correctness or sandbox isolation")
        except (OSError, ValueError, TypeError) as exc:
            record.verification = VerificationStatus.FAILED
            record.evidence.append(Evidence("qasc.verify", str(exc), kind="error"))
        finally:
            record.finished_at = utc_now()
        return record

    def report(self, record: OperationRecord) -> OperationRecord:
        return record
