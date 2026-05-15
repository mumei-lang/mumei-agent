"""Tests for fix_strategy module."""
from unittest.mock import MagicMock, patch, call
from agent.strategies.fix_strategy import get_fix, _build_prompt_for_report
from agent.strategies.multi_stage_strategy import _parse_diagnosis, _extract_code


def _mock_client(response_text: str) -> MagicMock:
    """Create a mock OpenAI client that returns the given text."""
    client = MagicMock()
    message = MagicMock()
    message.content = response_text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    client.chat.completions.create.return_value = response
    return client


def test_effect_mismatch_selects_correct_template():
    """Test that effect_mismatch violation uses the effect_mismatch prompt."""
    client = _mock_client("```mumei\natom fixed() body: 1;\n```")
    report = {
        "violation_type": "effect_mismatch",
        "atom": "write_log",
        "effect_violation": {
            "declared_effects": ["Log"],
            "required_effect": "FileWrite",
            "source_operation": "FileWrite.write",
            "resolution_paths": [
                {"strategy": "propagation", "description": "Add FileWrite"},
            ],
        },
    }
    result = get_fix(client, "test-model", "source", "error", report)
    assert "atom fixed()" in result

    # Verify the prompt sent to the LLM contains effect_mismatch-specific content
    call_args = client.chat.completions.create.call_args
    messages = call_args.kwargs["messages"]
    user_prompt = messages[1]["content"]
    assert "Option A" in user_prompt
    assert "effect violation" in user_prompt


def test_effect_propagation_selects_correct_template():
    """Test that effect_propagation violation uses the propagation prompt."""
    client = _mock_client("```mumei\natom fixed() body: 1;\n```")
    report = {
        "violation_type": "effect_propagation",
        "effect_violation": {
            "caller": "main_handler",
            "callee": "write_log",
            "caller_effects": ["Log"],
            "callee_effects": ["Log", "FileWrite"],
            "missing_effects": ["FileWrite"],
            "resolution_paths": [],
        },
    }
    result = get_fix(client, "test-model", "source", "error", report)
    assert "atom fixed()" in result

    call_args = client.chat.completions.create.call_args
    messages = call_args.kwargs["messages"]
    user_prompt = messages[1]["content"]
    assert "propagation violation" in user_prompt
    assert "main_handler" in user_prompt


def test_precondition_selects_correct_template():
    """Test that non-effect violations use the precondition prompt."""
    client = _mock_client("```mumei\natom fixed() body: 1;\n```")
    report = {
        "status": "failed",
        "atom": "safe_divide",
        "reason": "Division by zero",
    }
    result = get_fix(client, "test-model", "source", "error", report)
    assert "atom fixed()" in result

    call_args = client.chat.completions.create.call_args
    messages = call_args.kwargs["messages"]
    user_prompt = messages[1]["content"]
    assert "requires" in user_prompt
    assert "formal verification" in user_prompt


def test_code_block_extraction():
    """Test that code is correctly extracted from various fence formats."""
    client = _mock_client("Some text\n```rust\nfn main() {}\n```\nMore text")
    result = get_fix(client, "m", "src", "err", {})
    assert result == "fn main() {}"


def test_no_code_block_returns_raw():
    """Test that raw content is returned when no code block is found."""
    client = _mock_client("Just plain text fix suggestion")
    result = get_fix(client, "m", "src", "err", {})
    assert result == "Just plain text fix suggestion"


def test_get_fix_updates_spec_code_mapping():
    client = _mock_client(
        "```mumei\n"
        "atom safe_div(a: i64, b: i64) -> i64\n"
        "    requires: b != 0;\n"
        "    ensures: result == a / b;\n"
        "    body: a / b;\n"
        "```"
    )
    report = {"status": "failed"}
    spec = {
        "name": "safe_div",
        "params": [{"name": "a"}, {"name": "b"}],
        "requires": "b != 0",
        "ensures": "result == a / b",
    }

    result = get_fix(client, "m", "src", "err", report, spec=spec)

    assert "atom safe_div" in result
    assert report["spec_code_mapping"][0]["spec_type"] == "requires"
    assert report["spec_code_mapping"][1]["spec_type"] == "ensures"


# --- P2: failure_type routing tests ---

def test_division_by_zero_routes_correctly():
    """Test that failure_type division_by_zero uses the division_by_zero prompt."""
    client = _mock_client("```mumei\natom fixed() body: 1;\n```")
    report = {"failure_type": "division_by_zero"}
    result = get_fix(client, "test-model", "source", "error", report)
    assert "atom fixed()" in result
    prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "division-by-zero" in prompt


def test_linearity_violated_routes_correctly():
    """Test that failure_type linearity_violated uses the linearity prompt."""
    client = _mock_client("```mumei\natom fixed() body: 1;\n```")
    report = {"failure_type": "linearity_violated"}
    get_fix(client, "test-model", "source", "error", report)
    prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "linearity" in prompt.lower()


def test_invariant_violated_routes_correctly():
    """Test that failure_type invariant_violated uses the invariant prompt."""
    client = _mock_client("```mumei\natom fixed() body: 1;\n```")
    report = {"failure_type": "invariant_violated"}
    get_fix(client, "test-model", "source", "error", report)
    prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "invariant" in prompt.lower()


