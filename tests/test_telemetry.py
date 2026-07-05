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


# ---------------------------------------------------------------------------
# P15-2: MumeiClient subprocess span instrumentation (NoOp path)
# ---------------------------------------------------------------------------


def test_record_verify_duration_noop(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    telemetry.record_verify_duration(1.5)
    telemetry.record_verify_duration(0)
    telemetry.record_verify_duration(-1)


def test_mumei_client_verify_returns_dict_under_noop_span(monkeypatch, tmp_path):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    mm_file = tmp_path / "test.mm"
    mm_file.write_text("// dummy", encoding="utf-8")
    from agent.mumei_client import MumeiClient

    client = MumeiClient(mumei_bin="echo")
    result = client.verify(str(mm_file))
    assert isinstance(result, dict)
    assert "success" in result
    assert "report" in result
    assert "stdout" in result
    assert "stderr" in result
    assert "spec_code_mapping" in result


def test_mumei_client_check_returns_dict_under_noop_span(monkeypatch, tmp_path):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    mm_file = tmp_path / "test.mm"
    mm_file.write_text("// dummy", encoding="utf-8")
    from agent.mumei_client import MumeiClient

    client = MumeiClient(mumei_bin="echo")
    result = client.check(str(mm_file))
    assert isinstance(result, dict)
    assert "success" in result
    assert "stdout" in result
    assert "stderr" in result


def test_mumei_client_infer_effects_returns_dict_under_noop_span(monkeypatch, tmp_path):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    mm_file = tmp_path / "test.mm"
    mm_file.write_text("// dummy", encoding="utf-8")
    from agent.mumei_client import MumeiClient

    client = MumeiClient(mumei_bin="echo")
    result = client.infer_effects(str(mm_file))
    assert isinstance(result, dict)
    assert "success" in result
    assert "analysis" in result


def test_mumei_client_infer_contracts_returns_dict_under_noop_span(monkeypatch, tmp_path):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    mm_file = tmp_path / "test.mm"
    mm_file.write_text("// dummy", encoding="utf-8")
    from agent.mumei_client import MumeiClient

    client = MumeiClient(mumei_bin="echo")
    result = client.infer_contracts(str(mm_file))
    assert isinstance(result, dict)
    assert "success" in result
    assert "analysis" in result


def test_mumei_client_build_returns_dict_under_noop_span(monkeypatch, tmp_path):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    mm_file = tmp_path / "test.mm"
    mm_file.write_text("// dummy", encoding="utf-8")
    from agent.mumei_client import MumeiClient

    client = MumeiClient(mumei_bin="echo")
    result = client.build(str(mm_file))
    assert isinstance(result, dict)
    assert "success" in result
    assert "stdout" in result
    assert "stderr" in result


def test_mumei_client_build_with_emit_returns_dict_under_noop_span(monkeypatch, tmp_path):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    mm_file = tmp_path / "test.mm"
    mm_file.write_text("// dummy", encoding="utf-8")
    from agent.mumei_client import MumeiClient

    client = MumeiClient(mumei_bin="echo")
    result = client.build_with_emit(str(mm_file), "c-header")
    assert isinstance(result, dict)
    assert "success" in result
    assert "stdout" in result
    assert "stderr" in result


def test_mumei_client_verify_loss_vector_returns_dict_under_noop_span(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    mm_file = tmp_path / "test.mm"
    mm_file.write_text("// dummy", encoding="utf-8")
    from agent.mumei_client import MumeiClient

    client = MumeiClient(mumei_bin="echo")
    result = client.verify_loss_vector(str(mm_file))
    assert isinstance(result, dict)
    assert "success" in result
    assert "loss_vector" in result
    assert "stdout" in result
    assert "stderr" in result


def test_verify_duration_histogram_noop(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    hist = telemetry._verify_duration_histogram()
    assert isinstance(hist, telemetry._NoOpInstrument)
    hist.record(0.5)


# ---------------------------------------------------------------------------
# P15-3: Loop root span instrumentation (NoOp path)
# ---------------------------------------------------------------------------


def test_start_loop_span_noop(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    with telemetry.start_loop_span(
        "generate", max_retries=3, strategy="single",
    ) as span:
        assert isinstance(span, telemetry._NoOpSpan)
        span.set_attribute("mumei.loop.final_success", True)
        span.set_attribute("mumei.loop.attempt", 1)
        span.set_attribute("mumei.loop.stop_reason", "success")
        span.add_event("budget_decision", {"action_class": "verify"})


def test_add_thought_event_noop(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    telemetry.add_thought_event("initial_verify", {"thought.step_number": 1})
    telemetry.add_thought_event("llm_fix", None)


def test_thought_process_add_step_emits_event_noop(monkeypatch):
    """ThoughtProcess.add_step emits a span event under NoOp without error."""
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    from agent.thought_log import ThoughtProcess

    tp = ThoughtProcess(target_file="test.mm")
    step = tp.add_step(action="initial_verify", verification_success=True)
    assert step.action == "initial_verify"
    assert step.step_number == 1
    step2 = tp.add_step(action="llm_fix", verification_success=False, fix_strategy="llm")
    assert step2.step_number == 2
    # to_dict output must be unchanged
    d = tp.to_dict()
    assert d["target_file"] == "test.mm"
    assert len(d["steps"]) == 2
    assert d["steps"][0]["action"] == "initial_verify"


def test_generate_code_noop_span(monkeypatch):
    """generate_code with NoOp span returns the same result and to_dict."""
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    from agent.strategies.generate_strategy import generate_code
    from agent.thought_log import ThoughtProcess

    # Build a fake client and mumei_client that simulate immediate success
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content="```mumei\natom add(a: i64, b: i64) -> i64\n  requires: true;\n  ensures: result == a + b;\n  body: { a + b };\n```"
        ))],
        usage=SimpleNamespace(total_tokens=10),
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_: fake_response)
        )
    )

    class ImmediateSuccessClient:
        def check(self, _path):
            return {"success": True, "stdout": "", "stderr": ""}

        def verify(self, _path):
            return {
                "success": True,
                "stdout": "",
                "stderr": "",
                "report": {"z3_check_result": "unsat"},
                "spec_code_mapping": None,
            }

        def infer_effects(self, _path):
            return {"success": True, "analysis": {}}

        def infer_contracts(self, _path):
            return {"success": True, "analysis": {}}

    tp = ThoughtProcess(target_file="test.mm")
    spec = {"name": "add", "params": [{"name": "a", "type": "i64"}, {"name": "b", "type": "i64"}]}
    code, verified = generate_code(
        fake_client, "test-model", spec,
        config_max_retries=1,
        mumei_client=ImmediateSuccessClient(),
        thought_process=tp,
    )
    assert isinstance(code, str)
    assert len(code) > 0
    d = tp.to_dict()
    assert "target_file" in d
    assert isinstance(d["steps"], list)


