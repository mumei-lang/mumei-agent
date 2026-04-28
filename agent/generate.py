"""Mumei Generate Mode: AI-driven code generation from specifications.

Accepts a specification (inline JSON or spec file) and generates
verified Mumei code using LLM + mumei check/verify pipeline.
"""
import argparse
import json
import sys

from agent.config import AgentConfig
from agent.mumei_client import create_mumei_client
from agent.metrics import Metrics
from agent.strategies.generate_strategy import generate_code


def _validate_spec(spec: dict) -> None:
    """Validate a spec dict (single-atom or multi-atom format).

    Single-atom format requires a ``name`` key.
    Multi-atom format requires ``atoms`` (list of atom dicts, each with ``name``).

    Raises:
        SystemExit: If the spec is invalid.
    """
    if "atoms" in spec:
        # Multi-atom format
        atoms = spec["atoms"]
        if not isinstance(atoms, list) or len(atoms) == 0:
            print(
                "Error: Multi-atom spec 'atoms' must be a non-empty list.",
                file=sys.stderr,
            )
            sys.exit(1)
        for i, atom in enumerate(atoms):
            if not isinstance(atom, dict) or "name" not in atom:
                print(
                    f"Error: atoms[{i}] must be a dict with a 'name' key.",
                    file=sys.stderr,
                )
                sys.exit(1)
    else:
        # Single-atom format
        if "name" not in spec:
            print(
                "Error: Single-atom spec must have a 'name' key.",
                file=sys.stderr,
            )
            sys.exit(1)


def _load_spec(args: argparse.Namespace) -> dict:
    """Load specification from --spec (inline JSON) or --spec-file (path)."""
    if args.spec is not None:
        try:
            spec = json.loads(args.spec)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in --spec: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.spec_file is not None:
        try:
            with open(args.spec_file, "r", encoding="utf-8") as f:
                spec = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Error: Failed to load spec file: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("Error: Either --spec or --spec-file is required.", file=sys.stderr)
        sys.exit(1)

    _validate_spec(spec)
    return spec


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,
    *,
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    """Build the argument parser for the generate subcommand.

    Args:
        subparsers: Optional subparsers action to add to.
        parser: Optional pre-created parser to add arguments to.
            If neither *subparsers* nor *parser* is given, creates a
            standalone parser.

    Returns:
        The configured ArgumentParser.
    """
    if parser is not None:
        pass  # use the provided parser as-is
    elif subparsers is not None:
        parser = subparsers.add_parser(
            "generate",
            help="Generate Mumei code from a specification",
            description="Generate verified Mumei code from a JSON specification",
        )
    else:
        parser = argparse.ArgumentParser(
            description="Mumei Generate Mode: AI-driven code generation"
        )

    spec_group = parser.add_mutually_exclusive_group(required=True)
    spec_group.add_argument(
        "--spec",
        type=str,
        help="Inline JSON specification string",
    )
    spec_group.add_argument(
        "--spec-file",
        type=str,
        help="Path to a JSON specification file",
    )

    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output path for the generated .mm file",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=None,
        help="Maximum number of fix attempts (default: from config or 5)",
    )
    parser.add_argument(
        "--metrics",
        action="store_true",
        default=False,
        help="Output JSON metrics summary at the end",
    )

    return parser


def main(args: argparse.Namespace | None = None) -> None:
    """Run the generate mode."""
    if args is None:
        parser = build_parser()
        args = parser.parse_args()

    spec = _load_spec(args)
    config = AgentConfig()
    client = config.create_client()
    # Honor ``USE_MCP_CLIENT`` so generate runs can pick up richer
    # semantic feedback from the mumei MCP server when available.
    mumei = create_mumei_client(config.mumei_bin)
    max_retries = args.max_retries if args.max_retries is not None else config.max_retries
    metrics = Metrics()

    if spec.get("atoms"):
        module_name = spec.get("module_name", "module")
        atom_names = [a["name"] for a in spec["atoms"]]
        print(
            f"Mumei Generate Mode: generating module '{module_name}' "
            f"({len(atom_names)} atoms: {', '.join(atom_names)})..."
        )
    else:
        print(f"Mumei Generate Mode: generating '{spec.get('name', 'unknown')}'...")

    generated_code, verified = generate_code(
        client=client,
        model=config.model,
        spec=spec,
        config_max_retries=max_retries,
        mumei_client=mumei,
        metrics=metrics,
    )

    if not generated_code:
        print("Error: Generation failed — no code produced.", file=sys.stderr)
        if args.metrics:
            print(metrics.to_json())
        sys.exit(1)

    # Write output
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(generated_code)

    if verified:
        print(f"Generated verified code written to {args.output}")
    else:
        print(
            f"Warning: Generated code written to {args.output} "
            "but verification failed — output is NOT verified.",
            file=sys.stderr,
        )

    if args.metrics:
        print(metrics.to_json())

    if not verified:
        sys.exit(1)
