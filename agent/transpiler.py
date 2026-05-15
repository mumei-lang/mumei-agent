"""Code transpiler: existing Rust/C/Go code to Mumei DSL."""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agent.config import AgentConfig

Language = Literal["rust", "c", "go"]


@dataclass
class TranspileResult:
    """Result of code transpilation."""

    success: bool
    mumei_code: str
    warnings: list[str]
    errors: list[str]


class CodeTranspiler:
    """Transpile existing code to Mumei DSL."""

    def __init__(self, config: AgentConfig):
        self.config = config

    def transpile_file(
        self,
        input_path: Path,
        language: Language,
        output_path: Path | None = None,
    ) -> TranspileResult:
        """Transpile a single file to Mumei DSL."""
        if language == "rust":
            from agent.transpilers.rust_transpiler import RustTranspiler

            transpiler = RustTranspiler(self.config)
        elif language == "c":
            from agent.transpilers.c_transpiler import CTranspiler

            transpiler = CTranspiler(self.config)
        else:
            return TranspileResult(
                success=False,
                mumei_code="",
                warnings=[],
                errors=[f"Unsupported language: {language}"],
            )

        return transpiler.transpile_file(input_path, output_path)


def build_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    """Build the transpile subcommand parser."""
    if parser is None:
        parser = argparse.ArgumentParser(
            description="Transpile existing code to Mumei DSL.",
        )

    parser.add_argument(
        "--input",
        required=True,
        help="Input source file path",
    )
    parser.add_argument(
        "--language",
        required=True,
        choices=["rust", "c", "go"],
        help="Input source language",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output .mm path. Prints to stdout when omitted.",
    )
    return parser


def main(args: argparse.Namespace) -> None:
    """Transpile existing code to Mumei DSL."""
    config = AgentConfig()
    transpiler = CodeTranspiler(config)

    input_path = Path(args.input)
    language: Language = args.language
    output_path = Path(args.output) if args.output else None

    result = transpiler.transpile_file(input_path, language, output_path)

    if result.success:
        print("Successfully transpiled to Mumei DSL")
        for warning in result.warnings:
            print(f"Warning: {warning}", file=sys.stderr)
        if output_path:
            print(f"Output: {output_path}")
        else:
            print(result.mumei_code)
    else:
        print("Transpilation failed:", file=sys.stderr)
        for error in result.errors:
            print(f"  - {error}", file=sys.stderr)
        sys.exit(1)
