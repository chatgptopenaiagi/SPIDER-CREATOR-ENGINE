# SCE v0.2 — the Spider discovers and creates

The Windows acceptance run passed on **2026-10-15** against implementation commit
`b596bca`. This is an evolution of the existing repository and its v0.1 foundation,
not a replacement repository. The public project is
[chatgptopenaiagi/SPIDER-CREATOR-ENGINE](https://github.com/chatgptopenaiagi/SPIDER-CREATOR-ENGINE).

The [canonical receipt](evidence/v0.2/acceptance.json) records the full source
commit, per-file SHA-256 values, commands, test results, wheel identity, installed
module location, original objective, generated application and its operation IDs.
Later documentation/evidence commits do not change this tested implementation.

## Observed results

| Check | Actual result |
| --- | --- |
| Automated tests | **321 passed; 0 failures; 0 errors; 0 skipped** |
| Package | SCE 0.2.0 wheel built and installed with `--no-index --no-deps` into a fresh virtual environment |
| Isolated import and CLI | Import came from the fresh installation; installed `sce` reported 0.2.0 |
| Existing behavior | Original five controlled build experiments matched expected success, missing dependency, unsupported input, failed verification and partial timeout outcomes |
| New application | Installed CLI discovered, acquired and analyzed two local components, connected them, built a CSV-report archive and independently checked its output |
| Additional input | A different city/value CSV holdout produced its independently expected result |
| Continuity | Another CLI process retrieved memory and all trace levels; resume retained the same six operation IDs without repeating completed work |
| Offline execution | Real Docker `NetworkMode=none`, only loopback, external socket failure; six-stage creation and second-process database reload passed |
| Public GitHub discovery | Inspected `pypa/sampleproject` at commit `621e4974ca25ce531773def586ba3ed8e736b3fc`, with bounded structured source/document observations |
| Local AI generation | First QASC call timed out after 240.53 seconds; one retry with a 600-second deadline generated source in 135.23 seconds |
| Generated application | Two generated unit tests and all three independent exact-output acceptance cases passed; three additional holdout/error cases passed |
| AI interpretation | Structured response received and stored as AI inference; one incorrect denial of runtime execution was retained with an attributable contradictory record |
| Human time recovered | **UNKNOWN** — no equivalent-outcome human baseline or active-time measurement exists |

The Python environment was 3.14.7 on Windows; the disconnected container used
Python 3.14.8 on Linux. Python 3.11+ is the package requirement, not a claim that
all supported versions and operating systems have been qualified.

## Inspect the application journey

The CSV application connects the checked-in CSV analysis component to the report
formatting component through isolated namespaces and a thin JSON bridge. Its
source trees are retained separately. The human-selected objective, interfaces
and expected output remain the authority for the task.

- [Summary trace](evidence/v0.2/creation-trace-1.stdout.txt): what happened.
- [Decision trace](evidence/v0.2/creation-trace-2.stdout.txt): the chosen route and scope.
- [Evidence trace](evidence/v0.2/creation-trace-3.stdout.txt): observations, revisions, hashes and verification.
- [Persisted knowledge](evidence/v0.2/creation-memory.stdout.txt): retrieved in another process.
- [Independent CSV holdout output](evidence/v0.2/application-holdout.stdout.txt).
- [JUnit results](evidence/v0.2/pytest.xml) and [test output](evidence/v0.2/tests.stdout.txt).
- [Original build matrix rerun](evidence/v0.2/experiments/summary.json).
- Canonical operation rendered as [JSON](evidence/v0.2/installed-operation.json),
  [Markdown](evidence/v0.2/installed-operation.md) and [HTML](evidence/v0.2/installed-operation.html).

Package-integrity verification and application-functional verification are
separate operations. Source changes between preparation, discovery, acquisition,
synthesis, build and verification are rejected where recorded snapshots apply.
Resume reports current artifact integrity separately from historical completion;
it does not overwrite a changed artifact or silently repeat a finished task.

The negative tests retain incorrect-output results, missing runtime resources,
partial construction, changed source/acceptance, missing dependencies and
contradictory knowledge. A failure capsule preserves a problem; it does not mark
that problem repaired.

## Local AI experiment

SCE used the existing installed QASC 0.1.0 interpreter through its inspected CLI,
with model `qwen3-coder-local` at `http://127.0.0.1:8080`. Source generation and
verification were separate calls. QASC and LocalAI source, environments and server
configuration were not changed. All generated project/control paths were inside
SCE's explicitly selected build workspace.

The [first timeout](evidence/v0.2/qasc-timeout.json) remains preserved. A server
observation showed active inference work during that interval, but the precise
cause of the timeout was not established. The bounded retry used a shorter request,
a 1,200-token output budget and a 600-second deadline. It did not automatically
repair or overwrite the first attempt.

The [generation and verification record](evidence/v0.2/qasc-creation.json),
[QASC state](evidence/v0.2/qasc-state.json), [generated main.py](evidence/v0.2/qasc-generated/main.py),
and [additional independent checks](evidence/v0.2/qasc-holdout.json) make the result
reviewable. The application converts Celsius to Fahrenheit. Fixed independent
checks covered 0, 100 and -40; holdouts covered 25, 37.5 and invalid input.
Generated unit tests checked exit status only. The independent checks compared
actual output and expected exit behavior, so the functional claim does not rest
on those weak generated tests.

This qualifies one local source-generation route and its explicit tests. It does
not qualify general autonomous application creation, arbitrary generated code,
automatic repairs, packaging or installation. Inference duration and availability
depend on the actual shared local runtime.

The [first AI interpretation](evidence/v0.2/ai-interpretation.json) incorrectly
said runtime execution had not occurred. SCE did not execute its redundant
suggestions or replace the actual verification result. An
[attributable reviewer correction](evidence/v0.2/ai-interpretation-correction.json)
links the contradiction to captured execution evidence and preserves the original
model claim. This correction was made by the Codex engineering worker, not falsely
attributed to a human. The context was subsequently improved to include bounded
command-output excerpts and operation chronology. A structured model response is
not, by itself, a verified engineering conclusion.

A [follow-up interpretation](evidence/v0.2/ai-interpretation-followup.json) received
actual stdout/exit excerpts and correctly summarized the numeric and invalid-input
checks, while still repeating one stale generation-stage unknown. It remains
AI inference. The response was stored before a Windows redirected-output encoding
failure was encountered; the CLI now emits UTF-8, with a regression test under an
explicit legacy encoding. No further model request was needed to recover the
already persisted response.

## Offline and integration boundaries

The [offline report](OFFLINE.md) links immutable Docker inspection, source hashes,
network observations and canonical functional evidence. This demonstrates the
local component route without internet access. It does not claim disconnected
GitHub discovery, local Qwen qualification inside that container, or a disconnected
Windows host. The test used an already cached image; all temporary containers and
volumes were removed. The explicit volume transport was selected because Docker
Desktop could not bind the host's I: drive; no host settings were changed.

[Independent-component inspection](evidence/v0.2/independent-components.json)
identifies the actual QASC, LocalAI, UIB and UIE documents/manifests observed.
UIB/UIE execution adapters remain proposed. Their implementation languages and
working files were preserved.

## Reproduce and extend

Run `python scripts/run_acceptance.py` in the development environment. It creates
a fresh receipt directory, runs tests, builds/installs a wheel, creates and checks
an application through the installed CLI, reloads memory and runs the original
experiment matrix. It does not invoke live AI or write to GitHub.

Run `python scripts/verify_offline.py --transport volume` with the documented
cached Docker image to repeat the disconnected check. Live model invocation is
an explicit separate `sce create-ai` operation; see [integration instructions](INTEGRATIONS.md).

Full local logs and artifacts remain in `.sce/acceptance/spider-v0.2-publish` and
`.sce/ai-v02`. Curated receipts are versioned without line-ending normalization.

Next milestone: **v0.3 — evidence-guided discovery and adaptation**. Extend this
route to a qualified external component and a generated/adapted component,
demonstrate memory-assisted repair with a rejected look-alike failure, and measure
human active time for equivalent useful outcomes. See the [roadmap](ROADMAP.md).
