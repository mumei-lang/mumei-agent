"""C11 evidence-check-adapter route: static adapter-manifest representation.

`python -m agent evidence-check-adapter` feeds a saved manifest's exact
bytes to `<core> evidence check-adapter --stdin --json` inside the C11
dispatch lifecycle. The request fingerprint binds the Core executable
and manifest bytes; the route then re-hashes both declared inputs and
publishes reconciled lineage compare-and-set.

Selection requires Core's exact representation-only diagnostic and a
matching local `AdapterDescriptor.from_manifest` view of the declared
attempt argv, stdin and verdict-marker count. Selection means only that
Core validated the manifest representation: argv and stdin stay inert
without host opt-in, markers are self-report vocabulary, and
`max_memory_mb` is a declared ceiling. The route does not execute an
adapter, assess command safety, accept Evidence or promote a grade.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

from agent.core_evidence import MAX_CHECK_TIMEOUT_MS
from agent.verification_planner import (
    MAX_VERDICT_MARKERS,
    AdapterDescriptor,
)

CHECK_REQUEST_PROFILE = "mumei.evidence-check-adapter-request/v1"
CHECK_REPORT_PROFILE = "mumei.evidence-check-adapter-report/v1"
MAX_INPUT_BYTES = 65_536
DEFAULT_ATTEMPT_TIMEOUT_MS = 30_000

CHECKS_PERFORMED = ["representation_gate", "manifest_consistency"]
CHECKS_NOT_PERFORMED = [
    "adapter_execution",
    "command_safety",
    "stdin_semantics",
    "reported_outcome_truth",
    "resource_enforcement",
    "producer_authenticity",
    "host_policy",
    "grade_promotion",
]
DECLARED_FIELD_MEANING = {
    "attempt_argv": "inert_without_host_opt_in",
    "attempt_stdin": "inert_without_host_opt_in",
    "verdict_markers": "adapter_self_report_vocabulary",
    "max_memory_mb": "declared_ceiling_not_enforced_by_core",
}
DIAGNOSTIC_KEYS = frozenset(
    {
        "schema_version",
        "manifest_schema_version",
        "representation",
        "acceptance",
        "attempt_argv",
        "attempt_stdin",
        "verdict_marker_count",
        "declared_field_meaning",
        "checks_performed",
        "checks_not_performed",
    }
)


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _file_sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _check_request(args: argparse.Namespace) -> None:
    """Validate declared paths and bounds before dispatch."""
    if os.name != "posix":
        raise ValueError("evidence-check-adapter requires a POSIX host")
    for name, path in (("--core", args.core), ("--manifest", args.manifest)):
        if not os.path.isabs(path) or "\x00" in path:
            raise ValueError(f"{name} must be an absolute path")
    if not 1 <= args.attempt_timeout <= MAX_CHECK_TIMEOUT_MS:
        raise ValueError(f"--attempt-timeout must be 1..{MAX_CHECK_TIMEOUT_MS} ms")
    for name, path in (("Core executable", args.core), ("manifest", args.manifest)):
        try:
            mode = Path(path).stat().st_mode
        except OSError as exc:
            raise ValueError(f"cannot read declared {name}: {exc}") from exc
        if not stat.S_ISREG(mode):
            raise ValueError(f"declared {name} must be a regular file")
    try:
        size = os.path.getsize(args.manifest)
    except OSError as exc:
        raise ValueError(f"cannot read declared manifest: {exc}") from exc
    if size > MAX_INPUT_BYTES:
        raise ValueError(
            f"--manifest exceeds the Core input bound ({MAX_INPUT_BYTES} bytes)"
        )
    if args.output is not None:
        out_path = Path(args.output)
        for declared in (args.core, args.manifest):
            try:
                if out_path.samefile(declared):
                    raise ValueError(
                        "--output may not overwrite a declared input document"
                    )
            except FileNotFoundError:
                continue


def _attempt_fingerprint(args: argparse.Namespace, manifest_bytes: bytes) -> str:
    """Bind Core bytes and the exact manifest bytes fed to the check."""
    request = {
        "schema_version": CHECK_REQUEST_PROFILE,
        "core": _file_sha256(args.core),
        "manifest": {
            "path": args.manifest,
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        },
    }
    return hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _decode_manifest(manifest_bytes: bytes) -> AdapterDescriptor | None:
    try:
        document = json.loads(
            manifest_bytes.decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
        return AdapterDescriptor.from_manifest(document)
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError):
        return None


def _parse_diagnostic(captured: bytes, manifest_bytes: bytes) -> dict | None:
    """Accept only Core's exact diagnostic and matching manifest declarations."""
    try:
        document = json.loads(
            captured.decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if type(document) is not dict or set(document) != DIAGNOSTIC_KEYS:
        return None
    expected = {
        "schema_version": "mumei.adapter-manifest-check/v1",
        "manifest_schema_version": "mumei.verifier-adapter/v1",
        "representation": "valid",
        "acceptance": "not_evaluated",
        "declared_field_meaning": DECLARED_FIELD_MEANING,
        "checks_performed": CHECKS_PERFORMED,
        "checks_not_performed": CHECKS_NOT_PERFORMED,
    }
    if any(document.get(key) != value for key, value in expected.items()):
        return None
    attempt_argv = document.get("attempt_argv")
    attempt_stdin = document.get("attempt_stdin")
    marker_count = document.get("verdict_marker_count")
    if type(attempt_argv) is not str or attempt_argv not in {"declared", "absent"}:
        return None
    if type(attempt_stdin) is not str or attempt_stdin not in {"declared", "absent"}:
        return None
    if type(marker_count) is not int or not 0 <= marker_count <= MAX_VERDICT_MARKERS:
        return None

    descriptor = _decode_manifest(manifest_bytes)
    if descriptor is None:
        return None
    expected_attempt_argv = (
        "declared" if descriptor.attempt_argv is not None else "absent"
    )
    expected_attempt_stdin = (
        "declared" if descriptor.attempt_stdin is not None else "absent"
    )
    if (
        attempt_argv != expected_attempt_argv
        or attempt_stdin != expected_attempt_stdin
        or marker_count != len(descriptor.verdict_markers)
    ):
        return None
    return document


def build_check_adapter_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="evidence-check-adapter")
    parser.description = (
        "Run a declared Core adapter-manifest representation check as "
        "one attempt and emit the reconciled lineage and bounded diagnostic."
    )
    parser.add_argument(
        "--core",
        required=True,
        metavar="PATH",
        help=(
            "Declared Core executable (absolute path) used to run "
            "`evidence check-adapter`."
        ),
    )
    parser.add_argument(
        "--manifest",
        required=True,
        metavar="PATH",
        help=(
            "Declared saved mumei.verifier-adapter/v1 manifest "
            "(absolute regular-file path, at most 65536 bytes); its "
            "bytes are fed to the check on stdin."
        ),
    )
    parser.add_argument(
        "--attempt-timeout",
        type=int,
        default=DEFAULT_ATTEMPT_TIMEOUT_MS,
        metavar="<MS>",
        help=f"Declared attempt bound in ms (max {MAX_CHECK_TIMEOUT_MS}).",
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
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Write the check report JSON here instead of stdout.",
    )
    return parser


