"""Tests for fix_strategy module."""
from unittest.mock import MagicMock, patch
from agent.strategies.fix_strategy import get_fix


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
