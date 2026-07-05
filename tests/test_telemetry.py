"""Tests for the P15 OpenTelemetry helpers and their NoOp fallback.

These run in the default environment where the ``otel`` extra is not
installed, so they exercise the zero-dependency NoOp path that must keep the
agent's existing flows byte-for-byte identical.
"""
from __future__ import annotations

from types import SimpleNamespace

from agent import telemetry
from agent.llm_provider import McpSamplingLLMProvider, OpenAILLMProvider


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    assert telemetry.is_enabled() is False


def test_noop_tracer_and_meter(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    tracer = telemetry.get_tracer("probe")
    assert isinstance(tracer, telemetry._NoOpTracer)
    with tracer.start_as_current_span("llm.complete") as span:
        # NoOp span accepts the OTel API surface without raising.
        span.set_attribute("gen_ai.request.model", "gpt-4o")
        span.add_event("event", {"k": "v"})
    meter = telemetry.get_meter("probe")
    assert isinstance(meter, telemetry._NoOpMeter)
    counter = meter.create_counter("gen_ai.usage.total_tokens")
    counter.add(5, {"gen_ai.request.model": "gpt-4o"})


def test_record_llm_tokens_noop(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    # No exporter configured and OTel disabled -> must be a silent no-op.
    telemetry.record_llm_tokens(123, model="gpt-4o")
    telemetry.record_llm_tokens(0)
    telemetry.record_llm_tokens(-5)


def test_otlp_protocol_env(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_PROTOCOL", raising=False)
    assert telemetry._otlp_protocol() == "grpc"
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
    assert telemetry._otlp_protocol() == "http/protobuf"


def test_exporter_builders_return_none_without_extra():
    # In the default env the otel exporter packages are not installed, so the
    # builders must swallow the ImportError and return None (never raise).
    assert telemetry._build_span_exporter() is None
    assert telemetry._build_metric_exporter() is None


def test_response_token_count_accepts_model():
    from types import SimpleNamespace

    from agent.strategies.fix_strategy_helpers import response_token_count

    response = SimpleNamespace(usage=SimpleNamespace(total_tokens=21))
    assert response_token_count(response, "gpt-4o") == 21
    assert response_token_count(response) == 21


def test_inject_trace_context_passthrough_when_disabled(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    carrier = {"mumei_agent_llm_provider": "mcp_sampling"}
    result = telemetry.inject_trace_context(carrier)
    assert result is carrier
    assert "traceparent" not in result


def test_openai_provider_complete_returns_text_with_noop_span(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)

    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))],
        usage=SimpleNamespace(total_tokens=17),
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_: response)
        )
    )
    provider = OpenAILLMProvider(config=None, client=fake_client)
    assert provider.complete([{"role": "user", "content": "hi"}], "gpt-4o") == "hello"


def test_mcp_sampling_metadata_has_no_traceparent_when_disabled(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)

    recorded: dict = {}

    def create_message(messages, **kwargs):
        recorded["kwargs"] = kwargs
        from mcp import types as mcp_types

        return mcp_types.CreateMessageResult(
            role="assistant",
            content=mcp_types.TextContent(type="text", text="done"),
            model="client-model",
        )

    ctx = SimpleNamespace(
        session=SimpleNamespace(
            create_message=create_message,
            _client_params={"capabilities": {"sampling": {}}},
        )
    )
    provider = McpSamplingLLMProvider(ctx)
    assert provider.complete([{"role": "user", "content": "hi"}], "gpt-4o") == "done"
    metadata = recorded["kwargs"]["metadata"]
    assert metadata == {"mumei_agent_llm_provider": "mcp_sampling"}
    assert "traceparent" not in metadata
