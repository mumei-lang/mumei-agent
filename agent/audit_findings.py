"""Stable machine-readable finding and triage projection for audit results.

The projection is derived from the fixed audit keys; those keys remain the
source of truth. It adds category, confidence and verification-basis metadata
so CI consumers do not have to re-implement string-based dogfood triage.
"""
from __future__ import annotations

import hashlib

from agent.audit_models import AuditDirectoryResult, AuditResult

FINDINGS_SCHEMA = "mumei.audit-findings/v1"
TRIAGE_SCHEMA = "mumei.audit-triage/v1"
_TIMEOUT_MARKERS = ("timeout", "timed out", "deadline exceeded")
_RATE_LIMIT_MARKERS = (
    "error code: 429",
    "rate limit",
    "rate_limit",
    "tokens per min",
    "too many requests",
    "retry-after",
)


def build_file_findings(result: AuditResult) -> list[dict]:
    rows: list[dict] = []
    rows.extend(
        _finding(
            result.source_file,
            category="code",
            severity="error",
            confidence=_violation_confidence(message),
            verification_basis=_violation_basis(message),
            message=message,
            triage_bucket="code_review",
        )
        for message in result.verification_violations
    )
    rows.extend(
        _finding(
            result.source_file,
            category=_spec_category(message),
            severity="error" if _is_malformed(message) else "warning",
            confidence="high",
            verification_basis=_spec_basis(message),
            message=message,
            triage_bucket=(
                "operational" if _is_malformed(message)
                else "model_limitation" if _is_encoding_gap(message)
                else "spec_review"
            ),
        )
        for message in result.spec_health_issues
    )
    rows.extend(
        _finding(
            result.source_file,
            category="spec",
            severity="warning",
            confidence="medium",
            verification_basis="cross-validation",
            message=message,
            triage_bucket="spec_review",
        )
        for message in result.cross_validation_gaps
    )
    for atom in result.trusted_atoms:
        rows.append(_trusted_atom_finding(result.source_file, atom))
    rows.extend(
        _finding(
            result.source_file,
            category="error",
            severity="error",
            confidence="high",
            verification_basis="operational",
            message=message,
            triage_bucket="operational",
        )
        for message in result.errors
    )
    return rows


def build_directory_findings(result: AuditDirectoryResult) -> list[dict]:
    rows = [
        finding
        for file_result in result.file_results
        for finding in (file_result.findings or build_file_findings(file_result))
    ]
    seen = {finding["fingerprint"] for finding in rows}
    for atom in result.trusted_atoms:
        source_file = (
            str(atom.get("file") or result.source_dir)
            if isinstance(atom, dict)
            else result.source_dir
        )
        row = _trusted_atom_finding(source_file, atom)
        if row["fingerprint"] not in seen:
            seen.add(row["fingerprint"])
            rows.append(row)
    rows.extend(
        {
            "schema": FINDINGS_SCHEMA,
            "category": "error",
            "severity": "error",
            "confidence": "high",
            "verification_basis": "operational",
            "message": message,
            "source_file": result.source_dir,
            "line": None,
            "triage_bucket": "operational",
            "fingerprint": _fingerprint(
                "error", "operational", message, result.source_dir, None
            ),
        }
        for message in result.errors
    )
    return rows


def build_file_triage(result: AuditResult) -> dict:
    category = _unverifiable_category(result)
    refuted = (
        [result.source_file] if result.verification_status == "refuted" else []
    )
    verified = [result.source_file] if result.verification_status == "verified" else []
    unverifiable = {key: [] for key in _unverifiable_keys()}
    if result.verification_status not in {"refuted", "verified"}:
        unverifiable[category].append(result.source_file)
    return _triage_dict(refuted, verified, unverifiable)


def build_directory_triage(result: AuditDirectoryResult) -> dict:
    refuted: list[str] = []
    verified: list[str] = []
    unverifiable = {key: [] for key in _unverifiable_keys()}
    for file_result in result.file_results:
        if file_result.verification_status == "refuted":
            refuted.append(file_result.source_file)
        elif file_result.verification_status == "verified":
            verified.append(file_result.source_file)
        else:
            unverifiable[_unverifiable_category(file_result, result)].append(
                file_result.source_file
            )
    return _triage_dict(refuted, verified, unverifiable)


