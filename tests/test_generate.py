"""Tests for the generate mode."""

import json
from unittest.mock import MagicMock

from agent.generate import _load_spec, _normalize_forge_task_spec
from agent.metrics import Metrics
from agent.prompts import generate_atom, generate_stdlib
from agent.strategies.generate_strategy import (
    generate_code,
    generate_code_with_mapping,
    _extract_code,
    _has_effects,
    _select_prompt_module,
    _build_skeleton,
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


def test_load_single_atom_forge_task_spec_uses_single_atom_path(tmp_path):
    """Forge task specs with one atom normalize to generate's single-atom shape."""
    spec = {
        "task_id": "nl-safe-transfer",
        "target_file": "std/finance/safe_transfer.mm",
        "mode": "create",
        "atoms": [
            {
                "name": "safe_transfer",
                "inputs": [
                    {"name": "from_balance", "type": "i64"},
                    {"name": "amount", "type": "i64"},
                ],
                "return_type": "i64",
                "requires": "from_balance >= amount && amount > 0",
                "ensures": "result == from_balance - amount",
                "effects": [],
            },
        ],
    }
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))

    ns = MagicMock()
    ns.spec = None
    ns.spec_file = str(spec_file)
    result = _load_spec(ns)

    assert result["name"] == "safe_transfer"
    assert "atoms" not in result
    assert result["params"] == spec["atoms"][0]["inputs"]
    assert result["target_file"] == "std/finance/safe_transfer.mm"
    assert result["module_name"] == "std/finance/safe_transfer"


def test_normalize_forge_task_spec_multi_atom_with_null_task_id():
    """Multi-atom forge spec with task_id=None falls back to path-based name.

    ``dict.get("task_id", default)`` would return ``None`` when the key is
    explicitly set to ``None``; the normalizer must fall through to the
    target_file/path-based fallback instead of producing ``module_name=None``.
    """
    spec = {
        "task_id": None,
        "mode": "create",
        "atoms": [
            {"name": "a", "inputs": [], "return_type": "i64"},
            {"name": "b", "inputs": [], "return_type": "i64"},
        ],
    }
    result = _normalize_forge_task_spec(spec)
    assert result["module_name"] == "module"
    assert result["module_name"] is not None


# --- Prompt generation tests ---


def test_generate_stdlib_prompt_produces_valid_string():
    """Test that generate_stdlib.build_prompt returns a non-empty string."""
    spec_json = json.dumps(
        {
            "name": "safe_read",
            "params": [{"name": "path", "type": "Str"}],
            "effects": ["SafeFileRead(path)"],
            "requires": 'starts_with(path, "/tmp/") && not_contains(path, "..")',
            "ensures": "result >= 0",
            "description": "Read a file safely with path traversal prevention",
        }
    )
    result = generate_stdlib.build_prompt(spec_json, "", {})
    assert isinstance(result, str)
    assert len(result) > 0
    assert "safe_read" in result
    assert "SafeFileRead" in result
    assert "std/file.mm" in result
    assert "std/http.mm" in result
    assert "Z3-stable specification fragment" in result
    assert "outside_decidable_fragment" in result


def test_generate_stdlib_prompt_with_errors():
    """Test that generate_stdlib.build_prompt includes error context."""
    spec_json = '{"name": "test"}'
    result = generate_stdlib.build_prompt(
        spec_json, "Parse error: unexpected token", {}
    )
    assert "Parse error" in result


def test_generate_atom_prompt_produces_valid_string():
    """Test that generate_atom.build_prompt returns a non-empty string."""
    spec_json = json.dumps(
        {
            "name": "add",
            "params": [{"name": "a", "type": "i64"}, {"name": "b", "type": "i64"}],
            "requires": "true",
            "ensures": "result == a + b",
            "description": "Add two numbers",
        }
    )
    result = generate_atom.build_prompt(spec_json, "", {})
    assert isinstance(result, str)
    assert len(result) > 0
    assert "add" in result
    assert "requires" in result.lower()
    assert "ensures" in result.lower()
    assert "Z3-stable specification fragment" in result
    assert "outside_decidable_fragment" in result


def test_generate_atom_prompt_with_errors():
    """Test that generate_atom.build_prompt includes compact retry context."""
    spec_json = '{"name": "test"}'
    report = {"failure_type": "postcondition_violated", "counterexample": {"x": "0"}}
    result = generate_atom.build_prompt(spec_json, "Verification Error", report)
    assert "Verification Error" in result
    assert "Actionable fix instructions" in result
    assert "ensures" in result.lower()
    assert "Verification report" not in result


