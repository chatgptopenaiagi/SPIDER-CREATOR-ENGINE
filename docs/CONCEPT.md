# Concept and mission

SCE exists to recover human lifetime from repetitive engineering work. Its future
workflow is objective → scoped task → discovery → acquisition → analysis → adaptation
or construction → build → verification → packaging → optional installation and
integration. Each arrow must carry evidence and retain uncertainty.

The foundation deliberately preserves six separate categories:

| Category | Canonical representation |
| --- | --- |
| Requested | Human task objective, allowed capabilities, operation `requested` |
| Planned | Task steps/dependencies and operation `planned` |
| Executed | Append-only operation attempt records and `executed` entries |
| Produced | Artifact locations, identities, hashes in `produced` |
| Verified | Independent verification status and supporting evidence |
| Unknown | Explicit `unknowns`, limitations, absent measurements |

Generated code volume, number of agents, and number of features are not substitutes
for recovered time. A failed experiment can preserve valuable information without
being a solved problem. A successful past build can suggest a repair without proving
its applicability in a new environment.

Human objectives define authority. A model may propose actions and source content;
it cannot grant itself capabilities, approve its own execution, expand path scope,
or declare verification successful. The host validates proposals and stores actual
observations. The v0.1 CLI intentionally leaves proposal-to-execution planning as a
future integration; typed validation primitives are available for a scoped host.
