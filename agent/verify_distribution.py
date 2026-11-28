"""Thin native-first distribution verification orchestrator.

`python -m agent verify-distribution` composes the existing declared
consumer routes instead of reimplementing Core semantics:

* `native-recheck` for bundle identity plus fresh source/LLVM evidence
* `native-accept` for object/executable reproduction
* `native-observations-accept` only when runtime observation is explicitly
  enabled
* `verify-cert --strict` as an independent proof-certificate check when the
  bundle layout is one this orchestrator can honestly check

The output is a role map for consumer UX, not a deep acceptance fold. It
does not produce a unified verdict, proof grade, reusable Evidence, or a
new trust claim. Exit 0 requires every non-skipped role to be accepted;
exit 1 is an orchestration failure/non-completion signal;
per-role `inconclusive` values preserve the underlying routes' ambiguity
instead of treating every non-zero Core exit as proved semantic failure.

Runtime observation executes the distributed executable. It is therefore
off by default and must be enabled only for a source and bundle the caller
trusts. The runtime lane reuses `native-observations-accept` unchanged,
including its timeout and optional memory bound.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from agent import native_accept, native_observations_accept, native_recheck
from agent.native_bundle import MAX_RECORD_BYTES, RECORD_FILE, declared_members

REPORT_SCHEMA = "mumei.verify-distribution-report/v1"
PROOF_CERT = "proof-cert.json"

ROLE_STATUSES = frozenset(
    {"accepted", "skipped", "failed", "inconclusive", "unsupported"}
)

GLOBAL_CHECKS_NOT_PERFORMED = [
    "adapter_evidence",
    "abi_runtime_crt_loader_semantics",
    "clock_authenticity",
    "deep_acceptance_fold",
    "input_matrix_runtime_verification",
    "key_rotation",
    "producer_authenticity",
    "proof_grade_promotion",
    "revocation",
    "signature_verification",
    "unified_verdict",
]


def build_distribution_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="verify-distribution")
    parser.description = (
        "Verify a native-first distribution through the existing declared "
        "consumer routes and emit a role-separated JSON report. This is "
        "thin orchestration, not a deep acceptance fold. Exit 0 requires "
        "every non-skipped role to be accepted; unsupported or unclaimed "
        "non-completion exits 1, and explicit Core inconclusive exits 3. "
        "That exit code is an orchestration signal, not a unified verdict."
    )
    parser.add_argument(
        "--core", required=True, metavar="PATH",
        help="Declared Core executable (absolute path).",
    )
    parser.add_argument(
        "--bundle", required=True, metavar="DIR",
        help="Declared native-bundle directory (absolute path).",
    )
    parser.add_argument(
        "--source", required=True, metavar="PATH",
        help="Declared caller-supplied .mm source (absolute path).",
    )
    parser.add_argument(
        "--expected-build-id", required=True, metavar="SHA256",
        help="SHA-256 of native-bundle.json obtained through a separately trusted channel.",
    )
    parser.add_argument(
        "--enable-runtime-observations",
        action="store_true",
        help=(
            "Execute the distributed program once through the existing "
            "native-observations-accept route. Off by default; enable only "
            "when the declared source and bundle are trusted."
        ),
    )
    parser.add_argument(
        "--attempt-timeout", type=int, default=60_000, metavar="<MS>",
        help="Declared timeout in milliseconds for each reused attempt route.",
    )
    parser.add_argument(
        "--memory-bound-mb", type=int, default=None, metavar="<MB>",
        help=(
            "Optional declared POSIX RLIMIT_AS ceiling passed unchanged to "
            "each reused attempt route."
        ),
    )
    parser.add_argument(
        "--output", metavar="PATH",
        help="Write the role-separated report JSON here instead of stdout.",
    )
    return parser


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_build_id(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _check_common(args: argparse.Namespace) -> dict:
    if os.name != "posix":
        raise ValueError("verify-distribution requires a POSIX host")
    for flag, value in (
        ("--core", args.core),
        ("--bundle", args.bundle),
        ("--source", args.source),
    ):
        if not os.path.isabs(value) or "\x00" in value:
            raise ValueError(f"{flag} must be an absolute path")
    if not Path(args.core).is_file():
        raise ValueError("--core must be an executable file")
    if not os.access(args.core, os.X_OK):
        raise ValueError("--core must be an executable file")
    bundle = Path(args.bundle)
    if not bundle.is_dir():
        raise ValueError("--bundle must be a native-bundle directory")
    record_path = bundle / RECORD_FILE
    if not record_path.is_file():
        raise ValueError(f"--bundle does not contain {RECORD_FILE}")
    if record_path.stat().st_size > MAX_RECORD_BYTES:
        raise ValueError(f"{RECORD_FILE} exceeds the Core input bound")
    if not Path(args.source).is_file():
        raise ValueError("--source must be a readable file")
    if not _is_build_id(args.expected_build_id):
        raise ValueError("--expected-build-id must be a 64-character lowercase sha256")
    if not 1 <= args.attempt_timeout <= 300_000:
        raise ValueError("--attempt-timeout must be 1..300000 ms")
    if args.memory_bound_mb is not None and not 1 <= args.memory_bound_mb <= 1_048_576:
        raise ValueError("--memory-bound-mb must be 1..1048576")
    if args.output is not None:
        output = Path(args.output)
        for declared in (args.core, args.source, record_path):
            try:
                if output.samefile(declared):
                    raise ValueError("--output may not overwrite a declared input")
            except FileNotFoundError:
                pass
    try:
        record = json.loads(record_path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"cannot parse {RECORD_FILE}: {exc}") from exc
    if not isinstance(record, dict):
        raise ValueError(f"{RECORD_FILE} is not a JSON object")
    # Validate the member grammar and require declared component members to
    # exist before dispatch. The reused routes perform the authoritative
    # per-route validation again; this check only prevents partial reports
    # for inputs no route can consume.
    for member in declared_members(bundle):
        if not (bundle / member).is_file():
            raise ValueError(f"declared bundle member is missing: {member}")
    return record


def _orchestration_inputs(args: argparse.Namespace) -> dict:
    """Hash the complete input set shared across all orchestrated lanes."""
    bundle = Path(args.bundle)
    members = declared_members(bundle)
    return {
        "members": members,
        "member_sha256": {
            member: _sha256(bundle / member) for member in members
        },
        "core_sha256": _sha256(Path(args.core)),
        "source_sha256": _sha256(Path(args.source)),
        "expected_build_id": args.expected_build_id,
    }


def _suppress_accepted_for_input_drift(role: dict) -> None:
    if role.get("status") == "accepted":
        role["status"] = "inconclusive"
        role["reason"] = "inputs_changed"


def _route_args(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        core=args.core,
        bundle=args.bundle,
        source=args.source,
        expected_build_id=args.expected_build_id,
        attempt_timeout=args.attempt_timeout,
        memory_bound_mb=args.memory_bound_mb,
        output=None,
    )


def _project_route(report: dict, outcome_key: str, positive: str) -> dict:
    """Project a reused route report without upgrading ambiguous exits.

    Existing routes intentionally omit their outcome field for exit 1 and
    unknown exits because those exits conflate semantic mismatch with static
    or operational failure. That absence is projected to `inconclusive`
    with `unclaimed_exit_outcome`, never to deterministic `failed` evidence.
    """
    projected = {
        "checks_not_performed": report.get("checks_not_performed", []),
        "report_schema": report.get("schema_version"),
        "report": report,
    }
    if report.get("inputs_changed"):
        projected.update(status="inconclusive", reason="inputs_changed")
        return projected
    outcome = report.get(outcome_key)
    if outcome == positive:
        projected["status"] = "accepted"
    elif outcome == "inconclusive":
        projected.update(status="inconclusive", reason="core_inconclusive")
    else:
        exit_code = (report.get("normalized") or {}).get("exit_code")
        projected.update(status="inconclusive", reason="unclaimed_exit_outcome")
        if exit_code is not None:
            projected["exit_code"] = exit_code
    return projected


def _route_call(fn, args: argparse.Namespace, outcome_key: str, positive: str) -> dict:
    try:
        return _project_route(fn(args), outcome_key, positive)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        return {
            "status": "failed",
            "reason": "route_input_or_operational_error",
            "error": str(exc),
            "checks_not_performed": [],
        }


def _file_request_sha256(core: Path, cert: Path, source: Path) -> str:
    request = {
        "schema_version": "mumei.verify-distribution-proof-certificate-request/v1",
        "core": _sha256(core),
        "certificate": {"path": str(cert), "sha256": _sha256(cert)},
        "source": {"path": str(source), "sha256": _sha256(source)},
    }
    return hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _run_proof_certificate(args: argparse.Namespace) -> dict:
    """Run `verify-cert --strict` as a small declared attempt.

    No existing public route wraps proof-certificate verification, so this
    lane uses the same AttemptSequence/input-drift pattern directly rather
    than pretending `verify-accept`'s source-Evidence route applies.
    """
    from agent.attempt_runner import dispatch_attempt
    from agent.verification_attempt import AttemptSequence, AttemptSequenceStore

    core = Path(args.core)
    cert = Path(args.bundle) / PROOF_CERT
    source = Path(args.source)
    fingerprint = _file_request_sha256(core, cert, source)
    argv = (args.core, "verify-cert", "--strict", str(cert), args.source)
    sequence = AttemptSequence(fingerprint, args.attempt_timeout)
    store = AttemptSequenceStore()
    store.publish(sequence)
    current = store.current
    dispatch = dispatch_attempt(
        current.begin_attempt(), argv, memory_bound_mb=args.memory_bound_mb
    )
    try:
        inputs_changed = _file_request_sha256(core, cert, source) != fingerprint
    except OSError:
        inputs_changed = True
    record = dispatch.run.record
    exit_code = None
    if record.state == "exited" and record.events:
        exit_code = record.events[-1].exit_code
    if exit_code == 0 and not inputs_changed:
        updated = dispatch.sequence.select_result(dispatch.captured_output())
    else:
        updated = dispatch.sequence
    published = store.compare_and_set(current, updated)
    report = {
        "sequence": published.to_dict(),
        "normalized": dispatch.run.normalized().to_dict(),
    }
    result = {
        "checks_not_performed": [
            "historical_execution",
            "producer_authenticity",
            "proof_certificate_native_artifact_correspondence",
        ],
        "report": report,
    }
    if inputs_changed:
        result.update(status="inconclusive", reason="inputs_changed")
    elif exit_code == 0:
        result["status"] = "accepted"
    else:
        result.update(status="inconclusive", reason="unclaimed_exit_outcome")
        if exit_code is not None:
            result["exit_code"] = exit_code
    return result


def _proof_certificate_role(args: argparse.Namespace, record: dict) -> dict:
    cert = Path(args.bundle) / PROOF_CERT
    if (
        record.get("schema") == "mumei.native-multifile-bundle/v1"
        or record.get("sources")
    ):
        return {
            "status": "unsupported",
            "reason": "multifile_certificate_source_binding_not_declared",
            "checks_not_performed": ["proof_certificate_independent_recheck"],
        }
    if not cert.is_file():
        return {
            "status": "failed",
            "reason": "missing_proof_certificate",
            "checks_not_performed": ["proof_certificate_independent_recheck"],
        }
    try:
        return _run_proof_certificate(args)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        return {
            "status": "failed",
            "reason": "proof_certificate_input_or_operational_error",
            "error": str(exc),
            "checks_not_performed": ["proof_certificate_independent_recheck"],
        }


def _runtime_pins_present(record: dict) -> bool:
    link_build = record.get("link_build")
    if not isinstance(link_build, dict):
        return False
    return any(
        link_build.get(key) is not None
        for key in (
            "expected_exit_status",
            "expected_stdout_sha256",
            "expected_stderr_sha256",
        )
    )


def run_distribution(args: argparse.Namespace) -> dict:
    record = _check_common(args)
    initial_inputs = _orchestration_inputs(args)
    route_args = _route_args(args)
    roles = {
        "proof_certificate": _proof_certificate_role(args, record),
        "native_source_llvm": _route_call(
            native_recheck.run_recheck, route_args, "recheck", "equivalent"
        ),
        "artifact_reproduction": _route_call(
            native_accept.run_accept, route_args, "acceptance", "accepted"
        ),
    }
    if not args.enable_runtime_observations:
        roles["runtime_observation"] = {
            "status": "skipped",
            "reason": "runtime_observations_not_enabled",
            "checks_not_performed": [
                "os_exit_status_observation",
                "os_stdout_observation",
                "os_stderr_observation",
            ],
        }
    elif not _runtime_pins_present(record):
        roles["runtime_observation"] = {
            "status": "skipped",
            "reason": "runtime_observation_pins_absent",
            "checks_not_performed": [
                "os_exit_status_observation",
                "os_stdout_observation",
                "os_stderr_observation",
            ],
        }
    else:
        roles["runtime_observation"] = _route_call(
            native_observations_accept.run_observations_accept,
            route_args,
            "acceptance",
            "accepted",
        )

    try:
        final_inputs = _orchestration_inputs(args)
        inputs_changed = final_inputs != initial_inputs
    except (OSError, ValueError):
        inputs_changed = True
    if inputs_changed:
        for role in roles.values():
            _suppress_accepted_for_input_drift(role)

    report = {
        "schema_version": REPORT_SCHEMA,
        "scope": "native_first_distribution_role_orchestration",
        "inputs": {
            "bundle_record_sha256": initial_inputs["member_sha256"][RECORD_FILE],
            "source_sha256": initial_inputs["source_sha256"],
            "expected_build_id": args.expected_build_id,
        },
        "runtime_execution": "opt_in_only_for_trusted_source_and_bundle",
        "roles": roles,
        "checks_not_performed": GLOBAL_CHECKS_NOT_PERFORMED,
    }
    if inputs_changed:
        report["inputs_changed"] = True
    return report


def distribution_exit_code(report: dict) -> int:
    roles = report["roles"].values()
    if any(role["status"] in {"failed", "unsupported"} for role in roles):
        return 1
    if any(
        role["status"] == "inconclusive"
        and role.get("reason") != "core_inconclusive"
        for role in roles
    ):
        return 1
    if any(role["status"] == "inconclusive" for role in roles):
        return 3
    return 0


def main_distribution(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_distribution_parser().parse_args()
    try:
        report = run_distribution(args)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"verify-distribution: {exc}", file=sys.stderr)
        return 1
    document = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        Path(args.output).write_text(document, encoding="utf-8")
    else:
        sys.stdout.write(document)
    return distribution_exit_code(report)
