"""Tests for natural-language ambiguity detection."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from agent.ambiguity_detector import AmbiguityDetector, AmbiguityFinding
from agent.config import AgentConfig
from agent.prompts.ambiguity_detection import build_disambiguation_prompt


def _make_response(text: str) -> MagicMock:
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def test_detect_ambiguity_patterns_without_llm() -> None:
    detector = AmbiguityDetector(AgentConfig(api_key="test"))

    result = detector.detect_ambiguity(
        "必要に応じて適切な検査を行い、もし異常なら停止する。",
        use_llm=False,
    )

    assert result.has_ambiguity is True
    assert result.errors == []
    assert {finding.ambiguity_type for finding in result.findings} == {
        "quantifier",
        "vague_adjective",
        "conditional",
    }
    assert any(
        "具体的" in suggestion or "concrete" in suggestion
        for suggestion in result.findings[0].suggested_clarifications
    )


def test_suggest_disambiguation_uses_existing_finding_suggestions() -> None:
    detector = AmbiguityDetector(AgentConfig(api_key="test"))
    finding = AmbiguityFinding(
        ambiguous_text="十分な",
        ambiguity_type="vague_adjective",
        location="Position 0-3",
        suggested_clarifications=["define sufficient capacity"],
    )

    assert detector.suggest_disambiguation(finding) == ["define sufficient capacity"]


def test_suggest_disambiguation_from_ambiguity_type() -> None:
    detector = AmbiguityDetector(AgentConfig(api_key="test"))

    suggestions = detector.suggest_disambiguation("conditional")

    assert any("else" in suggestion for suggestion in suggestions)


def test_detect_ambiguity_llm_object_payload() -> None:
    config = AgentConfig(api_key="test", model="m")
    client = MagicMock()
    client.chat.completions.create.return_value = _make_response(
        json.dumps(
            {
                "findings": [
                    {
                        "ambiguous_text": "迅速に",
                        "ambiguity_type": "vague_adjective",
                        "location": "sentence 1",
                        "suggested_clarifications": ["Set a maximum response time."],
                    }
                ]
            },
            ensure_ascii=False,
        )
    )
    config.create_client = MagicMock(return_value=client)  # type: ignore[method-assign]
    detector = AmbiguityDetector(config)

    result = detector.detect_ambiguity("迅速に応答する", use_llm=True)

    assert result.has_ambiguity is True
    assert any(finding.ambiguous_text == "迅速に" for finding in result.findings)
    assert client.chat.completions.create.call_args.kwargs["model"] == "m"


def test_detect_ambiguity_skips_llm_when_disabled() -> None:
    config = AgentConfig(api_key="", enable_ambiguity_detection=False)
    detector = AmbiguityDetector(config)

    result = detector.detect_ambiguity("適切な検査を行う", use_llm=True)

    assert result.has_ambiguity is True
    assert result.warnings == []
    assert result.findings[0].ambiguous_text == "適切な"


def test_detect_ambiguity_returns_error_for_empty_input() -> None:
    detector = AmbiguityDetector(AgentConfig(api_key="test"))

    result = detector.detect_ambiguity(" ", use_llm=False)

    assert result.has_ambiguity is False
    assert result.errors == ["natural_language must be non-empty"]


def test_build_disambiguation_prompt_contains_requirement() -> None:
    prompt = build_disambiguation_prompt("十分な残高がある場合に送金する")

    assert "十分な残高がある場合に送金する" in prompt
    assert "vague_adjective" in prompt
    assert "findings" in prompt
