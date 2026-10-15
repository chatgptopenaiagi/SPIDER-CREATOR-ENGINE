from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

from sce import __version__
from sce.ai import LocalAIConfig, LoopbackAIProvider, ProviderError, TaskContext
from sce.analysis import analyze_local
from sce.capabilities import default_registry
from sce.core.config import Config
from sce.core.models import Task, TaskStatus, OperationOutcome, VerificationStatus, jsonable
from sce.orchestration import Orchestrator
from sce.reporting import render_report, write_report
from sce.resources import discover_environment
from sce.storage.task_store import TaskStore


def emit(value) -> None:
    print(json.dumps(jsonable(value), indent=2, ensure_ascii=False, allow_nan=False))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="sce", description="Spider Creator Engine: local software discovery, engineering intelligence and creation")
    root.add_argument("--version", action="version", version=f"SCE {__version__}")
    root.add_argument("--config", type=Path, help="TOML config; relative storage paths use its directory")
    commands = root.add_subparsers(dest="command", required=True)
    from sce.cli.spider import add_commands
    add_commands(commands)
    commands.add_parser("config", help="Show resolved configuration without creating storage")
    commands.add_parser("init", help="Explicitly initialize selected storage paths")
    commands.add_parser("doctor", help="Observe environment and configured resource limits")
    commands.add_parser("capabilities", help="List implemented and proposed capability contracts")
    commands.add_parser("ai-probe", help="Check availability of the configured local model")
    propose = commands.add_parser("ai-propose", help="Get a bounded proposal; this command never executes it")
    propose.add_argument("objective")
    analyze = commands.add_parser("analyze", help="Bounded static inspection of a local directory")
    analyze.add_argument("source", type=Path)
    build = commands.add_parser("build", help="Build a controlled Python fixture")
    build.add_argument("source", type=Path)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--trust-source", action="store_true", help="Authorize running this explicitly selected source during verification")
    build.add_argument("--verify", action="store_true", help="Run declared functional verification separately from packaging")
    build.add_argument("--prepare-only", action="store_true", help="Read-only validation/plan; no output or database writes")
    task = commands.add_parser("task", help="Create, execute, inspect, and cancel checkpointed tasks")
    task_commands = task.add_subparsers(dest="task_command", required=True)
    create = task_commands.add_parser("create")
    create.add_argument("objective")
    task_commands.add_parser("list")
    show = task_commands.add_parser("show")
    show.add_argument("id")
    cancel = task_commands.add_parser("cancel")
    cancel.add_argument("id")
    run = task_commands.add_parser("run")
    run.add_argument("file", type=Path, help="Explicit task JSON; paths relative to this file")
    run.add_argument("--trust-source", action="store_true")
    resume = task_commands.add_parser("resume")
    resume.add_argument("id")
    resume.add_argument("--trust-source", action="store_true")
    report = commands.add_parser("report", help="Render a stored canonical operation")
    report.add_argument("id")
    report.add_argument("--format", choices=["json", "markdown", "html"], default="json")
    report.add_argument("--output", type=Path)
    return root


def _provider(config: Config) -> LoopbackAIProvider:
    return LoopbackAIProvider(LocalAIConfig(
        endpoint=config.ai.endpoint, model_id=config.ai.model,
        max_context_chars=config.ai.max_context_chars,
        max_output_tokens=config.ai.max_response_tokens,
        model_context_tokens=config.resources.model_context_tokens,
        timeout_seconds=min(config.resources.execution_timeout_seconds, config.ai.timeout_seconds),
    ))


def _adapter(config: Config):
    from sce.builders.python import PythonBuildAdapter
    return PythonBuildAdapter(timeout_seconds=config.resources.execution_timeout_seconds,
                              temporary_root=config.storage["TEMP_STORAGE"])


