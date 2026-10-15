# SPIDER CREATOR ENGINE

**AUTONOMOUS SOFTWARE DISCOVERY, ENGINEERING INTELLIGENCE AND CREATION.**

**Return human time to human life.** Spider Creator Engine (SCE) is a local-first
software creation platform. Its purpose is to turn a human idea and available
software knowledge into a useful, functioning application.

The human determines what should exist. The Spider discovers relevant resources,
understands their interfaces, and remembers engineering experience. Local AI
helps design and adapt software. Engineering adapters execute the work, test the
result, and preserve what happened for the next task.

The primary measure is **HUMAN_TIME_RECOVERED**: baseline human active time minus
SCE-assisted human active time for an equivalent functional outcome. Machine
runtime is measured separately. Unknown and negative results remain visible.
**Human time recovered for this project is currently UNKNOWN.**

## From an idea to working software

1. **Discover software.** Start from an objective, project name, repository,
   public GitHub account, or local resource. The current Spider inspects explicit
   local files/folders and public GitHub projects. SourceForge, direct downloads,
   MediaFire, forums, releases, and broader local software catalogs are development
   targets, labeled **PROPOSED** until their adapters are qualified.
2. **Understand what is available.** Preserve source identity and revision;
   inspect project structure, language clues, dependency declarations, and
   documented interfaces. Static observations are evidence about source material,
   not proof that a project builds or works.
3. **Remember engineering knowledge.** Store observations, source provenance,
   environment conditions, conflicts, relationships, and applicability limits in
   local SQLite memory. Retrieve relevant experience across sessions within
   explicit task and resource scopes.
4. **Work with local AI.** Qwen is the initial model target, behind a provider
   interface. Give the model bounded relevant context and actual execution
   evidence. Validate proposals against task authority and available capability
   contracts. Model text cannot grant itself execution authority.
5. **Create software from components.** Connect useful interfaces with thin
   adapters, reuse suitable artifacts, and progressively add generated missing
   components. The current synthesis adapter constructs a Python application
   from explicitly selected callable components and a JSON bridge. An optional
   adapter can ask an independently installed QASC to generate Python source,
   with separate source trust and functional checks. Autonomous interface
   selection and general hybrid creation remain **PROPOSED**.
6. **Build and deliver a result.** Create application source, build a Python
   archive, execute declared functional checks, and retain artifact hashes and
   reports. General packaging, native executables, installation, and installation
   verification require additional adapters. Each is a separate engineering stage.
7. **Learn from unsuccessful work.** Keep failures, diagnostics, attempted repairs,
   partial artifacts, and unresolved hypotheses. A future task can compare a
   historical repair's conditions without assuming the same symptom has the same
   cause. Human corrections append attributable evidence rather than erase history.
8. **Keep essential work local.** Source inspection, component synthesis, builds,
   verification, memory, and reporting use local files and tools. Online discovery
   adds resources when available. The controlled local creation workflow passed
   a real disconnected-container test; see [offline qualification](docs/OFFLINE.md).

SCE v0.1 established the infrastructure: package, CLI, orchestration, persistence,
adapters, verification, and reporting. **The v0.2 development milestone connects
that foundation to the Spider's discovery and software-creation workflow.**
The [vision](VISION.md) defines the destination; the [roadmap](docs/ROADMAP.md)
identifies what must be built next.

## What exists today

| Component | Implemented behavior | Current boundary |
| --- | --- | --- |
| Spider discovery | Local inspection; public GitHub repository/account/keyword search; pinned trees and bounded root documentation | Keyword search is literal, not semantic objective decomposition; no network acquisition |
| Local acquisition and analysis | Bounded snapshots, content hashes, source structure and metadata observations | No source execution during inspection; no archive extraction |
| Component synthesis | Separate Python components connected through a generated JSON CLI bridge | Explicit interfaces and source selection; one caller-supplied acceptance case |
| Python build and verification | Controlled `.pyz` construction and separate stdout/exit checks | Available interpreter required; no general dependency installation or native executable |
| Engineering memory | Provenance categories, typed relationships, historical candidates, applicability checks, attributed corrections | Matching history is not an automatically verified repair |
| Living trace | Task summaries, route decisions, and full supporting evidence in JSON/Markdown/HTML | Trace and operation checkpoints have distinct persistence boundaries |
| Execution foundation | Capability contracts, dependency graphs, checkpoints, bounded recovery, cancellation | Sequential execution; one owner per task |
| Local AI boundary | Loopback provider, availability probe, bounded proposals, exact scope validation, structured evidence interpretation | Interpretations remain AI inference; no automatic expansion of execution authority |
| Optional AI source generation | Adapter to the explicitly selected installed QASC CLI; generation and functional checks stored separately | Inspected QASC interface only; requires a reachable model; live qualification recorded separately |
| Storage and resources | Independently configured paths, environment observations, time/context limits | RAM/GPU/temporary-storage quotas remain advisory |

SourceForge/MediaFire/general URL acquisition, autonomous research and repair,
general autonomous hybrid creation, .NET builds, installation, and UIB/UIE integration are
**PROPOSED**. Existing Rust or other-language components can retain their
implementation language when an inspected adapter contract supports integration.

