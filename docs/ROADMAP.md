# Development roadmap

All items below are proposed until implemented and supported by recorded evidence.

## Next milestone: scoped planning and .NET qualification (v0.2)

1. Add a human-approved task planning boundary. Bind validated model actions to
   immutable capability/input scopes; persist the proposal separately from the
   approved plan. Close the evidence-to-model interpretation loop without giving
   model text execution authority.
2. Add a .NET adapter using controlled SDK-qualified fixtures. Separate build,
   artifact, functional, packaging, and installation checks. Test missing SDKs,
   dependency resolution failures, timeouts, partial outputs, and failed checks.
3. Add task ownership leases and checkpoint reconciliation before allowing multiple
   runner processes. Add schema migration/version compatibility and broader crash tests.
4. Record baseline/assisted human active time in a small repeated task study. Preserve
   negative results and unknowns; report machine durations separately.

Exit criteria: reviewed scoped plans cannot expand authority, the new adapter passes
its controlled matrix, interrupted tasks can be reconciled with evidence, and timing
claims have a recorded source. Existing Python tests must continue to pass.

## Later milestones

- Verified GitHub and HTTP acquisition connectors with revisions, integrity checks,
  quotas, provenance, interruption/resume, and explicit repository category contracts.
- Broader project analysis and dependency/build environment qualification without
  importing untrusted code. Expand supported project classes one fixture matrix at a time.
- Engineering memory ingestion from operations, environment-aware repair candidates,
  contradiction handling, and relevance evaluation. Historical success remains a hypothesis.
- Thin CLI/API synthesis bridges and reusable intermediate artifacts. Distinguish
  building an original component from creating a new application that uses it.
- Package and installation adapters with independent authorization and installation
  verification. Never infer functionality from a successful installer exit status.
- Inspect actual UIB/UIE interfaces and preserve working Rust components when appropriate.
- OS-enforced resource budgets, process-tree containment, trusted execution environments,
  fair scheduling with local model workloads, and model tokenizer-aware context budgeting.
- Review licensing and any future repository visibility change as separate owner decisions.