def test_generate_atom_prompt_truncates_retry_context():
    """Retry report context respects the configured character budget."""
    spec_json = '{"name": "test"}'
    report = {
        "failure_type": "postcondition_violated",
        "suggestion": "When counterexample x=0, " + ("details " * 50),
    }

    result = generate_atom.build_prompt(
        spec_json,
        "Verification Error",
        report,
        prompt_report_truncate_chars=80,
    )

    assert "truncated to 80 chars" in result
    assert "Verification report" not in result


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
    result, verified = generate_code(
        client,
        "test-model",
        spec,
        mumei_client=None,
        enable_dense_properties=False,
    )
    assert "atom test()" in result
    assert verified is True
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
    result, verified = generate_code(
        client,
        "test-model",
        spec,
        mumei_client=mumei,
        metrics=metrics,
    )
    assert "atom test()" in result
    assert verified is True
    assert metrics.successes == 1


def test_generate_code_attaches_mapping_to_verification():
    """Test generation passes mapping metadata to verification."""
    client = _mock_client(
        "```mumei\n"
        "atom test() -> i64\n"
        "    requires: true;\n"
        "    ensures: result == 1;\n"
        "    body: 1;\n"
        "```"
    )
    mumei = MagicMock()
    mumei.check.return_value = {"success": True, "stdout": "", "stderr": ""}
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "",
        "stderr": "",
    }

    spec = {
        "name": "test",
        "params": [],
        "requires": "true",
        "ensures": "result == 1",
    }
    result, verified = generate_code(client, "test-model", spec, mumei_client=mumei)

    assert "atom test()" in result
    assert verified is True
    kwargs = mumei.verify.call_args.kwargs
    assert kwargs["spec_code_mapping"][0]["spec_item_id"] == "test"
    assert kwargs["spec_code_mapping"][0]["spec_type"] == "requires"
    assert kwargs["spec_code_mapping"][1]["spec_type"] == "ensures"


def test_generate_code_with_mapping_returns_json_payload():
    client = _mock_client("```mumei\natom test() body: 1;\n```")
    spec = {"name": "test", "params": []}

    result = generate_code_with_mapping(
        client,
        "test-model",
        spec,
        mumei_client=None,
    )

    assert result["verified"] is True
    assert "atom test()" in result["code"]
    assert result["spec_code_mapping"][0]["spec_item_id"] == "test"


def test_generate_code_can_disable_spec_code_mapping():
    client = _mock_client("```mumei\natom test() body: 1;\n```")
    mumei = MagicMock()
    mumei.check.return_value = {"success": True, "stdout": "", "stderr": ""}
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "",
        "stderr": "",
    }

    spec = {"name": "test", "params": [], "requires": "true"}
    result, verified = generate_code(
        client,
        "test-model",
        spec,
        mumei_client=mumei,
        enable_spec_code_mapping=False,
    )

    assert "atom test()" in result
    assert verified is True
    assert "spec_code_mapping" not in mumei.verify.call_args.kwargs


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
    result, verified = generate_code(
        client,
        "test-model",
        spec,
        mumei_client=mumei,
        enable_dense_properties=False,
    )
    assert "atom fixed()" in result
    assert verified is True


def test_generate_code_fix_after_verify_failure():
    """Test that generation retries after verification failure."""
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        # Initial generation
        _make_response("```mumei\natom test() requires: true; body: 1;\n```"),
        # Fix attempt
        _make_response(
            "```mumei\natom test() requires: true; ensures: result >= 0; body: 1;\n```"
        ),
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
    result, verified = generate_code(
        client,
        "test-model",
        spec,
        mumei_client=mumei,
        metrics=metrics,
        enable_dense_properties=False,
    )
    assert "atom test()" in result
    assert verified is True


def test_generate_code_all_retries_exhausted():
    """Test that generate_code returns verified=False when all retries fail."""
    client = MagicMock()
    # Initial generation + fix attempts (max_retries=2 means 2 loop iterations)
    client.chat.completions.create.side_effect = [
        _make_response("```mumei\natom bad() body: ;\n```"),
        _make_response("```mumei\natom still_bad() body: ;\n```"),
        _make_response("```mumei\natom still_bad2() body: ;\n```"),
    ]

    mumei = MagicMock()
    mumei.check.return_value = {"success": True, "stdout": "", "stderr": ""}
    mumei.verify.return_value = {
        "success": False,
        "report": {"violation_type": "postcondition_violated"},
        "stdout": "Error",
        "stderr": "",
    }

    spec = {"name": "bad", "params": []}
    metrics = Metrics()
    result, verified = generate_code(
        client,
        "test-model",
        spec,
        config_max_retries=2,
        mumei_client=mumei,
        metrics=metrics,
        enable_dense_properties=False,
    )
    assert verified is False
    assert result != ""
    assert metrics.successes == 0


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


