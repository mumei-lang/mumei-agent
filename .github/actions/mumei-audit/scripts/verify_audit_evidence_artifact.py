#!/usr/bin/env python3
"""Verify a downloaded mumei-audit action evidence artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "mumei.migration-execution/v1"
STATES = ("ready_for_human_review", "blocked", "operational_error")
HOST_BOUNDARY = "not proof that host-language code implements the same behavior"


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


def verify_artifact(
    root: Path,
    *,
    require_hidden_companion: bool,
    forbidden_literal: str = "",
    require_blocked_candidate: bool = False,
    require_generated_mm: bool = False,
) -> dict[str, int]:
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
    if summary.get("review_required") is not True or status.get("review_required") is not True:
        raise ArtifactVerificationError("blocked/ready migration execution evidence must require human review")
    if computed_counts["operational_error"] != 0:
        raise ArtifactVerificationError("successful action artifact contains candidate operational_error")
    if computed_counts["blocked"] + computed_counts["ready_for_human_review"] != len(candidates) or not candidates:
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
    for candidate in candidates:
        generated_mm = candidate.get("generated_mm")
        verification = candidate.get("verification")
        if isinstance(generated_mm, dict) and _validate_file_claim(
            generated_mm,
            label="generated .mm",
            original_root_text=generated_value,
            generated_root=generated_root,
        ):
            validated_mm += 1
        if isinstance(verification, dict):
            proof = verification.get("proof_certificate")
            sarif_claim = verification.get("sarif")
            if isinstance(proof, dict) and _validate_written_claim(
                proof,
                label="generated proof certificate",
                original_root_text=generated_value,
                generated_root=generated_root,
            ):
                validated_proof += 1
            if isinstance(sarif_claim, dict) and _validate_written_claim(
                sarif_claim,
                label="generated SARIF",
                original_root_text=generated_value,
                generated_root=generated_root,
            ):
                validated_sarif += 1
    if require_generated_mm and validated_mm == 0:
        raise ArtifactVerificationError("no generated .mm companion claim was validated")

    print("audit report artifact verified: audit.json and audit.sarif")
    print("ci policy artifact verified: generated-baseline.json")
    print("diagnostic log artifacts verified: audit.stdout.log and audit.stderr.log")
    print("timing artifacts verified: start/setup_end/audit_start/audit_end")
    print(f"migration execution candidates verified: {len(candidates)}")
    print(f"generated companion files verified: {len(companion_files)}")
    print(f"generated companion claims verified: mm={validated_mm}, proof={validated_proof}, sarif={validated_sarif}")
    print(f"hidden generated companion files verified: {len(hidden_files)}")
    print("verification mode: action artifact layout, metadata, counts, and companion hashes only")
    print("migration execution boundary: generated-.mm acceptance evidence only; not host semantic-equivalence proof")
    print("baseline boundary: generated CI policy artifact; not evidence")
    return {
        "candidate_count": len(candidates),
        "companion_file_count": len(companion_files),
        "hidden_companion_count": len(hidden_files),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir")
    parser.add_argument("--require-hidden-companion", action="store_true")
    parser.add_argument("--require-blocked-candidate", action="store_true")
    parser.add_argument("--require-generated-mm", action="store_true")
    parser.add_argument("--forbidden-literal", default="")
    args = parser.parse_args()
    try:
        verify_artifact(
            Path(args.artifact_dir),
            require_hidden_companion=args.require_hidden_companion,
            forbidden_literal=args.forbidden_literal,
            require_blocked_candidate=args.require_blocked_candidate,
            require_generated_mm=args.require_generated_mm,
        )
    except ArtifactVerificationError as exc:
        raise SystemExit(f"audit evidence artifact verification failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
