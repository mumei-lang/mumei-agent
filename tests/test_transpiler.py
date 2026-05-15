"""Tests for code transpiler."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from agent.config import AgentConfig
from agent.transpiler import CodeTranspiler, build_parser


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_rust_transpiler_simple_function() -> None:
    """Test transpiling simple Rust functions."""
    config = AgentConfig()
    transpiler = CodeTranspiler(config)

    result = transpiler.transpile_file(
        FIXTURES_DIR / "rust_samples" / "simple.rs",
        "rust",
    )

    assert result.success
    assert result.errors == []
    assert "Auto-generated from Rust code" in result.mumei_code
    assert "atom add(a: i64, b: i64) -> i64" in result.mumei_code
    assert "body: {" in result.mumei_code
    assert "a + b" in result.mumei_code
    assert "atom is_positive(x: i64) -> bool" in result.mumei_code
    assert "requires: x >= 0;" in result.mumei_code


def test_c_transpiler_simple_function() -> None:
    """Test transpiling simple C functions."""
    config = AgentConfig()
    transpiler = CodeTranspiler(config)

    result = transpiler.transpile_file(
        FIXTURES_DIR / "c_samples" / "simple.c",
        "c",
    )

    assert result.success
    assert result.errors == []
    assert "Auto-generated from C code" in result.mumei_code
    assert "atom add(a: i64, b: i64) -> i64" in result.mumei_code
    assert "return" not in result.mumei_code
    assert "a + b" in result.mumei_code
    assert "atom clamp_nonzero(x: u64) -> u64" in result.mumei_code
    assert "requires: x > 0;" in result.mumei_code


def test_transpiler_writes_output_path(tmp_path: Path) -> None:
    """Transpiler writes generated Mumei code when output path is provided."""
    output_path = tmp_path / "generated" / "simple.mm"
    result = CodeTranspiler(AgentConfig()).transpile_file(
        FIXTURES_DIR / "rust_samples" / "simple.rs",
        "rust",
        output_path,
    )

    assert result.success
    assert output_path.read_text(encoding="utf-8") == result.mumei_code


def test_transpiler_reports_unsupported_language() -> None:
    """Unsupported languages fail without reading or writing files."""
    result = CodeTranspiler(AgentConfig()).transpile_file(
        Path("missing.go"),
        "go",
    )

    assert result.success is False
    assert result.mumei_code == ""
    assert result.errors == ["Unsupported language: go"]


def test_transpile_parser_accepts_required_options() -> None:
    """CLI parser accepts input, language, and output options."""
    args = build_parser().parse_args(
        [
            "--input",
            "examples/rust_code.rs",
            "--language",
            "rust",
            "--output",
            "output.mm",
        ]
    )

    assert args.input == "examples/rust_code.rs"
    assert args.language == "rust"
    assert args.output == "output.mm"


def test_transpile_subcommand_prints_generated_code() -> None:
    """python -m agent transpile prints generated code when output is omitted."""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent",
            "transpile",
            "--input",
            str(FIXTURES_DIR / "c_samples" / "simple.c"),
            "--language",
            "c",
        ],
        cwd=Path(__file__).parents[1],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Successfully transpiled to Mumei DSL" in completed.stdout
    assert "atom add(a: i64, b: i64) -> i64" in completed.stdout
