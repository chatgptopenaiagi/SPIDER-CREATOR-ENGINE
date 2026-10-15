# SPIDER CREATOR ENGINE — SCE Foundation v0.1

**Return human time to human life.** SCE is a local-first foundation for engineering
orchestration. It turns explicit, scoped tasks into recorded attempts and verified
results. It is not yet a general autonomous software factory.

The primary metric is **HUMAN_TIME_RECOVERED**: baseline human active time minus
SCE-assisted human active time. Unknown measurements stay unknown, and negative
results stay visible. No productivity gain has been measured for this milestone.

## What works

- Installable Python package and `sce` command, with no third-party runtime dependencies.
- Strict task models, dependency graph validation, sequential scheduling, SQLite
  checkpoints, bounded explicitly safe retries, and cooperative cancellation.
- Capability contracts that separate proposed, implemented, available, and verified.
- Provenance-bearing engineering memory, bounded task-scoped retrieval, contradictory
  evidence, and unresolved failure capsules.
- Explicit local resource discovery, bounded acquisition with content hashes, and
  static project observations. No network discovery integration is claimed.
- Read-only build preparation, controlled Python archive packaging, and separate
  functional verification. Original-project builds and new-app synthesis are distinct.
- Canonical operation records rendered as JSON, Markdown, and escaped HTML.
- Local AI provider interface, loopback availability probing, bounded structured
  proposals, registry validation, and exact human-approved input scopes.
- Independent storage paths, environment observation, and configurable resource budgets.

The Python adapter is qualified only against the included fixtures. It does not
support general `pyproject.toml` projects, install dependencies, create native
executables, or install generated applications. `.NET` and synthesis capabilities
are listed as **proposed and unavailable**. UIB/UIE components have not been inspected
or integrated. The AI CLI proposes only; it cannot run its own proposals.

## Quick start (PowerShell 7)

Python 3.11+ is required; local acceptance was performed with Python 3.14.7.

```powershell
Set-Location I:\SPIDER-CREATOR-ENGINE
py -3.14 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e '.[dev]'
& .\.venv\Scripts\sce.exe --version
& .\.venv\Scripts\sce.exe capabilities
& .\.venv\Scripts\sce.exe doctor
```

The default managed storage is `.sce` under the current directory. For a stable
configuration, copy `config/example.toml` to ignored `config/local.toml`, edit the
paths, and use `sce --config config/local.toml <command>`. Relative configured
paths resolve against the configuration file. `sce init` explicitly creates the
selected storage directories. An unusable destination fails without changing volume.

```powershell
# Read-only plan: no output directories, database, or subprocess execution.
& .\.venv\Scripts\sce.exe build examples/fixtures/success --output .sce/demo --trust-source --prepare-only

# Packaging and explicit functional verification of our controlled source.
& .\.venv\Scripts\sce.exe build examples/fixtures/success --output .sce/demo --trust-source --verify

# The operation ID printed above can be used with the report command.
& .\.venv\Scripts\sce.exe report OPERATION_ID --format markdown

# An explicit task graph; fixture paths resolve against the JSON file.
& .\.venv\Scripts\sce.exe task run examples/task.json --trust-source

# Availability and a proposal-only interaction with the configured local model.
& .\.venv\Scripts\sce.exe ai-probe
& .\.venv\Scripts\sce.exe ai-propose 'Describe the next engineering step'
```

Use fresh output directories when repeating builds; existing artifacts are never
overwritten. `--trust-source` is authority to execute that selected source during
verification. A task file's `trusted` field alone cannot grant this authority.
There is no security sandbox or process-tree containment. Run only reviewed source.

`task create` records an objective without inventing a plan. `task list`, `task show`,
`task cancel`, and `task resume` expose stored state. A resume after ambiguous
interruption blocks for inspection; it does not blindly repeat possible side effects.
One caller owns a task at a time in this release.

## Validate the foundation

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe scripts/run_experiments.py
& .\.venv\Scripts\python.exe -m build --wheel
```

Expected failed builds and failed verification are successful test assertions when
their recorded states match the declared case. See [acceptance evidence](docs/ACCEPTANCE.md)
for actual results and [controlled experiments](docs/EXPERIMENTS.md) for the supported
boundary. Generated runtime reports live under `.sce`; curated acceptance receipts
are versioned under `docs/evidence`.

## Architecture and development

Start with [architecture](docs/ARCHITECTURE.md), [concept](docs/CONCEPT.md),
[adapter contract](docs/ADAPTER_CONTRACT.md), [engineering memory](docs/KNOWLEDGE_SYSTEM.md),
[local AI](docs/LOCAL_AI.md), and [human time recovery](docs/HUMAN_TIME_RECOVERED.md).
The [roadmap](docs/ROADMAP.md) identifies proposed work without claiming it exists.

The independent repository is initially private. See [license status](LICENSE-STATUS.md).
No other local repository or concurrent conceptual session is part of this workspace.
