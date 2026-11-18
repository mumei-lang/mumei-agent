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
import hashlib
import json
import os
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
ACCEPT_PROFILE = "mumei.go-summary-accept/v1"


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
    parser.add_argument(
        "--summary-aware-calls",
        dest="summary_aware_calls",
        metavar="<MANIFEST>",
        default=None,
        help=(
            "Declared callee summary manifest "
            "(mumei.go-scalar-parameter-deps/v1): calls resolving to a "
            "callee it covers fold the declared return_dependencies and "
            "statement_reads instead of the opaque every-argument "
            "approximation. Advisory only — callees it misses keep "
            "opaque-call behavior."
        ),
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


def build_attempt_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    """Parser for ``go-summaries-attempt``: the produce route's declared
    inputs plus the attempt's own declared timeout and optional memory
    bound. The child inherits the caller's environment."""
    parser = build_parser(parser)
    parser.description = (
        "Run the go-summaries produce route as one declared attempt "
        "and emit the reconciled lineage descriptors."
    )
    parser.add_argument(
        "--attempt-timeout",
        type=int,
        required=True,
        metavar="<MS>",
        help=(
            "Declared attempt bound in milliseconds (required). The "
            "inner helper's own --timeout stays a separate bound."
        ),
    )
    parser.add_argument(
        "--memory-bound-mb",
        type=int,
        default=None,
        metavar="<MB>",
        help=(
            "Optional declared POSIX RLIMIT_AS ceiling applied to the "
            "attempt child's whole address space."
        ),
    )
    for action in parser._actions:
        if action.dest == "output":
            action.help = (
                "Write the attempt report JSON here instead of stdout."
            )
    return parser


def build_accept_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    """Parser for ``go-summaries-accept``: the produce route's declared
    inputs plus ``--manifest`` and ``--binding`` naming the manifest and
    the function identity whose declared summary is accepted."""
    parser = build_check_parser(parser)
    parser.description = (
        "Run a provisioned go-types helper on declared Go sources and "
        "accept one function's declared summary under the strict "
        "whole-context gate."
    )
    parser.add_argument(
        "--binding",
        required=True,
        metavar="<ID>",
        help=(
            "Binding identity of the function whose declared summary to "
            "accept."
        ),
    )
    for action in parser._actions:
        if action.dest == "manifest":
            action.help = (
                "Summary manifest (mumei.go-scalar-parameter-deps/v1) "
                "to accept from."
            )
        elif action.dest == "output":
            action.help = (
                "Write the accept report JSON here instead of stdout."
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


def _summarize(
    sources: dict[str, str],
    payload: bytes,
    target_arch: str,
    declared: "GoSummarySet | None" = None,
):
    if len(sources) == 1:
        source = next(iter(sources.values()))
        return summarize_go(
            source,
            load_go_snapshot(payload, source, target_arch=target_arch),
            declared=declared,
        )
    return summarize_go_package(
        sources,
        load_go_package_snapshot(payload, sources, target_arch=target_arch),
        declared=declared,
    )


def _declared_paths(args: argparse.Namespace) -> set[Path]:
    """Every file whose bytes the route declares or reads as input."""
    try:
        declared = {Path(raw).resolve() for raw in args.source}
        declared.update(
            Path(spec.partition("=")[2]).resolve()
            for spec in args.imports
        )
        manifest = getattr(args, "manifest", None)
        if manifest is not None:
            declared.add(Path(manifest).resolve())
        callee_manifest = getattr(args, "summary_aware_calls", None)
        if callee_manifest is not None:
            declared.add(Path(callee_manifest).resolve())
        go_types = getattr(args, "go_types", None)
        if go_types is not None:
            declared.add(Path(go_types).resolve())
    except RuntimeError:
        raise SnapshotError("declared path cannot be resolved") from None
    return declared


def _check_output_path(
    args: argparse.Namespace, declared: set[Path]
) -> None:
    """Fail statically when ``--output`` names a declared input."""
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
        for path in declared:
            try:
                same_file = os.path.samefile(args.output, path)
            except OSError:
                continue
            if same_file:
                raise SnapshotError(
                    "declared output path would overwrite a "
                    "declared source"
                )


def summarize_declared(
    sources: dict[str, str],
    go_types: str,
    target_arch: str,
    imports: dict[str, dict[str, str]] | None = None,
    timeout: int = 30,
    declared: "GoSummarySet | None" = None,
):
    """Run a provisioned helper on declared sources and summarize.

    The wire's public entry point shared by the CLI routes and the
    MCP tool: the caller declares every byte (source texts keyed by
    basename, import units keyed by import path) plus the helper
    binary — nothing is resolved from disk, the project or the
    toolchain here.
    """
    if len(sources) == 1:
        request: dict = {
            "source": next(iter(sources.values())),
            "target_arch": target_arch,
        }
    else:
        request = {
            "sources": [
                {"name": name, "source": text}
                for name, text in sources.items()
            ],
            "target_arch": target_arch,
        }
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
    report = _run_helper(go_types, payload, timeout)
    return _summarize(sources, report, target_arch, declared), report


def _run_declared(
    args: argparse.Namespace,
) -> tuple[dict[str, str], "GoSummarySet", bytes]:
    """Read declared inputs, run the helper and summarize.

    Shared by both routes: the produce route emits the manifest, the
    check route compares a declared manifest against the same fresh
    report.
    """
    sources = _read_sources(args.source)
    declared = _declared_paths(args)
    _check_output_path(args, declared)
    imports = _read_imports(args.imports)
    callee_manifest = (
        _read_manifest(args.summary_aware_calls)
        if getattr(args, "summary_aware_calls", None)
        else None
    )
    summary, report = summarize_declared(
        sources,
        args.go_types,
        args.target_arch,
        imports,
        args.timeout,
        declared=callee_manifest,
    )
    return sources, summary, report


def _callee_manifest(args: argparse.Namespace) -> GoSummarySet | None:
    """The `--summary-aware-calls` manifest, when declared."""
    path = getattr(args, "summary_aware_calls", None)
    return _read_manifest(path) if path is not None else None


def _emit(document: str, output: str | None) -> None:
    if output:
        Path(output).write_text(document, encoding="utf-8")
    else:
        sys.stdout.write(document)


def main(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_parser().parse_args()
    try:
        _sources, live, _report = _run_declared(args)
        manifest = live.to_dict()
        document = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        _emit(document, args.output)
    except (SnapshotError, OSError, UnicodeDecodeError) as exc:
        print(f"go-summaries: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0


def _reuse_partition(
    restored: GoSummarySet,
    live: GoSummarySet,
    report: bytes,
    callee: GoSummarySet | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Partition the manifest's functions against the fresh report.

    `reusable` — the identity survives in the fresh report and
    `stale_dependents` does not flag it; `stale` — it references a
    replaced identity, transitively; `missing` — the fresh report no
    longer produces the identity. Detection only.

    With `--summary-aware-calls` the callee manifest's declared
    transitive identities (`call_targets`, `pinned`) join `known`:
    it is already the trusted input the fold consumed, so a folded
    transfer's transitive targets are checkable against it — a
    regenerated manifest's churned ids still flag the caller.
    Without this a folded callee dep the helper never emits (e.g.
    an import's import) would flag its caller stale on every
    identical input. The callee's own `binding_id` does NOT join:
    a live fold emits it through the caller's fresh `call_targets`
    whenever it is still mintable, so the only caller records that
    reference it are ones the same manifest still reproduces —
    letting it blanket-join would keep a caller reusable after the
    callee's file digest moved its fold target opaque.
    """
    known: set[str] = set()
    _report_identities(json.loads(report), known)
    if callee is not None:
        for f in callee.functions:
            known.update(f.call_targets)
            known.update(f.pinned)
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
        document = (
            json.dumps(
                summary_check_document(args), indent=2, sort_keys=True
            )
            + "\n"
        )
        _emit(document, args.output)
    except (SnapshotError, OSError, UnicodeDecodeError) as exc:
        print(f"go-summaries-check: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0


def summary_check_document(args: argparse.Namespace) -> dict:
    """Build the ``mumei.go-summary-check/v1`` document.

    Shared by ``go-summaries-check`` and the ``go_summaries_check``
    MCP tool so both emit the identical partition.
    """
    restored = _read_manifest(args.manifest)
    _sources, live, report = _run_declared(args)
    reusable, stale_ids, missing = _reuse_partition(
        restored, live, report, _callee_manifest(args)
    )
    return {
        "schema_version": CHECK_PROFILE,
        "context_match": restored.context_key == live.context_key,
        "reusable": sorted(reusable),
        "stale": sorted(stale_ids),
        "missing": sorted(missing),
    }


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
        merged = summary_reuse_set(args)
        document = json.dumps(merged.to_dict(), indent=2, sort_keys=True) + "\n"
        _emit(document, args.output)
    except (SnapshotError, OSError, UnicodeDecodeError) as exc:
        print(f"go-summaries-reuse: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0


def summary_reuse_set(args: argparse.Namespace) -> "GoSummarySet":
    """Build the merged manifest ``go-summaries-reuse`` emits.

    Shared by the CLI route and the ``go_summaries_reuse`` MCP tool
    so both emit the identical per-function freshness merge.
    """
    restored = _read_manifest(args.manifest)
    if restored.target_arch != args.target_arch:
        raise SnapshotError(
            "declared manifest was derived for a different "
            "target architecture"
        )
    _sources, live, report = _run_declared(args)
    reusable, _, _ = _reuse_partition(
        restored, live, report, _callee_manifest(args)
    )
    by_id = {f.binding_id: f for f in restored.functions}
    return GoSummarySet(
        live.context_key,
        tuple(
            by_id[f.binding_id] if f.binding_id in reusable else f
            for f in live.functions
        ),
        live.target_arch,
        call_modeling=live.call_modeling,
    )


def main_accept(args: argparse.Namespace | None = None) -> int:
    """Accept one declared summary under the strict whole-set gate.

    Emits ``mumei.go-summary-accept/v1``: `accepted` is true only when
    the manifest's declared context key still matches the fresh
    derivation — the same monolithic check `for_function` enforces —
    and the named binding survives in the fresh report. The weaker
    identity partition never authorizes: a single changed byte anywhere
    in the unit refuses the summary outright. The accepted record is
    the fresh derivation's — the manifest's records are never trusted,
    only its context key and binding identities.
    """
    if args is None:
        args = build_accept_parser().parse_args()
    try:
        document = (
            json.dumps(
                summary_accept_document(args), indent=2, sort_keys=True
            )
            + "\n"
        )
        _emit(document, args.output)
    except (SnapshotError, OSError, UnicodeDecodeError) as exc:
        print(f"go-summaries-accept: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0


def summary_accept_document(args: argparse.Namespace) -> dict:
    """Build the ``mumei.go-summary-accept/v1`` document.

    Shared by ``go-summaries-accept`` and the ``go_summaries_accept``
    MCP tool so both apply the identical strict whole-set gate.
    """
    restored = _read_manifest(args.manifest)
    _sources, live, report = _run_declared(args)
    context_match = restored.context_key == live.context_key
    by_id = {f.binding_id: f for f in restored.functions}
    live_by_id = {f.binding_id: f for f in live.functions}
    entry = by_id.get(args.binding)
    accepted = (
        context_match
        and entry is not None
        and entry.binding_id in live_by_id
    )
    report_dict: dict[str, object] = {
        "schema_version": ACCEPT_PROFILE,
        "accepted": accepted,
        "binding_id": args.binding,
        "context_match": context_match,
    }
    if not context_match:
        report_dict["reason"] = "context_mismatch"
    elif entry is None or entry.binding_id not in live_by_id:
        report_dict["reason"] = "unknown_binding"
    if accepted:
        # The strict gate checks the manifest's context key, not its
        # records: emit the freshly derived summary — identical for
        # an honest manifest, immune to a tampered declared record.
        report_dict["summary"] = live_by_id[entry.binding_id].to_dict()
    return report_dict


ATTEMPT_REQUEST_PROFILE = "mumei.go-summaries-attempt-request/v1"
ATTEMPT_REPORT_PROFILE = "mumei.go-summaries-attempt-report/v1"


def _file_sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _optional_file_sha256(path: str | None) -> str | None:
    return _file_sha256(path) if path is not None else None


def _attempt_fingerprint(args: argparse.Namespace) -> str:
    """Bind the request's declared inputs into one request identity.

    The fingerprint covers the provisioned helper's bytes, every
    declared source/import file's bytes, the target architecture and
    the inner helper bound — what the produce route would consume.
    The attempt's own timeout_ms is the sequence's separate declared
    field, not part of request identity.
    """
    request = {
        "schema_version": ATTEMPT_REQUEST_PROFILE,
        "go_types": _file_sha256(args.go_types),
        "sources": [
            {"path": path, "sha256": _file_sha256(path)}
            for path in sorted(args.source)
        ],
        "imports": [
            {"spec": spec, "sha256": _file_sha256(spec.partition("=")[2])}
            for spec in sorted(args.imports)
        ],
        "summary_aware_calls": _optional_file_sha256(
            getattr(args, "summary_aware_calls", None)
        ),
        "target_arch": args.target_arch,
        "timeout_seconds": args.timeout,
    }
    return hashlib.sha256(
        json.dumps(
            request, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def main_attempt(args: argparse.Namespace | None = None) -> int:
    """Run the produce route as one declared attempt.

    Spawns ``python -m agent go-summaries`` with the same declared
    inputs through the C11 dispatch lifecycle: a fresh
    ``AttemptSequence`` keyed to the request fingerprint (the helper
    binary's bytes plus every declared input file's bytes), one
    reserved attempt observed by ``AttemptRunner``, reconcile and
    compare-and-set publication — an ``exited`` run's captured stdout
    becomes the sequence's selected result, and failed, timed-out or
    cancelled runs publish the terminal lineage with no selection.
    Because the child re-reads the declared paths, the route re-hashes
    every declared input after the observed run and skips the
    selection when any byte drifted mid-run — a result that no longer
    matches the request fingerprint is recorded, not bound.

    Emits ``mumei.go-summaries-attempt-report/v1``: the canonical
    lineage, the normalized run-result descriptor and — only when a
    result was selected — the ``mumei.verifier-evidence-candidate/v1``
    handoff descriptor. The report carries no manifest bytes; the
    child's manifest is only observed through its bounded capture
    claim. A nonzero observed exit is still a completed observation —
    outcomes live in the report, not this route's own exit status.
    """
    if args is None:
        args = build_attempt_parser().parse_args()
    try:
        _check_output_path(args, _declared_paths(args))
        report = run_attempt(args)
        document = json.dumps(report, indent=2, sort_keys=True) + "\n"
        _emit(document, args.output)
    except (SnapshotError, OSError, UnicodeDecodeError) as exc:
        print(f"go-summaries-attempt: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0


def run_attempt(args: argparse.Namespace) -> dict:
    """Run the produce route as one declared attempt → report dict.

    Shared by ``go-summaries-attempt`` and the
    ``go_summaries_attempt`` MCP tool so both run the identical C11
    lifecycle: a fresh ``AttemptSequence`` keyed to the request
    fingerprint (the helper binary's bytes plus every declared input
    file's bytes), one reserved attempt observed by
    ``dispatch_attempt`` under ``args.attempt_timeout``, reconcile
    and compare-and-set publication — an ``exited`` run's captured
    stdout becomes the selected result only when every declared
    input byte is unchanged after the observed run. Returns the
    ``mumei.go-summaries-attempt-report/v1`` document; raises
    ``SnapshotError``/``OSError``/``UnicodeDecodeError``/``ValueError``
    on a declared failure.
    """
    from agent.attempt_runner import dispatch_attempt
    from agent.verification_attempt import (
        AttemptSequence,
        AttemptSequenceStore,
    )

    fingerprint = _attempt_fingerprint(args)
    argv = (
        sys.executable,
        "-m",
        "agent",
        "go-summaries",
        "--go-types",
        args.go_types,
        "--target-arch",
        args.target_arch,
        "--timeout",
        str(args.timeout),
    ) + tuple(
        arg
        for path in args.source
        for arg in ("--source", path)
    ) + tuple(
        arg
        for spec in args.imports
        for arg in ("--import", spec)
    ) + tuple(
        ("--summary-aware-calls", args.summary_aware_calls)
        if getattr(args, "summary_aware_calls", None)
        else ()
    )
    sequence = AttemptSequence(fingerprint, args.attempt_timeout)
    store = AttemptSequenceStore()
    store.publish(sequence)
    current = store.current
    dispatch = dispatch_attempt(
        current.begin_attempt(),
        argv,
        memory_bound_mb=args.memory_bound_mb,
    )
    try:
        inputs_changed = _attempt_fingerprint(args) != fingerprint
    except OSError:
        inputs_changed = True
    if dispatch.run.record.state == "exited" and not inputs_changed:
        updated = dispatch.sequence.select_result(
            dispatch.captured_output()
        )
    else:
        updated = dispatch.sequence
    published = store.compare_and_set(current, updated)
    report: dict[str, object] = {
        "schema_version": ATTEMPT_REPORT_PROFILE,
        "sequence": published.to_dict(),
        "normalized": dispatch.run.normalized().to_dict(),
    }
    if published.selected_result is not None:
        report["candidate"] = (
            published.evidence_candidate().to_dict()
        )
    return report
