from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import platform
import zipfile

from sce.acquisition import LocalAcquirer
from sce.analysis import analyze_local
from sce.builders.python import PythonBuildAdapter, BuildPlan, SourceFile
from sce.capabilities import default_registry
from sce.core.config import Config
from sce.core.models import (Evidence, OperationRecord, OperationOutcome, Task, TaskStep,
                             TaskStatus, VerificationStatus, jsonable, utc_now)
from sce.discovery import inspect_local
from sce.knowledge import KnowledgeRecord, KnowledgeStore, Provenance, ProvenanceCategory, KnowledgeRelationship
from sce.orchestration import Orchestrator
from sce.recovery import FailureCapsule
from sce.reporting import write_report
from sce.reporting.trace import TraceEvent, TraceStore
from sce.storage import TaskStore
from sce.synthesis import ComponentSpec, PythonSynthesisAdapter


@dataclass
class CreationPlan:
    task: Task
    validation_errors: list[str]
    selected_route: str
    source_preview: dict
    task_sha256: str


def _component(value):
    if isinstance(value, str):
        return Path(value)
    return ComponentSpec(**{**value, "source_files": tuple(value["source_files"]),
                            "required_modules": tuple(value.get("required_modules", ()))})


def _build_plan(values: dict) -> BuildPlan:
    return BuildPlan(**{**values, "files": tuple(SourceFile(**item) for item in values["files"]),
                         "required_modules": tuple(values["required_modules"]),
                         "verification_args": tuple(values["verification_args"]),
                         "validation_errors": tuple(values["validation_errors"])})


