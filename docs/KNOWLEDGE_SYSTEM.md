# Engineering knowledge and failure memory

SCE stores original engineering observations with their provenance. A
record is evidence for a particular claim under particular conditions; it does
not confer execution authority or establish compatibility with another project.

`KnowledgeRecord` holds a claim, source observations, explicit task associations,
supporting and contradictory evidence, environment conditions, limitations, and
links to other records. Optional `resource_id`, `resource_revision`, `subject`,
`description`, and explicit `applicability` conditions identify what the record
describes. Unknown fields remain absent or `None`. `limitations` is also exposed
as the `known_limitations` property. Supported kinds include project references,
observations, repair recipes, build configurations, incompatibilities, artifact
references, corrections, verification observations, analyses, decisions, and
failure capsules. All kinds use the same provenance requirements. A repair recipe
is preserved knowledge, not an executable or verified capability.

Every `Provenance` requires a source, observation method, and observation time.
Its category is one of `AUTHOR_DOCUMENTATION`, `AI_INFERENCE`,
`OBSERVED_BEHAVIOR`, or `VERIFIED_TEST_EVIDENCE`. Existing v0.1 observations
default to `OBSERVED_BEHAVIOR`; they are never migrated to verified facts.
Verified-test provenance requires attached supporting evidence. A record can
contain several sources, including conflicting sources. An optional `actor`
attributes a human correction or another named contributor. Neither a human
correction nor an AI explanation automatically becomes verified test evidence.
Source revision and SHA-256 are optional and remain unknown when not observed.
An observation timestamp records when evidence was seen, not when the source was
created. Resource identities and references do not depend on their storage path.

## Persistence and bounded retrieval

`KnowledgeStore(path)` uses SQLite at the explicitly selected path. It can share
the task database; it does not choose a fallback volume. Inserts are append-only
through this API, and duplicate IDs fail instead of overwriting earlier evidence.
Corrections are new records linked through `related_record_ids` and contradictory
evidence. Additional resource indexes, relationship tables, and retrieval-scope
audit tables are created additively; existing payloads and task records remain
unchanged. SQLite file access is not a tamper-proof audit system.

```python
from sce.knowledge import KnowledgeRecord, KnowledgeStore, Provenance

memory = KnowledgeStore(".sce/tasks.sqlite3")
record = KnowledgeRecord(
    claim="The controlled fixture produced the expected greeting.",
    provenance=[Provenance(source="operation:build-001", method="stdout comparison")],
    task_ids=["task-001"],
    resource_id="controlled-greeting",
    resource_revision="fixture-v1",
    environment={"fixture_revision": "v1"},
    applicability={"fixture_revision": "v1"},
    limitations=["This observation applies only to this controlled fixture."],
)
memory.append(record)
context = memory.retrieve("task-001", "greeting", limit=8, max_chars=12000)
```

Retrieval requires an explicit task ID. It applies literal substring matching to
claims, supports an optional exact `resource_id` filter, considers at most the
newest 128 matching records, and returns complete
records within a maximum count and serialized character budget. SQLite LIKE is
case-insensitive for ASCII characters; non-ASCII case folding is not provided.
Wildcard characters in queries are escaped. Oversize records are omitted rather
than separating claims from provenance. An empty result does not prove that no
relevant knowledge exists. Character budgets are not tokenizer-specific model
context limits; AI providers must enforce their own additional context bound.

### Cross-session engineering memory

`find_candidates` can retrieve previous experience for the same resource, even
after a process restart. Historical lookup must be explicitly requested with
`include_history=True`; the default considers only the named task's records.
This lookup does not silently associate old records with a new task.

```python
candidates = memory.find_candidates(
    "task-002", "controlled-greeting", include_history=True,
    environment={"fixture_revision": "v1"}, resource_revision="fixture-v1",
    limit=4, max_chars=8000,
)
```

Every candidate preserves its entire record and provenance, whether it is
historical, and an applicability assessment: `matched`, `mismatch`, or `unknown`.
The comparison checks recorded `applicability` conditions and source revision
against supplied observations. Missing conditions, missing observations, and
unknown revisions remain unknown. Recorded `environment` is descriptive; only
explicit `applicability` entries are treated as required conditions. A matching
assessment does not prove a repair applies, authorize execution, or mark a
failure resolved. Count and serialized-character budgets include the assessment.

An engineer may explicitly add an old record to a new task's retrieval scope:

```python
assessment = memory.reuse(
    candidates[0].record.id, "task-002", actor="human:reviewer",
    reason="Compare the earlier missing runtime-data failure",
    environment={"fixture_revision": "v1"}, resource_revision="fixture-v1",
)
```

This appends an attributable scope event with applicability conditions and adds
a task association. The original record's `task_ids` remains the original
attribution; database scope associations determine current retrieval eligibility.
`scope_history(record_id)` shows explicit reuses. Reusing even an incompatible
record is allowed for comparison, without treating it as a repair to execute.

### Relationships and human corrections

`KnowledgeRelationship` records a source record, target record, typed relation,
task scope, and provenance. Relations include `depends_on`, `uses_component`,
`built_from`, `derived_from`, `supports`, `contradicts`, `corrects`, `verified_by`,
`attempted_repair`, and `has_failure`. Represent a project, dependency, source
artifact, environment, or capability as a knowledge record, then connect its
records using these typed links. Both endpoints must already belong to the
relationship's task scope; an explicit `reuse` can establish that scope when
comparing history. Relationships are append-only and queryable through
`relationships(task_id, record_id=None)`.

