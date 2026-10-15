# SCE FOUNDATION V0.1 — acceptance

The local foundation acceptance run passed on **2026-10-15**, Windows 10 AMD64,
PowerShell 7.6.6, Python 3.14.7. The private repository is
[chatgptopenaiagi/SPIDER-CREATOR-ENGINE](https://github.com/chatgptopenaiagi/SPIDER-CREATOR-ENGINE),
with independent workspace `I:\SPIDER-CREATOR-ENGINE`.

The tested implementation revision is `5ebb900` (full hash in the receipt). The
subsequent evidence/documentation commit does not change the tested source. Obtain
the current delivery commit with `git rev-parse HEAD`; do not confuse a report's
source revision with an inferred future commit hash.

## Results

| Acceptance item | Actual result |
| --- | --- |
| Repository structure | Package, CLI, adapters, tests, fixtures, configuration, scripts, required technical documents |
| Automated tests | **148 passed; 0 failed; 0 errors; 0 skipped** |
| Python package | Editable installation and newly built wheel installed into a fresh local virtual environment |
| Wheel import | `-I` import resolved inside fresh environment's `site-packages`, independent of source layout |
| CLI | Installed executable reported `SCE 0.1.0` and returned capability contracts |
| Task serialization and capability registration | Regression tests passed, including malformed scope rejection |
| Adapter contract | Read-only preparation, explicit execution, independent verification, canonical reporting tested |
| Orchestrated task | Installed wheel completed the explicit controlled fixture task with persisted evidence |
| Canonical reports | JSON round-trip and Markdown/HTML generation passed; HTML source text escaped |
| Controlled build matrix | **5 of 5 expected outcomes matched**, including negative cases |
| Dependency consistency | `pip check` passed in both development and clean installation environments |
| Local AI availability | Configured `qwen3-coder-local` model appeared in live model listing |
| Live AI proposal | **Unsuccessful:** single request timed out after 30.314 seconds; compatibility remains unverified |
| Human time recovered | **Unknown:** no baseline or assisted human active time was measured |

The automated test count does not hide the live AI timeout. Controlled HTTP fixtures
verify the adapter protocol and rejection behavior; they do not prove that the
currently running Qwen service can complete this request within its configured bound.

## Evidence

- [Canonical acceptance receipt](evidence/acceptance.json): every command, exit code,
  timestamps, full tested commit, source SHA-256 manifest, wheel hash, task and operation IDs.
- [JUnit test results](evidence/pytest.xml) and [test output](evidence/tests.stdout.txt).
- [Controlled experiment summary](evidence/experiments/summary.json) and adjacent
  canonical records for success, missing dependency, unsupported input, failed
  verification, and timeout with partial artifacts.
- Installed operation rendered as [JSON](evidence/installed-operation.json),
  [Markdown](evidence/installed-operation.md), and [HTML](evidence/installed-operation.html).
- [Environment observation](evidence/environment.json), [Windows hardware observation](evidence/windows-hardware.json),
  and [development package versions](evidence/development-packages.json).
- [Live local AI receipt](evidence/local-ai-smoke.json), including the exact timeout.
- [Unresolved AI failure capsule](evidence/local-ai-failure-capsule.json), persisted
  and retrieved through the local knowledge store with original receipt provenance.

Full local logs, installed environment, built wheel, databases, and artifacts remain
under `.sce/acceptance/foundation-v0.1-final`. A copy of the accepted wheel is in `dist`.
These generated environments/artifacts are ignored by Git; curated receipts are versioned.
The final collector excludes generated package metadata from source fingerprints and
checks that all recorded source inputs remain unchanged through the complete run.
Evidence files are stored without Git line-ending normalization so their original
bytes and provenance digests remain consistent.

Reproduce acceptance with `python scripts/run_acceptance.py` from the installed
development environment. It chooses a fresh output directory, builds and installs a
new wheel, and makes no live AI request or GitHub write. The installed CLI build
uses only the reviewed fixture source.

## Implemented and proposed components

Implemented: Python package/CLI, strict TOML storage configuration, task and timing
models, sequential DAG orchestration, SQLite checkpoints, cancellation/recovery,
capability registry, adapter interfaces, provenance-bearing knowledge and failure
capsules, local discovery/acquisition/static analysis, controlled Python packaging
and functional verification, canonical reports, bounded local AI provider and
proposal validation, environment observation, tests, and technical documentation.

Proposed: .NET adapter, general Python project support, external discovery/download
connectors, synthesis bridges, automated repair, installation/installation verification,
UIB/UIE integration, concurrent scheduling, OS resource quotas, and the complete
approved-plan-to-execution-to-model-interpretation loop.

## Unresolved issues and next milestone

- Live Qwen proposal timeout cause is unknown; no model reconfiguration or retry occurred.
- Python compatibility is qualified only for the controlled fixtures. Python 3.11+
  is the declared package requirement; this acceptance run used Python 3.14.7 only.
- RAM/GPU/aggregate temporary storage limits are advisory. Verification is not a
  sandbox and does not contain arbitrary descendant process trees.
- One runner owns a task at a time. Multi-process leases and schema migrations are future work.
- No UIB/UIE component, installation workflow, or recovered-human-time claim was verified.

Next engineering milestone: **v0.2 scoped planning and .NET qualification**, with
immutable approved input scopes, recorded proposals, controlled .NET fixtures,
checkpoint ownership/reconciliation, and an evidence-backed active-time study.
See the [roadmap](ROADMAP.md) for exit criteria.