def test_self_correction_loop_noop_span(monkeypatch, tmp_path):
    """StructuredFeedbackSelfCorrectionLoop runs under NoOp span."""
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    from agent.self_correction import StructuredFeedbackSelfCorrectionLoop

    source = tmp_path / "test.mm"
    source.write_text("// dummy", encoding="utf-8")

    class AlwaysPass:
        def verify(self, _path):
            return {
                "success": True,
                "report": {"z3_check_result": "unsat"},
                "stdout": "",
                "stderr": "",
            }

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_: None)
        )
    )
    loop = StructuredFeedbackSelfCorrectionLoop(
        fake_client, "test", AlwaysPass(),
        max_retries=2, convergence_threshold=2,
    )
    feedback = {"status": "verification_failed", "error_type": "test"}
    result = loop.run(str(source), feedback)
    d = result.to_dict()
    assert d["converged"] is True
    assert d["stop_reason"] == "converged"
    assert "self_correction_metadata" in d


def test_self_correction_strategy_noop_span(monkeypatch, tmp_path):
    """SelfCorrectionStrategy.run under NoOp span returns correct to_dict."""
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    from agent.strategies.self_correction_strategy import SelfCorrectionStrategy

    source = tmp_path / "test.mm"
    source.write_text("// dummy", encoding="utf-8")

    class AlwaysPass:
        def verify(self, _path):
            return {
                "success": True,
                "report": {"z3_check_result": "unsat"},
                "stdout": "",
                "stderr": "",
            }

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_: None)
        )
    )
    strategy = SelfCorrectionStrategy(
        fake_client, "test", AlwaysPass(),
        max_repairs=2, required_successes=2,
    )
    result = strategy.run(str(source))
    d = result.to_dict()
    assert d["converged"] is True
    assert d["stop_reason"] == "converged"
    assert "self_correction_metadata" in d