class SpiderEngine:
    """Use preserved engineering infrastructure to create a new local application.

    The first route connects inspected Python callables. It does not infer an
    arbitrary interface from natural language. Original objectives remain intact.
    All paths are captured in the task; resume rejects a different storage profile.
    """

    def __init__(self, config: Config):
        self.config = config

    def prepare(self, objective: str, components: list[str | dict], *, name: str,
                input_data: dict, expected_output, trusted: bool = False) -> CreationPlan:
        if not isinstance(components, list) or not 1 <= len(components) <= 8:
            raise ValueError("Select 1..8 inspected components")
        normalized = []
        for component in components:
            if isinstance(component, str):
                normalized.append(str(Path(component).resolve(strict=True)))
            elif isinstance(component, dict):
                normalized.append({**component, "source": str(Path(component["source"]).resolve(strict=True))})
            else:
                raise ValueError("Components must be local paths or explicit interface specifications")
        if not isinstance(input_data, dict):
            raise ValueError("Component input must be a JSON object")
        encoded = json.dumps({"input": input_data, "expected_output": expected_output}, allow_nan=False)
        if len(encoded) > 100_000:
            raise ValueError("Acceptance contract exceeds the input budget")
        task = Task(objective, mode="CREATE_NEW_APPLICATION")
        workspace = self.config.storage["BUILD_WORKSPACES"] / task.id / "application"
        artifact_root = self.config.storage["ARTIFACT_STORAGE"] / task.id
        request = {"components": normalized, "name": name, "input_data": input_data,
                   "expected_output": expected_output, "trusted": trusted,
                   "workspace": str(workspace), "artifact_root": str(artifact_root),
                   "storage_profile": {key: str(value) for key, value in self.config.storage.items()}}
        stages = [("discovery", "spider.discover"), ("acquisition", "resource.acquire_local"),
                  ("analysis", "project.analyze"), ("synthesis", "application.synthesize"),
                  ("build", "python.build"), ("functional_verification", "application.verify")]
        task.allowed_capabilities = [capability for _, capability in stages]
        for index, (stage, capability) in enumerate(stages):
            inputs = {"request": request} if capability != "python.build" else {
                "source": str(workspace), "output_root": str(artifact_root), "trusted": trusted}
            task.steps.append(TaskStep(stage, capability, inputs, [stages[index - 1][0]] if index else []))
        synthesis = PythonSynthesisAdapter(max_components=8).prepare(
            [_component(value) for value in normalized], workspace, name=name, input_data=input_data,
            expected_output=expected_output, trusted=trusted, task_id=task.id)
        request["prepared_components"] = jsonable(synthesis.components)
        request["source_roots"] = [part.spec.source for part in synthesis.components]
        request["manifest_names"] = [part.manifest.path if part.manifest else None for part in synthesis.components]
        return CreationPlan(task, list(synthesis.validation_errors),
                            "Connect declared Python JSON callables using a thin CLI bridge; build a new application",
                            jsonable(synthesis), hashlib.sha256(json.dumps(jsonable(task), sort_keys=True).encode()).hexdigest())

    def _stores(self):
        database = self.config.storage["TASK_DATABASE"]
        return TaskStore(database), KnowledgeStore(database), TraceStore(database)

    def run(self, plan: CreationPlan) -> dict:
        if plan.validation_errors:
            raise ValueError("Creation preparation failed: " + "; ".join(plan.validation_errors))
        if hashlib.sha256(json.dumps(jsonable(plan.task), sort_keys=True).encode()).hexdigest() != plan.task_sha256:
            raise ValueError("Prepared task scope changed; prepare a new plan")
        store, knowledge, trace = self._stores()
        trace.append(TraceEvent(plan.task.id, "planning", "planned", "Create a new application from selected components",
            objective=plan.task.objective, decision=plan.selected_route,
            selected_components=plan.task.steps[0].inputs["request"]["components"] if all(
                isinstance(value, str) for value in plan.task.steps[0].inputs["request"]["components"]) else [],
            planned_actions=[{"stage": step.id, "capability": step.capability_id} for step in plan.task.steps]))
        result = Orchestrator(store, self._executor(plan.task, store, knowledge, trace)).run(plan.task)
        return self._result(result, store, trace)

    def resume(self, task_id: str, *, trusted: bool = False) -> dict:
        store, knowledge, trace = self._stores()
        task = store.get_task(task_id)
        if task.mode != "CREATE_NEW_APPLICATION" or not task.steps:
            raise ValueError("This task does not use the Spider creation workflow")
        if not trusted:
            raise ValueError("Resuming source execution requires explicit trust")
        result = Orchestrator(store, self._executor(task, store, knowledge, trace)).resume(task_id)
        return self._result(result, store, trace)

    def _executor(self, task, store, knowledge, trace):
        request = task.steps[0].inputs["request"]
        if request["storage_profile"] != {key: str(value) for key, value in self.config.storage.items()}:
            raise ValueError("Storage profile changed; inspect the task before resuming")
        if request["trusted"] is not True:
            raise ValueError("Creation requires explicit source trust")
        registry = default_registry()
        for step in task.steps:
            registry.validate_call(step.capability_id, step.inputs)
        environment = {"python": platform.python_version(), "platform": platform.system()}

        def check_selected_sources():
            for component in request["prepared_components"]:
                root = Path(component["spec"]["source"])
                if root.resolve() != root:
                    raise ValueError("Prepared component location changed")
                expected = [*component["files"], *([component["manifest"]] if component["manifest"] else [])]
                for item in expected:
                    actual, _ = PythonSynthesisAdapter()._read_file(root, item["path"])
                    if jsonable(actual) != item:
                        raise ValueError("Selected source changed after PREPARE; prepare a new plan")

        def prior(capability):
            matches = [record for record in store.operations_for_task(task.id) if record.capability_id == capability]
            if not matches or matches[-1].outcome != OperationOutcome.SUCCEEDED or matches[-1].verification != VerificationStatus.PASSED:
                raise ValueError(f"No verified prerequisite for {capability}")
            return matches[-1]

        def resources():
            snapshots = prior("resource.acquire_local").produced
            for item in snapshots:
                current = LocalAcquirer().prepare(Path(item["location"]), self.config.storage["RESOURCE_LIBRARY"])
                if current.content_hashes != item["content_hashes"]:
                    raise ValueError("Acquired resource changed; historical checkpoint cannot authorize newer content")
            return snapshots

        def execute(step):
            trace.append(TraceEvent(task.id, step.id, "planned", f"Prepare {step.capability_id}", objective=task.objective,
                                    planned_actions=[{"capability": step.capability_id}]))
            record = OperationRecord(capability_id=step.capability_id, task_id=task.id, requested=step.inputs,
                                     planned={"stage": step.id}, started_at=utc_now())
            try:
                if step.id == "discovery":
                    check_selected_sources()
                    for source in request["source_roots"]:
                        project = inspect_local(Path(source))
                        record.produced.append({"kind": "discovered_project", **jsonable(project)})
                        record.evidence.extend(project.evidence)
                    record.planned["verification_scope"] = "Structured local source observations, not software functionality"
                    record.outcome, record.verification = OperationOutcome.SUCCEEDED, VerificationStatus.PASSED
                elif step.id == "acquisition":
                    check_selected_sources()
                    projects = prior("spider.discover").produced
                    for source, project in zip(request["source_roots"], projects, strict=True):
                        acquirer = LocalAcquirer()
                        acquisition = acquirer.prepare(Path(source), self.config.storage["RESOURCE_LIBRARY"], source_revision=project["revision"])
                        if any(acquisition.content_hashes.get(name) != digest for name, digest in project["metadata"].get("content_hashes", {}).items()):
                            raise ValueError("Source changed after discovery; cannot associate new bytes with the earlier revision")
                        snapshot = acquirer.execute(acquisition)
                        item = {"kind": "resource_snapshot", **jsonable(snapshot), "resource_id": project["resource_id"]}
                        record.produced.append(item)
                        record.evidence.extend(snapshot.evidence)
                        if snapshot.transfer_status != "completed":
                            record.unknowns.extend(snapshot.unknowns)
                            raise ValueError("Local resource transfer is partial")
                    record.planned["verification_scope"] = "Acquired bytes match the prepared source inventory"
                    record.outcome, record.verification = OperationOutcome.SUCCEEDED, VerificationStatus.PASSED
                elif step.id == "analysis":
                    for item in resources():
                        analysis = analyze_local(Path(item["location"]))
                        record.produced.append({"kind": "static_analysis", "resource_id": item["resource_id"], **analysis})
                        record.evidence.append(Evidence(item["location"], "Static structure and dependencies inspected without importing source", kind="static_analysis"))
                    record.planned["verification_scope"] = "Bounded static inspection completed; interface validity is checked during synthesis"
                    record.outcome, record.verification = OperationOutcome.SUCCEEDED, VerificationStatus.PASSED
                elif step.id == "synthesis":
                    snapshots = resources()
                    selected = []
                    for component, item, manifest_name in zip(request["components"], snapshots, request["manifest_names"], strict=True):
                        selected.append(Path(item["location"]) / manifest_name if isinstance(component, str) else _component({**component, "source": item["location"]}))
                    adapter = PythonSynthesisAdapter(max_components=8)
                    plan = adapter.prepare(selected, request["workspace"], name=request["name"],
                        input_data=request["input_data"], expected_output=request["expected_output"], trusted=True,
                        task_id=task.id, resource_ids=[item["resource_id"] for item in snapshots],
                        resource_revisions=[item["source_revision"] for item in snapshots])
                    for component, snapshot in zip(plan.components, snapshots, strict=True):
                        files = [*component.files, *([component.manifest] if component.manifest else [])]
                        if any(snapshot["content_hashes"].get(item.path) != item.sha256 for item in files):
                            raise ValueError("Selected acquired bytes changed before synthesis; source revision no longer applies")
                    record = adapter.verify(plan, adapter.execute(plan, cancelled=lambda: store.cancellation_requested(task.id)))
                elif step.id == "build":
                    adapter = PythonBuildAdapter(timeout_seconds=self.config.resources.execution_timeout_seconds,
                        temporary_root=self.config.storage["TEMP_STORAGE"])
                    plan = adapter.prepare(Path(request["workspace"]), Path(request["artifact_root"]), trusted=True, task_id=task.id)
                    synthesized = prior("application.synthesize")
                    expected = {str(Path(item["path"]).relative_to(request["workspace"]).as_posix()): item["sha256"]
                                for item in synthesized.produced if item.get("kind") == "application_source"}
                    if {item.path: item.sha256 for item in plan.files} != expected:
                        raise ValueError("Application source changed after synthesis; refusing a stale construction checkpoint")
                    expected_stdout = json.dumps(request["expected_output"], ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
                    expected_input = json.dumps(request["input_data"], ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
                    if plan.expected_stdout != expected_stdout or plan.expected_exit != 0 or plan.verification_args != ("--input-json", expected_input):
                        raise ValueError("Build acceptance differs from the original creation request")
                    record = adapter.execute(plan, cancelled=lambda: store.cancellation_requested(task.id))
                    if record.outcome == OperationOutcome.SUCCEEDED:
                        artifact = Path(record.produced[0]["path"])
                        with zipfile.ZipFile(artifact) as archive:
                            intact = archive.testzip() is None and "__main__.py" in archive.namelist()
                        with artifact.open("rb") as stream:
                            intact = intact and hashlib.file_digest(stream, "sha256").hexdigest() == record.produced[0]["sha256"]
                        record.verification = VerificationStatus.PASSED if intact else VerificationStatus.FAILED
                        record.evidence.append(Evidence(str(artifact), "Package integrity checked; functional verification is a separate operation", kind="package_integrity"))
                elif step.id == "functional_verification":
                    built = prior("python.build")
                    plan = _build_plan(built.planned)
                    adapter = PythonBuildAdapter(timeout_seconds=self.config.resources.execution_timeout_seconds,
                        temporary_root=self.config.storage["TEMP_STORAGE"])
                    if jsonable(adapter._snapshot(Path(plan.source))) != jsonable(plan.files):
                        raise ValueError("Application source changed after build; do not verify an outdated checkpoint as current")
                    checked = adapter.verify(plan, OperationRecord.from_dict(jsonable(built)),
                        cancelled=lambda: store.cancellation_requested(task.id))
                    record = OperationRecord(capability_id=step.capability_id, task_id=task.id,
                        requested={"build_operation_id": built.id, "artifact": built.produced},
                        planned={"verification_scope": "Functional acceptance", "input": request["input_data"], "expected_output": request["expected_output"]},
                        outcome=checked.outcome, verification=checked.verification,
                        executed=[item for item in checked.executed if item.get("stage") == "verify"],
                        evidence=[item for item in checked.evidence if item.kind in {"verification", "error"}],
                        unknowns=checked.unknowns, started_at=utc_now())
                else:
                    raise ValueError(f"Unknown creation stage: {step.id}")
            except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile) as error:
                record.outcome = OperationOutcome.PARTIAL if record.produced else OperationOutcome.FAILED
                record.verification = VerificationStatus.INCONCLUSIVE
                record.evidence.append(Evidence(step.capability_id, f"{type(error).__name__}: {error}", kind="error"))
                record.unknowns.append("Inspect preserved evidence before retry; no automatic repair was applied")
            record.finished_at = utc_now()
            self._remember(task, step, record, knowledge, trace, environment)
            write_report(record, self.config.storage["REPORT_STORAGE"] / task.id / f"{record.id}.json")
            return record
        return execute

    def _remember(self, task, step, record, knowledge, trace, environment):
        resource_id = f"application:{task.id}"
        memory = knowledge.record_operation(record, resource_id=resource_id, environment=environment)
        for item in record.produced:
            if item.get("resource_id"):
                observation = KnowledgeRecord(claim=f"{step.id}: {item.get('name', item['resource_id'])}",
                    task_ids=[task.id], resource_id=item["resource_id"], resource_revision=item.get("revision") or item.get("source_revision"),
                    kind="project_reference" if step.id == "discovery" else "observation", subject=step.id,
                    provenance=[Provenance(source=f"operation:{record.id}", method="Recorded local engineering observation")],
                    supporting_evidence=[item], environment=environment,
                    applicability={"python": platform.python_version()}, limitations=["Applicability must be reevaluated for another task"])
                knowledge.append(observation)
                knowledge.append_relationship(KnowledgeRelationship(memory.id, observation.id, "derived_from", task.id,
                    [Provenance(f"operation:{record.id}", "Recorded source relationship")]))
        failed = record.outcome not in {OperationOutcome.SUCCEEDED} or record.verification != VerificationStatus.PASSED
        if failed:
            messages = [item.detail for item in record.evidence if item.kind == "error"] or [f"Outcome {record.outcome.value}; verification {record.verification.value}"]
            capsule = FailureCapsule(project_identity=resource_id,
                provenance=[Provenance(f"operation:{record.id}", "Observed unsuccessful engineering stage")], relevant_errors=messages,
                original_objective=task.objective, failed_operation=step.capability_id, relevant_inputs=record.requested,
                environment=environment, software_versions={"python": platform.python_version()},
                error_signature=hashlib.sha256(messages[0].encode()).hexdigest(), partial_artifacts=record.produced or record.requested.get("artifact", []),
                supporting_evidence=jsonable(record.evidence), suggested_next_checks=["Compare current source, environment, and acceptance against the preserved plan"],
                limitations=["No correction has been established by this capsule"])
            knowledge.append(capsule.to_knowledge_record([task.id]))
        trace.append(TraceEvent(task.id, step.id, "failed" if failed else "verified",
            f"{step.capability_id}: {record.outcome.value}; declared verification {record.verification.value}",
            objective=task.objective, operation_id=record.id, outcome=record.outcome, verification=record.verification,
            evidence=jsonable(record.evidence), artifacts=record.produced, unknowns=record.unknowns,
            decision=record.planned.get("verification_scope", "Apply the selected component route and declared adapter contract"),
            errors=[item.detail for item in record.evidence if item.kind == "error"]))

    def _result(self, task, store, trace):
        operations = store.operations_for_task(task.id)
        request = task.steps[0].inputs["request"]
        artifacts = [item for record in operations if record.capability_id == "python.build" for item in record.produced]
        current_integrity = []
        for item in artifacts:
            try:
                with Path(item["path"]).open("rb") as source:
                    matched = hashlib.file_digest(source, "sha256").hexdigest() == item["sha256"]
                current_integrity.append({"path": item["path"], "status": "matched" if matched else "changed"})
            except OSError:
                current_integrity.append({"path": item["path"], "status": "unavailable"})
        result = {"task": jsonable(task), "operation_ids": [record.id for record in operations],
                  "application_source": request["workspace"],
                  "artifacts": artifacts, "current_artifact_integrity": current_integrity,
                  "functional_application_created": task.status == TaskStatus.COMPLETED,
                  "verification_basis": "Recorded acceptance at execution time; resume does not repeat completed checks",
                  "human_time_recovered": task.time.human_time_recovered_seconds,
                  "installation": "not_run", "ai_generation": "not_run",
                  "remaining_work": [step.id for step in task.steps if step.status != TaskStatus.COMPLETED]}
        destination = self.config.storage["REPORT_STORAGE"] / task.id
        destination.mkdir(parents=True, exist_ok=True)
        # Each snapshot has its own name; prior evidence is retained on resume.
        from uuid import uuid4
        snapshot = str(uuid4())
        (destination / f"trace-{snapshot}.html").write_text(trace.render(task.id, level=3, format="html"), encoding="utf-8")
        (destination / f"result-{snapshot}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