def _task_execution(args, config: Config, store: TaskStore) -> int:
    if args.task_command == "run":
        if args.file.stat().st_size > 1_000_000:
            raise ValueError("Task file exceeds input budget")
        task = Task.from_dict(json.loads(args.file.read_text(encoding="utf-8")))
        if task.status != TaskStatus.PENDING or any(step.attempts or step.status != TaskStatus.PENDING or step.operation_ids for step in task.steps):
            raise ValueError("New task files must contain only pending, unexecuted steps")
        base = args.file.resolve().parent
        for step in task.steps:
            for key in ("source", "output_root"):
                value = step.inputs.get(key)
                if isinstance(value, str):
                    path = Path(value)
                    step.inputs[key] = str((base / path).resolve())
    else:
        task = store.get_task(args.id)
        if task.mode == "CREATE_NEW_APPLICATION":
            from sce.spider import SpiderEngine
            result = SpiderEngine(config).resume(task.id, trusted=args.trust_source)
            emit(result)
            return 0 if result["functional_application_created"] else 1
    registry = default_registry()
    for step in task.steps:
        if step.capability_id != "python.build":
            raise ValueError("Task JSON executor supports python.build only; use the corresponding Spider product workflow")
        registry.validate_call(step.capability_id, step.inputs)
        if step.max_attempts > config.resources.max_retries + 1:
            raise ValueError("Task retry budget exceeds configured maximum")
        if step.capability_id == "python.build" and (not args.trust_source or step.inputs["trusted"] is not True):
            raise ValueError("Task builds require trusted=true and explicit --trust-source authority")
    adapter = _adapter(config)

    def execute(step):
        plan = adapter.prepare(Path(step.inputs["source"]), Path(step.inputs["output_root"]),
                               trusted=True, task_id=task.id)
        cancelled = lambda: store.cancellation_requested(task.id)
        record = adapter.execute(plan, cancelled=cancelled)
        if record.outcome == OperationOutcome.SUCCEEDED:
            record = adapter.verify(plan, record, cancelled=cancelled)
        return adapter.report(record)

    engine = Orchestrator(store, execute)
    result = engine.run(task) if args.task_command == "run" else engine.resume(task.id)
    for operation in store.operations_for_task(result.id):
        destination = config.storage["REPORT_STORAGE"] / f"{operation.id}.json"
        if not destination.exists():
            write_report(operation, destination)
    emit(result)
    return 0 if result.status == TaskStatus.COMPLETED else 1


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = Config.load(args.config) if args.config else Config.default(Path.cwd())
        if args.command in {"discover", "spider", "trace", "memory", "ai-interpret", "create-ai"}:
            from sce.cli.spider import execute
            return execute(args, config, emit, _provider)
        if args.command == "config":
            emit(config)
        elif args.command == "init":
            config.initialize_storage()
            emit({"initialized": config.storage})
        elif args.command == "doctor":
            emit({"environment": discover_environment(Path.cwd()), "limits": config.resources.as_dict(),
                  "enforcement": config.resources.enforcement_status()})
        elif args.command == "capabilities":
            emit(default_registry().list())
        elif args.command == "ai-probe":
            result = _provider(config).probe()
            emit(result)
            return 0 if result.available else 1
        elif args.command == "ai-propose":
            proposal = _provider(config).propose(TaskContext(args.objective, (
                "No execution capability is authorized by this proposal-only command. Return actions: [].",
            )))
            from sce.ai import validate_proposal
            validate_proposal(proposal, default_registry(), [], lambda capability, inputs: None)
            emit({"proposal": jsonable(proposal), "executed": False})
        elif args.command == "analyze":
            emit(analyze_local(args.source))
        elif args.command == "build":
            adapter = _adapter(config)
            plan = adapter.prepare(args.source, args.output, trusted=args.trust_source)
            if args.prepare_only:
                emit(plan)
                return 0 if not plan.validation_errors and not plan.unsupported else 1
            record = adapter.execute(plan)
            if args.verify and record.outcome == OperationOutcome.SUCCEEDED:
                record = adapter.verify(plan, record)
            record = adapter.report(record)
            TaskStore(config.storage["TASK_DATABASE"]).save_operation(record)
            write_report(record, config.storage["REPORT_STORAGE"] / f"{record.id}.json")
            emit(record)
            success = record.outcome == OperationOutcome.SUCCEEDED
            return 0 if success and (not args.verify or record.verification == VerificationStatus.PASSED) else 1
        elif args.command == "task":
            store = TaskStore(config.storage["TASK_DATABASE"])
            if args.task_command == "create":
                task = Task(args.objective)
                store.create_task(task)
                emit(task)
            elif args.task_command == "list":
                emit(store.list_tasks())
            elif args.task_command == "show":
                emit(store.get_task(args.id))
            elif args.task_command == "cancel":
                store.request_cancellation(args.id)
                emit({"task_id": args.id, "cancellation_requested": True})
            else:
                return _task_execution(args, config, store)
        elif args.command == "report":
            record = TaskStore(config.storage["TASK_DATABASE"]).get_operation(args.id)
            if args.output:
                write_report(record, args.output, args.format)
                emit({"report": str(args.output.resolve())})
            else:
                print(render_report(record, args.format), end="")
        return 0
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error, ProviderError) as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('{"error": "Interrupted; inspect checkpoint before resuming"}', file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
