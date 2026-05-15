"""Tests for generation health checks."""
from __future__ import annotations

import json

from agent.config import AgentConfig
from agent.generation_health_checker import GenerationHealthChecker
from agent.strategies.generate_strategy import generate_code, generate_multi_atom

from tests.test_generate import _make_response, _mock_client


def test_health_check_accepts_spec_matching_code() -> None:
    config = AgentConfig(api_key="test")
    checker = GenerationHealthChecker(config)
    spec_text = json.dumps(
        {
            "name": "safe_add",
            "requires": "a_nonnegative and b_nonnegative",
            "ensures": "sum_result equals a plus b",
        }
    )
    generated_code = """
atom safe_add(a_nonnegative: i64, b_nonnegative: i64) -> i64
    ensures: sum_result == a_nonnegative + b_nonnegative;
    body: { a_nonnegative + b_nonnegative }
"""

    result = checker.check_generation_health(spec_text, generated_code)

    assert result.is_healthy is True
    assert result.spec_adherence_score >= 0.5
    assert result.code_diversity_score == 1.0
    assert result.warnings == []
    assert result.errors == []


def test_low_spec_adherence_adds_warning_and_marks_unhealthy() -> None:
    config = AgentConfig(api_key="test")
    checker = GenerationHealthChecker(config)

    result = checker.check_generation_health(
        "withdrawal balance overdraft guard transfer_limit",
        "atom unrelated() -> i64 body: { 1 }",
    )

    assert result.is_healthy is False
    assert result.spec_adherence_score < 0.3
    assert any("Low spec adherence score" in warning for warning in result.warnings)


def test_code_diversity_compares_against_past_examples() -> None:
    config = AgentConfig(api_key="test")
    checker = GenerationHealthChecker(config)
    code = "atom copy_me() -> i64 requires: true; ensures: result == 1; body: { 1 }"
    checker.add_past_example(code)

    result = checker.check_generation_health("copy_me result", code)

    assert result.code_diversity_score == 0.0
    assert result.is_healthy is False
    assert any("Low code diversity score" in warning for warning in result.warnings)


def test_public_scoring_methods_are_available() -> None:
    config = AgentConfig(api_key="test")
    checker = GenerationHealthChecker(config)

    assert checker.check_spec_adherence("safe_add result", "atom safe_add result") == 1.0
    assert checker.check_code_diversity("atom fresh() body: { 0 }") == 1.0


def test_generation_health_check_enabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ENABLE_GENERATION_HEALTH_CHECK", raising=False)

    assert AgentConfig(api_key="test").enable_generation_health_check is True


def test_generation_health_check_env_can_disable(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_GENERATION_HEALTH_CHECK", "false")

    assert AgentConfig(api_key="test").enable_generation_health_check is False


def test_generate_code_regenerates_after_health_failure() -> None:
    client = _mock_client("```mumei\natom unrelated() -> i64 body: { 0 }\n```")
    client.chat.completions.create.side_effect = [
        _make_response("```mumei\natom unrelated() -> i64 body: { 0 }\n```"),
        _make_response("```mumei\natom safe_add(a: i64, b: i64) -> i64 body: { a + b }\n```"),
    ]
    spec = {
        "name": "safe_add",
        "params": [{"name": "a", "type": "i64"}, {"name": "b", "type": "i64"}],
        "requires": "a_nonnegative b_nonnegative",
        "ensures": "safe_add result",
        "_agent_config": AgentConfig(api_key="test", enable_generation_health_check=True),
    }

    result, verified = generate_code(client, "test-model", spec, mumei_client=None)

    assert verified is True
    assert "safe_add" in result
    assert client.chat.completions.create.call_count == 2
    assert "_agent_config" in spec


def test_generate_code_skips_health_check_when_disabled() -> None:
    client = _mock_client("```mumei\natom unrelated() -> i64 body: { 0 }\n```")
    spec = {
        "name": "safe_add",
        "params": [],
        "requires": "a_nonnegative b_nonnegative",
        "_agent_config": AgentConfig(api_key="test", enable_generation_health_check=False),
    }

    result, verified = generate_code(client, "test-model", spec, mumei_client=None)

    assert verified is True
    assert "unrelated" in result
    assert client.chat.completions.create.call_count == 1


def test_generate_code_regenerates_after_parse_valid_health_failure() -> None:
    client = _mock_client("```mumei\natom unrelated() -> i64 body: { 0 }\n```")
    client.chat.completions.create.side_effect = [
        _make_response("```mumei\natom unrelated() -> i64 body: { 0 }\n```"),
        _make_response("```mumei\natom safe_add(a: i64, b: i64) -> i64 body: { a + b }\n```"),
    ]
    mumei = _mock_client("")
    mumei.check.side_effect = [
        {"success": True, "stdout": "", "stderr": ""},
        {"success": True, "stdout": "", "stderr": ""},
    ]
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "",
        "stderr": "",
    }
    spec = {
        "name": "safe_add",
        "params": [{"name": "a", "type": "i64"}, {"name": "b", "type": "i64"}],
        "requires": "a_nonnegative b_nonnegative",
        "ensures": "safe_add result",
        "_agent_config": AgentConfig(api_key="test", enable_generation_health_check=True),
    }

    result, verified = generate_code(client, "test-model", spec, mumei_client=mumei)

    assert verified is True
    assert "safe_add" in result
    assert client.chat.completions.create.call_count == 2
    assert mumei.verify.call_count == 1


def test_generate_multi_atom_regenerates_after_parse_valid_health_failure() -> None:
    client = _mock_client("```mumei\natom unrelated() -> i64 body: { 0 }\n```")
    client.chat.completions.create.side_effect = [
        _make_response("```mumei\natom unrelated() -> i64 body: { 0 }\n```"),
        _make_response("```mumei\natom safe_add(a: i64, b: i64) -> i64 body: { a + b }\n```"),
    ]
    mumei = _mock_client("")
    mumei.check.side_effect = [
        {"success": True, "stdout": "", "stderr": ""},
        {"success": True, "stdout": "", "stderr": ""},
    ]
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "",
        "stderr": "",
    }
    spec = {
        "module_name": "math",
        "atoms": [
            {
                "name": "safe_add",
                "inputs": [{"name": "a", "type": "i64"}, {"name": "b", "type": "i64"}],
                "requires": "a_nonnegative b_nonnegative",
                "ensures": "safe_add result",
            }
        ],
        "_agent_config": AgentConfig(api_key="test", enable_generation_health_check=True),
    }

    result, verified = generate_multi_atom(client, "test-model", spec, mumei_client=mumei)

    assert verified is True
    assert "safe_add" in result
    assert client.chat.completions.create.call_count == 2
    assert mumei.verify.call_count == 1
