"""Product commands built on the discovery, memory, synthesis and AI adapters."""
from __future__ import annotations

import json
from pathlib import Path
import platform

from sce.core.models import Evidence, OperationRecord, OperationOutcome, Task, TaskStatus, VerificationStatus, jsonable, utc_now
from sce.discovery import SpiderDiscovery
from sce.knowledge import KnowledgeStore, KnowledgeRecord, Provenance, ProvenanceCategory
from sce.reporting import write_report
from sce.reporting.trace import TraceEvent, TraceStore
from sce.storage import TaskStore
from sce.spider import SpiderEngine


def add_commands(commands):
    discover = commands.add_parser("discover", help="Inspect local resources or explicitly search public GitHub; retain attributable knowledge")
    discover.add_argument("start")
    discover.add_argument("--online", action="store_true")
    discover.add_argument("--limit", type=int, default=5)
    discover.add_argument("--task-id", help="Associate discoveries with an existing task")
    spider = commands.add_parser("spider", help="Discover, acquire, analyze and connect components into a verified application")
    sub = spider.add_subparsers(dest="spider_command", required=True)
    create = sub.add_parser("create")
    create.add_argument("objective")
    create.add_argument("--component", action="append", default=[], help="Local component with an explicit sce-component.json interface")
    create.add_argument("--component-spec", type=Path, action="append", default=[], help="JSON interface specification for ordinary Python source; paths relative to this file")
    create.add_argument("--acceptance", type=Path, required=True, help="JSON containing input object and independently expected_output")
    create.add_argument("--name", default="spider-application")
    create.add_argument("--trust-source", action="store_true")
    create.add_argument("--prepare-only", action="store_true")
    resume = sub.add_parser("resume")
    resume.add_argument("id")
    resume.add_argument("--trust-source", action="store_true")
    trace = commands.add_parser("trace", help="Inspect what happened, why, and the underlying evidence")
    trace.add_argument("id")
    trace.add_argument("--level", type=int, choices=[1, 2, 3], default=1)
    trace.add_argument("--format", choices=["json", "markdown", "html"], default="json")
    memory = commands.add_parser("memory", help="Retrieve scoped engineering knowledge; historical matches remain candidates")
    memory.add_argument("id", help="Task id")
    memory.add_argument("--resource-id")
    memory.add_argument("--query", default="")
    memory.add_argument("--include-history", action="store_true")
    memory.add_argument("--limit", type=int, default=8)
    interpret = commands.add_parser("ai-interpret", help="Ask local AI to interpret bounded actual task evidence; never execute its suggestions")
    interpret.add_argument("id")
    ai = commands.add_parser("create-ai", help="Generate Python with an explicitly selected installed QASC; optional separate verification")
    ai.add_argument("objective")
    ai.add_argument("--qasc-python", type=Path, required=True)
    ai.add_argument("--name", required=True)
    ai.add_argument("--acceptance", type=Path, required=True)
    ai.add_argument("--max-tokens", type=int, default=3000)
    ai.add_argument("--verify", action="store_true")
    ai.add_argument("--trust-generated-source", action="store_true")
    ai.add_argument("--prepare-only", action="store_true")


def read_json(path: Path, limit=100_000):
    with path.open("rb") as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"Input exceeds {limit} bytes")
    return json.loads(raw)


