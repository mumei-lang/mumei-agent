#!/usr/bin/env python3
"""Verify a downloaded mumei-audit action evidence artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "mumei.migration-execution/v1"
STATES = ("ready_for_human_review", "blocked", "operational_error")
HOST_BOUNDARY = "not proof that host-language code implements the same behavior"
CERT_BOUNDARY = (
    "proof certificate verification is certificate/source correspondence only; "
    "not a Z3 re-proof, not host semantic-equivalence proof, and no contract-vacuity assessment"
)
Z3_REVERIFY_BOUNDARY = (
    "independent Z3 re-verification of generated .mm only; not host semantic-equivalence proof, "
    "not a contract-vacuity assessment, and independent from certificate correspondence"
)
VERIFY_CERT_TIMEOUT_SECONDS = 60
VERIFY_Z3_TIMEOUT_SECONDS = 60
REVERIFY_MAX_FILES = 2048
REVERIFY_MAX_TOTAL_BYTES = 256 * 1024 * 1024
DIAGNOSTIC_CAP = 300


class ArtifactVerificationError(Exception):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactVerificationError(f"{path} is missing or malformed JSON") from exc
    if not isinstance(value, dict):
        raise ArtifactVerificationError(f"{path} is not a JSON object")
    return value


def _regular_file(path: Path, *, allow_empty: bool = False) -> None:
    if path.is_symlink() or not path.is_file():
        raise ArtifactVerificationError(f"required artifact file is missing or not regular: {path}")
    if not allow_empty and path.stat().st_size == 0:
        raise ArtifactVerificationError(f"required artifact file is empty: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_contains(path: Path, needle: bytes) -> bool:
    if not needle:
        return False
    overlap = max(len(needle) - 1, 0)
    tail = b""
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            data = tail + chunk
            if needle in data:
                return True
            tail = data[-overlap:] if overlap else b""
    return False


def _scan_regular_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        for dirname in dirnames:
            if (current_path / dirname).is_symlink():
                raise ArtifactVerificationError("downloaded artifact contains a symlinked directory")
        for filename in filenames:
            path = current_path / filename
            if path.is_symlink() or not path.is_file():
                raise ArtifactVerificationError("downloaded artifact contains a symlink or non-regular file")
            files.append(path)
    return sorted(files)


def _read_timing(path: Path) -> int:
    text = path.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+", text):
        raise ArtifactVerificationError(f"timing artifact is not a non-negative integer: {path.name}")
    return int(text)


def _normalized_absolute(path_text: str) -> PurePosixPath:
    return PurePosixPath(posixpath.normpath(path_text))


def _map_claimed_path(path_text: str, original_root_text: str, generated_root: Path) -> Path:
    if not posixpath.isabs(path_text) or not posixpath.isabs(original_root_text):
        raise ArtifactVerificationError("generated artifact claims must use absolute paths in the action artifact")
    original_root = _normalized_absolute(original_root_text)
    claimed = _normalized_absolute(path_text)
    try:
        suffix = claimed.relative_to(original_root)
    except ValueError as exc:
        raise ArtifactVerificationError("generated artifact claim is outside the generated artifact directory") from exc
    if not suffix.parts:
        raise ArtifactVerificationError("generated artifact claim is the generated artifact directory itself")
    target = generated_root.joinpath(*suffix.parts)
    resolved_root = generated_root.resolve()
    resolved_target = target.resolve(strict=False)
    if not resolved_target.is_relative_to(resolved_root):
        raise ArtifactVerificationError("generated artifact claim escapes the downloaded generated artifact directory")
    return target


def _validate_file_claim(
    claim: dict[str, Any],
    *,
    label: str,
    original_root_text: str,
    generated_root: Path,
) -> bool:
    path_text = claim.get("path")
    sha256 = claim.get("sha256")
    if path_text is None and sha256 is None:
        return False
    if not isinstance(path_text, str) or not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ArtifactVerificationError(f"{label} claim has inconsistent path/hash metadata")
    target = _map_claimed_path(path_text, original_root_text, generated_root)
    _regular_file(target)
    if _sha256(target) != sha256:
        raise ArtifactVerificationError(f"{label} sha256 does not match the downloaded generated artifact")
    return True


def _validate_written_claim(
    claim: dict[str, Any],
    *,
    label: str,
    original_root_text: str,
    generated_root: Path,
) -> bool:
    written = claim.get("written")
    if written is False:
        if claim.get("sha256") is not None:
            raise ArtifactVerificationError(f"{label} unwritten claim carries sha256 metadata")
        return False
    if written is not True:
        raise ArtifactVerificationError(f"{label} claim is missing written metadata")
    if claim.get("path") is None and claim.get("sha256") is None:
        raise ArtifactVerificationError(f"{label} written claim is missing generated artifact metadata")
    return _validate_file_claim(claim, label=label, original_root_text=original_root_text, generated_root=generated_root)


def _check_reverify_copy_budget(companion_files: list[Path]) -> None:
    if len(companion_files) > REVERIFY_MAX_FILES:
        raise ArtifactVerificationError(
            f"generated artifact re-verification copy exceeds the file-count cap ({REVERIFY_MAX_FILES})"
        )
    total_bytes = sum(path.stat().st_size for path in companion_files)
    if total_bytes > REVERIFY_MAX_TOTAL_BYTES:
        raise ArtifactVerificationError(
            f"generated artifact re-verification copy exceeds the byte cap ({REVERIFY_MAX_TOTAL_BYTES})"
        )


def _copy_generated_tree(companion_files: list[Path], generated_root: Path, copy_root: Path) -> None:
    """Copy only validated regular generated-artifact files, preserving relative layout."""
    resolved_copy_root = copy_root.resolve(strict=False)
    for source in companion_files:
        relative = source.relative_to(generated_root)
        if any(part in {"", ".", ".."} for part in relative.parts):
            raise ArtifactVerificationError("generated artifact re-verification copy path is malformed")
        target = copy_root.joinpath(*relative.parts)
        resolved_target = target.resolve(strict=False)
        if not resolved_target.is_relative_to(resolved_copy_root):
            raise ArtifactVerificationError("generated artifact re-verification copy escapes its temporary directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def _reverify_generated_mm(
    binary: Path,
    mm_artifacts: list[tuple[str, Path]],
    generated_root: Path,
    companion_files: list[Path],
) -> int:
    if not mm_artifacts:
        raise ArtifactVerificationError("independent Z3 re-verification found no validated generated .mm artifact")
    _check_reverify_copy_budget(companion_files)
    with tempfile.TemporaryDirectory(prefix="mumei-audit-reverify-") as temporary:
        temporary_root = Path(temporary)
        copy_root = temporary_root / "generated-artifacts"
        run_root = temporary_root / "run"
        copy_root.mkdir(parents=True)
        run_root.mkdir()
        _copy_generated_tree(companion_files, generated_root, copy_root)
        copy_root = copy_root.resolve()
        verified = 0
        for label, original_mm in mm_artifacts:
            relative = original_mm.relative_to(generated_root)
            copied_mm = copy_root.joinpath(*relative.parts)
            resolved_copied_mm = copied_mm.resolve(strict=False)
            if not resolved_copied_mm.is_relative_to(copy_root):
                raise ArtifactVerificationError(f"generated .mm re-verification path escapes its copy for candidate {label}")
            try:
                completed = subprocess.run(
                    [str(binary), "verify", str(copied_mm), "--json"],
                    cwd=run_root,
                    capture_output=True,
                    text=True,
                    timeout=VERIFY_Z3_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired as exc:
                raise ArtifactVerificationError(f"mumei verify --json timed out for candidate {label}") from exc
            except OSError as exc:
                raise ArtifactVerificationError(f"mumei verify --json could not execute for candidate {label}") from exc
            except UnicodeDecodeError as exc:
                raise ArtifactVerificationError(f"mumei verify --json returned undecodable output for candidate {label}") from exc
            if completed.returncode != 0:
                diagnostic = (completed.stderr or completed.stdout or "").replace("\n", " ")[:DIAGNOSTIC_CAP]
                raise ArtifactVerificationError(
                    f"mumei verify --json failed for candidate {label}: {diagnostic or 'no diagnostic output'}"
                )
            try:
                verification_json = json.loads(completed.stdout)
            except json.JSONDecodeError as exc:
                raise ArtifactVerificationError(f"mumei verify --json returned malformed JSON for candidate {label}") from exc
            if not isinstance(verification_json, dict) or verification_json.get("status") != "success":
                raise ArtifactVerificationError(f"mumei verify --json did not return status success for candidate {label}")
            verified += 1
        return verified


def verify_artifact(
    root: Path,
    *,
    require_hidden_companion: bool,
    forbidden_literal: str = "",
    require_blocked_candidate: bool = False,
    require_generated_mm: bool = False,
    allow_zero_candidates: bool = False,
    mumei_bin: str = "",
    reverify_z3: bool = False,
) -> dict[str, int]:
    if reverify_z3 and not mumei_bin:
        raise ArtifactVerificationError("--reverify-z3 requires --mumei-bin")
    if root.is_symlink() or not root.is_dir():
        raise ArtifactVerificationError("evidence artifact root is missing or is not a regular directory")
    root = root.resolve()

    required_nonempty = [
        root / "audit.json",
        root / "audit.sarif",
        root / "generated-baseline.json",
        root / "migration-execution" / "migration_execution.json",
        root / "migration-execution" / "status.json",
    ]
    for path in required_nonempty:
        _regular_file(path)
    for path in (root / "audit.stdout.log", root / "audit.stderr.log"):
        _regular_file(path, allow_empty=True)

    all_files = _scan_regular_files(root)
    if forbidden_literal:
        encoded = forbidden_literal.encode("utf-8")
        for path in all_files:
            if _file_contains(path, encoded):
                raise ArtifactVerificationError("credential-like sentinel appeared in the downloaded artifact")

    audit = _load_json(root / "audit.json")
    for key in ("verification_status", "finding_counts", "migration_hints", "trusted_atoms"):
        if key not in audit:
            raise ArtifactVerificationError(f"audit report is missing {key}")
    if audit.get("schema") == SCHEMA:
        raise ArtifactVerificationError("audit report role is conflated with migration execution evidence")

    sarif = _load_json(root / "audit.sarif")
    if sarif.get("version") != "2.1.0":
        raise ArtifactVerificationError("audit SARIF is missing version 2.1.0")

    baseline = _load_json(root / "generated-baseline.json")
    if baseline.get("version") != "mumei.audit-baseline/v1" or not isinstance(baseline.get("fingerprints"), list):
        raise ArtifactVerificationError("generated baseline is not a mumei audit baseline")

    timing = {}
    for name in ("start", "setup_end", "audit_start", "audit_end"):
        path = root / "timing" / name
        _regular_file(path)
        timing[name] = _read_timing(path)
    if not timing["start"] <= timing["setup_end"] <= timing["audit_start"] <= timing["audit_end"]:
        raise ArtifactVerificationError("timing artifacts are not monotonically ordered")

    migration_auto_migrate = root / "migration-auto-migrate"
    _regular_file(migration_auto_migrate)
    if migration_auto_migrate.read_text(encoding="utf-8").strip() not in {"added", "requested"}:
        raise ArtifactVerificationError("migration auto-migrate provenance is unknown")
    if (root / "migration-cli-support").exists():
        raise ArtifactVerificationError("successful migration evidence must not carry an unsupported-CLI marker")

    execution = _load_json(root / "migration-execution" / "migration_execution.json")
    status = _load_json(root / "migration-execution" / "status.json")
    if execution.get("schema") != SCHEMA:
        raise ArtifactVerificationError("migration execution schema is missing or unsupported")
    candidates = execution.get("candidates")
    summary = execution.get("summary")
    artifact_paths = execution.get("artifact_paths")
    boundary = execution.get("evidence_boundary")
    selection = execution.get("selection")
    if not isinstance(candidates, list) or not isinstance(summary, dict) or not isinstance(artifact_paths, dict):
        raise ArtifactVerificationError("migration execution artifact is missing candidates, summary, or artifact paths")
    if not isinstance(boundary, list) or not any(isinstance(item, str) and HOST_BOUNDARY in item for item in boundary):
        raise ArtifactVerificationError("migration execution artifact is missing the host semantic-equivalence boundary")
    if not isinstance(status.get("boundary"), str) or HOST_BOUNDARY not in status["boundary"]:
        raise ArtifactVerificationError("migration execution status is missing the host semantic-equivalence boundary")
    if status.get("status") != "emitted_by_audit_cli":
        raise ArtifactVerificationError("migration execution was not emitted by the audit CLI")

    computed_counts = {state: 0 for state in STATES}
    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get("execution_state") not in STATES:
            raise ArtifactVerificationError("migration execution candidate has an unknown execution state")
        computed_counts[candidate["execution_state"]] += 1
    status_counts = status.get("counts")
    if not isinstance(status_counts, dict):
        raise ArtifactVerificationError("migration execution status counts are missing")
    for state in STATES:
        if type(summary.get(state)) is not int or summary[state] != computed_counts[state]:
            raise ArtifactVerificationError("migration execution summary counts are inconsistent")
        if type(status_counts.get(state)) is not int or status_counts[state] != computed_counts[state]:
            raise ArtifactVerificationError("migration execution status counts are inconsistent")
    if type(summary.get("candidate_count")) is not int or summary["candidate_count"] != len(candidates):
        raise ArtifactVerificationError("migration execution candidate count is inconsistent")
    if type(status.get("ready_count")) is not int or status["ready_count"] != computed_counts["ready_for_human_review"]:
        raise ArtifactVerificationError("migration execution ready count is inconsistent")
    if not candidates and not allow_zero_candidates:
        raise ArtifactVerificationError(
            "zero migration candidates: no blocked/ready review evidence exists "
            "to verify, so the verifier fails closed. This is a review-evidence "
            "policy outcome, not an operational failure and not a verification "
            "failure; pass --allow-zero-candidates only when zero candidates is "
            "the intended outcome for the audited input"
        )
    if candidates:
        if summary.get("review_required") is not True or status.get("review_required") is not True:
            raise ArtifactVerificationError("blocked/ready migration execution evidence must require human review")
    elif allow_zero_candidates:
        if summary.get("review_required") is not False or status.get("review_required") is not False:
            raise ArtifactVerificationError("zero-candidate migration execution evidence unexpectedly requires review")
        if not isinstance(selection, dict) or not isinstance(selection.get("missing_requested_functions"), list):
            raise ArtifactVerificationError("zero-candidate migration execution artifact is missing selection evidence")
        missing_requested = selection["missing_requested_functions"]
        if not all(isinstance(item, str) for item in missing_requested):
            raise ArtifactVerificationError("zero-candidate migration execution missing-selection evidence is malformed")
        if missing_requested:
            raise ArtifactVerificationError("zero-candidate migration execution evidence has missing requested functions")
    if computed_counts["operational_error"] != 0:
        raise ArtifactVerificationError("successful action artifact contains candidate operational_error")
    if computed_counts["blocked"] + computed_counts["ready_for_human_review"] != len(candidates):
        raise ArtifactVerificationError("successful action artifact does not consist of blocked/ready review evidence")
    if require_blocked_candidate and computed_counts["blocked"] == 0:
        raise ArtifactVerificationError("fixed selftest artifact does not exercise the blocked review path")

    generated_value = artifact_paths.get("generated_artifacts")
    if not isinstance(generated_value, str):
        raise ArtifactVerificationError("generated artifact directory path is missing")
    generated_root = root / "migration-execution" / "generated-artifacts"
    if generated_root.is_symlink() or not generated_root.is_dir():
        raise ArtifactVerificationError("generated companion artifact directory is missing")
    generated_root = generated_root.resolve()
    companion_files = sorted(path for path in all_files if path.is_relative_to(generated_root))
    if not companion_files:
        raise ArtifactVerificationError("generated companion artifacts are missing")
    copied_count = status.get("generated_artifacts_copied")
    if type(copied_count) is not int or copied_count != len(companion_files):
        raise ArtifactVerificationError("generated companion file count changed during upload/download round trip")

    hidden_files = [
        path for path in companion_files if any(part.startswith(".") for part in path.relative_to(generated_root).parts)
    ]
    if require_hidden_companion:
        expected_hidden = generated_root / ".mumei-generated-artifacts"
        _regular_file(expected_hidden)
        if not hidden_files:
            raise ArtifactVerificationError("hidden generated companion files are missing after download")

    validated_mm = 0
    validated_proof = 0
    validated_sarif = 0
    certificate_pairs: list[tuple[str, Path, Path]] = []
    validated_mm_artifacts: list[tuple[str, Path]] = []
    incomplete_pair_candidates: list[str] = []
    for candidate in candidates:
        generated_mm = candidate.get("generated_mm")
        verification = candidate.get("verification")
        generated_mm_valid = isinstance(generated_mm, dict) and _validate_file_claim(
            generated_mm,
            label="generated .mm",
            original_root_text=generated_value,
            generated_root=generated_root,
        )
        if candidate["execution_state"] == "ready_for_human_review" and not generated_mm_valid:
            raise ArtifactVerificationError("ready_for_human_review candidate is missing a validated generated .mm artifact")
        proof_valid = False
        if isinstance(verification, dict):
            proof = verification.get("proof_certificate")
            sarif_claim = verification.get("sarif")
            if isinstance(proof, dict) and _validate_written_claim(
                proof,
                label="generated proof certificate",
                original_root_text=generated_value,
                generated_root=generated_root,
            ):
                proof_valid = True
            if isinstance(sarif_claim, dict) and _validate_written_claim(
                sarif_claim,
                label="generated SARIF",
                original_root_text=generated_value,
                generated_root=generated_root,
            ):
                validated_sarif += 1
        if generated_mm_valid:
            validated_mm += 1
            mm_label = str(candidate.get("function_name") or "<unknown>")
            validated_mm_artifacts.append((mm_label, _map_claimed_path(generated_mm["path"], generated_value, generated_root)))
        if proof_valid:
            validated_proof += 1
        if generated_mm_valid and proof_valid:
            mm_target = _map_claimed_path(generated_mm["path"], generated_value, generated_root)
            cert_target = _map_claimed_path(verification["proof_certificate"]["path"], generated_value, generated_root)
            label = candidate.get("function_name") or "<unknown>"
            certificate_pairs.append((str(label), cert_target, mm_target))
        else:
            incomplete_pair_candidates.append(str(candidate.get("function_name") or "<unknown>"))
    if require_generated_mm and validated_mm == 0:
        raise ArtifactVerificationError("no generated .mm companion claim was validated")

    verified_certificates = 0
    if mumei_bin:
        binary = Path(mumei_bin)
        if binary.is_symlink() or not binary.is_file() or not os.access(binary, os.X_OK):
            raise ArtifactVerificationError("--mumei-bin is not an executable regular file")
        binary = binary.resolve()
        if binary.is_relative_to(root):
            raise ArtifactVerificationError("--mumei-bin must not resolve inside the untrusted downloaded artifact")
        if incomplete_pair_candidates:
            raise ArtifactVerificationError(
                "strict certificate verification requires a validated pair for every candidate; missing for: "
                + ", ".join(sorted(incomplete_pair_candidates))
            )
        if not certificate_pairs:
            raise ArtifactVerificationError("strict certificate verification found no validated generated-.mm/proof-certificate pair")
        for label, cert_path, mm_path in certificate_pairs:
            try:
                completed = subprocess.run(
                    [str(binary), "verify-cert", str(cert_path), str(mm_path), "--strict"],
                    capture_output=True,
                    text=True,
                    timeout=VERIFY_CERT_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired as exc:
                raise ArtifactVerificationError(f"mumei verify-cert timed out for candidate {label}") from exc
            except OSError as exc:
                raise ArtifactVerificationError(f"mumei verify-cert could not execute for candidate {label}") from exc
            if completed.returncode != 0:
                diagnostic = (completed.stderr or completed.stdout or "").replace("\n", " ")[:DIAGNOSTIC_CAP]
                raise ArtifactVerificationError(
                    f"mumei verify-cert --strict failed for candidate {label}: {diagnostic or 'no diagnostic output'}"
                )
            verified_certificates += 1
        print(f"proof certificate correspondence verified with mumei verify-cert --strict: {verified_certificates} candidate pair(s)")
        print(f"certificate verification boundary: {CERT_BOUNDARY}")

    reverified_mm = 0
    if reverify_z3:
        reverified_mm = _reverify_generated_mm(binary, validated_mm_artifacts, generated_root, companion_files)
        print(f"generated .mm independent Z3 re-verification verified: {reverified_mm} candidate artifact(s)")
        print(f"Z3 re-verification boundary: {Z3_REVERIFY_BOUNDARY}")

    print("audit report artifact verified: audit.json and audit.sarif")
    print("ci policy artifact verified: generated-baseline.json")
    print("diagnostic log artifacts verified: audit.stdout.log and audit.stderr.log")
    print("timing artifacts verified: start/setup_end/audit_start/audit_end")
    print(f"migration execution candidates verified: {len(candidates)}")
    print(f"generated companion files verified: {len(companion_files)}")
    print(f"generated companion claims verified: mm={validated_mm}, proof={validated_proof}, sarif={validated_sarif}")
    print(f"hidden generated companion files verified: {len(hidden_files)}")
    if not candidates and allow_zero_candidates:
        print("zero migration candidates explicitly allowed; no generated-.mm acceptance evidence present")
    if mumei_bin and reverify_z3:
        print("verification mode: layout, metadata, counts, companion hashes, certificate correspondence, and independent Z3 re-verification")
    elif mumei_bin:
        print("verification mode: layout, metadata, counts, companion hashes, and certificate correspondence")
    else:
        print("verification mode: action artifact layout, metadata, counts, and companion hashes only")
    print("migration execution boundary: generated-.mm acceptance evidence only; not host semantic-equivalence proof")
    print("baseline boundary: generated CI policy artifact; not evidence")
    return {
        "candidate_count": len(candidates),
        "companion_file_count": len(companion_files),
        "hidden_companion_count": len(hidden_files),
        "verified_certificate_count": verified_certificates,
        "reverified_mm_count": reverified_mm,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir")
    parser.add_argument("--require-hidden-companion", action="store_true")
    parser.add_argument("--require-blocked-candidate", action="store_true")
    parser.add_argument("--require-generated-mm", action="store_true")
    parser.add_argument("--allow-zero-candidates", action="store_true")
    parser.add_argument("--forbidden-literal", default="")
    parser.add_argument("--mumei-bin", default="", help="optional trusted mumei binary enabling strict proof-certificate correspondence verification")
    parser.add_argument("--reverify-z3", action="store_true", help="independently re-verify validated generated .mm files with the trusted mumei binary")
    args = parser.parse_args()
    if args.allow_zero_candidates and args.require_blocked_candidate:
        parser.error("--allow-zero-candidates cannot be combined with --require-blocked-candidate")
    if args.allow_zero_candidates and args.require_generated_mm:
        parser.error("--allow-zero-candidates cannot be combined with --require-generated-mm")
    if args.reverify_z3 and not args.mumei_bin:
        parser.error("--reverify-z3 requires --mumei-bin")
    try:
        verify_artifact(
            Path(args.artifact_dir),
            require_hidden_companion=args.require_hidden_companion,
            forbidden_literal=args.forbidden_literal,
            require_blocked_candidate=args.require_blocked_candidate,
            require_generated_mm=args.require_generated_mm,
            allow_zero_candidates=args.allow_zero_candidates,
            mumei_bin=args.mumei_bin,
            reverify_z3=args.reverify_z3,
        )
    except ArtifactVerificationError as exc:
        raise SystemExit(f"audit evidence artifact verification failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
