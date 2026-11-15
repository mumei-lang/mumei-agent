"""Opt-in CLI route for declared Go interprocedural summary manifests.

``python -m agent go-summaries`` runs a provisioned ``tools/go-types``
helper on explicitly supplied sources, validates the compiler report
through the fail-closed snapshot reader and emits the
``mumei.go-scalar-parameter-deps/v1`` summary manifest on stdout.

The command stays a host declaration boundary: it never chooses tools,
discovers projects or resolves imports — the caller provisions the
binary and supplies every byte the helper reads. The manifest is a
handoff descriptor (context key, declared dependencies, transfers and
gaps), not a verification verdict or evidence acceptance.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from agent.go_interprocedural import summarize_go, summarize_go_package
from agent.go_type_snapshot import (
    MAX_FILES,
    MAX_SOURCE_BYTES,
    TARGETS,
    SnapshotError,
    load_go_package_snapshot,
    load_go_snapshot,
)

# Mirrors `maxRequest` in tools/go-types/main.go — the helper rejects
# any JSON request larger than 512 KiB, so the route checks the same
# declared bound before spawning instead of reporting a helper failure.
MAX_REQUEST_BYTES = 512 * 1024


def build_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    parser = parser or argparse.ArgumentParser(
        description=(
            "Run a provisioned go-types helper on declared Go sources and "
            "print the summary manifest JSON."
        ),
    )
    parser.add_argument(
        "--go-types",
        required=True,
        metavar="<PATH>",
        help="Path to the provisioned tools/go-types helper binary.",
    )
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        metavar="<PATH>",
        help=(
            "Go source file to summarize. Repeat for a multi-file package "
            "unit; each file is declared under its basename and basenames "
            "must be unique."
        ),
    )
    parser.add_argument(
        "--target-arch",
        choices=sorted(TARGETS),
        default="amd64",
        help="Target architecture for gc sizes (default: amd64).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        metavar="<SECONDS>",
        help="Helper process timeout in seconds (default: 30).",
    )
    parser.add_argument(
        "--output",
        metavar="<PATH>",
        help="Write the manifest JSON here instead of stdout.",
    )
    return parser


def _read_sources(paths: list[str]) -> dict[str, str]:
    """Map each declared basename to its UTF-8 file contents.

    File size is bounded like a report-borne unit: the snapshot reader
    re-checks it, but rejecting an oversized file here keeps the error
    at the route boundary instead of inside the wire format.
    """
    sources: dict[str, str] = {}
    for raw in paths:
        path = Path(raw)
        data = path.read_bytes()
        if len(data) > MAX_SOURCE_BYTES:
            raise SnapshotError(f"declared source exceeds {MAX_SOURCE_BYTES} bytes")
        name = path.name
        if name in sources:
            raise SnapshotError(f"duplicate declared source name {name!r}")
        sources[name] = data.decode("utf-8")
    if len(sources) > MAX_FILES:
        raise SnapshotError(f"declared sources exceed {MAX_FILES} files")
    return sources


def _run_helper(binary: str, payload: bytes, timeout: int) -> bytes:
    if timeout <= 0:
        raise SnapshotError("declared helper timeout must be positive")
    try:
        completed = subprocess.run(
            [binary],
            input=payload,
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise SnapshotError("go-types helper is not executable") from None
    except PermissionError:
        raise SnapshotError("go-types helper is not executable") from None
    except subprocess.TimeoutExpired:
        raise SnapshotError("go-types helper timed out") from None
    if completed.returncode != 0 or completed.stderr:
        # The helper speaks one JSON object and nothing else; any side
        # channel or nonzero exit means the report cannot be trusted.
        raise SnapshotError("go-types helper failed to produce a report")
    return completed.stdout


def _summarize(sources: dict[str, str], payload: bytes, target_arch: str):
    if len(sources) == 1:
        source = next(iter(sources.values()))
        return summarize_go(
            source, load_go_snapshot(payload, source, target_arch=target_arch)
        )
    return summarize_go_package(
        sources,
        load_go_package_snapshot(payload, sources, target_arch=target_arch),
    )


def main(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_parser().parse_args()
    try:
        sources = _read_sources(args.source)
        if args.output is not None and Path(args.output).resolve() in {
            Path(raw).resolve() for raw in args.source
        }:
            raise SnapshotError(
                "declared output path would overwrite a declared source"
            )
        if len(sources) == 1:
            request = {
                "source": next(iter(sources.values())),
                "target_arch": args.target_arch,
            }
        else:
            request = {
                "sources": [
                    {"name": name, "source": text}
                    for name, text in sources.items()
                ],
                "target_arch": args.target_arch,
            }
        payload = json.dumps(request).encode()
        if len(payload) > MAX_REQUEST_BYTES:
            raise SnapshotError(
                f"declared request exceeds the {MAX_REQUEST_BYTES}-byte "
                "helper bound"
            )
        report = _run_helper(args.go_types, payload, args.timeout)
        manifest = _summarize(sources, report, args.target_arch).to_dict()
        document = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        if args.output:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (SnapshotError, OSError, UnicodeDecodeError) as exc:
        print(f"go-summaries: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
