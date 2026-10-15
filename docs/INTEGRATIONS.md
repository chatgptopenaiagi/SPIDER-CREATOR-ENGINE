# Independent engineering components

SCE integrates existing components through their observed interfaces. An adjacent
directory or a product name does not establish an available capability. Components
retain their own languages, repositories and working environments.

## QASC generation adapter

The independent local QASC installation exposes a Python CLI. Its inspected
`qasc 0.1.0` interface provides `create`, `test`, `status`, `resume`, and `package`,
with explicit model and project-directory options. SCE's
`sce.adapters.qasc.PythonQASCAdapter` uses `create` and `test` only. It does not
modify QASC source, install dependencies, or copy QASC implementations into SCE.

The installed interpreter is supplied explicitly. The adapter invokes
`python -I -B -m qasc`; isolation ignores project-local import overrides and `-B`
disables bytecode writes. `PYTHONDONTWRITEBYTECODE=1` is also set for child
processes. The process working directory, QASC `--projects-dir`, request files,
acceptance files and temporary directory are inside configured SCE
`BUILD_WORKSPACES`. A missing selected interpreter is reported without installing
or replacing an environment.

```python
from sce.adapters.qasc import PythonQASCAdapter

adapter = PythonQASCAdapter(
    r"I:\QWEN-AUTONOMOUS-SOFTWARE-CREATOR\.venv\Scripts\python.exe",
    r"I:\SPIDER-CREATOR-ENGINE\.sce\builds",
    endpoint="http://127.0.0.1:8080",
    model_timeout_seconds=180,
    timeout_seconds=240,
)
plan = adapter.prepare(
    "Create a Python greeting CLI accepting one name argument.",
    "greeting-example",
    acceptance={"cases": [
        {"name": "ada", "args": ["Ada"], "stdout": "Hello Ada\n"},
        {"name": "grace", "args": ["Grace"], "stdout": "Hello Grace\n"},
    ]},
)
record = adapter.execute(plan)
# Inspect generated source first or supply established task execution authority.
record = adapter.verify(plan, record, trusted_generated_source=True)
canonical_record = adapter.report(record)
```

This example is an API illustration, not a claim that arbitrary requests are
qualified. The endpoint remains a configuration candidate until an actual model
request succeeds. Supply a fresh project name; SCE refuses to overwrite an
existing project. Request and acceptance files are created during EXECUTE.
PREPARE reads configuration, checks locations and interpreter identity, validates
acceptance cases, and creates an immutable plan without creating files or calling
QASC or the model.

EXECUTE uses QASC's generation-only default, does not pass `--run`, and sets no
automatic correction budget. Exit code zero alone is insufficient: SCE requires
a structured generated status, an existing managed source inventory, retained
operator acceptance, and observed content hashes. A generation failure preserves
partial project files and an unsuccessful or partial canonical record.

VERIFY is separate and requires explicit source trust. SCE checks the generated
source against its recorded inventory before requesting `qasc test`. A functional
pass requires all of the following:

- A structured QASC verification record matching its current status response.
- A positive integer unit-test count and passing unit-test status.
- The original independent acceptance specification, every expected case name,
  passing case outcomes, empty mismatch lists and receipt references.
- Successful independent acceptance, unchanged source, and a source fingerprint
  recomputed by SCE that matches both generation and verification.

An exit code, the model's explanation, or QASC's summary label alone does not
satisfy these checks. Test failure leaves source-generation outcome separate from
functional verification status. Timeouts remain inconclusive. Source changes or
changed acceptance are rejected, retaining previous evidence.

Captured output and direct-process duration are bounded. Executed generated code
still has current-user permissions; this is **not an OS sandbox**. SCE does not
guarantee termination of arbitrary process descendants or prevent generated code
from accessing unrelated files. The adapter does not implement automatic repair,
resume, package, install, or capability registration; QASC CLI operations outside
this boundary remain unintegrated. Source fingerprints cover managed source
files, not every possible environment effect.

`tests/test_qasc_adapter.py` qualifies lifecycle separation, scope checks, fixed
acceptance, nonzero-test requirements, stale source rejection, partial generation,
and bounded process capture with deterministic mock QASC responses. A real
read-only interpreter invocation returned `qasc 0.1.0`; the CLI was inspected
before integration. A real model generation plus independent acceptance run is
required separately before claiming a live end-to-end QASC creation capability.
Published experiment records describe any such run and its actual outcome.

The [v0.2 live experiment](ACCEPTANCE_V0.2.md#local-ai-experiment) completed one
temperature-converter generation and separate verification after an earlier
timeout. This establishes that declared experiment, not arbitrary QASC requests.
The CLI exposes the same boundary:

```powershell
sce create-ai 'Create a minimal Celsius-to-Fahrenheit CLI with one numeric argument and one-decimal output' `
  --qasc-python I:\QWEN-AUTONOMOUS-SOFTWARE-CREATOR\.venv\Scripts\python.exe `
  --name temperature-example `
  --acceptance examples/ai/temperature-acceptance.json `
  --verify --trust-generated-source
```

Use `--prepare-only` for a read-only plan. Generation without `--verify` remains
unverified work; its task is blocked pending verification rather than labeled a
functional application. Set `[ai].timeout_seconds` in an explicit config when the
observed model runtime needs a longer deadline. The successful experiment used
600 seconds and `--max-tokens 1200`; the default deadline is not a performance
guarantee. `sce ai-interpret TASK_ID` sends bounded actual operation evidence and
stores the response as AI inference, without executing its suggestions.

## Other components

UIB/UIE adapters are **PROPOSED** until supported operations, effect boundaries,
input/output contracts and real verification evidence are established. No working
component needs to be rewritten merely to match SCE's implementation language.
LocalAI is an independent inference environment, not an installation target for
this adapter. SCE can keep using its provider-independent local AI interface
without a QASC installation; local discovery, memory and controlled builds remain
independent of both optional systems.

Read-only [inspection receipts](evidence/v0.2/independent-components.json) identify
the observed source documents. UIB exposes a PowerShell/Python-oriented wrapper;
UIE declares a Python entry point and a Rust workspace. These observations establish
interfaces to investigate, not packaging or installation capabilities in SCE.
