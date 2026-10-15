"""Opt-in real disconnected-container verification using an already cached image.

Run with the project interpreter from Windows/PowerShell. This does not pull
images, install packages, change host networking, or affect existing containers.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import socket
import subprocess
import sys
import tarfile
from uuid import uuid4


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def source_hashes(root):
    selected = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for directory in (root / "src/sce", root / "examples/components")
        for path in directory.rglob("*") if path.is_file() and "__pycache__" not in path.parts
    }
    selected["scripts/verify_offline.py"] = hashlib.sha256((root / "scripts/verify_offline.py").read_bytes()).hexdigest()
    return selected


def reload_memory():
    """A second interpreter establishes retrieval without conversation state."""
    from sce.knowledge.store import KnowledgeStore
    identifiers = json.loads(Path("/workspace/knowledge_ids.json").read_text())
    store = KnowledgeStore("/workspace/engineering.sqlite3")
    records = [store.get(identifier) for identifier in identifiers]
    assert len(records) == 2
    assert all(record.task_ids == ["offline-synthesis-verification"] for record in records)
    assert records[-1].metadata["operation"]["verification"] == "passed"
    from sce.core.config import Config
    from sce.storage import TaskStore
    pipeline = json.loads(Path("/workspace/spider_result.json").read_text())
    database = Config.default(Path("/workspace/spider")).storage["TASK_DATABASE"]
    task = TaskStore(database).get_task(pipeline["task"]["id"])
    assert task.status.value == "completed"
    operations = TaskStore(database).operations_for_task(task.id)
    assert len(operations) == 6 and operations[-1].verification.value == "passed"
    # Whole evidence-bearing records may exceed a small context budget; direct
    # durable identity retrieval remains available independently of retrieval size.
    result = {"status": "passed", "record_ids": [record.id for record in records],
              "spider_task_id": task.id, "spider_operation_count": len(operations),
              "new_interpreter_pid": __import__("os").getpid()}
    write_json("/workspace/reloaded_memory.json", result)
    print(json.dumps(result))


def inside_container():
    from sce.builders.python import PythonBuildAdapter
    from sce.core.models import jsonable
    from sce.knowledge.store import KnowledgeStore
    from sce.synthesis import PythonSynthesisAdapter

    root = Path("/repo")
    work = Path("/workspace")
    before = source_hashes(root)
    write_json(work / "source-before.json", before)
    network = {"interfaces": sorted(path.name for path in Path("/sys/class/net").iterdir()),
               "ipv4_routes": Path("/proc/net/route").read_text(),
               "ipv6_routes": Path("/proc/net/ipv6_route").read_text(),
               "probe_target": "1.1.1.1:443"}
    assert network["interfaces"] == ["lo"], network["interfaces"]
    assert not any(line.split()[1] == "00000000" for line in network["ipv4_routes"].splitlines()[1:] if line.strip())
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(2)
        try:
            probe.connect(("1.1.1.1", 443))
        except OSError as exc:
            network["external_connection"] = {"status": "blocked", "error": str(exc), "errno": exc.errno}
        else:
            raise AssertionError("External numeric-address connection unexpectedly succeeded")
    write_json(work / "network.json", network)

    fixture = json.loads((root / "examples/components/csv_report_request.json").read_text())
    sources = [root / "examples/components/csv_summary", root / "examples/components/summary_report"]
    synthesis = PythonSynthesisAdapter()
    plan = synthesis.prepare(sources, work / "application_source", name="offline-csv-report",
                             input_data=fixture["input"], expected_output=fixture["expected_output"],
                             trusted=True, task_id="offline-synthesis-verification")
    creation = synthesis.verify(plan, synthesis.execute(plan))
    write_json(work / "synthesis.json", jsonable(creation))
    assert creation.outcome.value == "succeeded", creation.evidence
    assert creation.verification.value == "passed", creation.evidence
    builder = PythonBuildAdapter()
    build_plan = builder.prepare(plan.workspace, work / "artifacts", trusted=True, task_id=plan.task_id)
    built = builder.verify(build_plan, builder.execute(build_plan))
    write_json(work / "build.json", jsonable(built))
    assert built.outcome.value == "succeeded", built.evidence
    assert built.verification.value == "passed", built.evidence

    store = KnowledgeStore(work / "engineering.sqlite3")
    records = [store.record_operation(operation, resource_id="sce:offline-csv-report",
                                     environment={"python": sys.version, "platform": platform.platform(),
                                                  "network": "Docker network namespace: none"})
               for operation in (creation, built)]
    write_json(work / "knowledge_ids.json", [record.id for record in records])
    from sce.core.config import Config
    from sce.spider import SpiderEngine
    engine = SpiderEngine(Config.default(work / "spider"))
    product_plan = engine.prepare("Discover the local CSV components and create a useful reporting application",
                                  [str(source) for source in sources], name="spider-offline-report",
                                  input_data=fixture["input"], expected_output=fixture["expected_output"], trusted=True)
    product = engine.run(product_plan)
    write_json(work / "spider_result.json", product)
    assert product["functional_application_created"] is True, product
    reloaded = subprocess.run([sys.executable, "/repo/scripts/verify_offline.py", "--reload-memory"],
                              capture_output=True, text=True, timeout=20, check=True)
    after = source_hashes(root)
    write_json(work / "source-after.json", after)
    assert before == after, "Read-only source inventory changed during disconnected verification"
    receipt = {"status": "passed", "network": network, "python": sys.version,
               "platform": platform.platform(), "synthesis_operation_id": creation.id,
               "build_operation_id": built.id, "functional_verification": built.verification.value,
               "persistent_memory_second_process": json.loads(reloaded.stdout),
               "artifacts": built.produced,
               "spider_task_id": product["task"]["id"],
               "source_hashes_unchanged": before == after,
               "scope": "Local discovery, acquisition, analysis, callable synthesis, Python zipapp build, declared fixture, SQLite persistence; no AI or online discovery"}
    write_json(work / "offline-results.json", receipt)
    print(json.dumps(receipt, indent=2))


def command(args, *, timeout=30, check=True):
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {args!r}\n{result.stderr.strip()}")
    return result


def host(image, transport):
    root = Path(__file__).resolve().parents[1]
    output_base = (root / ".sce" / "offline").resolve()
    # The host owns only this newly created run and its disposable container.
    output = output_base / str(uuid4())
    if root not in output.parents:
        raise ValueError("Offline evidence must remain inside this repository")
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"status": "failed", "started_at": datetime.now(timezone.utc).isoformat(),
               "evidence_directory": str(output), "requested_image": image,
               "storage_transport": transport,
               "network_mode": "none", "limitations": [
                   "This verifies selected local engineering operations in a disconnected Linux container, not every SCE capability.",
                   "Local Qwen inference and host Windows builds are not exercised by this container test.",
                   "Dependencies/toolchain must already be available; the harness never pulls an image or installs software."]}
    container_id = None
    staging_container = None
    temporary_volumes = []
    exit_code = 1
    try:
        image_record = json.loads(command(["docker", "image", "inspect", image]).stdout)[0]
        receipt["image_id"] = image_record["Id"]
        receipt["image_repo_digests"] = image_record.get("RepoDigests", [])
        receipt["docker_server"] = json.loads(command(["docker", "version", "--format", "{{json .Server}}"]).stdout)
        receipt["source_files"] = source_hashes(root)
        if transport == "volume":
            # Explicit opt-in for hosts whose selected drive is not bind-shareable.
            # Only bounded selected source is staged; no automatic fallback occurs.
            archive = io.BytesIO()
            total_bytes = 0
            with tarfile.open(fileobj=archive, mode="w") as bundle:
                for relative in sorted(receipt["source_files"]):
                    path = root / relative
                    total_bytes += path.stat().st_size
                    if total_bytes > 20_000_000:
                        raise ValueError("Offline source staging exceeds the explicit 20 MB ceiling")
                    bundle.add(path, arcname=relative, recursive=False)
            for suffix in ("source", "output"):
                volume = f"sce-offline-{output.name}-{suffix}"
                command(["docker", "volume", "create", volume])
                temporary_volumes.append(volume)
            receipt["temporary_storage"] = {
                "provider": "Docker-managed named volumes (explicit --transport volume)",
                "volumes": temporary_volumes, "source_bytes": total_bytes,
                "source_limit_bytes": 20_000_000, "final_evidence_destination": str(output),
                "output_limit": "Controlled fixture only; Docker volume has no hard filesystem quota",
            }
            source_mount = f"type=volume,source={temporary_volumes[0]},target=/repo,readonly"
            output_mount = f"type=volume,source={temporary_volumes[1]},target=/workspace"
            staging_container = command([
                "docker", "create", "--interactive", "--network", "none", "--pull", "never",
                "--memory", "512m", "--cpus", "1", "--pids-limit", "128", "--read-only",
                "--mount", f"type=volume,source={temporary_volumes[0]},target=/repo",
                receipt["image_id"], "python", "-c",
                "import sys,tarfile; tarfile.open(fileobj=sys.stdin.buffer,mode='r|').extractall('/repo',filter='data')",
            ]).stdout.strip()
            copied = subprocess.run(["docker", "start", "--attach", "--interactive", staging_container],
                                    input=archive.getvalue(), capture_output=True, timeout=30)
            if copied.returncode:
                raise RuntimeError("Source staging failed: " + copied.stderr.decode("utf-8", errors="replace"))
        else:
            source_mount = f"type=bind,source={root},target=/repo,readonly"
            output_mount = f"type=bind,source={output},target=/workspace"
        created = command([
            "docker", "create", "--name", f"sce-offline-{output.name}", "--pull", "never",
            "--network", "none", "--cpus", "1", "--memory", "512m", "--pids-limit", "128",
            "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--mount", source_mount,
            "--mount", output_mount,
            "--env", "PYTHONPATH=/repo/src", "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--workdir", "/workspace", receipt["image_id"],
            "python", "/repo/scripts/verify_offline.py", "--inside",
        ])
        container_id = created.stdout.strip()
        receipt["container_id"] = container_id
        inspected = json.loads(command(["docker", "inspect", container_id]).stdout)[0]
        settings = inspected["HostConfig"]
        assert settings["NetworkMode"] == "none"
        assert settings["Memory"] == 512 * 1024 * 1024
        assert settings["NanoCpus"] == 1_000_000_000
        assert settings["PidsLimit"] == 128
        assert settings["ReadonlyRootfs"] is True
        mounts = {mount["Destination"]: mount for mount in inspected["Mounts"]}
        assert mounts["/repo"]["RW"] is False and mounts["/workspace"]["RW"] is True
        receipt["verified_before_start"] = {
            "network_mode": settings["NetworkMode"], "memory_bytes": settings["Memory"],
            "nano_cpus": settings["NanoCpus"], "pids_limit": settings["PidsLimit"],
            "readonly_rootfs": settings["ReadonlyRootfs"], "mounts": inspected["Mounts"],
            "image_id": inspected["Image"],
        }
        write_json(output / "docker-before-start.json", receipt["verified_before_start"])
        write_json(output / "receipt.json", receipt)
        execution = command(["docker", "start", "--attach", container_id], timeout=120, check=False)
        (output / "container.stdout.txt").write_text(execution.stdout, encoding="utf-8")
        (output / "container.stderr.txt").write_text(execution.stderr, encoding="utf-8")
        state = json.loads(command(["docker", "inspect", "--format", "{{json .State}}", container_id]).stdout)
        receipt["container_state"] = state
        receipt["docker_attach_exit_code"] = execution.returncode
        if transport == "volume":
            command(["docker", "cp", f"{container_id}:/workspace/.", str(output)], timeout=30)
        if execution.returncode != 0 or state["ExitCode"] != 0:
            raise RuntimeError(f"Disconnected verification failed: {execution.stderr.strip()}")
        receipt["inside"] = json.loads((output / "offline-results.json").read_text(encoding="utf-8"))
        assert receipt["inside"]["status"] == "passed"
        receipt["status"] = "passed"
        exit_code = 0
    except (OSError, ValueError, KeyError, AssertionError, RuntimeError, subprocess.TimeoutExpired) as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if container_id:
            try:
                removed = command(["docker", "rm", "--force", container_id], check=False)
                receipt["disposable_container_removed"] = removed.returncode == 0
                if removed.returncode:
                    receipt["cleanup_error"] = removed.stderr
            except (OSError, subprocess.TimeoutExpired) as exc:
                receipt["cleanup_error"] = str(exc)
        if staging_container:
            try:
                result = command(["docker", "rm", "--force", staging_container], check=False)
                receipt["staging_container_removed"] = result.returncode == 0
            except (OSError, subprocess.TimeoutExpired) as exc:
                receipt["staging_cleanup_error"] = str(exc)
        receipt["temporary_volumes_removed"] = []
        for volume in temporary_volumes:
            try:
                result = command(["docker", "volume", "rm", volume], check=False)
                receipt["temporary_volumes_removed"].append({"name": volume, "removed": result.returncode == 0})
            except (OSError, subprocess.TimeoutExpired) as exc:
                receipt["temporary_volumes_removed"].append({"name": volume, "removed": False, "error": str(exc)})
        if (receipt.get("disposable_container_removed") is False
                or receipt.get("staging_container_removed") is False
                or receipt.get("cleanup_error") or receipt.get("staging_cleanup_error")
                or any(not item["removed"] for item in receipt["temporary_volumes_removed"])):
            receipt["status"] = "failed"
            receipt["error"] = "Disposable Docker test resources were not fully removed; inspect cleanup evidence"
            exit_code = 1
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(output / "receipt.json", receipt)
    print(json.dumps({"status": receipt["status"], "evidence_directory": str(output),
                      "image_id": receipt.get("image_id"), "network_mode": "none",
                      "error": receipt.get("error")}, indent=2))
    return exit_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="python:3.14-slim", help="already cached Python 3.11+ Linux image")
    parser.add_argument("--transport", choices=("bind", "volume"), default="bind",
                        help="bind selected project drive, or explicitly stage bounded source/evidence in temporary Docker volumes")
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--reload-memory", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.reload_memory:
        reload_memory()
        return 0
    if args.inside:
        inside_container()
        return 0
    return host(args.image, args.transport)


if __name__ == "__main__":
    raise SystemExit(main())
