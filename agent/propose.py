"""Phase 2-A — Forge task spec proposer.

Bridges the ``analyze_std_gaps`` MCP tool (exposed by the mumei
repository's ``mcp_server.py``) to mumei-agent's forge pipeline.

Flow
----
1. Read a JSON document produced by ``analyze_std_gaps`` (either from a
   file via ``--gaps-json`` or by invoking the MCP tool live via
   ``--auto``).
2. For every proposal under ``proposals``, synthesise a
   ``forge_tasks/vstd_*.json`` spec that is forward-compatible with the
   existing forge runner (``agent/forge.py``).
3. Convert ``depends_on`` entries into an ``import "<module>" as
   <alias>;`` preamble so the generated module can rely on the upstream
   std contracts, and scale ``max_retries`` by ``difficulty``
   (``low``=3, ``medium``=5, ``high``=8).
4. Print a human-readable summary for each proposal so operators can
   sanity-check the plan before kicking off a forge run.

The output specs are fully compatible with ``python -m agent generate``
(single-atom shape via the wrapped task is not produced here — forge
tasks intentionally drive the ``create`` mode pipeline).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Seam-free pure helpers live in ``agent.propose_helpers``; re-import them
# here so the historical ``agent.propose.<name>`` surface is preserved for
# callers and tests.
from agent.propose_helpers import (  # noqa: F401
    _DIFFICULTY_RETRIES,
    _SLUG_RE,
    _build_import_preamble,
    _load_gaps_from_file,
    _module_name_from_path,
    _module_to_import,
    _module_to_slug,
    _print_summary,
    _proposal_filename,
    _proposal_to_task_id,
    _resolve_max_retries,
    build_spec_from_proposal,
    build_specs_from_gaps,
    write_specs,
)


def _load_gaps_from_mcp() -> dict[str, Any]:
    """Invoke the ``analyze_std_gaps`` MCP tool in-process.

    Imports the mumei MCP server module lazily so this path is optional:
    when mumei is not reachable on ``PYTHONPATH``, operators can still
    use ``--gaps-json`` with a pre-captured payload.
    """
    try:
        import importlib

        module = importlib.import_module("mcp_server")
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Error: --auto requires the mumei repo's mcp_server module to be "
            "importable (set PYTHONPATH to the mumei checkout, or install "
            "the mumei package).\n"
            f"  underlying error: {exc}"
        ) from exc

    analyze = getattr(module, "analyze_std_gaps", None)
    if analyze is None:
        raise SystemExit(
            "Error: 'analyze_std_gaps' is not exported by the imported mcp_server module"
        )

    # FastMCP decorates tool callables with a ``.fn`` attribute that
    # exposes the raw Python function.  Fall back to direct invocation
    # when no such wrapper is present.
    raw_callable = getattr(analyze, "fn", analyze)
    if not callable(raw_callable):
        raise SystemExit("Error: analyze_std_gaps is not callable")

    result = raw_callable()
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"Error: analyze_std_gaps returned non-JSON output: {exc}"
            ) from exc
    if isinstance(result, dict):
        return result
    raise SystemExit(
        "Error: analyze_std_gaps returned an unexpected type: "
        f"{type(result).__name__}"
    )


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,
    *,
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    """Build the ``propose`` subcommand parser."""
    if parser is None and subparsers is not None:
        parser = subparsers.add_parser(
            "propose",
            help="Generate forge_tasks/ specs from analyze_std_gaps output",
            description=(
                "Phase 2-A — convert the JSON output of mumei's "
                "analyze_std_gaps MCP tool into forge task spec files "
                "consumable by `python -m agent forge`."
            ),
        )
    elif parser is None:
        parser = argparse.ArgumentParser(
            prog="python -m agent propose",
            description=(
                "Generate forge task specs from analyze_std_gaps output"
            ),
        )

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--gaps-json",
        type=str,
        help="Path to a JSON file produced by analyze_std_gaps",
    )
    source.add_argument(
        "--auto",
        action="store_true",
        help=(
            "Invoke analyze_std_gaps via the mumei MCP server in-process "
            "(requires the mumei repo on PYTHONPATH)"
        ),
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default="forge_tasks",
        help="Directory to write generated spec files into (default: forge_tasks/)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="Overwrite existing vstd_*.json files instead of writing a suffixed copy",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print the plan without writing any files",
    )

    return parser


def main(args: argparse.Namespace | None = None) -> None:
    """CLI entrypoint for ``python -m agent propose``."""
    if args is None:
        parser = build_parser()
        args = parser.parse_args()

    if getattr(args, "gaps_json", None):
        gaps = _load_gaps_from_file(Path(args.gaps_json))
    elif getattr(args, "auto", False):
        gaps = _load_gaps_from_mcp()
    else:  # pragma: no cover — argparse enforces the exclusivity
        raise SystemExit("Error: either --gaps-json or --auto is required")

    specs = build_specs_from_gaps(gaps)
    if not specs:
        print("propose: no proposals found in analyze_std_gaps output; nothing to do.")
        return

    if args.dry_run:
        print(
            f"propose: dry-run — would generate {len(specs)} spec(s) "
            f"into {args.output_dir}/"
        )
        for spec in specs:
            deps = ", ".join(spec.get("depends_on") or []) or "(none)"
            print(
                f"  - {spec['task_id']:<30} -> {spec['target_file']} "
                f"[max_retries={spec.get('max_retries', '?')}, "
                f"depends_on={deps}]"
            )
        return

    output_dir = Path(args.output_dir)
    paths = write_specs(specs, output_dir, overwrite=args.overwrite)
    _print_summary(specs, paths)


if __name__ == "__main__":  # pragma: no cover - manual invocation
    logging.basicConfig(level=logging.INFO)
    main()