def _finding(
    source_file: str,
    *,
    category: str,
    severity: str,
    confidence: str,
    verification_basis: str,
    message: str,
    triage_bucket: str,
    line: int | None = None,
) -> dict:
    return {
        "schema": FINDINGS_SCHEMA,
        "category": category,
        "severity": severity,
        "confidence": confidence,
        "verification_basis": verification_basis,
        "message": str(message),
        "source_file": source_file,
        "line": line,
        "triage_bucket": triage_bucket,
        "fingerprint": _fingerprint(
            category, verification_basis, str(message), source_file, line
        ),
    }


def _trusted_atom_finding(source_file: str, atom: dict) -> dict:
    line = atom.get("line") if isinstance(atom, dict) else None
    line = line if type(line) is int and line > 0 else None
    atom_name = atom.get("atom") if isinstance(atom, dict) else ""
    message = "trusted atom bypasses Z3 verification" + (
        f": {atom_name}" if atom_name else ""
    )
    row = _finding(
        source_file,
        category="advisory",
        severity="warning",
        confidence="high",
        verification_basis="trusted-atom",
        message=message,
        triage_bucket="advisory",
        line=line,
    )
    return row


def _violation_basis(message: str) -> str:
    lowered = message.lower()
    if "native-replay:" in lowered:
        return "native-replay"
    if lowered.startswith("body-port:"):
        return "body-port"
    if "counterexample" in lowered or "status=refuted" in lowered or "status=failed" in lowered:
        return "z3"
    return "deterministic-static-analysis"


def _violation_confidence(message: str) -> str:
    basis = _violation_basis(message)
    if basis == "native-replay":
        return "high"
    if basis == "body-port":
        return "medium"
    if basis == "z3":
        return "high" if "counterexample" in message.lower() else "medium"
    return "medium"


def _spec_category(message: str) -> str:
    if _is_malformed(message):
        return "error"
    if _is_encoding_gap(message):
        return "model_limitation"
    return "spec"


def _spec_basis(message: str) -> str:
    if _is_malformed(message):
        return "deterministic-extraction-check"
    if _is_encoding_gap(message):
        return "mumei-encoding"
    return "z3-spec-health"


def _is_malformed(message: str) -> bool:
    return message.startswith("malformed-extraction:") or ": malformed-extraction:" in message


def _is_encoding_gap(message: str) -> bool:
    return message.startswith("encoding-gap") or ": encoding-gap:" in message


def _unverifiable_keys() -> tuple[str, ...]:
    return (
        "skipped_rate_limited",
        "timeout",
        "encoding_gap",
        "no_function_declarations",
        "other",
    )


def _unverifiable_category(
    result: AuditResult, directory: AuditDirectoryResult | None = None
) -> str:
    issues = [
        *result.errors,
        *result.spec_health_issues,
        *result.verification_violations,
        *result.cross_validation_gaps,
    ]
    lowered = [issue.lower() for issue in issues]
    if (
        result.skipped_rate_limited
        or (
            directory is not None
            and result.source_file in directory.skipped_rate_limited_files
        )
        or any(marker in issue for issue in lowered for marker in _RATE_LIMIT_MARKERS)
    ):
        return "skipped_rate_limited"
    if any(marker in issue for issue in lowered for marker in _TIMEOUT_MARKERS):
        return "timeout"
    lowering_markers = (
        "spec_lowering_failed",
        "skipped unsupported z3 clause",
        "unsupported clause",
        "unsupported expression",
        "forall() requires exactly",
        "unknown function:",
        "expected bool for",
        "spec_not_boolean",
        "must lower to boolean",
    )
    if any(
        _is_encoding_gap(issue) or any(marker in issue.lower() for marker in lowering_markers)
        for issue in issues
    ):
        return "encoding_gap"
    if not result.spec_extracted or any(
        marker in issue
        for issue in lowered
        for marker in ("no mumei atoms", "no supported source", "no functions")
    ):
        return "no_function_declarations"
    return "other"


def _triage_dict(
    refuted: list[str], verified: list[str], unverifiable: dict[str, list[str]]
) -> dict:
    return {
        "schema": TRIAGE_SCHEMA,
        "refuted": refuted,
        "verified": verified,
        "unverifiable": unverifiable,
        "counts": {
            "refuted": len(refuted),
            "verified": len(verified),
            "unverifiable": sum(len(files) for files in unverifiable.values()),
            "unverifiable_by_cause": {
                key: len(files) for key, files in unverifiable.items()
            },
        },
    }


def _fingerprint(
    category: str, basis: str, message: str, source_file: str, line: int | None
) -> str:
    return hashlib.sha256(
        f"{category}\0{basis}\0{message}\0{source_file}\0{line}".encode(
            "utf-8", errors="replace"
        )
    ).hexdigest()
