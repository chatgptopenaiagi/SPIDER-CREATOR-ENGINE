# Concept and mission

Spider Creator Engine is a local-first autonomous software discovery,
engineering intelligence, and creation platform. Its purpose is to recover human
lifetime from repetitive engineering work while helping people turn ideas into
useful functioning applications. The complete product direction is recorded in
[the original vision](../VISION.md).

The human determines what should exist. The Spider discovers resources, understands
software interfaces, and remembers engineering experience. Local AI proposes designs,
source, and repairs. Engineering adapters execute scoped actions, verify outcomes,
and preserve artifacts and evidence. The existing task orchestrator serves that
journey as infrastructure.

## Knowledge becomes useful software

Resources can enter through local paths, repository URLs, public accounts, project
names, natural-language objectives, archives, or supplied links. Implemented
providers inspect local sources and public GitHub metadata/source structures;
additional providers remain proposed. Source selection and interface declarations
are explicit in the current Python creation route.

The Software Knowledge Library preserves what the Spider has learned, with source
attribution, observed conditions, conflicting evidence, and applicability limits.
The Executable Capability Library separately describes what installed adapters can
actually do and what has been verified. A repair recipe is knowledge; it is not
execution authority or proof of a working correction.

Software creation can connect existing components, adapt a tool, reuse a partial
artifact, generate a missing piece, or combine these patterns. The first implemented
synthesis pattern connects declared Python JSON-callable components through a thin
bridge. An optional inspected QASC adapter offers source generation followed by
separate explicitly trusted verification. General autonomous missing-component
selection and hybrid creation remain proposed. Existing projects retain their identity; creating a new application using
a component is distinct from building that component's original project.

## Preserve the engineering truth

| Category | Canonical representation |
| --- | --- |
| Requested | Original human objective, acceptance requirements, allowed capabilities, operation `requested` |
| Discovered and selected | Resource identities/revisions, source observations, selected component references |
| Planned | Task steps/dependencies, engineering decisions, operation `planned` |
| Executed | Append-only operation attempts and `executed` entries |
| Produced | Artifact locations, identities, and hashes in `produced` |
| Verified | Separate declared verification status, procedure, and supporting evidence |
| Unknown | Explicit `unknowns`, applicability limitations, absent measurements |

A living trace exposes what happened, why the route was selected, and supporting
evidence. Failed work retains diagnostic information and partial artifacts. Human
corrections add attributable records instead of replacing history. A prior success
or similar error can guide investigation without guaranteeing the next outcome.

The model receives bounded relevant context and actual execution evidence. Its
output must remain distinguishable from observations and independently tested
results. Proposals cannot grant new capabilities, authorize their own source, or
expand approved input scope. Essential local operations do not depend on a cloud
model; online resources are optional additions. Offline claims require actual
network-unavailable qualification, beyond an offline-compatible design.

## Measure human time honestly

`HUMAN_TIME_RECOVERED = BASELINE_HUMAN_ACTIVE_TIME - SCE_ASSISTED_HUMAN_ACTIVE_TIME`

Compare equivalent functional outcomes and include relevant setup, interventions,
review, and repair effort. Machine execution and total elapsed time remain
separate. Unknown measurements remain unknown, negative results remain visible,
and generated code volume, agent count, or feature count do not substitute for
recovered human time. The current project metric is **UNKNOWN**.
