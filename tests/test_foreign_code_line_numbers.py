"""Tests for foreign-code source line mapping."""
from __future__ import annotations

from agent.config import AgentConfig
from agent.cross_validation import validate_foreign_code
from agent.strategies.foreign_code_strategy import ForeignCodeExtractor


def test_python_extract_preserves_line_numbers() -> None:
    source = "\n\n\ndef add(a: int, b: int) -> int:\n    return a + b\n"

    specs = ForeignCodeExtractor().extract_python(source)

    assert specs[0].function_name == "add"
    assert specs[0].source_line == 4


def test_typescript_extract_preserves_line_numbers() -> None:
    source = "\n/**\n * ensures: result == a + b\n */\nexport function add(a: number, b: number): number {\n  return a + b;\n}\n"

    specs = ForeignCodeExtractor().extract_typescript(source)

    assert specs[0].function_name == "add"
    assert specs[0].source_line == 5


def test_rust_extract_preserves_line_numbers() -> None:
    source = "\n/// ensures: result >= x\npub fn widen(x: i64) -> i64 {\n    x + 1\n}\n"

    specs = ForeignCodeExtractor().extract_rust(source)

    assert specs[0].function_name == "widen"
    assert specs[0].source_line == 3


def test_validate_foreign_code_includes_source_line_map() -> None:
    source = "\n\ndef add(a: int, b: int) -> int:\n    return a + b\n"

    result = validate_foreign_code(
        source,
        "python",
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.source_line_map == {"add": 3}
