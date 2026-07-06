"""Tests for source-code to natural-language spec extraction."""
from __future__ import annotations

import typing
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent.code_to_spec import CodeToSpecConverter, CodeToSpecExtractor, Language
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


def test_detect_language_solidity_from_extension_and_content() -> None:
    extractor = CodeToSpecExtractor(AgentConfig(api_key="test"))

    assert extractor._detect_language(Path("Ledger.sol"), "") == "solidity"
    assert extractor._detect_language(
        Path("unknown"),
        "pragma solidity ^0.8.0;\nfunction add(uint256 a) {}",
    ) == "solidity"
    assert extractor._detect_language(
        Path("unknown"),
        "contract Ledger {\n    function add() public {}\n}",
    ) == "solidity"


def test_convert_source_layer_b_solidity_succeeds() -> None:
    converter = CodeToSpecConverter(AgentConfig())
    result = converter.convert_source(
        "function add(uint256 a, uint256 b) public pure returns (uint256) {\n"
        "    return a + b;\n"
        "}\n",
        "solidity",
    )

    assert result.success is True
    assert result.detected_language == "solidity"
    assert result.atoms[0].name == "add"


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


def test_extract_from_shift_jis_file_with_mock_llm(tmp_path: Path) -> None:
    source = tmp_path / "simple_add.rs"
    source.write_bytes(
        "// 日本語コメント\npub fn simple_add(a: i64, b: i64) -> i64 { a + b }\n".encode("cp932")
    )

    forge_spec = {
        "task_id": "code-simple-add",
        "target_file": "std/math/simple_add.mm",
        "mode": "create",
        "atoms": [],
    }
    client = MagicMock()
    client.chat.completions.create.return_value = _make_response("Add two signed integers.")
    config = AgentConfig(api_key="test", model="test-model")
    config.create_client = MagicMock(return_value=client)
    extractor = CodeToSpecExtractor(config)

    with patch("agent.spec_extractor.extract_spec", return_value=forge_spec):
        result = extractor.extract_from_file(source)

    assert result.success is True
    assert result.detected_language == "rust"
    prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "日本語コメント" in prompt


def test_detect_language_from_extension_java_cpp() -> None:
    """Layer A languages: Java and C++ are detected from extensions."""
    extractor = CodeToSpecExtractor(AgentConfig(api_key="test"))

    assert extractor._detect_language(Path("Main.java"), "") == "java"
    assert extractor._detect_language(Path("lib.cpp"), "") == "cpp"
    assert extractor._detect_language(Path("lib.cc"), "") == "cpp"
    assert extractor._detect_language(Path("lib.cxx"), "") == "cpp"
    assert extractor._detect_language(Path("header.hpp"), "") == "cpp"
    assert extractor._detect_language(Path("app.js"), "") == "javascript"
    assert extractor._detect_language(Path("app.jsx"), "") == "javascript"


def test_detect_language_from_content_java_cpp() -> None:
    """Layer A languages: Java and C++ are detected from content heuristics."""
    extractor = CodeToSpecExtractor(AgentConfig(api_key="test"))

    assert extractor._detect_language(
        Path("unknown"),
        "public static void main(String[] args) {}",
    ) == "java"
    assert extractor._detect_language(
        Path("unknown"),
        '#include <vector>\nstd::vector<int> v;\nnamespace demo {}',
    ) == "cpp"


def test_extract_from_file_layer_a_java(tmp_path: Path) -> None:
    """Layer A extraction works for Java (no LLM, deterministic fallback)."""
    source = tmp_path / "Main.java"
    source.write_text(
        "public class Main {\n"
        "    public static int add(int a, int b) { return a + b; }\n"
        "}\n",
        encoding="utf-8",
    )
    config = AgentConfig(api_key="")
    extractor = CodeToSpecExtractor(config)

    result = extractor.extract_from_file(source)

    assert result.detected_language == "java"


def test_convert_source_layer_b_unsupported_returns_layer_a_hint() -> None:
    """convert_source for a Layer-A-only language returns a helpful error."""
    converter = CodeToSpecConverter(AgentConfig())
    result = converter.convert_source("class Main {}", "java")

    assert result.success is False
    assert "spec extraction (Layer A)" in result.errors[0]
    assert "Z3 strict verification (Layer B)" in result.errors[0]
    assert result.detected_language == "java"


def test_convert_source_layer_b_supported_succeeds() -> None:
    """convert_source for a Layer B language succeeds."""
    converter = CodeToSpecConverter(AgentConfig())
    result = converter.convert_source(
        "def add(a: int, b: int) -> int:\n    return a + b\n",
        "python",
    )

    assert result.success is True
    assert result.detected_language == "python"


def test_extension_map_matches_language_type() -> None:
    """EXTENSION_MAP values are a subset of the Language literal."""
    allowed = set(typing.get_args(Language))
    ext_languages = set(CodeToSpecExtractor.EXTENSION_MAP.values())
    assert ext_languages <= allowed, f"EXTENSION_MAP has languages not in Language type: {ext_languages - allowed}"
