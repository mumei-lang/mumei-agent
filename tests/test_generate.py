"""Tests for the generate mode."""
import json
from unittest.mock import MagicMock, patch

from agent.generate import _load_spec
from agent.metrics import Metrics, ViolationMetrics
from agent.prompts import generate_atom, generate_stdlib
from agent.strategies.generate_strategy import (
    generate_code,
    _extract_code,
    _has_effects,
    _select_prompt_module,
)


# --- Spec loading tests ---


def test_load_spec_inline(tmp_path):
    """Test loading spec from --spec inline JSON."""
    ns = MagicMock()
    ns.spec = '{"name": "test_atom", "params": []}'
    ns.spec_file = None
    result = _load_spec(ns)
    assert result["name"] == "test_atom"


def test_load_spec_from_file(tmp_path):
    """Test loading spec from --spec-file."""
    spec = {"name": "safe_read", "params": [{"name": "path", "type": "Str"}]}
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))

    ns = MagicMock()
    ns.spec = None
    ns.spec_file = str(spec_file)
    result = _load_spec(ns)
    assert result["name"] == "safe_read"
    assert len(result["params"]) == 1


# --- Prompt generation tests ---


def test_generate_stdlib_prompt_produces_valid_string():
    """Test that generate_stdlib.build_prompt returns a non-empty string."""
    spec_json = json.dumps({
        "name": "safe_read",
        "params": [{"name": "path", "type": "Str"}],
        "effects": ["SafeFileRead(path)"],
        "requires": 'starts_with(path, "/tmp/") && not_contains(path, "..")',
        "ensures": "result >= 0",
        "description": "Read a file safely with path traversal prevention",
    })
    result = generate_stdlib.build_prompt(spec_json, "", {})
    assert isinstance(result, str)
    assert len(result) > 0
    assert "safe_read" in result
    assert "SafeFileRead" in result
    assert "std/file.mm" in result
    assert "std/http.mm" in result


def test_generate_stdlib_prompt_with_errors():
    """Test that generate_stdlib.build_prompt includes error context."""
    spec_json = '{"name": "test"}'
    result = generate_stdlib.build_prompt(spec_json, "Parse error: unexpected token", {})
    assert "Parse error" in result


def test_generate_atom_prompt_produces_valid_string():
    """Test that generate_atom.build_prompt returns a non-empty string."""
    spec_json = json.dumps({
        "name": "add",
        "params": [{"name": "a", "type": "i64"}, {"name": "b", "type": "i64"}],
        "requires": "true",
        "ensures": "result == a + b",
        "description": "Add two numbers",
    })
    result = generate_atom.build_prompt(spec_json, "", {})
    assert isinstance(result, str)
    assert len(result) > 0
    assert "add" in result
    assert "requires" in result.lower()
    assert "ensures" in result.lower()


def test_generate_atom_prompt_with_errors():
    """Test that generate_atom.build_prompt includes error and report context."""
    spec_json = '{"name": "test"}'
    report = {"status": "failed", "reason": "postcondition violated"}
    result = generate_atom.build_prompt(spec_json, "Verification Error", report)
    assert "Verification Error" in result
    assert "postcondition violated" in result


# --- Strategy tests ---


def test_has_effects_true():
    """Test _has_effects detects effects."""
    assert _has_effects({"effects": ["FileRead"]}) is True


def test_has_effects_false():
    """Test _has_effects returns False for no effects."""
    assert _has_effects({"effects": []}) is False
    assert _has_effects({}) is False


def test_select_prompt_module_with_effects():
    """Test that specs with effects select generate_stdlib."""
    module = _select_prompt_module({"effects": ["FileRead"]})
    assert module is generate_stdlib


def test_select_prompt_module_without_effects():
    """Test that specs without effects select generate_atom."""
    module = _select_prompt_module({"params": []})
    assert module is generate_atom


def test_extract_code_from_fences():
    """Test extracting code from markdown fences."""
    content = "Here's the code:\n```mumei\natom test() body: 1;\n```\nDone."
    assert _extract_code(content) == "atom test() body: 1;"


def test_extract_code_raw():
    """Test raw content returned when no fences."""
    assert _extract_code("atom test() body: 1;") == "atom test() body: 1;"


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


# --- generate_code tests with mocked LLM and MumeiClient ---