def execute(args, config, emit, provider):
    database = config.storage["TASK_DATABASE"]
    if args.command == "spider":
        engine = SpiderEngine(config)
        if args.spider_command == "resume":
            result = engine.resume(args.id, trusted=args.trust_source)
        else:
            acceptance = read_json(args.acceptance)
            if not isinstance(acceptance, dict) or set(acceptance) != {"input", "expected_output"}:
                raise ValueError("Acceptance must contain exactly input and expected_output")
            components = list(args.component)
            for filename in args.component_spec:
                spec = read_json(filename)
                spec["source"] = str((filename.resolve().parent / spec["source"]).resolve())
                components.append(spec)
            plan = engine.prepare(args.objective, components, name=args.name, input_data=acceptance["input"],
                                  expected_output=acceptance["expected_output"], trusted=args.trust_source)
            if args.prepare_only:
                emit(plan)
                return int(bool(plan.validation_errors))
            result = engine.run(plan)
        emit(result)
        return 0 if result["functional_application_created"] else 1
    if args.command == "trace":
        print(TraceStore(database).render(args.id, level=args.level, format=args.format))
        return 0
    if args.command == "memory":
        if args.include_history and not args.resource_id:
            raise ValueError("Historical retrieval requires an explicit resource identity")
        memory = KnowledgeStore(database)
        if args.resource_id:
            result = memory.find_candidates(args.id, resource_id=args.resource_id, query=args.query,
                environment={"python": platform.python_version(), "platform": platform.system()},
                include_history=args.include_history, limit=args.limit, max_chars=config.ai.max_context_chars)
        else:
            result = memory.retrieve(args.id, query=args.query, limit=args.limit, max_chars=config.ai.max_context_chars)
        emit(result)
        return 0
    if args.command == "discover":
        tasks = TaskStore(database)
        task = tasks.get_task(args.task_id) if args.task_id else Task(args.start, mode="DISCOVERY")
        if not args.task_id:
            tasks.create_task(task)
        discovered = SpiderDiscovery(offline=not args.online).discover(args.start, limit=args.limit)
        record = OperationRecord(capability_id="spider.discover", task_id=task.id, requested={"start": args.start},
            planned={"online": args.online, "limit": args.limit, "scope": "Bounded static inspection; no source execution"},
            started_at=utc_now(), finished_at=utc_now(), produced=[jsonable(project) for project in discovered.projects],
            outcome=OperationOutcome.SUCCEEDED if not (discovered.errors or discovered.unsupported) else OperationOutcome.PARTIAL if discovered.projects else OperationOutcome.FAILED,
            verification=VerificationStatus.PASSED if discovered.projects and not discovered.errors else VerificationStatus.INCONCLUSIVE,
            evidence=[item for project in discovered.projects for item in project.evidence],
            unknowns=[*discovered.errors, *discovered.unsupported, *discovered.limitations])
        tasks.save_operation(record)
        memory = KnowledgeStore(database)
        memory.record_operation(record)
        for project in discovered.projects:
            memory.append(KnowledgeRecord(claim=f"Inspected {project.name}", task_ids=[task.id],
                resource_id=project.resource_id, resource_revision=project.revision, subject="software_project", kind="project_reference",
                provenance=[Provenance(project.source_uri, "Bounded static discovery", source_revision=project.revision)],
                supporting_evidence=[jsonable(project)], limitations=project.limitations))
            for observation in project.observations:
                memory.append(KnowledgeRecord(claim=f"{project.name}: {observation.subject}", task_ids=[task.id],
                    resource_id=project.resource_id, resource_revision=project.revision, subject=observation.subject,
                    provenance=[Provenance(observation.source, "Static document inspection", category=observation.provenance, content_sha256=observation.content_sha256)],
                    supporting_evidence=[{"value": observation.value}], limitations=["Declarations are not verified behavior"]))
        TraceStore(database).append(TraceEvent(task.id, "discovery", "executed", "Discovery observations recorded",
            objective=task.objective, operation_id=record.id, evidence=jsonable(record.evidence), artifacts=record.produced,
            outcome=record.outcome, verification=record.verification, unknowns=record.unknowns,
            decision="Inspect only selected local sources or explicitly enabled public GitHub endpoints"))
        write_report(record, config.storage["REPORT_STORAGE"] / task.id / f"{record.id}.json")
        if not args.task_id:
            task.status = TaskStatus.COMPLETED if record.outcome == OperationOutcome.SUCCEEDED else TaskStatus.FAILED
            tasks.save_task(task)
        emit({"task_id": task.id, "operation_id": record.id, "discovery": discovered})
        return 0 if record.outcome == OperationOutcome.SUCCEEDED else 1
    if args.command == "ai-interpret":
        from sce.ai import TaskContext
        from sce.ai.provider import INTERPRETATION_PROMPT
        tasks = TaskStore(database)
        task = tasks.get_task(args.id)
        memory = KnowledgeStore(database)
        operations = tasks.operations_for_task(task.id)
        if not operations:
            raise ValueError("Interpretation requires actual recorded operations")
        context_records, included_ids = [], []
        for operation in reversed(operations[-6:]):
            receipts = []
            for execution in operation.executed[-3:]:
                excerpt = {key: execution[key] for key in ("stage", "exit_code", "timed_out", "interrupted") if key in execution}
                for key in ("stdout", "stderr", "detail"):
                    if key in execution:
                        value = str(execution[key])
                        excerpt[key] = value[:500]
                        if len(value) > 500:
                            excerpt[key + "_truncated"] = True
                if isinstance(execution.get("argv"), (list, tuple)):
                    excerpt["argv"] = [str(arg)[:200] for arg in execution["argv"][:12]]
                    excerpt["argv_is_excerpt"] = True
                receipts.append(excerpt)
            artifacts = operation.produced or operation.requested.get("artifact", [])
            identities = [{key: artifact[key] for key in ("kind", "path", "sha256", "source_fingerprint") if key in artifact}
                          for artifact in artifacts[:3]]
            item = {"operation_id": operation.id, "capability": operation.capability_id,
                    "operation_order": next(index for index, candidate in enumerate(operations) if candidate.id == operation.id),
                    "started_at": operation.started_at, "finished_at": operation.finished_at,
                    "outcome": operation.outcome.value, "verification": operation.verification.value,
                    "evidence": [{"source": evidence.source[:200], "kind": evidence.kind, "detail": evidence.detail[:400]}
                                 for evidence in operation.evidence[-3:]],
                    "executed": receipts, "artifact_identities": identities,
                    "artifact_count": len(operation.produced), "unknowns": operation.unknowns[:3],
                    "scope": "Historical status of this operation only. Earlier generation NOT_RUN may be superseded by later actual checks only for the same artifact and check scope. Actual executed receipts below show runtime activity. Bounded excerpt; omitted content is not an assertion of success."}
            encoded = json.dumps(item, ensure_ascii=False)
            payload = json.dumps({"objective": task.objective, "records": [*context_records, encoded]}, ensure_ascii=False)
            estimated = len(payload.encode("utf-8")) + len(INTERPRETATION_PROMPT.encode("utf-8")) + 128
            if len(payload) > config.ai.max_context_chars or estimated + config.ai.max_response_tokens > config.resources.model_context_tokens:
                continue
            context_records.append(encoded)
            included_ids.append(operation.id)
        if not context_records:
            raise ValueError("No actual operation evidence fits the configured context budget")
        context = TaskContext(task.objective, tuple(context_records))
        interpretation = provider(config).interpret(context)
        record = KnowledgeRecord(claim=interpretation.summary, task_ids=[task.id], subject="AI interpretation of execution evidence",
            provenance=[Provenance(config.ai.endpoint, "Bounded local AI interpretation", category=ProvenanceCategory.AI_INFERENCE, actor=config.ai.model)],
            supporting_evidence=[{"operation_ids": included_ids, "interpretation": jsonable(interpretation)}],
            limitations=["AI interpretation is not verification; no suggested action was executed"])
        memory.append(record)
        emit({"interpretation": interpretation, "knowledge_record_id": record.id, "executed_suggestions": False})
        return 0
    if args.command == "create-ai":
        from sce.adapters.qasc import PythonQASCAdapter
        if args.verify and not args.trust_generated_source:
            raise ValueError("--verify requires explicit --trust-generated-source")
        adapter = PythonQASCAdapter(args.qasc_python, config.storage["BUILD_WORKSPACES"],
            endpoint=config.ai.endpoint, model=config.ai.model, model_timeout_seconds=config.ai.timeout_seconds,
            timeout_seconds=max(config.resources.execution_timeout_seconds, config.ai.timeout_seconds + 30), max_tokens=args.max_tokens)
        task = Task(args.objective, mode="CREATE_NEW_APPLICATION", allowed_capabilities=["qasc.create_python"])
        plan = adapter.prepare(args.objective, args.name, acceptance=read_json(args.acceptance, 32_000), task_id=task.id)
        if args.prepare_only:
            emit(plan)
            return 0
        tasks = TaskStore(database)
        task.status = TaskStatus.RUNNING
        tasks.create_task(task)
        generation = adapter.execute(plan)
        tasks.save_operation(generation)
        memory = KnowledgeStore(database)
        memory.record_operation(generation, resource_id=f"qasc:{task.id}")
        write_report(generation, config.storage["REPORT_STORAGE"] / task.id / f"{generation.id}.json")
        record = generation
        if args.verify and generation.outcome == OperationOutcome.SUCCEEDED:
            # Preserve the generation-only record even after verification is attempted.
            record = OperationRecord.from_dict(jsonable(generation))
            from sce.core.models import identifier
            record.id = identifier()
            record = adapter.verify(plan, record, trusted_generated_source=True)
            tasks.save_operation(record)
            memory.record_operation(record, resource_id=f"qasc:{task.id}")
            write_report(record, config.storage["REPORT_STORAGE"] / task.id / f"{record.id}.json")
        TraceStore(database).append(TraceEvent(task.id, "ai_creation", "executed", "Local QASC generation and requested checks recorded",
            objective=task.objective, operation_id=record.id, evidence=jsonable(record.evidence), artifacts=record.produced,
            outcome=record.outcome, verification=record.verification, unknowns=record.unknowns,
            decision="Use the independently installed QASC through its inspected CLI; preserve supplied acceptance"))
        if record.outcome != OperationOutcome.SUCCEEDED or record.verification == VerificationStatus.FAILED:
            task.status = TaskStatus.FAILED
        elif record.verification == VerificationStatus.PASSED:
            task.status = TaskStatus.COMPLETED
        else:
            task.status = TaskStatus.BLOCKED
            task.unknowns.append("Generated application awaits functional verification; QASC recovery is not integrated")
        tasks.save_task(task)
        if task.status == TaskStatus.FAILED or (args.verify and record.verification == VerificationStatus.INCONCLUSIVE):
            from sce.recovery import FailureCapsule
            capsule = FailureCapsule(project_identity=f"qasc:{task.id}", original_objective=task.objective,
                failed_operation="qasc.create_python", relevant_inputs=record.requested,
                relevant_errors=[item.detail for item in record.evidence if item.kind == "error"] or [f"outcome={record.outcome.value}; verification={record.verification.value}"],
                provenance=[Provenance(f"operation:{record.id}", "Recorded incomplete AI creation attempt")],
                partial_artifacts=record.produced, supporting_evidence=jsonable(record.evidence),
                suggested_next_checks=["Inspect generated source and preserved QASC verification receipts before choosing a repair"],
                limitations=["No repair is established; SCE does not automatically resume QASC tasks"])
            memory.append(capsule.to_knowledge_record([task.id]))
        emit({"task_id": task.id, "operation": record})
        return 0 if record.outcome == OperationOutcome.SUCCEEDED and (not args.verify or record.verification == VerificationStatus.PASSED) else 1
    raise ValueError("Unknown Spider command")
