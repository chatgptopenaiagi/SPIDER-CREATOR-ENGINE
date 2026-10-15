# Spider discovery

The Spider turns a starting point into a bounded, attributable software observation.
It preserves project identity, source revision, file structure, declared dependencies,
author documentation, evidence and limitations. Discovery does not execute the
software it encounters and does not establish that the software works.

## Implemented entry points

```python
from sce.discovery import SpiderDiscovery, DiscoveryLimits, inspect_local
from sce.core.models import jsonable

# Local discovery is available without an Internet connection.
project = inspect_local(r"I:\my-explicit-source")

# Online discovery is an explicit choice. All requests are anonymous GETs.
result = SpiderDiscovery(offline=False, limits=DiscoveryLimits(
    max_files=500, max_requests=12, timeout_seconds=10,
)).discover("https://github.com/pypa/sampleproject", limit=1)

# jsonable(result) is a portable document suitable for memory/evidence storage.
```

`StartingPoint.normalize()` recognizes:

| Starting point | Current behavior |
| --- | --- |
| Existing file/folder, explicit path or local `file:` URL | Bounded static local inspection |
| `https://github.com/owner/repository`, `owner/repository`, `github:owner/repository` | Inspect one public repository |
| `https://github.com/owner`, `@owner`, `github:owner` | Enumerate bounded public account candidates and inspect them |
| Project name or natural-language text | Literal GitHub repository keyword search followed by inspection; semantic objective decomposition is **PROPOSED** |
| Local archive | Register content observation and hash; contents are not extracted |
| SourceForge, MediaFire, direct download URL | Classify only; their connectors are **PROPOSED** |
| GitHub deep source/branch URL | Explicitly unsupported; use the repository root URL |

The old `LocalDiscovery(roots).discover(query)` API remains compatible. The newer
`inspect_local()` and `SpiderDiscovery` interfaces return structured observations.
Discovery can run independently of acquisition, building and application creation.

## Observation contract

`DiscoveryResult` contains `starting_point`, `online`, `projects`, `errors`,
`unsupported`, and `limitations`. A successful HTTP request is not a functional
verification result. Partial document inspection remains visible in a project's
limitations. A failed source-tree or revision request does not become a successful
project inspection.

Each `SoftwareProject` retains:

- `resource_id`, `source_uri`, `name`, `revision`, `kind`, and observation time.
- Structured metadata: file structure, inferred languages, declared dependencies,
  declared build backend and, when present, script declarations.
- Individual observations with `subject`, `value`, `provenance`, `source` and
  optional content SHA-256.
- Attributable execution evidence and limitations.

README and manifest text have `AUTHOR_DOCUMENTATION` provenance. Observing a
declaration does not verify it. Filename and hash observations have
`OBSERVED_BEHAVIOR` provenance; inferred languages are explicitly identified as
filename-based. This provider never emits `VERIFIED_TEST_EVIDENCE` or treats
discovered text as an execution instruction.

The local resource ID describes the bounded observed set of relative paths and
content hashes. Moving identical observed content preserves this ID. Excluded,
unread or budget-limited content is outside that identity. The reported
`observed-sha256` revision is an observation fingerprint, **not a Git revision or
a claim that every repository byte was hashed**. Local acquisition retains its
own acquisition identity and full prepared inventory within its separate limits.
The GitHub resource ID uses the repository's numeric ID, independent of download
location. GitHub source observations are pinned to a resolved commit SHA.

## Bounds and offline behavior

Default limits are 500 files, 65,536 bytes per text document, 10 MB of local
content hashing, 2 MB per API response, 40 API requests, 2 listing pages, and a
10-second socket timeout per request. A discovery result is capped at 20 projects
(default 5). This is bounded inspection, not a general Internet crawler.

Local discovery skips linked paths and common environment/generated directories
such as `.git`, `.venv`, `node_modules`, and `__pycache__`. It does not import
Python modules or evaluate build files. Root README files and supported root
manifests (`pyproject.toml`, `requirements.txt`, `package.json`, `Cargo.toml`)
provide text observations. Dependencies remain declarations, including unknown
or unsupported requirement directives.

The GitHub provider uses a fixed public `api.github.com` transport, rejects
redirects, reads no authentication credentials, and observes anonymous rate
limits. Repository metadata and the default branch identify a commit; that
commit identifies the tree; selected tree blobs are checked against their Git
object hashes before their text is admitted. Symlinks and submodules are not
followed. A GitHub-truncated tree, response/request budget, missing document,
rate limit, malformed metadata or unavailable network remains explicit.

`SpiderDiscovery()` defaults to `offline=True`. Online starting points produce
a disabled-network error without calling the transport. Local inspection keeps
working. Tests establish this provider's network refusal. They do not by
themselves establish whole-machine disconnected operation for every SCE engine.

## Qualification and remaining work

`tests/test_spider_discovery.py` covers local inspection, identity changes,
provenance, bounds, starting-point routing, offline refusal, mock GitHub account
and query discovery, pinned revisions, blob integrity, HTTP failures, and
unsupported connectors. Existing local discovery/acquisition tests are retained.

A real, read-only public inspection of `pypa/sampleproject` is recorded in
[github-discovery.json](evidence/v0.2/github-discovery.json). It observed commit
`621e4974ca25ce531773def586ba3ed8e736b3fc`, Python source, root documentation and
the declared `peppercorn` dependency. This qualifies that bounded inspection;
the external project was not downloaded for execution, built or installed.

SourceForge, MediaFire, generic URL acquisition, releases, documentation/forum
crawlers, semantic objective decomposition and archive extraction are
**PROPOSED**. Discovery of a resource does not grant reuse or installation
authority. Applications can already be created from explicitly selected local
resources through the separate engineering path documented elsewhere.

GitHub protocol references:
[repository metadata/listing](https://docs.github.com/en/rest/repos/repos),
[commit lookup](https://docs.github.com/en/rest/commits/commits),
[Git trees](https://docs.github.com/en/rest/git/trees), and
[Git blobs](https://docs.github.com/en/rest/git/blobs).