def test_generate_code_without_mumei_client():
    """Test generation without mumei_client (no verification)."""
    client = _mock_client("```mumei\natom test() body: 1;\n```")
    spec = {"name": "test", "params": []}
    result = generate_code(client, "test-model", spec, mumei_client=None)
    assert "atom test()" in result
    assert client.chat.completions.create.call_count == 1


def test_generate_code_success_on_first_try():
    """Test generation that passes verification on first try."""
    client = _mock_client("```mumei\natom test() body: 1;\n```")
    mumei = MagicMock()
    mumei.check.return_value = {"success": True, "stdout": "", "stderr": ""}
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "",
        "stderr": "",
    }

    spec = {"name": "test", "params": []}
    metrics = Metrics()
    result = generate_code(
        client, "test-model", spec,
        mumei_client=mumei, metrics=metrics,
    )
    assert "atom test()" in result
    assert metrics.successes == 1


def test_generate_code_fix_after_check_failure():
    """Test that generation retries after parse check failure."""
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        # Initial generation
        _make_response("```mumei\natom bad() body: ;\n```"),
        # Fix attempt
        _make_response("```mumei\natom fixed() body: 1;\n```"),
    ]

    mumei = MagicMock()
    # First check fails, second check + verify succeed
    mumei.check.side_effect = [
        {"success": False, "stdout": "", "stderr": "Parse error"},
        {"success": True, "stdout": "", "stderr": ""},
    ]
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "",
        "stderr": "",
    }

    spec = {"name": "fixed", "params": []}
    result = generate_code(client, "test-model", spec, mumei_client=mumei)
    assert "atom fixed()" in result


def test_generate_code_fix_after_verify_failure():
    """Test that generation retries after verification failure."""
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        # Initial generation
        _make_response("```mumei\natom test() requires: true; body: 1;\n```"),
        # Fix attempt
        _make_response("```mumei\natom test() requires: true; ensures: result >= 0; body: 1;\n```"),
    ]

    mumei = MagicMock()
    mumei.check.return_value = {"success": True, "stdout": "", "stderr": ""}
    # First verify fails, second succeeds
    mumei.verify.side_effect = [
        {
            "success": False,
            "report": {"violation_type": "postcondition_violated"},
            "stdout": "Error",
            "stderr": "",
        },
        {
            "success": True,
            "report": {"status": "ok"},
            "stdout": "",
            "stderr": "",
        },
    ]

    spec = {"name": "test", "params": []}
    metrics = Metrics()
    result = generate_code(
        client, "test-model", spec,
        mumei_client=mumei, metrics=metrics,
    )
    assert "atom test()" in result


# --- Metrics tests ---


def test_metrics_record_attempt():
    """Test recording an attempt."""
    m = Metrics()
    m.record_attempt("effect_mismatch")
    assert m.total_attempts == 1
    assert m.by_violation_type["effect_mismatch"].attempts == 1


def test_metrics_record_success():
    """Test recording a success."""
    m = Metrics()
    m.record_attempt("generation")
    m.record_success("generation")
    assert m.successes == 1
    assert m.by_violation_type["generation"].successes == 1


def test_metrics_to_dict():
    """Test converting metrics to dict."""
    m = Metrics()
    m.record_attempt("effect_mismatch")
    m.record_attempt("effect_mismatch")
    m.record_success("effect_mismatch")
    d = m.to_dict()
    assert d["total_attempts"] == 2
    assert d["successes"] == 1
    assert d["by_violation_type"]["effect_mismatch"]["attempts"] == 2
    assert d["by_violation_type"]["effect_mismatch"]["successes"] == 1


def test_metrics_to_json():
    """Test converting metrics to JSON string."""
    m = Metrics()
    m.record_attempt("generation")
    j = m.to_json()
    parsed = json.loads(j)
    assert parsed["total_attempts"] == 1


def test_metrics_multiple_violation_types():
    """Test metrics with multiple violation types."""
    m = Metrics()
    m.record_attempt("effect_mismatch")
    m.record_attempt("precondition_violated")
    m.record_success("precondition_violated")
    d = m.to_dict()
    assert len(d["by_violation_type"]) == 2
    assert d["by_violation_type"]["effect_mismatch"]["successes"] == 0
    assert d["by_violation_type"]["precondition_violated"]["successes"] == 1
