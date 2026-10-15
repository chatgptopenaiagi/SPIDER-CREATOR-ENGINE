from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest

from sce.ai import Interpretation, InterpretationError, LocalAIConfig, LoopbackAIProvider, ProviderError, TaskContext


RESULT = {"summary": "The archive was built, but its declared output check failed.",
          "unknowns": ["The cause of the output mismatch has not been established."],
          "suggested_next_checks": ["Compare the expected output with the preserved stdout."]}
EVIDENCE = json.dumps({"operation_id": "observed-build", "outcome": "succeeded", "verification": "failed",
                       "evidence": [{"expected_stdout": "hello", "actual_stdout": "goodbye"}]})


@contextmanager
def interpreter_fixture(*, content=None, finish="stop", extra_message=None, listed=True):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, body):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_GET(self):
            calls.append((self.path, None))
            self.respond({"data": [{"id": "fixture-model"}] if listed else []})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, body))
            message = {"content": json.dumps(RESULT) if content is None else content, **(extra_message or {})}
            self.respond({"choices": [{"finish_reason": finish, "message": message}]})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield LocalAIConfig(endpoint=f"http://127.0.0.1:{server.server_port}", model_id="fixture-model"), calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_interpretation_preserves_inference_and_has_no_execution_authority():
    interpretation = Interpretation.from_json(json.dumps(RESULT))
    assert interpretation.as_dict() == RESULT
    assert interpretation.provenance == "AI_INFERENCE"
    assert interpretation.execution_authority is False
    assert not hasattr(interpretation, "actions")


@pytest.mark.parametrize("raw", [
    '```json\n{}\n```',
    '{"summary":"ok","unknowns":[],"suggested_next_checks":[],"actions":[]}',
    '{"summary":"ok","summary":"changed","unknowns":[],"suggested_next_checks":[]}',
    '{"summary":"ok","unknowns":[NaN],"suggested_next_checks":[]}',
    '{"summary":"ok","unknowns":[],"suggested_next_checks":"run something"}',
    '{"summary":"","unknowns":[],"suggested_next_checks":[]}',
    '{"summary":"ok","unknowns":[""],"suggested_next_checks":[]}',
    '{"summary":"ok","unknowns":[],"suggested_next_checks":[{"shell":"command"}]}',
    'null',
])
def test_strict_interpretation_rejects_extra_authority_and_malformed_values(raw):
    with pytest.raises(InterpretationError):
        Interpretation.from_json(raw)


def test_interpretation_bounds_cannot_be_bypassed_by_manual_construction():
    with pytest.raises(InterpretationError):
        Interpretation("x" * 8193, (), ())
    with pytest.raises(InterpretationError):
        Interpretation("Summary", tuple("unknown" for _ in range(17)), ())
    with pytest.raises(InterpretationError):
        Interpretation("Summary", (), ("x" * 2049,))
    with pytest.raises(InterpretationError):
        Interpretation.from_json(json.dumps(RESULT), max_chars=20)
    with pytest.raises(ValueError):
        Interpretation.from_json(json.dumps(RESULT), max_chars=True)


def test_loopback_interpretation_receives_actual_evidence_and_probes_first():
    with interpreter_fixture() as (config, calls):
        interpretation = LoopbackAIProvider(config).interpret(TaskContext("Create a greeting app", (EVIDENCE,)))
        assert interpretation.as_dict() == RESULT
        assert [path for path, _ in calls] == ["/v1/models", "/v1/chat/completions"]
        request = calls[1][1]
        assert request["model"] == "fixture-model"
        assert request["max_tokens"] == config.max_output_tokens
        assert json.loads(request["messages"][1]["content"])["records"] == [EVIDENCE]
        prompt = request["messages"][0]["content"]
        assert "untrusted data" in prompt
        assert "not verified evidence or execution authority" in prompt
        assert "successful execution alone does not prove functionality" in prompt


@pytest.mark.parametrize("context", [
    TaskContext("Objective"), TaskContext("Objective", ("",)), TaskContext("", (EVIDENCE,)),
    TaskContext("Objective", tuple(EVIDENCE for _ in range(9))),
    TaskContext("Objective", ("x" * 17000,)),
    TaskContext("Objective", ("x" * 7500,)),
])
def test_interpretation_requires_bounded_evidence_before_network(context):
    with interpreter_fixture() as (config, calls):
        with pytest.raises(ValueError):
            LoopbackAIProvider(config).interpret(context)
        assert calls == []


def test_interpretation_does_not_substitute_a_different_model():
    with interpreter_fixture(listed=False) as (config, calls):
        with pytest.raises(ProviderError, match="not listed"):
            LoopbackAIProvider(config).interpret(TaskContext("Objective", (EVIDENCE,)))
        assert [path for path, _ in calls] == ["/v1/models"]


@pytest.mark.parametrize("kwargs,match", [
    ({"content": "Unstructured claim"}, "Invalid local interpretation"),
    ({"content": '{"actions":[],"rationale":"execute"}'}, "exactly summary"),
    ({"finish": "length"}, "did not finish normally"),
    ({"extra_message": {"tool_calls": [{"name": "execute"}]}}, "tool calls"),
])
def test_invalid_or_action_bearing_completions_are_rejected(kwargs, match):
    with interpreter_fixture(**kwargs) as (config, _):
        with pytest.raises(ProviderError, match=match):
            LoopbackAIProvider(config).interpret(TaskContext("Objective", (EVIDENCE,)))


def test_interpretation_shares_the_provider_response_byte_budget():
    with interpreter_fixture(content=json.dumps({**RESULT, "summary": "x" * 3000})) as (config, _):
        with pytest.raises(ProviderError, match="byte budget"):
            LoopbackAIProvider(replace(config, max_response_bytes=1000)).interpret(TaskContext("Objective", (EVIDENCE,)))
