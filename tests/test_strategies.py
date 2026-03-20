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
