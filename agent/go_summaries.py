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

from agent.go_interprocedural import (
    GoSummarySet,
    summarize_go,
    summarize_go_package,
)
from agent.go_type_snapshot import (
    MAX_FILES,
    MAX_SOURCE_BYTES,
    TARGETS,
    SnapshotError,
    load_go_package_snapshot,
    load_go_snapshot,
)

# Mirrors `maxRequest`/`maxImports` in tools/go-types/main.go — the
# helper rejects a JSON request larger than 512 KiB or declaring more
# than 64 import units, so the route checks the same declared bounds
# before spawning instead of reporting a helper failure.
MAX_REQUEST_BYTES = 512 * 1024
MAX_IMPORTS = 64

# A manifest derives from a reply-bounded helper report (at most 64
# files), so 8 MiB — the helper's own `maxReply` — bounds a declared
# manifest file the check route reads.
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
CHECK_PROFILE = "mumei.go-summary-check/v1"


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
        "--import",
        dest="imports",
        action="append",
        default=[],
        metavar="<IMPORT_PATH>=<FILE>",
        help=(
            "Declare one source file of an importable package. Repeat "
            "per file and per import path; each path declares a "
            "package unit. Requires a multi-file --source package unit."
        ),
    )
    parser.add_argument(
        "--output",
        metavar="<PATH>",
        help="Write the manifest JSON here instead of stdout.",
    )
    return parser


def build_check_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    """Parser for ``go-summaries-check``: the produce route's declared
    inputs plus ``--manifest`` naming the summary manifest to check."""
    parser = build_parser(parser)
    parser.description = (
        "Run a provisioned go-types helper on declared Go sources and "
        "check a declared summary manifest against the fresh report."
    )
    parser.add_argument(
        "--manifest",
        required=True,
        metavar="<PATH>",
        help="Summary manifest (mumei.go-scalar-parameter-deps/v1) to check.",
    )
    for action in parser._actions:
        if action.dest == "output":
            action.help = "Write the check report JSON here instead of stdout."
    return parser


