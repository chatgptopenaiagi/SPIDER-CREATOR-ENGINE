"""Run only repository-controlled fixtures and preserve canonical evidence."""

import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4

from sce.builders import PythonBuildAdapter
from sce.core.models import jsonable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="fresh evidence/output directory")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    destination = (args.output or root / ".sce" / "experiments" / str(uuid4())).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    expected = {
        "success": ("succeeded", "passed"),
        "missing_dependency": ("failed", "not_run"),
        "unsupported": ("unsupported", "not_run"),
        "failed_verification": ("succeeded", "failed"),
        "timeout": ("partial", "inconclusive"),
    }
    observed = []
    for name, statuses in expected.items():
        adapter = PythonBuildAdapter(timeout_seconds=0.2 if name == "timeout" else 10)
        plan = adapter.prepare(root / "examples" / "fixtures" / name, destination / name, trusted=True)
        record = adapter.verify(plan, adapter.execute(plan))
        data = jsonable(adapter.report(record))
        (destination / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        actual = (data["outcome"], data["verification"])
        observed.append({"fixture": name, "expected": list(statuses), "actual": list(actual), "passed": actual == statuses, "operation_id": record.id})
    summary = {"python": sys.version, "executable": sys.executable, "evidence_root": str(destination), "experiments": observed}
    (destination / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if all(result["passed"] for result in observed) else 1


if __name__ == "__main__":
    raise SystemExit(main())