Capability status is recorded separately from current availability and observed
verification. A registered definition does not establish functionality. The
[v0.2 acceptance record](docs/ACCEPTANCE_V0.2.md), [controlled experiments](docs/EXPERIMENTS.md),
and tests establish the actual tested boundary; the original v0.1 receipt is
historical evidence rather than a claim about all later changes.

Current qualification: **321 automated tests passed**, a real disconnected
six-stage creation run passed, and a local Qwen/QASC temperature-converter
experiment passed independent output checks. The first model request timed out;
that failure and the successful bounded retry are both preserved in the
[experiment evidence](docs/ACCEPTANCE_V0.2.md#local-ai-experiment).

## Try the Spider locally

Python 3.11+ and PowerShell 7 are the Windows development baseline. From this
checkout, create or use the project's virtual environment:

```powershell
Set-Location I:\SPIDER-CREATOR-ENGINE
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e '.[dev]'
& .\.venv\Scripts\sce.exe --version
& .\.venv\Scripts\sce.exe doctor
& .\.venv\Scripts\sce.exe capabilities
```

Inspect the included source components, then construct a CSV reporting application
from their declared interfaces. The acceptance file supplies the input and
expected result independently of the generated bridge.

```powershell
& .\.venv\Scripts\sce.exe discover examples/components/csv_summary

& .\.venv\Scripts\sce.exe spider create 'Create an application that summarizes CSV data and produces a readable report' `
  --component examples/components/csv_summary `
  --component examples/components/summary_report `
  --acceptance examples/components/csv_report_request.json `
  --name csv-report `
  --trust-source

# Use the task ID from the result to inspect what happened and its evidence.
& .\.venv\Scripts\sce.exe trace TASK_ID --level 1 --format markdown
& .\.venv\Scripts\sce.exe trace TASK_ID --level 3 --format json
& .\.venv\Scripts\sce.exe memory TASK_ID

# Optional interpretation sends bounded actual evidence to the configured local model.
& .\.venv\Scripts\sce.exe ai-interpret TASK_ID

# Online discovery requires an explicit opt-in.
& .\.venv\Scripts\sce.exe discover 'https://github.com/chatgptopenaiagi/SPIDER-CREATOR-ENGINE' --online
```

This demonstration exercises discovery, acquisition, analysis, route selection,
application construction, build, functional verification, and memory. The human
selects the components and expected outcome. The pipeline does not infer arbitrary
interfaces or silently generate new product requirements. `--trust-source`
authorizes execution of the selected reviewed source during functional checks;
the runtime is not a security sandbox.

For existing controlled projects, `sce build SOURCE --output DESTINATION
--trust-source --prepare-only` inspects a plan without executing it. Remove
`--prepare-only` and add `--verify` to build and run declared checks. Building an
original project and creating a new application using components remain distinct
operations. Use a fresh output location; earlier artifacts are not overwritten.

`sce create-ai --help` describes the optional installed-QASC route. Its interpreter
and independent acceptance file must be selected explicitly. Generation creates
source; `--verify --trust-generated-source` separately authorizes functional
checks. Successful generation alone leaves the application unverified. This
adapter does not modify QASC's independent project or environment.

## Storage, continuity, and local operation

Managed paths default to `.sce` under the current directory. Copy
`config/example.toml` to ignored `config/local.toml`, choose destinations, and use
`sce --config config/local.toml COMMAND` for a stable profile. Relative configured
paths resolve against the configuration file. `sce init` explicitly creates the
selected directories; an unusable destination fails without silently changing
volume. Resource identities remain separate from current file locations.

`task list`, `task show`, `task cancel`, and `task resume` expose persistent state.
Interrupted operations with ambiguous effects require reconciliation; completed
checkpoints are retained. There is no automatic rollback or exactly-once external
side-effect guarantee. Local dependencies and a suitable interpreter must already
be available for offline operation. A Docker network namespace with only loopback
verified the local six-stage creation workflow and persistence across interpreters;
the [disconnected test evidence](docs/OFFLINE.md) states the exact scope and limits.

## Verify and contribute

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe scripts/run_experiments.py
& .\.venv\Scripts\python.exe -m build --wheel
& .\.venv\Scripts\python.exe scripts/run_acceptance.py
```

Expected failures count as passing test cases only when observed outcomes and
verification states match the declared case. Runtime receipts live under `.sce`;
curated acceptance evidence is versioned under `docs/evidence`.

Read the [vision](VISION.md), [architecture](docs/ARCHITECTURE.md),
[roadmap](docs/ROADMAP.md), [adapter contract](docs/ADAPTER_CONTRACT.md),
[engineering memory](docs/KNOWLEDGE_SYSTEM.md), [local AI](docs/LOCAL_AI.md),
and [human time recovery model](docs/HUMAN_TIME_RECOVERED.md).

The project is published at
[chatgptopenaiagi/SPIDER-CREATOR-ENGINE](https://github.com/chatgptopenaiagi/SPIDER-CREATOR-ENGINE).
See [license status](LICENSE-STATUS.md) before reusing or redistributing code.
