# Local AI and resource boundaries

SCE v0.1 defines a provider-independent `AIProvider` protocol with `probe()` and
`propose(TaskContext)` operations. The implemented `LoopbackAIProvider` uses the
OpenAI-compatible HTTP wire format with a local server. It does not use the
OpenAI hosted API, require an OpenAI API key, or fall back to a remote service.

`http://127.0.0.1:8080` and `qwen3-coder-local` are configuration candidates.
Availability is an observation made at request time. The provider checks
`GET /v1/models` before each `POST /v1/chat/completions` request and requires the
configured model identifier to appear in the result. A successful listing does
not verify model reasoning quality, model weight identity, GPU placement, or
compatibility with every completion option. Configure the actual server model
identifier explicitly; SCE never silently picks a different listed model.

Only literal loopback IP addresses are accepted. Both IPv4 and IPv6 loopback
addresses are supported. Hostnames, remote addresses, embedded credentials,
queries, and arbitrary URL paths are rejected. Environment proxy settings are
ignored and redirects are rejected, preventing these mechanisms from forwarding
task context to a remote endpoint. The accepted optional base path is `/v1`.

## Model proposal and task authority

Model output must be one strict JSON object:

```json
{
  "actions": [
    {
      "capability_id": "python.build",
      "inputs": {
        "source": "approved-source",
        "output_root": "approved-output",
        "trusted": true
      }
    }
  ],
  "rationale": "Use the host-approved controlled fixture."
}
```

The host must supply `allowed_capabilities` and a task input validator to
`validate_proposal`. Validation checks all of the following before returning a
detached proposal:

1. Strict shape, duplicate-field rejection, action count, and serialized size.
2. Capability membership in the human-authorized task scope.
3. Registry implementation status, current availability, and exact input contract.
4. Task-scoped authorization of every input value, including source locations,
   output destinations, source content, and trust flags.

`ExactInputScope` is the v0.1 conservative task validator. It accepts only input
sets already approved by the host. A model cannot change a source path, output
path, trust flag, or source content merely because it names an allowed
capability. New free-form scope validators are trusted host code and must
preserve these boundaries. They must return `None` on success and raise on
failure; a boolean return is rejected to avoid ambiguous authorization.

Validation performs no build, shell execution, installation, or other adapter
operation. Dispatch remains the orchestrator's responsibility. Revalidate at
dispatch if task scope, inputs, or registry state changed. The model cannot
register capabilities or establish trust for acquired source. A valid proposal
is not evidence that an action executed or that its output works.

## Bounded retrieval and requests

`TaskContext` accepts an objective and a bounded sequence of retrieved record
strings. No repository loader injects whole source trees. The host selects the
records and should retain their provenance in the task's knowledge store.
Default limits are 8 records, 16,000 serialized context characters, an 8,192
context-token budget, 1,024 requested output tokens, 131,072 response bytes,
8 proposed actions, and a 30-second HTTP operation timeout.

The client uses serialized input UTF-8 byte length plus a protocol allowance
as a deliberately conservative input budget. This is not an exact tokenizer
measurement. The provider applies its actual tokenizer and must reject requests
that exceed its capacity. SCE requests `max_tokens` for output and rejects
truncated or abnormally finished responses. HTTP errors, malformed JSON,
oversized responses, absent models, and invalid proposals remain failures.

The v0.1 implementation covers proposal generation and validation, not an
autonomous model-driven execution loop. Structured post-execution model
interpretation, model-side tool calling, streaming, and automatic model loading
are future work. Model responses have no authority to execute tools directly.

## Resource observations and limits

`discover_environment(storage_path, probe_gpu=False)` records timestamped Python,
platform, logical CPU count, CPU description when available, physical memory,
the specifically requested storage location, and discovered tool paths. Optional
`probe_gpu=True` reads NVIDIA device memory through `nvidia-smi`; absence or
failure stays explicit. No device or memory amount is inferred from previously
reported specifications. A missing storage destination is reported as missing;
the observer never creates or substitutes another location.

`ResourceLimits` configures RAM bytes, GPU bytes, model context tokens, worker
count, build parallelism, temporary bytes, execution timeout, and retries.
`enforcement_status()` explains enforcement per field. RAM, GPU, and temporary
storage budgets are advisory because v0.1 provides no operating-system memory
isolation or disk quota. Scheduling, builder concurrency, retries, and timeouts
depend on the corresponding caller consuming its configured limit. Model
context limits do not configure model offload. Environment observations do not
reserve capacity or prevent contention with another process or Codex session.

## Validation evidence and limitations

`tests/test_ai.py` uses a temporary loopback HTTP fixture to exercise the local
wire protocol; it does not run a language model. Tests cover exact model
matching, probe-before-chat ordering, local endpoint constraints, redirects,
HTTP failures, request/response bounds, malformed and truncated output, and
strict task input authorization. `tests/test_resources.py` covers limit
validation, truthful advisory labels, actual local environment observations,
missing storage, and absent GPU tooling.

A live model-list observation and controlled HTTP tests do not establish live
Qwen inference compatibility or quality. Record live inference experiments
separately, including server configuration, resource contention, result, and
unknowns. Do not load or reconfigure the model merely to make a probe pass.

### Live compatibility experiment: 2026-10-15

The installed CLI checked the local model listing at 12:15:14 UTC. The endpoint
`http://127.0.0.1:8080` listed the configured `qwen3-coder-local` model, and
`sce ai-probe` exited zero. One bounded `sce ai-propose` request then asked:

> Report whether any execution action is authorized in this proposal-only request.

No execution capability was authorized and no source context was supplied.
The proposal request exited with code 2 after 30.314 seconds and reported:

```text
Local provider request failed at /chat/completions: timed out
```

Live proposal compatibility remains **unverified**. This observed timeout does
not identify its cause: model load, server contention, prompt processing, and
other server conditions were not diagnosed. No retry or model reconfiguration
was performed. No model-driven adapter execution occurred. Post-execution
report interpretation remains roadmap work.

The exact commands, timestamps, probe response, stderr, and verification result
are preserved in [local-ai-smoke.json](evidence/local-ai-smoke.json).
