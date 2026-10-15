# Controlled build experiments

The initial controlled experiment ran on 2026-10-15 with the project virtual
environment, Python 3.14.7, Windows AMD64. All five expected behaviors matched.
These results qualify the checked-in fixture set, not arbitrary Python projects.

| Fixture | Expected and observed outcome | Expected and observed verification | What it establishes |
| --- | --- | --- | --- |
| success | succeeded | passed | Archive creation, artifact hash, declared stdout and exit |
| missing_dependency | failed | not_run | Missing declared module blocks execution; nothing installed |
| unsupported | unsupported | not_run | Missing controlled manifest is handled truthfully |
| failed_verification | succeeded | failed | Packaging success and zero exit do not imply correct output |
| timeout | partial | inconclusive | A timed-out check preserves the packaged artifact and uncertainty |

The initial automated builder suite passed 19 test cases with zero failures.
A subsequent output-budget regression brought the builder suite to 20 passing
cases; the combined builder and local-resource suites passed 33 cases.
The suite also checks read-only preparation, separate execution/verification,
source and artifact mutation detection, explicit trust, output isolation,
existing artifact preservation, cancellation, source size limits, and malformed
manifest rejection. The repository-wide acceptance report is authoritative for
the final suite count after other components are integrated.

## Reproduction

From the repository in PowerShell 7, after installing the package and dev tools:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_builder.py -q
& .\.venv\Scripts\python.exe .\scripts\run_experiments.py
```

The experiment script uses only the checked-in fixtures. It creates a new
directory under `.sce/experiments/<unique-id>` and returns its path. Supply
`--output <fresh-directory>` to choose another explicit destination; an existing
destination is refused. Each fixture has a full canonical JSON operation record,
including source hashes, produced artifact identity, execution/verification
evidence, errors, and unknowns. `summary.json` compares expected and actual
states. Expected negative cases count as successful experiment assertions.

Initial local evidence directory:
`.sce/experiments/foundation-builder-initial`. It is generated runtime data and
is intentionally excluded from Git. The initial operation IDs were:

| Fixture | Operation ID |
| --- | --- |
| success | 9c2256d6-d21f-430f-bb48-50ec1e05bccd |
| missing_dependency | c583a7fb-77c3-4d0f-8085-f8ac19c9d71d |
| unsupported | 3675d675-5927-45db-aae3-ec6e2a637b67 |
| failed_verification | 13e7795d-e09e-493a-ac90-e3e5d704621b |
| timeout | adb9249b-79c1-41ad-a8b2-5e029f79d851 |

No installation, arbitrary downloaded project, .NET build, native executable,
GPU inference, or Qwen response was qualified by these experiments. No baseline
human active time was measured, so human time recovered remains unknown.