`correct(record_id, claim, task_id=..., actor=..., reason=...,
supporting_evidence=[...])` atomically appends an attributed human correction
and a `corrects` relationship, with explicit contradictory evidence. It retains
the original observation, conditions, revision, and environment. A later
verification observation may support or contradict either claim. No delete or
in-place claim replacement API is provided.

`record_operation(operation, resource_id=..., resource_revision=...,
environment=...)` captures canonical execution evidence as a knowledge record.
Its claim explicitly separates operation outcome from declared verification.
The full canonical operation is retained under `metadata["operation"]`.
Passed declared verification with evidence is attributable test evidence for
that declared procedure; it is not a claim of general application compatibility.

This milestone does not implement embeddings, automatic semantic relevance,
arbitrary project similarity matching, automatic repair selection, model
retraining, or reliable deduction that historical success guarantees success now.

## Navigable engineering trace

`TraceStore(database)` may share the selected SQLite task database. Append a
`TraceEvent` for each meaningful step, retaining the original objective,
discovered resources, selected components, planned actions, route decisions,
operations, errors, artifacts, verification results, and unknowns. Events are
append-only and task-scoped. Duplicate event IDs fail rather than overwrite.

`read(task_id, level=1|2|3, limit=1000, offset=0)` provides chronological pages:

1. **What happened?** Stage, lifecycle status, summary, timestamp, operation
   outcome, and verification status.
2. **Why this route?** The first level plus objective, decisions, selected
   components, resources, planned actions, operation reference, and unknowns.
3. **What supports it?** The full events, including original evidence, errors,
   and artifact references.

`render(task_id, level=..., format="json"|"markdown"|"html")` renders the same
trace. Lifecycle values are `planned`, `executed`, `verified`, `failed`,
`not_run`, and `inconclusive`. An executed event can have successful operation
outcome and `not_run` verification. A `verified` event requires passed declared
verification and evidence; the evidence still determines what was actually
tested. Rendering does not change those statuses. Trace persistence is distinct
from an adapter's transaction, so callers must reconcile interrupted operations
using canonical task checkpoints rather than assume trace completeness.

## Failure capsules

`FailureCapsule` preserves project identity, unknown or observed source revision,
environment information, errors, reproduction instructions, attempted repairs,
partial artifacts, unresolved hypotheses, suggested checks, and evidence.
Additional optional fields preserve the original objective, failed operation,
relevant inputs, observed software versions, and error signature. Conversion
also indexes the project identity and source revision for historical retrieval.
`capsule.to_knowledge_record(task_ids)` yields an appendable knowledge record.
`FailureCapsule.from_dict(record.metadata["capsule"])` restores it.

A capsule always has state `unresolved`. A repair attempt can report an observed
success, but that observation does not resolve the capsule or prove the whole
project works. A later validated result is a separate, linked record. No capsule
or model-generated repair proposal grants permission to execute code.

The focused `tests/test_memory_graph.py` suite verifies legacy database loading,
task isolation, historical retrieval bounds, applicability comparisons, explicit
reuse, atomic corrections, relationship scope, trace levels and rendering, and
failure-capsule round trips. These are controlled persistence tests; they do not
establish automatic diagnosis or repair of arbitrary real projects.

## Task checkpoints and recovery

`TaskStore` persists task snapshots, cancellation requests, and canonical operation
records. `checkpoint(task, operation)` commits the snapshot and its operation in
one transaction. Operation IDs cannot overwrite earlier evidence. Task state is
mutable by design; operation history is append-only through the API.

`Orchestrator(store, executor).run(task)` requires a fresh task, validates its
capability allowlist and dependency DAG, records the running checkpoint, and then
calls `executor(step)`. Execution is sequential. Dependencies require completed
steps. A step completes only if operation outcome is `succeeded` and declared
verification is `passed`; the executor remains responsible for the quality and
scope of its verification evidence. Successful execution with absent or
inconclusive verification blocks; failed verification fails the step.

Each step has 1–10 maximum attempts. Automatic retries require an explicitly
failed operation, `operation.planned["retry_safe"] is True`, and remaining
attempts. Partial execution and executor exceptions block for reconciliation.
Dependents of failed, blocked, or cancelled steps are blocked; independent steps
can still proceed.

`resume(task_id)` continues a safe saved checkpoint without repeating completed
steps. A completed checkpoint must reference a stored operation for the same
task and capability with successful execution and passed verification. Missing or
inconsistent evidence blocks for reconciliation. A running step found after
interruption is ambiguous: it is blocked and
annotated with an unknown, never silently replayed. Reconciliation and approving
a replacement task are caller responsibilities in this milestone. There is no
automatic rollback or exactly-once external side-effect guarantee.

`request_cancellation(task_id)` persists a cooperative request separately from
task snapshots. The orchestrator checks it between operations, preserving work
that already finished. It does not terminate an active subprocess. This engine
supports one owner per task; concurrent resume callers and distributed workers
are not supported. Process timeouts and resource limits belong to the adapters.