def run_check_adapter(args: argparse.Namespace) -> dict:
    """Run one declared Core adapter-manifest check and return its report."""
    from agent.attempt_runner import dispatch_attempt
    from agent.verification_attempt import (
        AttemptSequence,
        AttemptSequenceStore,
    )

    _check_request(args)
    manifest_bytes = Path(args.manifest).read_bytes()
    if len(manifest_bytes) > MAX_INPUT_BYTES:
        raise ValueError(
            f"--manifest exceeds the Core input bound ({MAX_INPUT_BYTES} bytes)"
        )
    fingerprint = _attempt_fingerprint(args, manifest_bytes)
    argv = (
        args.core,
        "evidence",
        "check-adapter",
        "--stdin",
        "--json",
    )
    sequence = AttemptSequence(fingerprint, args.attempt_timeout)
    store = AttemptSequenceStore()
    store.publish(sequence)
    current = store.current
    dispatch = dispatch_attempt(
        current.begin_attempt(),
        argv,
        memory_bound_mb=args.memory_bound_mb,
        feed_bytes=manifest_bytes,
    )
    try:
        current_manifest = Path(args.manifest).read_bytes()
        inputs_changed = (
            len(current_manifest) > MAX_INPUT_BYTES
            or _attempt_fingerprint(args, current_manifest) != fingerprint
        )
    except OSError:
        inputs_changed = True
    record = dispatch.run.record
    exit_code = None
    if record.state == "exited" and record.events:
        exit_code = record.events[-1].exit_code
    diagnostic = (
        _parse_diagnostic(dispatch.run.stdout, manifest_bytes)
        if exit_code == 0 and not inputs_changed
        else None
    )
    if exit_code == 0 and not inputs_changed and diagnostic is not None:
        updated = dispatch.sequence.select_result(dispatch.captured_output())
    else:
        updated = dispatch.sequence
    published = store.compare_and_set(current, updated)
    report: dict[str, object] = {
        "schema_version": CHECK_REPORT_PROFILE,
        "sequence": published.to_dict(),
        "normalized": dispatch.run.normalized().to_dict(),
    }
    if inputs_changed:
        report["inputs_changed"] = True
    elif diagnostic is not None:
        report["manifest_schema_version"] = diagnostic["manifest_schema_version"]
        report["representation"] = diagnostic["representation"]
        report["acceptance"] = diagnostic["acceptance"]
        report["attempt_argv"] = diagnostic["attempt_argv"]
        report["attempt_stdin"] = diagnostic["attempt_stdin"]
        report["verdict_marker_count"] = diagnostic["verdict_marker_count"]
        report["declared_field_meaning"] = dict(diagnostic["declared_field_meaning"])
        report["checks_performed"] = list(diagnostic["checks_performed"])
        report["checks_not_performed"] = list(diagnostic["checks_not_performed"])
    if published.selected_result is not None:
        report["candidate"] = published.evidence_candidate().to_dict()
    return report


def main_check_adapter(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_check_adapter_parser().parse_args()
    try:
        report = run_check_adapter(args)
        document = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"evidence-check-adapter: {exc}", file=sys.stderr)
        sys.exit(1)
    return 0
