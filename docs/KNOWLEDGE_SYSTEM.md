# Engineering knowledge and failure memory

SCE v0.1 stores original engineering observations with their provenance. A
record is evidence for a particular claim under particular conditions; it does
not confer execution authority or establish compatibility with another project.

`KnowledgeRecord` holds a claim, source observations, explicit task associations,
supporting and contradictory evidence, environment conditions, limitations, and
links to other records. Supported kinds include project references, observations,
repair recipes, build configurations, incompatibilities, artifact references, and
failure capsules. All kinds use the same provenance requirements. A repair recipe
is preserved knowledge, not an executable or verified capability.

Every `Provenance` requires a source, observation method, and observation time.
Source revision and SHA-256 are optional and remain unknown when not observed.
An observation timestamp records when evidence was seen, not when the source was
created. Resource identities and references do not depend on their storage path.

## Persistence and bounded retrieval

`KnowledgeStore(path)` uses SQLite at the explicitly selected path. It can share
the task database; it does not choose a fallback volume. Inserts are append-only
through this API, and duplicate IDs fail instead of overwriting earlier evidence.
Corrections are new records linked through `related_record_ids` and contradictory
evidence. SQLite file access is not a tamper-proof audit system.

```python
from sce.knowledge import KnowledgeRecord, KnowledgeStore, Provenance

memory = KnowledgeStore(".sce/tasks.sqlite3")
record = KnowledgeRecord(
    claim="The controlled fixture produced the expected greeting.",
    provenance=[Provenance(source="operation:build-001", method="stdout comparison")],
    task_ids=["task-001"],
    environment={"fixture_revision": "v1"},
    limitations=["This observation applies only to this controlled fixture."],
)
memory.append(record)
context = memory.retrieve("task-001", "greeting", limit=8, max_chars=12000)
```

Retrieval requires an explicit task ID. It applies literal substring matching to
claims, considers at most the newest 128 matching records, and returns complete
records within a maximum count and serialized character budget. SQLite LIKE is
case-insensitive for ASCII characters; non-ASCII case folding is not provided.
Wildcard characters in queries are escaped. Oversize records are omitted rather
than separating claims from provenance. An empty result does not prove that no
relevant knowledge exists. Character budgets are not tokenizer-specific model
context limits; AI providers must enforce their own additional context bound.

This milestone does not implement embeddings, automatic relevance inference,
cross-task permission propagation, automatic repair selection, or reliable
deduction that a historical build configuration will work again.

## Failure capsules

`FailureCapsule` preserves project identity, unknown or observed source revision,
environment information, errors, reproduction instructions, attempted repairs,
partial artifacts, unresolved hypotheses, suggested checks, and evidence.
`capsule.to_knowledge_record(task_ids)` yields an appendable knowledge record.
`FailureCapsule.from_dict(record.metadata["capsule"])` restores it.

A capsule always has state `unresolved`. A repair attempt can report an observed
success, but that observation does not resolve the capsule or prove the whole
project works. A later validated result is a separate, linked record. No capsule
or model-generated repair proposal grants permission to execute code.

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