# ---------------------------------------------------------------------------
# P15-4: MCP server entry-span helpers (NoOp path)
# ---------------------------------------------------------------------------


def test_extract_trace_context_none_when_disabled(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    carrier = {"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"}
    # Disabled -> no parent context, but must never raise.
    assert telemetry.extract_trace_context(carrier) is None


def test_extract_trace_context_none_for_empty_carrier(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    assert telemetry.extract_trace_context(None) is None
    assert telemetry.extract_trace_context({}) is None


def test_inject_then_extract_roundtrip_noop(monkeypatch):
    """inject leaves no traceparent when disabled; extract still yields None."""
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    carrier: dict = {}
    telemetry.inject_trace_context(carrier)
    assert "traceparent" not in carrier
    assert telemetry.extract_trace_context(carrier) is None


def test_start_tool_span_noop(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    with telemetry.start_tool_span(
        "forge_task", carrier=None, dry_run=True, task_id="t1",
    ) as span:
        assert isinstance(span, telemetry._NoOpSpan)
        span.set_attribute("mcp.tool.status", "success")
        span.add_event("event", {"k": "v"})


def test_start_tool_span_noop_with_carrier(monkeypatch):
    """A caller-supplied trace carrier must not break the NoOp span."""
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    carrier = {"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"}
    with telemetry.start_tool_span("heal_file", carrier=carrier) as span:
        assert isinstance(span, telemetry._NoOpSpan)


def test_start_tool_span_records_exception_and_reraises(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    import pytest

    with pytest.raises(ValueError):
        with telemetry.start_tool_span("self_correct"):
            raise ValueError("boom")


def test_carrier_from_ctx_none_without_meta():
    from agent.mcp_server_helpers import _carrier_from_ctx

    assert _carrier_from_ctx(None) is None

    class _NoMeta:
        @property
        def request_context(self):  # pragma: no cover - trivial
            raise RuntimeError("no request context outside a request")

    assert _carrier_from_ctx(_NoMeta()) is None


def test_carrier_from_ctx_extracts_meta_fields():
    from agent.mcp_server_helpers import _carrier_from_ctx
    from mcp.types import RequestParams

    meta = RequestParams.Meta.model_validate(
        {
            "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
            "tracestate": "vendor=1",
        }
    )
    ctx = SimpleNamespace(request_context=SimpleNamespace(meta=meta))
    carrier = _carrier_from_ctx(ctx)
    assert carrier is not None
    assert carrier["traceparent"].startswith("00-")
    assert carrier["tracestate"] == "vendor=1"


def test_carrier_from_ctx_none_for_empty_meta():
    from agent.mcp_server_helpers import _carrier_from_ctx
    from mcp.types import RequestParams

    ctx = SimpleNamespace(
        request_context=SimpleNamespace(meta=RequestParams.Meta())
    )
    assert _carrier_from_ctx(ctx) is None
