"""CLI for extracting Mumei forge task specs from natural language."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent.config import AgentConfig
from agent.mumei_client import create_mumei_client
from agent.spec_extractor import extract_and_generate, extract_spec


def _read_text(args: argparse.Namespace) -> str:
    """Read requirement text from CLI arguments."""
    if args.text is not None:
        return args.text
    try:
        return Path(args.text_file).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Error: Failed to read --text-file: {exc}", file=sys.stderr)
        sys.exit(1)


def build_parser(parser=None):
    """Add extract-spec arguments to an argparse parser."""
    if parser is None:
        parser = argparse.ArgumentParser(
            description="Extract Mumei specifications from natural language text."
        )

    text_group = parser.add_mutually_exclusive_group(required=True)
    text_group.add_argument(
        "--text",
        type=str,
        help="Natural language requirement text",
    )
    text_group.add_argument(
        "--text-file",
        type=str,
        help="Path to a file containing natural language requirements",
    )
    parser.add_argument(
        "--domain",
        choices=["financial", "regtech", "security", "data_structure", "general"],
        default="",
        help="Optional domain hint for safer specification extraction",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output path for the extracted forge task spec JSON",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate and verify .mm code after extracting the spec",
    )
    parser.add_argument(
        "--generate-output",
        help="Output path for generated .mm code when --generate is set",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum spec extraction retry attempts",
    )
    parser.add_argument(
        "--max-generation-retries",
        type=int,
        default=None,
        help="Maximum code generation/self-healing retry attempts",
    )
    parser.add_argument(
        "--max-refinements",
        type=int,
        default=3,
        help="Maximum spec refinement attempts when --generate is set",
    )
    return parser


def main(args=None):
    """Run natural-language spec extraction."""
    if args is None:
        parser = build_parser()
        args = parser.parse_args()

    if args.generate and not args.generate_output:
        print("Error: --generate-output is required when --generate is set.", file=sys.stderr)
        sys.exit(1)

    natural_language = _read_text(args)
    config = AgentConfig()
    client = config.create_client()
    mumei = create_mumei_client(config.mumei_bin)
    domain_hint = "" if args.domain == "general" else args.domain

    try:
        if args.generate:
            max_generation_retries = (
                args.max_generation_retries
                if args.max_generation_retries is not None
                else config.max_retries
            )
            code, verified, spec = extract_and_generate(
                client,
                config.model,
                natural_language,
                domain_hint=domain_hint,
                mumei_client=mumei,
                max_extraction_retries=args.max_retries,
                max_generation_retries=max_generation_retries,
                max_refinements=args.max_refinements,
            )
        else:
            code = ""
            verified = False
            spec = extract_spec(
                client,
                config.model,
                natural_language,
                domain_hint=domain_hint,
                mumei_client=mumei,
                max_retries=args.max_retries,
            )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    Path(args.output).write_text(
        json.dumps(spec, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Extracted spec written to {args.output}")

    if args.generate:
        if not code:
            print("Error: Generation failed — no code produced.", file=sys.stderr)
            sys.exit(1)
        Path(args.generate_output).write_text(code, encoding="utf-8")
        if verified:
            print(f"Generated verified code written to {args.generate_output}")
        else:
            print(
                f"Warning: Generated code written to {args.generate_output} "
                "but verification failed — output is NOT verified.",
                file=sys.stderr,
            )
            sys.exit(1)