# --- _build_skeleton tests ---


def test_build_skeleton_basic():
    """Test skeleton generation with basic spec."""
    spec = {
        "name": "add",
        "params": [{"name": "a", "type": "i64"}, {"name": "b", "type": "i64"}],
    }
    result = _build_skeleton(spec)
    assert "atom add(a: i64, b: i64)" in result
    assert "requires: ___;" in result
    assert "ensures: ___;" in result
    assert "body: { ___ }" in result
    assert "effects:" not in result


def test_build_skeleton_with_effects():
    """Test skeleton generation with effects."""
    spec = {
        "name": "read_file",
        "params": [{"name": "path", "type": "Str"}],
        "effects": ["FileRead", "Log"],
    }
    result = _build_skeleton(spec)
    assert "atom read_file(path: Str)" in result
    assert "effects: [FileRead, Log]" in result
    assert "requires: ___;" in result


def test_build_skeleton_includes_return_type_when_present():
    """Test skeleton generation includes explicit return type."""
    spec = {
        "name": "safe_transfer",
        "params": [{"name": "from_balance", "type": "i64"}],
        "return_type": "i64",
    }
    result = _build_skeleton(spec)
    assert "atom safe_transfer(from_balance: i64) -> i64" in result


def test_build_skeleton_no_params():
    """Test skeleton generation with no params."""
    spec = {"name": "noop", "params": []}
    result = _build_skeleton(spec)
    assert "atom noop()" in result


def test_build_skeleton_default_type():
    """Test skeleton generation uses i64 as default type."""
    spec = {"name": "inc", "params": [{"name": "x"}]}
    result = _build_skeleton(spec)
    assert "atom inc(x: i64)" in result


# --- inferred_context prompt tests ---


def test_generate_atom_prompt_with_inferred_context():
    """Test that generate_atom.build_prompt includes inferred context."""
    spec_json = '{"name": "test"}'
    ctx = {
        "effects": {"inferred": ["FileRead"]},
        "contracts": {"requires": "x > 0"},
    }
    result = generate_atom.build_prompt(spec_json, "", {}, inferred_context=ctx)
    assert "Inferred effects" in result
    assert "FileRead" in result
    assert "Inferred contracts" in result
    assert "x > 0" in result


def test_generate_atom_prompt_without_inferred_context():
    """Test that generate_atom.build_prompt works without inferred context."""
    spec_json = '{"name": "test"}'
    result = generate_atom.build_prompt(spec_json, "", {})
    assert "Inferred effects" not in result
    assert "Inferred contracts" not in result


def test_generate_stdlib_prompt_with_inferred_context():
    """Test that generate_stdlib.build_prompt includes inferred context."""
    spec_json = '{"name": "test"}'
    ctx = {
        "effects": {"inferred": ["HttpGet"]},
        "contracts": {"ensures": "result >= 0"},
    }
    result = generate_stdlib.build_prompt(spec_json, "", {}, inferred_context=ctx)
    assert "Inferred effects" in result
    assert "HttpGet" in result
    assert "Inferred contracts" in result
    assert "result >= 0" in result


# --- generate_code with inferred_context tests ---


def test_generate_code_with_context_file():
    """Test generate_code calls infer_effects/infer_contracts when context_file is set."""
    client = _mock_client("```mumei\natom test() body: 1;\n```")
    mumei = MagicMock()
    mumei.check.return_value = {"success": True, "stdout": "", "stderr": ""}
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "",
        "stderr": "",
    }
    mumei.infer_effects.return_value = {
        "success": True,
        "analysis": {"effects": ["FileRead"]},
    }
    mumei.infer_contracts.return_value = {
        "success": True,
        "analysis": {"requires": "x > 0"},
    }

    spec = {"name": "test", "params": [], "context_file": "/tmp/ctx.mm"}
    result, verified = generate_code(
        client,
        "test-model",
        spec,
        mumei_client=mumei,
    )
    assert verified is True
    mumei.infer_effects.assert_called_once_with("/tmp/ctx.mm")
    mumei.infer_contracts.assert_called_once_with("/tmp/ctx.mm")


def test_generate_code_without_context_file():
    """Test generate_code does not call infer methods without context_file."""
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
    result, verified = generate_code(
        client,
        "test-model",
        spec,
        mumei_client=mumei,
    )
    assert verified is True
    mumei.infer_effects.assert_not_called()
    mumei.infer_contracts.assert_not_called()
