"""Tests for source-code to natural-language spec extraction."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agent.code_to_spec import CodeToSpecExtractor
from agent.config import AgentConfig


def _make_response(text: str) -> MagicMock:
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def test_detect_language_from_extension() -> None:
    extractor = CodeToSpecExtractor(AgentConfig(api_key="test"))

    assert extractor._detect_language(Path("simple_add.rs"), "") == "rust"
    assert extractor._detect_language(Path("simple_add.c"), "") == "c"
    assert extractor._detect_language(Path("simple_add.py"), "") == "python"
    assert extractor._detect_language(Path("simple_add.go"), "") == "go"
    assert extractor._detect_language(Path("simple_add.ts"), "") == "typescript"


def test_detect_language_from_content() -> None:
    extractor = CodeToSpecExtractor(AgentConfig(api_key="test"))

    assert extractor._detect_language(Path("unknown"), "fn main() {}") == "rust"
    assert extractor._detect_language(Path("unknown"), "#include <stdio.h>\nint main() {}") == "c"
    assert extractor._detect_language(Path("unknown"), "package main\nfunc add() {}") == "go"
    assert extractor._detect_language(Path("unknown"), "def simple_add(a, b):\n    return a + b") == "python"
    assert extractor._detect_language(Path("unknown"), "function simpleAdd(a, b) { return a + b; }") == "javascript"


def test_extract_from_file_with_mock_llm(tmp_path: Path) -> None:
    source = tmp_path / "simple_add.rs"
    source.write_text("pub fn simple_add(a: i64, b: i64) -> i64 { a + b }\n", encoding="utf-8")

    forge_spec = {
        "task_id": "code-simple-add",
        "target_file": "std/math/simple_add.mm",
        "mode": "create",
        "atoms": [
            {
                "name": "simple_add",
                "description": "Add two signed integers",
                "inputs": [{"name": "a", "type": "i64"}, {"name": "b", "type": "i64"}],
                "return_type": "i64",
                "requires": "a + b <= i64::MAX && a + b >= i64::MIN",
                "ensures": "result == a + b",
                "effects": [],
            }
        ],
    }
    client = MagicMock()
    client.chat.completions.create.return_value = _make_response(
        "The simple_add function returns the sum of two i64 inputs. "
        "The addition must not overflow, and the result equals a + b. "
        "It has no side effects."
    )
    config = AgentConfig(api_key="test", model="test-model")
    config.create_client = MagicMock(return_value=client)
    extractor = CodeToSpecExtractor(config)

    with patch("agent.spec_extractor.extract_spec", return_value=forge_spec) as mock_extract:
        result = extractor.extract_from_file(source)

    assert result.success is True
    assert result.detected_language == "rust"
    assert "result equals a + b" in result.natural_language_spec
    assert result.forge_task_spec == forge_spec
    client.chat.completions.create.assert_called_once()
    mock_extract.assert_called_once()
    assert mock_extract.call_args.kwargs["domain_hint"] == ""
