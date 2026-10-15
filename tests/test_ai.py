from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest

from sce.ai import (ExactInputScope, LocalAIConfig, LoopbackAIProvider, Proposal, ProposalError,
                    ProviderError, TaskContext, validate_proposal)
from sce.capabilities import default_registry


ACTION = {"capability_id": "python.build", "inputs": {"source": "approved-source",
          "output_root": "approved-output", "trusted": True}}


def proposal_json(action=ACTION):
    return json.dumps({"actions": [action], "rationale": "Use the already authorized fixture."})


@contextmanager
def fake_provider(*, models=None, content=None, status=200, redirect=False, finish="stop"):
    calls = []
    models = [{"id": "test-model"}] if models is None else models

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            calls.append((self.path, None))
            if redirect:
                self.send_response(302)
                self.send_header("Location", "http://example.invalid/v1/models")
                self.end_headers()
                return
            self.respond({"data": models})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, body))
            self.respond({"choices": [{"finish_reason": finish,
                                       "message": {"content": content if content is not None else proposal_json()}}]})

        def respond(self, body):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = LocalAIConfig(endpoint=f"http://127.0.0.1:{server.server_port}", model_id="test-model")
    try:
        yield config, calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_proposal_registry_and_exact_task_scope():
    proposal = Proposal.from_json(proposal_json())
    scope = ExactInputScope({"python.build": [ACTION["inputs"]]})
    validated = validate_proposal(proposal, default_registry(), {"python.build"}, scope)
    assert validated.as_dict() == proposal.as_dict()
    assert validated is not proposal


@pytest.mark.parametrize("raw", [
    '```json\n{}\n```', '{"actions":[],"rationale":"","shell":"whoami"}',
    '{"actions":[],"rationale":"","rationale":"duplicate"}',
    '{"actions":[],"rationale":NaN}',
    '{"actions":[{"capability_id":"shell;command","inputs":{}}],"rationale":""}',
    '{"actions":[{"capability_id":"python.build","inputs":{},"command":"whoami"}],"rationale":""}',
])
def test_strict_proposal_json(raw):
    with pytest.raises(ProposalError):
        Proposal.from_json(raw)


def test_proposal_budgets():
    with pytest.raises(ProposalError):
        Proposal.from_json(proposal_json(), max_chars=10)
    with pytest.raises(ProposalError):
        Proposal.from_json(json.dumps({"actions": [ACTION, ACTION], "rationale": ""}), max_actions=1)


@pytest.mark.parametrize("modified", [
    {"source": "outside-task", "output_root": "approved-output", "trusted": True},
    {"source": "approved-source", "output_root": "outside-task", "trusted": True},
    {"source": "approved-source", "output_root": "approved-output", "trusted": False},
    {"source": "approved-source", "output_root": "approved-output", "trusted": True, "source_code": "evil"},
])
def test_model_cannot_expand_paths_or_source_authority(modified):
    action = {"capability_id": "python.build", "inputs": modified}
    with pytest.raises(ProposalError):
        validate_proposal(Proposal.from_json(proposal_json(action)), default_registry(), {"python.build"},
                          ExactInputScope({"python.build": [ACTION["inputs"]]}))


def test_proposed_unavailable_capability_is_rejected():
    action = {"capability_id": "dotnet.build", "inputs": {"source": "s", "output_root": "o"}}
    with pytest.raises(ProposalError, match="unavailable"):
        validate_proposal(Proposal.from_json(proposal_json(action)), default_registry(), {"dotnet.build"},
                          ExactInputScope({"dotnet.build": [action["inputs"]]}))


def test_scope_validation_is_mandatory_and_capability_must_be_allowed():
    proposal = Proposal.from_json(proposal_json())
    with pytest.raises(ProposalError, match="required"):
        validate_proposal(proposal, default_registry(), {"python.build"}, None)
    with pytest.raises(ProposalError, match="outside task scope"):
        validate_proposal(proposal, default_registry(), set(), ExactInputScope({}))


