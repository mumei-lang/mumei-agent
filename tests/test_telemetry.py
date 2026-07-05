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


# ---------------------------------------------------------------------------
# P15-5: OTel Metrics instrument helpers (NoOp path)
# ---------------------------------------------------------------------------


def test_record_first_pass_success_rate_noop(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    telemetry.record_first_pass_success_rate(0.75)
    telemetry.record_first_pass_success_rate(0.0)


def test_record_z3_unknown_noop(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    telemetry.record_z3_unknown()
    telemetry.record_z3_unknown(3)
    telemetry.record_z3_unknown(0)
    telemetry.record_z3_unknown(-1)


def test_record_decidable_fragment_warning_noop(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    telemetry.record_decidable_fragment_warning()
    telemetry.record_decidable_fragment_warning(tags=["nonlinear", "quantifier"])
    telemetry.record_decidable_fragment_warning(0)


def test_record_fix_attempt_and_success_noop(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    telemetry.record_fix_attempt("postcondition_violation")
    telemetry.record_fix_success("postcondition_violation")
    telemetry.record_fix_attempt()
    telemetry.record_fix_success()


def test_record_harness_result_noop(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    telemetry.record_harness_result(
        tokens_to_success=500,
        solver_seconds_to_success=2.5,
        spec_drift_score=0.1,
        attributes={"stage": "forge", "module": "verification_gate", "profile": "full"},
    )
    telemetry.record_harness_result(0, 0.0, 0.0)


def test_record_lean_bridge_result_noop(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    telemetry.record_lean_bridge_result(duration_seconds=5.0, verified_count=3)
    telemetry.record_lean_bridge_result(duration_seconds=0.0, error_code="timeout")
    telemetry.record_lean_bridge_result(duration_seconds=1.0, verified_count=0, error_code=None)


def test_metrics_record_attempt_emits_otel_noop(monkeypatch):
    """Metrics.record_attempt/record_success work unchanged under NoOp."""
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    from agent.metrics import Metrics

    m = Metrics()
    m.record_attempt("postcondition_violation")
    m.record_success("postcondition_violation")
    d = m.to_dict()
    assert d["total_attempts"] == 1
    assert d["successes"] == 1
    assert d["by_violation_type"]["postcondition_violation"]["attempts"] == 1
    assert d["by_violation_type"]["postcondition_violation"]["successes"] == 1


def test_metrics_record_verification_time_emits_otel_noop(monkeypatch):
    """Metrics.record_verification_time preserves to_dict under NoOp."""
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    from agent.metrics import Metrics

    m = Metrics()
    m.record_verification_time(1.5)
    m.record_verification_time(2.0, dense_properties=True)
    d = m.to_dict()
    assert d["verification_times_seconds"] == [1.5, 2.0]
    assert d["dense_verification_times_seconds"] == [2.0]


def test_metrics_record_new_spec_emits_otel_noop(monkeypatch):
    """Metrics.record_new_spec preserves to_dict under NoOp."""
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    from agent.metrics import Metrics

    m = Metrics()
    m.record_new_spec(
        ["nonlinear"],
        outside_decidable_fragment=True,
        z3_unknown=True,
        first_pass_verified=False,
    )
    m.record_new_spec(first_pass_verified=True)
    d = m.to_dict()
    assert d["outside_decidable_fragment_warnings"] == 1
    assert d["z3_unknowns"] == 1
    assert d["first_pass_verification_attempts"] == 2
    assert d["first_pass_verification_successes"] == 1
    assert d["new_spec_attempts"] == 2


def test_harness_metrics_record_stage_emits_otel_noop(monkeypatch):
    """HarnessMetrics.record_stage preserves aggregate_metrics under NoOp."""
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    from agent.harness_metrics import HarnessMetrics

    hm = HarnessMetrics.from_profile("verifier")
    hm.record_stage(
        "forge",
        module="verification_gate",
        verification_gate=True,
        tokens_to_success=300,
        solver_seconds_to_success=1.25,
        spec_drift_score=0.2,
    )
    agg = hm.aggregate_metrics()
    assert agg["profile"] == "verifier"
    assert len(agg["records"]) == 1
    assert agg["records"][0]["tokens_to_success"] == 300
    assert agg["records"][0]["solver_seconds_to_success"] == 1.25
    assert agg["records"][0]["spec_drift_score"] == 0.2
    assert agg["by_stage"]["forge"]["tokens_to_success"] == 300


def test_harness_metrics_record_result_emits_otel_noop(monkeypatch):
    """HarnessMetrics.record_result preserves aggregate_metrics under NoOp."""
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    from agent.harness_metrics import HarnessMetrics

    hm = HarnessMetrics.from_profile("basic")
    hm.record_result(
        "generate",
        success=True,
        tokens_to_success=100,
        solver_seconds_to_success=0.5,
        spec_drift_score=0.05,
    )
    agg = hm.aggregate_metrics()
    assert agg["profile"] == "basic"
    assert len(agg["records"]) == 3  # record_result creates 3 records


def test_lean_bridge_repo_missing_emits_telemetry_noop(monkeypatch, tmp_path):
    """run_lean_bridge with missing repo returns correct dict under NoOp."""
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    result = telemetry  # just ensure import works
    from agent.lean_bridge import run_lean_bridge

    result = run_lean_bridge(
        cert_path=str(tmp_path / "dummy.proof-cert.json"),
        lean_cert_out=None,
        mumei_lean_repo=str(tmp_path / "nonexistent"),
    )
    assert result["success"] is False
    assert result["error_code"] == "repo_missing"
    assert result["returncode"] == -1


def test_lean_bridge_no_build_success_emits_telemetry_noop(monkeypatch, tmp_path):
    """run_lean_bridge no_build=True preserves result dict under NoOp."""
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    from agent.lean_bridge import run_lean_bridge

    repo = tmp_path / "lean_repo"
    repo.mkdir()
    (repo / "scripts").mkdir()
    (repo / "scripts" / "bridge.py").write_text(
        "import sys; sys.exit(0)", encoding="utf-8"
    )
    cert = tmp_path / "test.proof-cert.json"
    cert.write_text('{"atoms": []}', encoding="utf-8")
    result = run_lean_bridge(
        cert_path=str(cert),
        lean_cert_out=str(tmp_path / "out.lean-cert.json"),
        mumei_lean_repo=str(repo),
        no_build=True,
        enable_known_witness_fallback=False,
    )
    assert isinstance(result, dict)
    assert "success" in result
    assert "returncode" in result
    assert "lean_cert_path" in result
    assert "stdout" in result
    assert "stderr" in result


# ---------------------------------------------------------------------------
# P15-6: proliferate / NLAE / audit span helpers (NoOp path)
# ---------------------------------------------------------------------------


def test_start_span_noop(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    with telemetry.start_span(
        "mumei.proliferate", **{"mumei.proliferate.dry_run": True, "x": None},
    ) as span:
        assert isinstance(span, telemetry._NoOpSpan)
        span.set_attribute("mumei.proliferate.proposals_found", 3)


def test_set_span_attributes_noop(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    telemetry.set_span_attributes(None, {"a": 1})
    with telemetry.start_span("probe") as span:
        telemetry.set_span_attributes(span, {"a": 1, "b": None, "c": "x"})


def test_span_trace_id_none_when_disabled(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    with telemetry.start_span("probe") as span:
        assert telemetry.span_trace_id(span) is None
    assert telemetry.span_trace_id(None) is None


def test_capture_and_use_context_noop(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    ctx = telemetry.capture_context()
    assert ctx is None
    with telemetry.use_context(ctx):
        with telemetry.start_span("child") as span:
            assert isinstance(span, telemetry._NoOpSpan)
    with telemetry.use_context(None):
        pass


def test_start_span_records_exception_and_reraises(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    import pytest

    with pytest.raises(ValueError):
        with telemetry.start_span("boom"):
            raise ValueError("kaboom")


def test_proliferate_dry_run_returns_results_under_noop_span(monkeypatch, tmp_path):
    """proliferate() dry-run keeps its return shape under NoOp spans."""
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    from unittest.mock import MagicMock, patch

    from agent import proliferate

    std = tmp_path / "std"
    std.mkdir()
    fake_code = "// auto-generated\natom core_ok(x: i64) ensures: true; body: x;\n"

    with patch("agent.proliferate.generate_code") as gen_mock, patch(
        "agent.proliferate.AgentConfig"
    ) as cfg_mock, patch(
        "agent.proliferate.create_mumei_client"
    ) as client_mock:
        gen_mock.return_value = (fake_code, True)
        cfg_instance = MagicMock()
        cfg_instance.mumei_bin = "mumei"
        cfg_instance.model = "gpt-test"
        cfg_instance.max_retries = 2
        cfg_instance.enable_self_correction = False
        cfg_instance.create_client.return_value = MagicMock()
        cfg_mock.return_value = cfg_instance

        verify_client = MagicMock()
        verify_client.verify.return_value = {
            "success": True,
            "report": {"status": "ok"},
            "stdout": "",
            "stderr": "",
        }
        client_mock.return_value = verify_client

        results = proliferate.proliferate(tmp_path, dry_run=True, max_proposals=1)

    assert len(results) >= 1
    assert results[0]["success"] is True
    assert results[0].get("dry_run") is True
    assert results[0]["code"] == fake_code


def test_proliferate_no_std_returns_error_under_noop_span(monkeypatch, tmp_path):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    from agent import proliferate

    results = proliferate.proliferate(tmp_path, dry_run=True)
    assert results == [{"success": False, "reason": "std_dir_not_found"}]


def test_nlae_run_full_pipeline_returns_result_under_noop_span(monkeypatch, tmp_path):
    """NLAEPipeline.run_full_pipeline keeps its result/to_dict under NoOp."""
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    from agent.nlae_pipeline import NLAEPipeline

    class FakeAgent:
        def generate_code(self, spec: str) -> str:
            return (
                "atom nlae_ok(balance: i64, amount: i64)\n"
                "    requires: balance >= 0;\n"
                "    ensures: result >= 0;\n"
                "    body: balance - amount;\n"
            )

    class FakeMumeiClient:
        def verify(self, source_path: str) -> dict:
            return {"success": True, "report": {"status": "ok"}}

        def verify_loss_vector(self, source_path: str) -> dict:
            return {"success": True}

    class FakeLeanBridge:
        def run_lean_bridge(self, cert_path, lean_cert_out, mumei_lean_repo) -> dict:
            return {"success": True}

    pipeline = NLAEPipeline(
        agent=FakeAgent(),
        mumei_client=FakeMumeiClient(),
        self_correction_loop=object(),
        lean_bridge=FakeLeanBridge(),
        work_dir=tmp_path,
    )
    result = pipeline.run_full_pipeline("vault withdraw safety", tmp_path)
    assert result.verified is True
    assert result.lean_verified is True
    # trace_id is an optional field defaulting to None under NoOp.
    assert result.trace_id is None
    d = result.to_dict()
    assert d["verified"] is True
    assert d["trace_id"] is None


def test_audit_file_and_directory_return_results_under_noop_span(monkeypatch, tmp_path):
    """AuditPipeline.audit_file / audit_directory keep dataclass shape under NoOp."""
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    from unittest.mock import MagicMock

    from agent.audit import AuditDirectoryResult, AuditPipeline, AuditResult
    from agent.code_to_spec import CodeToSpecResult
    from agent.config import AgentConfig
    from agent.strategies.cross_validation_strategy import CrossValidationReport

    source = tmp_path / "payment.py"
    source.write_text(
        "def withdraw(balance: int, amount: int) -> int:\n"
        "    return balance - amount\n",
        encoding="utf-8",
    )

    def _make_pipeline() -> AuditPipeline:
        extractor = MagicMock()
        extractor.extract_from_file.return_value = CodeToSpecResult(
            success=True,
            natural_language_spec="withdraw preserves non-negative balance",
            forge_task_spec={
                "task_id": "audit-payment",
                "target_file": "audit/payment.mm",
                "mode": "create",
                "atoms": [
                    {
                        "name": "withdraw",
                        "inputs": [
                            {"name": "balance", "type": "i64"},
                            {"name": "amount", "type": "i64"},
                        ],
                        "return_type": "i64",
                        "requires": "balance >= amount && amount >= 0",
                        "ensures": "result == balance - amount && result >= 0",
                    }
                ],
            },
            detected_language="python",
        )
        foreign_verifier = MagicMock()
        foreign_verifier.verify.return_value = {"success": True, "errors": []}
        cross_validator = MagicMock()
        cross_validator.validate_spec_vs_impl.return_value = CrossValidationReport(
            spec_stronger_than_impl=[],
            details=[],
            coverage_ratio=1.0,
        )
        mumei = MagicMock()
        mumei.verify.return_value = {"success": True, "report": {}, "stdout": "", "stderr": ""}
        return AuditPipeline(
            AgentConfig(api_key="test"),
            code_to_spec_extractor=extractor,
            foreign_code_verifier=foreign_verifier,
            cross_validator=cross_validator,
            mumei_client=mumei,
        )

    file_result = _make_pipeline().audit_file(source, "python")
    assert isinstance(file_result, AuditResult)
    assert file_result.spec_extracted is True

    dir_result = _make_pipeline().audit_directory(tmp_path, "python")
    assert isinstance(dir_result, AuditDirectoryResult)
    assert dir_result.total_files >= 1
    assert all(isinstance(fr, AuditResult) for fr in dir_result.file_results)


def test_audit_source_returns_result_under_noop_span(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    from unittest.mock import MagicMock

    from agent.audit import AuditPipeline, AuditResult
    from agent.code_to_spec import CodeToSpecResult
    from agent.config import AgentConfig
    from agent.strategies.cross_validation_strategy import CrossValidationReport

    extractor = MagicMock()
    extractor.extract_from_file.return_value = CodeToSpecResult(
        success=False,
        natural_language_spec="",
        forge_task_spec=None,
        detected_language="python",
        errors=["no spec"],
    )
    pipeline = AuditPipeline(
        AgentConfig(api_key="test"),
        code_to_spec_extractor=extractor,
        foreign_code_verifier=MagicMock(),
        cross_validator=MagicMock(),
        mumei_client=MagicMock(),
    )
    result = pipeline.audit_source("def f():\n    return 1\n", "python")
    assert isinstance(result, AuditResult)
    assert result.source_file == "<inline:python>"
