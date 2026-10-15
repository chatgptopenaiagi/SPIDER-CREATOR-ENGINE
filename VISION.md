# SPIDER CREATOR ENGINE: original vision

**AUTONOMOUS SOFTWARE DISCOVERY, ENGINEERING INTELLIGENCE AND CREATION.**

SCE exists to return human time to human life. People should be able to describe
what they want to create while increasingly delegating repetitive technical work
to a local software engineering system. Human creativity determines the
destination. The Spider handles increasing amounts of the technical journey.

The product is a local-first autonomous software creation platform. Task
orchestration, databases, build adapters, and reports are infrastructure serving
that purpose. Their initial implementation does not define the limit of the
product's vision.

## The Spider's role

The Spider discovers software, understands its structure and interfaces, remembers
engineering experience, and connects useful components. Local AI helps interpret
objectives, investigate sources, design applications, generate missing pieces,
diagnose failures, and interpret actual execution evidence. Engineering adapters
construct, build, test, package, and deliver the resulting software.

The long-term resource landscape includes public GitHub repositories and accounts,
SourceForge, releases, source archives, user-provided links, documentation, forums,
existing applications, local source trees, Python/Anaconda environments, compilers,
SDKs, and build tools. Implemented connectors and proposed connectors must remain
distinguishable. Discovery should produce reusable structured knowledge about a
resource rather than end with an unexamined list of links.

## Software creation patterns

| Pattern | Intended engineering work | Current position |
| --- | --- | --- |
| Connect existing components | Join explicit interfaces through a thin adapter or shared representation | Python JSON-callable component chain implemented and covered by controlled tests |
| Transform an existing tool | Expose useful CLI/API functionality through a new application interface | General tool adaptation PROPOSED |
| Reuse partial artifacts | Evaluate useful source, fixtures, documentation, or intermediate results from unsuccessful work | Failure/artifact evidence can be preserved; automatic reuse selection PROPOSED |
| Generate missing components | Request bounded source proposals from local AI and validate their scope | Optional installed-QASC generation adapter implemented; general autonomous adaptation PROPOSED |
| Hybrid creation | Combine discovered components with newly generated implementation | Full autonomous hybrid loop PROPOSED |

Existing components may remain in Python, Rust, PowerShell, C++, .NET, or another
language. Integrations should follow observed interfaces, with independent build
and verification procedures. Rewriting working components is not a prerequisite
for connecting them.

## A living engineering memory

Memory belongs to the local system rather than only to a model conversation.
Projects, dependencies, environments, build outcomes, failures, attempted repairs,
verified corrections, interfaces, and reusable artifacts should be connected by
attributable records. Supporting and contradictory evidence remain available.
Human corrections preserve who changed the interpretation and why.

A previous packaging failure may suggest inspecting missing runtime data in a
later project. It does not prove the diagnosis or authorize applying an old fix.
The engine compares applicability conditions and gathers new evidence before
calling a correction verified. Failed work can be valuable engineering material
while its original problem remains unresolved. Model retraining is not required
to retrieve and use such experience.

The Software Knowledge Library describes what the Spider knows. The Executable
Capability Library describes operations that adapters actually implement, their
input/output contracts, current availability, limits, and verification evidence.
Knowledge, capability availability, and functional proof are separate concepts.

## Human communication and authority

The intended interaction is direct: “Spider, find the resources needed to build a
Windows GPU monitoring application.” The system should preserve the objective,
investigate useful alternatives, and ask only when an answer materially changes
the requested product. Routine technical choices should not repeatedly interrupt
the human. Progress and remaining work should survive session boundaries.

The current CLI demonstrates bounded parts of that journey. Natural-language
objective decomposition, conversational product negotiation, and general
autonomous creation remain development work. A model may propose code and actions;
it cannot expand execution authority, mark its output verified, or replace actual
test observations with an explanation.

## Evidence, delivery, and technological continuity

Every task should preserve what was requested, discovered, selected, planned,
executed, produced, verified, corrected, and still unknown. Its living trace has
three levels: what happened, why a route was selected, and the supporting evidence.
Successful process exit, artifact existence, functional verification, packaging,
installation, and installation verification have distinct meanings.

Essential engineering work should remain usable without cloud services. Local
models, dependency caches, documentation, recoverable databases, offline tools,
portable knowledge, and independent backups support that direction. Online
discovery enriches local resources. Disconnected operation must be established by
real tests with networking unavailable, with exact prerequisites and limits
recorded alongside their results.

## Success

`HUMAN_TIME_RECOVERED = BASELINE_HUMAN_ACTIVE_TIME - SCE_ASSISTED_HUMAN_ACTIVE_TIME`

Compare equivalent functional outcomes. Include request preparation, configuration,
interventions, review, correction, and attributable setup/maintenance effort.
Unattended processing is machine time, not automatically recovered human time.
Negative or uncertain measurements remain visible; absent measurements are
**UNKNOWN**.

Useful secondary observations include functional applications created, successful
automated builds, verified capabilities, reusable knowledge, documented avoided
interventions, and failures actually recovered. Code volume and agent count are
not substitutes for the primary purpose.

The [roadmap](docs/ROADMAP.md) turns this vision into bounded engineering work.
The [README](README.md) and acceptance evidence describe current functionality.