@pytest.mark.parametrize("allowed", ["python.build.extra", "python.build", {"python.build": True},
                                     ["python.build", ""], ["python.build", " "], ["python.build", 1]])
def test_scope_requires_collection_of_nonempty_identifiers(allowed):
    with pytest.raises(ProposalError, match="collection"):
        validate_proposal(Proposal.from_json(proposal_json()), default_registry(), allowed,
                          ExactInputScope({"python.build": [ACTION["inputs"]]}))


@pytest.mark.parametrize("allowed", [["python.build"], ("python.build",), {"python.build"}, frozenset({"python.build"})])
def test_scope_accepts_explicit_identifier_collections(allowed):
    validated = validate_proposal(Proposal.from_json(proposal_json()), default_registry(), allowed,
                                  ExactInputScope({"python.build": [ACTION["inputs"]]}))
    assert validated.actions[0].capability_id == "python.build"


@pytest.mark.parametrize("endpoint", ["http://example.com", "http://localhost:8080", "file:///tmp/model",
    "http://127.0.0.1:8080/?key=x", "http://user:password@127.0.0.1:8080", "http://192.168.1.2:8080",
    "http://127.0.0.1:0", "http://127.0.0.1:8080/arbitrary"])
def test_only_literal_loopback_base_urls_are_allowed(endpoint):
    with pytest.raises(ValueError):
        LocalAIConfig(endpoint=endpoint)


def test_probes_exact_model_before_bounded_proposal():
    with fake_provider() as (config, calls):
        provider = LoopbackAIProvider(config)
        proposal = provider.propose(TaskContext("Build the authorized fixture", ("bounded observation",)))
        assert proposal.actions[0].capability_id == "python.build"
        assert [call[0] for call in calls] == ["/v1/models", "/v1/chat/completions"]
        body = calls[1][1]
        assert body["model"] == "test-model"
        assert body["max_tokens"] == config.max_output_tokens
        assert len(body["messages"]) == 2


def test_missing_configured_model_prevents_inference():
    with fake_provider(models=[{"id": "different-model"}]) as (config, calls):
        provider = LoopbackAIProvider(config)
        with pytest.raises(ProviderError, match="not listed"):
            provider.propose(TaskContext("Build fixture"))
        assert [call[0] for call in calls] == ["/v1/models"]


def test_http_failure_is_reported_without_inference():
    with fake_provider(status=503) as (config, calls):
        availability = LoopbackAIProvider(config).probe()
        assert not availability.available
        assert "HTTP 503" in availability.reason
        assert len(calls) == 1


def test_redirects_are_rejected():
    with fake_provider(redirect=True) as (config, calls):
        availability = LoopbackAIProvider(config).probe()
        assert not availability.available
        assert "redirect rejected" in availability.reason
        assert len(calls) == 1


def test_response_budget_is_enforced():
    with fake_provider(models=[{"id": "x" * 1000}]) as (config, calls):
        availability = LoopbackAIProvider(replace(config, max_response_bytes=100)).probe()
        assert not availability.available
        assert "byte budget" in availability.reason


@pytest.mark.parametrize("context", [TaskContext("x" * 20000), TaskContext("x", tuple("r" for _ in range(9))),
                                      TaskContext("x" * 8000), TaskContext("")])
def test_context_budgets_fail_before_network(context):
    provider = LoopbackAIProvider(LocalAIConfig(endpoint="http://127.0.0.1:1"))
    with pytest.raises(ValueError):
        provider.propose(context)


def test_invalid_model_proposal_is_not_accepted():
    with fake_provider(content="I'll run a shell command") as (config, calls):
        with pytest.raises(ProviderError, match="Invalid local proposal"):
            LoopbackAIProvider(config).propose(TaskContext("Build fixture"))


def test_truncated_model_response_is_not_accepted():
    with fake_provider(finish="length") as (config, calls):
        with pytest.raises(ProviderError, match="did not finish normally"):
            LoopbackAIProvider(config).propose(TaskContext("Build fixture"))
