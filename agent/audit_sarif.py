"""SARIF 2.1.0 rendering and process exit classification for ``audit``.

This module deliberately derives SARIF only from the stable audit result keys.
It does not introduce a second verdict model: code violations are errors, spec
and cross-validation diagnostics are review warnings, and operational errors
stay distinguishable through the audit-error rule and exit code 2.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote

from agent.audit_models import AuditDirectoryResult, AuditResult

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
SARIF_VERSION = "2.1.0"
DRIVER_NAME = "mumei-agent audit"
INFORMATION_URI = "https://github.com/mumei-lang/mumei-agent"

_RULES = {
    "mumei.audit/verification-violation": {
        "name": "VerificationViolation",
        "shortDescription": {"text": "Evidence against the audited code"},
        "defaultConfiguration": {"level": "error"},
    },
    "mumei.audit/spec-health": {
        "name": "SpecHealthDiagnostic",
        "shortDescription": {"text": "Evidence against the extracted specification"},
        "defaultConfiguration": {"level": "warning"},
    },
    "mumei.audit/cross-validation-gap": {
        "name": "CrossValidationGap",
        "shortDescription": {"text": "Spec/code cross-validation gap requiring review"},
        "defaultConfiguration": {"level": "warning"},
    },
    "mumei.audit/trusted-atom": {
        "name": "TrustedAtom",
        "shortDescription": {"text": "Trusted atom bypasses Z3 verification"},
        "defaultConfiguration": {"level": "warning"},
    },
    "mumei.audit/audit-error": {
        "name": "AuditError",
        "shortDescription": {"text": "Audit could not complete normally"},
        "defaultConfiguration": {"level": "error"},
    },
}


def audit_exit_code(result: AuditResult | AuditDirectoryResult) -> int:
    """Return the stable process classification for one audit result.

    ``0`` means no failing code findings; ``1`` means the audit completed
    enough to report evidence against the code; ``2`` means operational or
    extraction errors prevented a normal audit. Spec-only diagnostics and
    ``unverifiable`` do not fail by default; stricter CI policy belongs to the
    later ``--fail-on`` contract rather than this baseline classification.
    """
    files = (
        result.file_results
        if isinstance(result, AuditDirectoryResult)
        else [result]
    )
    has_operational_error = bool(getattr(result, "errors", [])) or any(
        file_result.errors
        or any(_is_malformed_extraction(issue) for issue in file_result.spec_health_issues)
        for file_result in files
    )
    if has_operational_error:
        return 2
    has_code_finding = any(
        file_result.verification_status == "refuted" or bool(file_result.verification_violations)
        for file_result in files
    )
    return 1 if has_code_finding else 0


def sarif_document(result: AuditResult | AuditDirectoryResult) -> dict:
    """Render one audit result as a SARIF 2.1.0 document."""
    results: list[dict] = []
    if isinstance(result, AuditDirectoryResult):
        for file_result in result.file_results:
            results.extend(_file_sarif_results(file_result))
        results.extend(
            _finding_result(
                "mumei.audit/audit-error",
                "error",
                error,
                result.source_dir,
                None,
            )
            for error in result.errors
        )
    else:
        results.extend(_file_sarif_results(result))

    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": DRIVER_NAME,
                        "informationUri": INFORMATION_URI,
                        "rules": [
                            {"id": rule_id, **rule}
                            for rule_id, rule in _RULES.items()
                        ],
                    }
                },
                "results": results,
            }
        ],
    }


def sarif_json(result: AuditResult | AuditDirectoryResult) -> str:
    """Serialize the SARIF document in the canonical audit output shape."""
    return json.dumps(sarif_document(result), ensure_ascii=False, indent=2, sort_keys=True)


def write_sarif(result: AuditResult | AuditDirectoryResult, output_path: str | os.PathLike[str]) -> None:
    """Write SARIF, creating only missing output directories."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sarif_json(result) + "\n", encoding="utf-8")


def _file_sarif_results(result: AuditResult) -> list[dict]:
    output: list[dict] = []
    output.extend(
        _finding_result(
            "mumei.audit/verification-violation",
            "error",
            violation,
            result.source_file,
            None,
        )
        for violation in result.verification_violations
    )
    output.extend(
        _finding_result(
            "mumei.audit/spec-health",
            "warning",
            issue,
            result.source_file,
            None,
        )
        for issue in result.spec_health_issues
    )
    output.extend(
        _finding_result(
            "mumei.audit/cross-validation-gap",
            "warning",
            gap,
            result.source_file,
            None,
        )
        for gap in result.cross_validation_gaps
    )
    for atom in result.trusted_atoms:
        line = atom.get("line") if isinstance(atom, dict) else None
        output.append(
            _finding_result(
                "mumei.audit/trusted-atom",
                "warning",
                "trusted atom bypasses Z3 verification"
                + (f": {atom.get('atom')}" if isinstance(atom, dict) and atom.get("atom") else ""),
                result.source_file,
                line if type(line) is int and line > 0 else None,
            )
        )
    output.extend(
        _finding_result(
            "mumei.audit/audit-error",
            "error",
            error,
            result.source_file,
            None,
        )
        for error in result.errors
    )
    return output


def _finding_result(rule_id: str, level: str, message: str, source_file: str, line: int | None) -> dict:
    text = str(message)
    artifact_uri = _artifact_uri(source_file)
    fingerprint = hashlib.sha256(
        f"{rule_id}\0{artifact_uri}\0{line}\0{text}".encode("utf-8", errors="replace")
    ).hexdigest()
    physical_location = {"artifactLocation": {"uri": artifact_uri}}
    if line is not None:
        physical_location["region"] = {"startLine": line}
    return {
        "ruleId": rule_id,
        "level": level,
        "message": {"text": text},
        "locations": [{"physicalLocation": physical_location}],
        "partialFingerprints": {"mumeiAuditFinding/v1": fingerprint},
    }


def _artifact_uri(source_file: str) -> str:
    """Produce a stable SARIF URI without requiring an absolute checkout path."""
    if not source_file or source_file.startswith("<"):
        return quote(source_file or "unknown")
    path = Path(source_file)
    try:
        if path.is_absolute():
            try:
                path = path.resolve().relative_to(Path.cwd().resolve())
            except ValueError:
                return quote(path.as_posix())
    except OSError:
        pass
    return quote(path.as_posix(), safe="/:@._-~")


def _is_malformed_extraction(issue: str) -> bool:
    return issue.startswith("malformed-extraction:") or ": malformed-extraction:" in issue