def test_postcondition_violated_routes_correctly():
    """Test that failure_type postcondition_violated uses the postcondition prompt."""
    client = _mock_client("```mumei\natom fixed() body: 1;\n```")
    report = {"failure_type": "postcondition_violated"}
    get_fix(client, "test-model", "source", "error", report)
    prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "postcondition" in prompt.lower()


def test_temporal_effect_routes_correctly():
    """Test that failure_type temporal_effect_violated uses the temporal prompt."""
    client = _mock_client("```mumei\natom fixed() body: 1;\n```")
    report = {"failure_type": "temporal_effect_violated"}
    get_fix(client, "test-model", "source", "error", report)
    prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "temporal" in prompt.lower()


def test_violation_type_takes_precedence_over_failure_type():
    """Test that violation_type (effect) takes precedence over failure_type."""
    client = _mock_client("```mumei\natom fixed() body: 1;\n```")
    report = {
        "violation_type": "effect_mismatch",
        "failure_type": "division_by_zero",
        "atom": "test",
        "effect_violation": {
            "declared_effects": [],
            "required_effect": "Log",
            "source_operation": "Log.write",
            "resolution_paths": [],
        },
    }
    get_fix(client, "test-model", "source", "error", report)
    prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "effect violation" in prompt
    assert "division-by-zero" not in prompt


def test_unknown_failure_type_falls_back_to_precondition():
    """Test that unknown failure_type falls back to precondition prompt."""
    client = _mock_client("```mumei\natom fixed() body: 1;\n```")
    report = {"failure_type": "unknown_type"}
    get_fix(client, "test-model", "source", "error", report)
    prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "requires" in prompt.lower()
    assert "formal verification" in prompt


# --- P4: Multi-stage strategy tests ---

def test_build_prompt_for_report_returns_string():
    """Test that _build_prompt_for_report returns a non-empty string."""
    result = _build_prompt_for_report("source", "error", {"status": "failed"})
    assert isinstance(result, str)
    assert len(result) > 0


def test_parse_diagnosis_valid_json():
    """Test parsing a valid JSON diagnosis."""
    raw = '{"root_cause": "division by zero", "fix_approach": "add requires", "target_section": "requires"}'
    result = _parse_diagnosis(raw)
    assert result["root_cause"] == "division by zero"
    assert result["fix_approach"] == "add requires"
    assert result["target_section"] == "requires"


def test_parse_diagnosis_fenced_json():
    """Test parsing JSON inside markdown fences."""
    raw = '```json\n{"root_cause": "bad postcondition", "fix_approach": "fix body", "target_section": "body"}\n```'
    result = _parse_diagnosis(raw)
    assert result["root_cause"] == "bad postcondition"
    assert result["target_section"] == "body"


def test_parse_diagnosis_invalid_json_fallback():
    """Test that invalid JSON returns sensible defaults."""
    result = _parse_diagnosis("This is not JSON at all")
    assert result["root_cause"] == "unknown"
    assert result["target_section"] == "requires"


def test_extract_code_from_fences():
    """Test extracting code from markdown fences."""
    content = "Here's the fix:\n```mumei\natom safe() body: 1;\n```\nDone."
    assert _extract_code(content) == "atom safe() body: 1;"


def test_extract_code_raw():
    """Test that raw content is returned when no fences found."""
    assert _extract_code("atom raw() body: 1;") == "atom raw() body: 1;"


def test_get_fix_strategy_single_default():
    """Test that strategy='single' (default) uses one-shot LLM call."""
    client = _mock_client("```mumei\natom fixed() body: 1;\n```")
    result = get_fix(client, "m", "src", "err", {}, strategy="single")
    assert "atom fixed()" in result
    # Should be exactly one LLM call for single strategy
    assert client.chat.completions.create.call_count == 1


def test_get_fix_strategy_multi_stage_delegates():
    """Test that strategy='multi-stage' delegates to multi_stage_strategy."""
    # Create a client that returns diagnosis JSON first, then fix code
    client = MagicMock()
    responses = [
        # Stage 1: Diagnosis
        _make_response('{"root_cause": "div zero", "fix_approach": "add requires", "target_section": "requires"}'),
        # Stage 2: Fix
        _make_response("```mumei\natom fixed() requires: b != 0; body: a / b;\n```"),
    ]
    client.chat.completions.create.side_effect = responses

    mumei_client = MagicMock()
    mumei_client.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "",
        "stderr": "",
    }

    result = get_fix(
        client, "m", "src", "err", {"status": "failed"},
        strategy="multi-stage",
        mumei_client=mumei_client,
        source_path="test.mm",
    )
    assert "atom fixed()" in result
    # Should have at least 2 LLM calls (diagnose + fix)
    assert client.chat.completions.create.call_count >= 2


def test_get_fix_multi_stage_without_mumei_client_falls_back():
    """Test that multi-stage without mumei_client falls back to single."""
    client = _mock_client("```mumei\natom fixed() body: 1;\n```")
    result = get_fix(
        client, "m", "src", "err", {},
        strategy="multi-stage",
        mumei_client=None,
        source_path=None,
    )
    assert "atom fixed()" in result
    # Falls back to single: exactly one LLM call
    assert client.chat.completions.create.call_count == 1


def _make_response(text: str) -> MagicMock:
    """Create a mock completion response."""
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response
