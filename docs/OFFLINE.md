# Disconnected engineering verification

The controlled qualification passed on 2026-10-15 using a cached Python 3.14.8
Linux image. The real namespace exposed only loopback, an external socket
reported `Network is unreachable`, and all six local Spider stages completed.
Persistent task and engineering records were reloaded in a second interpreter.
These receipts are copied byte-for-byte from the actual run:

- [Offline results](evidence/v0.2/offline/offline-results.json)
- [Pre-start Docker network, mount and resource verification](evidence/v0.2/offline/docker-before-start.json)
- [Source hashes before](evidence/v0.2/offline/source-before.json) and
  [after](evidence/v0.2/offline/source-after.json), which match exactly
- [Runtime, image identity, storage transport and cleanup receipt](evidence/v0.2/offline/receipt.json)
- [Canonical build and functional check](evidence/v0.2/offline/build.json) and
  [Spider workflow functional verification](evidence/v0.2/offline/spider-functional-verification.json),
  including the expected and observed output, command, exit code and scope

The initial bind-mount attempt could not share this machine's `I:` drive through
Docker Desktop. The successful run explicitly selected temporary Docker volume
transport, described below. Host networking and Docker configuration were not
changed.

Local-first behavior must be demonstrated while connectivity is unavailable.
The opt-in `scripts/verify_offline.py` harness uses an already cached Python Linux
container image and Docker `--network none`. It does not emulate offline mode by
mocking network APIs, change Windows networking, or affect existing containers.

```powershell
.\.venv\Scripts\python.exe scripts\verify_offline.py
```

Docker must already be available, with `python:3.14-slim` cached (or supply another
cached Python 3.11+ image using `--image`). The harness never downloads an image
or installs dependencies. Missing prerequisites produce a failure receipt rather
than a claim of verified offline operation.

The harness creates one disposable container with one CPU, 512 MiB RAM, a
128-process ceiling and a read-only root filesystem. Repository source is
mounted read-only; only a fresh project-owned `.sce/offline/<run-id>` workspace
is mounted writable with the default `--transport bind` option. Before starting, Docker API inspection checks the actual
network mode, image ID, resource ceilings and mount permissions. The container
checks that only the loopback interface exists and there is no IPv4 default
route; a real socket connection to an external numeric IP must fail.

With that network namespace in place, SCE constructs the CSV reporting example
from two independent local components, creates its Python zipapp, runs the
caller-supplied functional fixture, and writes canonical operation evidence to
SQLite engineering memory. A second Python interpreter retrieves the saved
records and confirms the verified result persists beyond process context.
It also runs the complete local Spider workflow: discovery, acquisition,
analysis, synthesis, building, functional verification, and persistent task
history. The second interpreter confirms all six operations survive in SQLite.

If Docker Desktop cannot share the selected Windows drive, the default test
fails with that exact mount error. It never changes Docker settings or silently
uses a different disk. An explicit alternative is available:

```powershell
.\.venv\Scripts\python.exe scripts\verify_offline.py --transport volume
```

This option stages only the selected SCE source, controlled component examples
and verification script (maximum 20 MB) into uniquely named temporary
Docker-managed volumes. The verifier still mounts source read-only, and runs
with networking disabled. It copies the evidence back to the project-selected
`.sce/offline/<run-id>` path before removing its own containers and volumes.
The receipt records this explicit storage transport. Docker-managed volumes use
the engine's configured disk and do not have a hard filesystem quota; this
option exercises only the bounded checked-in fixture, and must not be treated
as a general arbitrary-source runner. No image pull or package installation is
performed in either transport.

The resulting directory retains `receipt.json`, the image/runtime identity,
source hashes, pre-start Docker inspection, in-container route/interface and
connection evidence, synthesis and build records, generated application,
functional artifact, and SQLite database. Only the disposable container is
removed; evidence remains on the selected project drive.

This establishes disconnected operation for the exercised local synthesis,
build, functional verification and persistent memory path. It does not establish
that every SCE adapter works offline, that missing dependencies can be installed
offline, or that local Qwen inference is available inside the container. Windows
host behavior and Linux container behavior remain separately attributable.

The development direction is to expand qualified offline fixtures, use explicit
dependency caches, preserve local documentation and model resources in selected
storage profiles, and add portable database export/backup validation. Those
broader continuity capabilities require their own verified adapters and tests.
