"""CLI for checking harvested test behavior against Mumei contracts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent.config import AgentConfig
from agent.mumei_client import create_mumei_client
from agent.test_harvest import HarvestInputError, harvest_tests
from agent.test_observations import (
    ObservationCheckError,
    align_harvest_to_spec,
    check_observations,
    observation_summary,
    observation_warnings,
    spec_to_observe_module,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agent observe-tests",
        description="Check harvested Python and Rust test observations against Mumei atoms.",
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--mm", help="Mumei module containing the contracts.")
    source_group.add_argument("--spec", help="Forge task spec JSON containing the contracts.")
    parser.add_argument("paths", nargs="+", help="Test source files or directories.")
    parser.add_argument("--language", choices=("rust", "python"))
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--output", help="Write the observation report to this file.")
    return parser


def main(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_parser().parse_args()
    try:
        harvest = harvest_tests(
            [Path(path) for path in args.paths],
            args.language,
            set(args.target) if args.target else None,
        )
    except HarvestInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    if not harvest.get("observations"):
        print("error: no test observations were harvested", file=sys.stderr)
        return 4

    try:
        spec = {}
        if args.mm:
            module_path_or_source: str | Path = Path(args.mm)
            aligned = harvest
        else:
            spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
            if not isinstance(spec, dict):
                raise ValueError("spec JSON must be an object")
            module_path_or_source = spec_to_observe_module(spec)
            aligned = align_harvest_to_spec(harvest, spec)
        report = check_observations(
            module_path_or_source,
            aligned,
            create_mumei_client(AgentConfig().mumei_bin),
        )
    except (OSError, json.JSONDecodeError, ObservationCheckError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4

    print(observation_summary(report), file=sys.stderr)
    for warning in observation_warnings(report, spec if args.spec else {}, aligned):
        print(f"Warning: {warning}", file=sys.stderr)
    output = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.output:
        try:
            output_path = Path(args.output).expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(output, encoding="utf-8")
        except OSError as exc:
            print(f"error: cannot write report: {exc}", file=sys.stderr)
            return 4
    else:
        sys.stdout.write(output)
    results = report.get("results", [])
    return int(
        any(
            isinstance(result, dict)
            and result.get("verdict")
            in {"contradicts_ensures", "requires_admits_rejected"}
            for result in results
        )
    )
