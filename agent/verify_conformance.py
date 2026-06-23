"""CLI for structured conformance verification."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from agent.conformance_verifier import (
    ConformanceVerificationResult,
    verify_conformance,
)
from agent.config import AgentConfig


def build_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    parser = parser or argparse.ArgumentParser(description="Verify spec-to-code conformance.")
    parser.add_argument("--spec", required=True, help="Path to natural-language spec file.")
    parser.add_argument("--code", required=True, help="Path to source code.")
    parser.add_argument("--language", choices=["python", "rust", "go"], help="Source language.")
    parser.add_argument("--output", help="Optional output path.")
    parser.add_argument(
        "--format",
        choices=["human", "json", "markdown"],
        default="json",
        help="Output format (default: json).",
    )
    parser.add_argument(
        "--lang",
        choices=["auto", "en", "ja"],
        default="auto",
        help="Report language.",
    )
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM contract inference.")
    parser.add_argument("--no-mumei", action="store_true", help="Skip mumei verify.")
    return parser


def main(args: argparse.Namespace | None = None) -> ConformanceVerificationResult:
    if args is None:
        args = build_parser().parse_args()
    spec = _read_text(args.spec)
    result = verify_conformance(
        spec,
        args.code,
        config=AgentConfig(),
        language=args.language,
        use_llm=not args.no_llm,
        run_mumei=not args.no_mumei,
    )
    _emit(result, args.output, args.format, args.lang)
    if not result.success:
        sys.exit(1)
    return result


def _emit(
    result: ConformanceVerificationResult,
    output: str | None,
    output_format: str,
    lang: str,
) -> None:
    if output_format == "json":
        payload = json.dumps(asdict(result), indent=2, ensure_ascii=False)
    else:
        from agent.report_formatter import format_result_report

        report_format = "markdown" if output_format == "markdown" else "human"
        payload = format_result_report(result, report_format, lang=lang)
    if output:
        Path(output).write_text(payload + "\n", encoding="utf-8")
    print(payload)


def _read_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Error: failed to read spec file: {exc}", file=sys.stderr)
        sys.exit(2)