def build_reuse_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    """Parser for ``go-summaries-reuse``: the produce route's declared
    inputs plus ``--manifest`` naming the summary manifest to reuse."""
    parser = build_check_parser(parser)
    parser.description = (
        "Run a provisioned go-types helper on declared Go sources and "
        "emit a manifest that reuses a declared manifest's summaries "
        "for the functions the fresh report confirms unchanged."
    )
    for action in parser._actions:
        if action.dest == "manifest":
            action.help = (
                "Summary manifest (mumei.go-scalar-parameter-deps/v1) "
                "to reuse."
            )
        elif action.dest == "output":
            action.help = (
                "Write the merged manifest JSON here instead of stdout."
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


def _read_imports(specs: list[str]) -> dict[str, dict[str, str]]:
    """Group declared ``<IMPORT_PATH>=<FILE>`` pairs per import path.

    Same per-unit discipline as `_read_sources`: every file bounded,
    basenames unique inside a unit, unit count bounded — mirroring the
    helper's `imports` contract so a malformed declaration fails at the
    route, not as an `invalid_request` report gap.
    """
    units: dict[str, dict[str, str]] = {}
    for spec in specs:
        path, sep, raw = spec.partition("=")
        if not sep or not path or not raw:
            raise SnapshotError(
                "declared import must be <IMPORT_PATH>=<FILE>"
            )
        data = Path(raw).read_bytes()
        if len(data) > MAX_SOURCE_BYTES:
            raise SnapshotError(
                f"declared source exceeds {MAX_SOURCE_BYTES} bytes"
            )
        unit = units.setdefault(path, {})
        name = Path(raw).name
        if name in unit:
            raise SnapshotError(
                f"duplicate declared source name {name!r} in import {path!r}"
            )
        unit[name] = data.decode("utf-8")
    if len(units) > MAX_IMPORTS:
        raise SnapshotError(f"declared imports exceed {MAX_IMPORTS} units")
    for path, unit in units.items():
        if len(unit) > MAX_FILES:
            raise SnapshotError(
                f"declared import {path!r} exceeds {MAX_FILES} files"
            )
    return units


def _read_manifest(path: str) -> GoSummarySet:
    """Restore a declared summary manifest file.

    Bounded like the report it derives from and restored through the
    strict `from_dict` boundary — a malformed document is a declared
    error, never a parse exception.
    """
    raw = Path(path).read_bytes()
    if len(raw) > MAX_MANIFEST_BYTES:
        raise SnapshotError(
            f"declared manifest exceeds {MAX_MANIFEST_BYTES} bytes"
        )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise SnapshotError("declared manifest is not JSON") from None
    return GoSummarySet.from_dict(value)


def _collect_strings(item: object, acc: set[str]) -> None:
    if isinstance(item, str):
        acc.add(item)
    elif isinstance(item, dict):
        for value in item.values():
            _collect_strings(value, acc)
    elif isinstance(item, list):
        for value in item:
            _collect_strings(value, acc)


def _report_identities(value: object, acc: set[str]) -> None:
    """Collect every identity string a helper report declares.

    `stale_dependents` flags a summary that references an identity the
    fresh report no longer produces, so `known` is the union of binding
    ids, imported member ids and type identities anywhere in the report
    — including the identity *lists* members declare
    (`signature_type_ids`, `pointee_type_ids`, `type_arg_type_ids`), not
    only scalar `id`/`binding_id`/`type_id` fields.
    """
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "id" or key.endswith("_id") or key.endswith("_ids"):
                _collect_strings(item, acc)
            else:
                _report_identities(item, acc)
    elif isinstance(value, list):
        for item in value:
            _report_identities(item, acc)


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


def _run_declared(
    args: argparse.Namespace,
) -> tuple[dict[str, str], bytes]:
    """Read declared inputs, build the helper request and run it.

    Shared by both routes: the produce route emits the manifest, the
    check route compares a declared manifest against the same fresh
    report.
    """
    sources = _read_sources(args.source)
    try:
        declared = {Path(raw).resolve() for raw in args.source}
        declared.update(
            Path(spec.partition("=")[2]).resolve()
            for spec in args.imports
        )
        manifest = getattr(args, "manifest", None)
        if manifest is not None:
            declared.add(Path(manifest).resolve())
    except RuntimeError:
        raise SnapshotError("declared path cannot be resolved") from None
    if args.output is not None:
        try:
            output_path = Path(args.output).resolve()
        except RuntimeError:
            raise SnapshotError(
                "declared output path cannot be resolved"
            ) from None
        if output_path in declared:
            raise SnapshotError(
                "declared output path would overwrite a declared source"
            )
    if len(sources) == 1:
        request: dict = {
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
    imports = _read_imports(args.imports)
    if imports and len(sources) == 1:
        raise SnapshotError(
            "declared imports require a multi-file --source package unit"
        )
    if imports:
        request["imports"] = [
            {
                "path": path,
                "sources": [
                    {"name": name, "source": text}
                    for name, text in unit.items()
                ],
            }
            for path, unit in imports.items()
        ]
    payload = json.dumps(request).encode()
    if len(payload) > MAX_REQUEST_BYTES:
        raise SnapshotError(
            f"declared request exceeds the {MAX_REQUEST_BYTES}-byte "
            "helper bound"
        )
    return sources, _run_helper(args.go_types, payload, args.timeout)


def _emit(document: str, output: str | None) -> None:
    if output:
        Path(output).write_text(document, encoding="utf-8")
    else:
        sys.stdout.write(document)


def main(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_parser().parse_args()
    try:
        sources, report = _run_declared(args)
        manifest = _summarize(sources, report, args.target_arch).to_dict()
        document = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        _emit(document, args.output)
    except (SnapshotError, OSError, UnicodeDecodeError) as exc:
        print(f"go-summaries: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0


def _reuse_partition(
    restored: GoSummarySet, live: GoSummarySet, report: bytes
) -> tuple[list[str], list[str], list[str]]:
    """Partition the manifest's functions against the fresh report.

    `reusable` — the identity survives in the fresh report and
    `stale_dependents` does not flag it; `stale` — it references a
    replaced identity, transitively; `missing` — the fresh report no
    longer produces the identity. Detection only.
    """
    known: set[str] = set()
    _report_identities(json.loads(report), known)
    live_ids = {f.binding_id for f in live.functions}
    stale = restored.stale_dependents(known)
    reusable, stale_ids, missing = [], [], []
    for entry in restored.functions:
        if entry.binding_id not in live_ids:
            missing.append(entry.binding_id)
        elif entry.binding_id in stale:
            stale_ids.append(entry.binding_id)
        else:
            reusable.append(entry.binding_id)
    return reusable, stale_ids, missing


def main_check(args: argparse.Namespace | None = None) -> int:
    """Check a declared manifest against a fresh helper report.

    Emits ``mumei.go-summary-check/v1``: whether the declared context
    key still matches (the strict `for_function` gate) and an
    identity-level partition of the manifest's functions — `reusable`
    (identity survived and nothing it references went stale), `stale`
    (references a replaced identity, transitively) and `missing` (the
    fresh report no longer produces the identity). Detection only —
    what to recompute is the host's call.
    """
    if args is None:
        args = build_check_parser().parse_args()
    try:
        restored = _read_manifest(args.manifest)
        sources, report = _run_declared(args)
        live = _summarize(sources, report, args.target_arch)
        reusable, stale_ids, missing = _reuse_partition(restored, live, report)
        document = (
            json.dumps(
                {
                    "schema_version": CHECK_PROFILE,
                    "context_match": restored.context_key
                    == live.context_key,
                    "reusable": sorted(reusable),
                    "stale": sorted(stale_ids),
                    "missing": sorted(missing),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        _emit(document, args.output)
    except (SnapshotError, OSError, UnicodeDecodeError) as exc:
        print(f"go-summaries-check: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0


def main_reuse(args: argparse.Namespace | None = None) -> int:
    """Emit a manifest reusing a declared manifest's unchanged summaries.

    Same partition as ``go-summaries-check``: a manifest function whose
    identity survives in the fresh report and that `stale_dependents`
    does not flag is reused verbatim, every other live function is
    freshly derived and a `missing` entry is dropped. The emitted set is
    keyed to the fresh context — per-function reuse stays the host's
    weaker freshness choice, never the strict `for_function` gate.
    """
    if args is None:
        args = build_reuse_parser().parse_args()
    try:
        restored = _read_manifest(args.manifest)
        if restored.target_arch != args.target_arch:
            raise SnapshotError(
                "declared manifest was derived for a different "
                "target architecture"
            )
        sources, report = _run_declared(args)
        live = _summarize(sources, report, args.target_arch)
        reusable, _, _ = _reuse_partition(restored, live, report)
        by_id = {f.binding_id: f for f in restored.functions}
        merged = GoSummarySet(
            live.context_key,
            tuple(
                by_id[f.binding_id] if f.binding_id in reusable else f
                for f in live.functions
            ),
        )
        document = json.dumps(merged.to_dict(), indent=2, sort_keys=True) + "\n"
        _emit(document, args.output)
    except (SnapshotError, OSError, UnicodeDecodeError) as exc:
        print(f"go-summaries-reuse: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
