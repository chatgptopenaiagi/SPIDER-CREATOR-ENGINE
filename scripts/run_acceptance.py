"""Reproduce local foundation acceptance and keep command logs and source hashes.

Uses the calling development environment, then installs a newly built wheel into
a fresh local virtual environment. No live AI request or GitHub write is made.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
import xml.etree.ElementTree as ET


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Fresh acceptance evidence directory")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = (args.output or root / ".sce" / "acceptance" / str(uuid4())).resolve()
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"started_at": datetime.now(timezone.utc).isoformat(), "checks": [], "passed": False}

    def run(name, command, *, cwd=root, timeout=180):
        started = datetime.now(timezone.utc).isoformat()
        result = subprocess.run([str(item) for item in command], cwd=cwd, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=timeout)
        (output / f"{name}.stdout.txt").write_text(result.stdout, encoding="utf-8")
        (output / f"{name}.stderr.txt").write_text(result.stderr, encoding="utf-8")
        receipt["checks"].append({"name": name, "command": [str(item) for item in command],
                                  "cwd": str(cwd), "started_at": started, "exit_code": result.returncode})
        if result.returncode:
            raise RuntimeError(f"{name} failed with exit {result.returncode}; see preserved command logs")
        return result.stdout

    try:
        receipt["tested_commit"] = run("tested-commit", ["git", "rev-parse", "HEAD"]).strip()
        receipt["working_tree_at_start"] = run("working-tree", ["git", "status", "--porcelain"]).splitlines()
        selected = [root / "pyproject.toml"]
        for directory in ("src", "tests", "examples", "scripts", "config"):
            selected.extend(path for path in (root / directory).rglob("*") if path.is_file()
                            and "__pycache__" not in path.parts
                            and not any(part.endswith(".egg-info") for part in path.parts)
                            and path.suffix in {".py", ".json", ".toml", ".ps1", ".txt"}
                            and path.name != "local.toml")
        receipt["source_sha256"] = {str(path.relative_to(root)).replace("\\", "/"):
                                    hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(selected)}
        run("tests", [sys.executable, "-m", "pytest", "-q", f"--junitxml={output / 'pytest.xml'}"])
        suite = ET.parse(output / "pytest.xml").getroot().find("testsuite")
        receipt["tests"] = {key: int(suite.get(key, "0")) for key in ("tests", "failures", "errors", "skipped")}
        run("dependencies", [sys.executable, "-m", "pip", "check"])
        run("wheel-build", [sys.executable, "-m", "build", "--wheel", "--outdir", output / "dist"])
        wheel, = (output / "dist").glob("*.whl")
        receipt["wheel"] = {"filename": wheel.name, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}
        install = output / "installed"
        run("create-install-environment", [sys.executable, "-m", "venv", install])
        python = install / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        executable = install / ("Scripts/sce.exe" if sys.platform == "win32" else "bin/sce")
        run("wheel-install", [python, "-m", "pip", "install", "--no-index", "--no-deps", wheel])
        receipt["installed_module"] = run("isolated-import", [python, "-I", "-c", "import sce; print(sce.__file__)"], cwd=output).strip()
        if not Path(receipt["installed_module"]).resolve().is_relative_to(install):
            raise RuntimeError("Package import did not come from the clean wheel installation")
        run("installed-dependencies", [python, "-m", "pip", "check"], cwd=output)
        receipt["cli_version"] = run("cli-version", [executable, "--version"], cwd=output).strip()
        capabilities = json.loads(run("capabilities", [executable, "capabilities"], cwd=output))
        if not any(item["id"] == "python.build" and item["implementation_status"] == "implemented" for item in capabilities):
            raise RuntimeError("Installed capability registry is incomplete")
        record = json.loads(run("installed-build", [executable, "build", root / "examples/fixtures/success",
                                                    "--output", output / "build-output", "--trust-source", "--verify"], cwd=output))
        if (record["outcome"], record["verification"]) != ("succeeded", "passed"):
            raise RuntimeError("Installed functional build did not pass")
        receipt["installed_build_operation"] = record["id"]
        for format, extension in (("json", "json"), ("markdown", "md"), ("html", "html")):
            run(f"report-{format}", [executable, "report", record["id"], "--format", format,
                                     "--output", output / f"installed-operation.{extension}"], cwd=output)
        task = json.loads((root / "examples/task.json").read_text(encoding="utf-8"))
        task["steps"][0]["inputs"].update(source=str(root / "examples/fixtures/success"), output_root=str(output / "task-output"))
        task_file = output / "task.json"
        task_file.write_text(json.dumps(task, indent=2), encoding="utf-8")
        task_result = json.loads(run("installed-task", [executable, "task", "run", task_file, "--trust-source"], cwd=output))
        if task_result["status"] != "completed":
            raise RuntimeError("Installed task graph did not complete")
        receipt["completed_task_id"] = task_result["id"]
        discovery = json.loads(run("installed-discovery", [executable, "discover", root / "examples/components/csv_summary"], cwd=output))
        if not discovery["discovery"]["projects"]:
            raise RuntimeError("Installed Spider did not retain structured source observations")
        creation = json.loads(run("installed-creation", [executable, "spider", "create",
            "Create a useful CSV summary report from inspected local components",
            "--component", root / "examples/components/csv_summary",
            "--component", root / "examples/components/summary_report",
            "--acceptance", root / "examples/components/csv_report_request.json",
            "--name", "acceptance-csv-report", "--trust-source"], cwd=output))
        if not creation["functional_application_created"] or len(creation["operation_ids"]) != 6:
            raise RuntimeError("Installed Spider creation did not complete its six engineering stages")
        receipt["created_application"] = creation
        application = creation["artifacts"][0]["path"]
        # Independent holdout data was not supplied to the synthesis acceptance plan.
        holdout = {"csv_text": "city,value\nVienna,1\nParis,2\nVienna,3\n"}
        expected = {"row_count": 3, "column_count": 2, "columns": ["city", "value"],
            "distinct_values": {"city": 2, "value": 3},
            "report": "Rows: 3\nColumns: 2\ncity: 2 distinct values\nvalue: 3 distinct values"}
        actual = json.loads(run("application-holdout", [python, "-I", "-B", application,
            "--input-json", json.dumps(holdout)], cwd=output))
        if actual != expected:
            raise RuntimeError("Independent application holdout output differs from expected result")
        receipt["holdout"] = {"input": holdout, "expected": expected, "actual": actual, "passed": True}
        for level in (1, 2, 3):
            run(f"creation-trace-{level}", [executable, "trace", creation["task"]["id"], "--level", level], cwd=output)
        memory = json.loads(run("creation-memory", [executable, "memory", creation["task"]["id"]], cwd=output))
        if not memory:
            raise RuntimeError("Created application evidence did not persist into another CLI process")
        resumed = json.loads(run("creation-resume", [executable, "spider", "resume", creation["task"]["id"], "--trust-source"], cwd=output))
        if resumed["operation_ids"] != creation["operation_ids"]:
            raise RuntimeError("Resume repeated completed engineering operations")
        run("experiments", [sys.executable, root / "scripts/run_experiments.py", "--output", output / "experiments"])
        receipt["experiments"] = json.loads((output / "experiments/summary.json").read_text())["experiments"]
        changed = [name for name, digest in receipt["source_sha256"].items()
                   if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest]
        receipt["source_tree_unchanged"] = not changed
        if changed:
            raise RuntimeError(f"Source inputs changed during acceptance: {changed}")
        receipt["passed"] = True
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        receipt["failure"] = f"{type(error).__name__}: {error}"
    finally:
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        (output / "acceptance.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"passed": receipt["passed"], "receipt": str(output / "acceptance.json"),
                          "tests": receipt.get("tests"), "failure": receipt.get("failure")}, indent=2))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
