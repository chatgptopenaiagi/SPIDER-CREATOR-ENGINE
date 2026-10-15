# Adapter contract

SCE adapters expose five explicit stages. The Python protocol is in
`src/sce/adapters/base.py`; the first implementation is `PythonBuildAdapter`.

| Stage | Responsibility | Python foundation behavior |
| --- | --- | --- |
| DESCRIBE | State operations, input/output contracts, requirements, limitations | Returns the `python.build` descriptor |
| PREPARE | Validate inputs and create a plan without executing the operation | Reads the manifest, checks declared module availability, hashes source files, records errors; writes nothing |
| EXECUTE | Perform the prepared operation within established authority | Rechecks source hashes, stages exact source files, creates a `.pyz` archive in an explicit output directory |
| VERIFY | Run the declared check separately | Rechecks artifact identity, runs the trusted archive with the current Python interpreter, compares exact stdout and exit code |
| REPORT | Return the canonical operation record | Returns requested, planned, executed, produced, evidence, unknowns, outcome, and verification fields |

The registry descriptor is an implementation declaration. Verification evidence
belongs to actual tests and operation records; describing an operation does not
prove it works for an arbitrary project.

## Controlled Python input

V0.1 supports `BUILD_ORIGINAL_PROJECT` for a small explicit `sce.zipapp.v1`
contract. It reports `CREATE_NEW_APPLICATION_USING_PROJECT` as unsupported.
It does not interpret arbitrary project build scripts or install dependencies.

```json
{
  "format": "sce.zipapp.v1",
  "name": "hello-sce",
  "entry_point": "main:main",
  "required_modules": [],
  "verification": {
    "args": ["Ada"],
    "expected_stdout": "Hello, Ada. Human time matters.\n",
    "expected_exit": 0
  }
}
```

The manifest must be named `sce-build.json` in the source directory. Extra
fields are rejected. The name is a safe filename and the entry point is a
module/function reference. A source `__main__.py` conflicts with this declared
entry point and is rejected. Required modules are top-level import names;
availability checks neither import them nor establish compatible versions.
Verification arguments are passed as an argument list with `shell=False`.
Stdout comparison uses UTF-8 text with replacement for invalid bytes and CRLF
normalized to LF, matching the declared text contract across Windows fixtures.

The build uses the standard library's
[zipapp archive implementation](https://docs.python.org/3.14/library/zipapp.html).
Its `.pyz` output requires a suitable Python interpreter; it is not a native
Windows executable. Native extension packaging, wheel construction, dependency
resolution, installers, .NET builds, and general repository compatibility remain
outside the verified foundation.

## Authority and filesystem rules

Building and running source requires explicit `trusted=True` authority from the
task or CLI. The default is false. Model-generated content cannot supply this
authority through the manifest. This flag expresses a caller decision; it is
not a security boundary against malicious host Python code.

Source and output directories are separate. PREPARE records relative filenames,
sizes, and SHA-256 hashes; EXECUTE compares source and staged files against that
snapshot. Detected changes require a new plan. Links within the source are
rejected. Existing artifacts are never overwritten. The output volume is never
silently changed. Staging directories are removed after the attempt; an artifact
created before an interrupted verification remains recorded for diagnosis.

EXECUTE packages source without running it. VERIFY executes trusted source with
the current Python interpreter in isolated interpreter mode (`-I`). This mode
does not sandbox filesystem, network, or process access. The timeout and
cancellation mechanism stop the immediate verification process. File-backed
stdout/stderr capture bounds saved output evidence to 1 MB per stream and stops
the direct process when a combined 1 MB output threshold is observed; this
periodic check is not a hard disk quota. Process-tree
containment and hard RAM/GPU quotas are not implemented. Checks are qualified
only for controlled fixtures without spawned child processes or large output.

## Outcome and verification

| Situation | Operation outcome | Verification status |
| --- | --- | --- |
| Archive created, verification not requested yet | succeeded | not_run |
| Archive created, declared output and exit match | succeeded | passed |
| Archive created, exit zero but output differs | succeeded | failed |
| Required dependency is absent | failed | not_run |
| Unsupported project/operation | unsupported | not_run |
| Cancellation before packaging | cancelled | not_run |
| Archive exists, verification times out or is cancelled | partial | inconclusive |

A zero exit code establishes neither functionality nor installation. A passed
declared check establishes only that particular check in its recorded runtime.
Packaging never triggers installation. Installation is neither performed nor
verified by this adapter. A missing or changed artifact fails verification
before project code can run.

## Python usage

```python
from pathlib import Path
from sce.builders import PythonBuildAdapter

adapter = PythonBuildAdapter(timeout_seconds=10)
plan = adapter.prepare(
    Path("examples/fixtures/success"), Path(".sce/example-output"), trusted=True
)
record = adapter.execute(plan)
record = adapter.verify(plan, record)
canonical = adapter.report(record)
```

Use a fresh output directory for each new attempt. A caller can inspect
`plan.ready`, `plan.validation_errors`, and `plan.unsupported` before EXECUTE.
Expected validation failures return canonical records instead of triggering
an implicit dependency installation or speculative repair.
