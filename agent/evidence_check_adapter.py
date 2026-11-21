"""C11 evidence-check-adapter route: static adapter-manifest checking.

`python -m agent evidence-check-adapter` feeds a saved
`mumei.verifier-adapter/v1` manifest to `<core> evidence check-adapter
--stdin --json` inside one C11 dispatch attempt. The request fingerprint binds
the Core executable and exact manifest bytes; both declared inputs are
re-hashed after the attempt and drift suppresses the diagnostic and selection.

Core checks static representation and manifest consistency only. It does not
execute adapters or assess command safety, host policy, resource enforcement,
producer authenticity, Evidence acceptance, or grade promotion. Declared
argv/stdin remain inert; selection is only a manifest-declared-success exit.
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


def _file_sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate JSON object key")
        document[key] = value
    return document


def _check_request(args: argparse.Namespace) -> None:
    """Validate declared paths and bounds before dispatch."""
    if os.name != "posix":
        raise ValueError("evidence-check-adapter requires a POSIX host")
    for name, path in (("--core", args.core), ("--manifest", args.manifest)):
        if not os.path.isabs(path) or "\x00" in path:
            raise ValueError(f"{name} must be an absolute path")
        try:
            mode = Path(path).stat().st_mode
        except OSError as exc:
            raise ValueError(f"cannot read declared {name[2:]}: {exc}") from exc
        if not stat.S_ISREG(mode):
            raise ValueError(f"declared {name[2:]} must be a regular file")
    if not 1 <= args.attempt_timeout <= MAX_CHECK_TIMEOUT_MS:
        raise ValueError(
            f"--attempt-timeout must be 1..{MAX_CHECK_TIMEOUT_MS} ms"
        )
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


def _attempt_fingerprint(
    args: argparse.Namespace, manifest_bytes: bytes
) -> str:
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


def _parse_diagnostic(captured: bytes) -> dict | None:
    """Accept only the exact static diagnostic contract from Core."""
    try:
        document = json.loads(
            captured.decode("utf-8"), object_pairs_hook=_unique_json_object
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
    if type(attempt_argv) is not str or attempt_argv not in (
        "declared",
        "absent",
    ):
        return None
    attempt_stdin = document.get("attempt_stdin")
    if type(attempt_stdin) is not str or attempt_stdin not in (
        "declared",
        "absent",
    ):
        return None
    marker_count = document.get("verdict_marker_count")
    if type(marker_count) is not int or marker_count < 0:
        return None
    return document


def build_check_adapter_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="evidence-check-adapter")
    parser.description = (
        "Check a declared adapter manifest's static representation and "
        "consistency only. No adapter execution, command safety, host policy, "
        "resource enforcement, producer authenticity, Evidence acceptance, "
        "or grade promotion is performed; declared argv/stdin remain inert."
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
            "Declared saved mumei.verifier-adapter/v1 manifest (absolute "
            "regular-file path, at most 65536 bytes); argv/stdin declarations "
            "remain inert."
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


def _dispatch_adapter_check(
    core: str,
    manifest_bytes: bytes,
    memory_bound_mb: int | None,
    sequence,
) -> tuple[dict, object]:
    from agent.attempt_runner import dispatch_attempt

    dispatch = dispatch_attempt(
        sequence.begin_attempt(),
        (core, "evidence", "check-adapter", "--stdin", "--json"),
        memory_bound_mb=memory_bound_mb,
        feed_bytes=manifest_bytes,
    )
    record = dispatch.run.record
    exit_code = None
    if record.state == "exited" and record.events:
        exit_code = record.events[-1].exit_code
    diagnostic = (
        _parse_diagnostic(dispatch.run.stdout) if exit_code == 0 else None
    )
    report: dict[str, object] = {
        "normalized": dispatch.run.normalized().to_dict(),
    }
    if diagnostic is not None:
        for field in (
            "representation",
            "acceptance",
            "attempt_argv",
            "attempt_stdin",
            "verdict_marker_count",
            "declared_field_meaning",
            "checks_performed",
            "checks_not_performed",
        ):
            report[field] = diagnostic[field]
    return report, dispatch


def run_check_adapter(args: argparse.Namespace) -> dict:
    """Run one declared Core adapter-manifest check and return its report."""
    from agent.verification_attempt import (
        AttemptSequence,
        AttemptSequenceStore,
    )

    _check_request(args)
    manifest_bytes = Path(args.manifest).read_bytes()
    fingerprint = _attempt_fingerprint(args, manifest_bytes)
    sequence = AttemptSequence(fingerprint, args.attempt_timeout)
    store = AttemptSequenceStore()
    store.publish(sequence)
    current = store.current
    check, dispatch = _dispatch_adapter_check(
        args.core,
        manifest_bytes,
        args.memory_bound_mb,
        current,
    )
    try:
        inputs_changed = (
            _attempt_fingerprint(
                args, Path(args.manifest).read_bytes()
            )
            != fingerprint
        )
    except OSError:
        inputs_changed = True
    exit_code = check["normalized"].get("exit_code")
    has_diagnostic = "representation" in check
    if exit_code == 0 and not inputs_changed and has_diagnostic:
        updated = dispatch.sequence.select_result(dispatch.captured_output())
    else:
        updated = dispatch.sequence
    published = store.compare_and_set(current, updated)
    report: dict[str, object] = {
        "schema_version": CHECK_REPORT_PROFILE,
        "sequence": published.to_dict(),
        "normalized": check["normalized"],
    }
    if inputs_changed:
        report["inputs_changed"] = True
    elif has_diagnostic:
        for field in (
            "representation",
            "acceptance",
            "attempt_argv",
            "attempt_stdin",
            "verdict_marker_count",
            "declared_field_meaning",
            "checks_performed",
            "checks_not_performed",
        ):
            report[field] = check[field]
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
