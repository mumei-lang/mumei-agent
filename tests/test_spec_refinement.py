"""Tests for P6-C: Specification Refinement Loop."""
import json
from unittest.mock import MagicMock, call

from agent.metrics import Metrics
from agent.strategies.spec_refinement import refine_spec, run_refinement_loop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(text: str) -> MagicMock:
    """Create a mock completion response."""
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _mock_client(response_text: str) -> MagicMock:
    """Create a mock OpenAI client that returns the given text."""
    client = MagicMock()
    client.chat.completions.create.return_value = _make_response(response_text)
    return client


ORIGINAL_SPEC = {
    "name": "bounded_add",
    "params": [{"name": "a", "type": "i64"}, {"name": "b", "type": "i64"}],
    "requires": "a >= 0 && b >= 0",
    "ensures": "result == a + b && result < 100",
}

REPORT = {
    "status": "failed",
    "failure_type": "postcondition_violated",
    "atom": "bounded_add",
    "counterexample": {"a": "50", "b": "60"},
    "suggestion": "Weaken ensures or strengthen requires",
}


# ---------------------------------------------------------------------------
# refine_spec tests
# ---------------------------------------------------------------------------

def test_refine_spec_returns_refined_json():
    """Test that refine_spec returns a new spec dict from LLM output."""
    refined = {
        "name": "bounded_add",
        "params": [{"name": "a", "type": "i64"}, {"name": "b", "type": "i64"}],
        "requires": "a >= 0 && b >= 0 && a + b < 100",
        "ensures": "result == a + b",
    }
    client = _mock_client(f"```json\n{json.dumps(refined)}\n```")

    result = refine_spec(client, "m", ORIGINAL_SPEC, REPORT)

    assert result["requires"] == "a >= 0 && b >= 0 && a + b < 100"
    assert result["ensures"] == "result == a + b"


def test_refine_spec_returns_original_on_invalid_json():
    """Test that refine_spec returns the original spec if LLM returns invalid JSON."""
    client = _mock_client("This is not valid JSON at all")

    result = refine_spec(client, "m", ORIGINAL_SPEC, REPORT)

    assert result == ORIGINAL_SPEC


def test_refine_spec_returns_original_on_non_dict():
    """Test that refine_spec returns the original spec if LLM returns non-dict JSON."""
    client = _mock_client("[1, 2, 3]")

    result = refine_spec(client, "m", ORIGINAL_SPEC, REPORT)

    assert result == ORIGINAL_SPEC


def test_refine_spec_handles_raw_json_without_fences():
    """Test that refine_spec handles raw JSON without markdown fences."""
    refined = {"name": "bounded_add", "requires": "a >= 0 && b >= 0 && a < 50 && b < 50"}
    client = _mock_client(json.dumps(refined))

    result = refine_spec(client, "m", ORIGINAL_SPEC, REPORT)

    assert result["requires"] == "a >= 0 && b >= 0 && a < 50 && b < 50"


def test_refine_spec_includes_error_log():
    """Test that refine_spec passes error_log to the LLM prompt."""
    refined = {"name": "test"}
    client = _mock_client(json.dumps(refined))

    refine_spec(client, "m", ORIGINAL_SPEC, REPORT, error_log="Z3 timed out")

    prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "Z3 timed out" in prompt


# ---------------------------------------------------------------------------
# run_refinement_loop tests
# ---------------------------------------------------------------------------

def test_refinement_loop_succeeds_on_first_try():
    """Test that the loop returns immediately if generation succeeds."""
    client = _mock_client("")  # Not used directly by mock generate_fn
    metrics = Metrics()

    def mock_generate(c, m, spec, config_max_retries=5, mumei_client=None, metrics=None):
        return "atom bounded_add() body: a + b;", True

    code, verified, final_spec = run_refinement_loop(
        client, "m", ORIGINAL_SPEC, mock_generate,
        max_refinements=3, metrics=metrics,
    )

    assert verified is True
    assert final_spec == ORIGINAL_SPEC


def test_refinement_loop_refines_and_succeeds():
    """Test that the loop refines the spec and succeeds on a subsequent attempt."""
    refined_spec = dict(ORIGINAL_SPEC, requires="a >= 0 && b >= 0 && a + b < 100")

    # Client for refine_spec call
    client = _mock_client(json.dumps(refined_spec))

    call_count = 0

    def mock_generate(c, m, spec, config_max_retries=5, mumei_client=None, metrics=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "bad code", False
        return "good code", True

    code, verified, final_spec = run_refinement_loop(
        client, "m", ORIGINAL_SPEC, mock_generate,
        max_refinements=3,
    )

    assert verified is True
    assert code == "good code"
    assert final_spec["requires"] == "a >= 0 && b >= 0 && a + b < 100"


def test_refinement_loop_exhausts_refinements():
    """Test that the loop returns verified=False after exhausting refinements."""
    refined_spec = dict(ORIGINAL_SPEC, requires="a >= 0 && b >= 0 && a + b < 100")
    client = _mock_client(json.dumps(refined_spec))

    def mock_generate(c, m, spec, config_max_retries=5, mumei_client=None, metrics=None):
        return "still bad", False

    code, verified, final_spec = run_refinement_loop(
        client, "m", ORIGINAL_SPEC, mock_generate,
        max_refinements=2,
    )

    assert verified is False


def test_refinement_loop_uses_report_from_generate_fn():
    """Test that the loop forwards the report from generate_fn to refine_spec."""
    failure_report = {
        "status": "failed",
        "failure_type": "postcondition_violated",
        "counterexample": {"a": "50", "b": "60"},
    }
    refined_spec = dict(ORIGINAL_SPEC, requires="a >= 0 && b >= 0 && a + b < 100")
    client = _mock_client(json.dumps(refined_spec))

    call_count = 0

    def mock_generate(c, m, spec, config_max_retries=5, mumei_client=None, metrics=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Return 3-tuple with report
            return "bad code", False, failure_report
        return "good code", True, {}

    code, verified, final_spec = run_refinement_loop(
        client, "m", ORIGINAL_SPEC, mock_generate,
        max_refinements=3,
    )

    assert verified is True
    assert code == "good code"

    # Verify that the report was passed to refine_spec (appears in the LLM prompt)
    refine_call = client.chat.completions.create.call_args
    prompt = refine_call.kwargs["messages"][1]["content"]
    assert "postcondition_violated" in prompt
    assert "50" in prompt  # counterexample value


def test_refinement_loop_stops_when_spec_unchanged():
    """Test that the loop stops early if refinement produces no changes."""
    # LLM returns the exact same spec
    client = _mock_client(json.dumps(ORIGINAL_SPEC))

    call_count = 0

    def mock_generate(c, m, spec, config_max_retries=5, mumei_client=None, metrics=None):
        nonlocal call_count
        call_count += 1
        return "bad code", False

    code, verified, final_spec = run_refinement_loop(
        client, "m", ORIGINAL_SPEC, mock_generate,
        max_refinements=5,
    )

    assert verified is False
    # Should stop after first generate + one refinement attempt
    assert call_count == 1
