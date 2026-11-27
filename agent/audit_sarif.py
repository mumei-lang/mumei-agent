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
import re
from pathlib import Path
from urllib.parse import quote

from agent.audit_findings import _stable_source_key
from agent.audit_baseline import (
    FAIL_ON_CHOICES,
    active_code_findings,
    active_findings,
    has_unbaselined_refuted_without_findings,
)
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


def audit_exit_code(
    result: AuditResult | AuditDirectoryResult, *, fail_on: str = "refuted"
) -> int:
    """Return the stable process classification for one audit result.

    ``0`` means no failing code findings; ``1`` means the audit completed
    enough to report evidence against the code; ``2`` means operational or
    extraction errors prevented a normal audit. Spec-only diagnostics and
    ``unverifiable`` do not fail by default. ``fail_on`` then selects whether
    non-suppressed findings fail on any refuted/code evidence, any error-level
    finding, only high-confidence code evidence, or never.
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
    if fail_on not in FAIL_ON_CHOICES:
        raise ValueError(f"unsupported fail-on policy: {fail_on}")
    if fail_on == "never":
        return 0

    active_code = active_code_findings(result)
    unbaselined_refuted = has_unbaselined_refuted_without_findings(result)
    if fail_on == "high-confidence":
        return (
            1
            if unbaselined_refuted
            or any(row.get("confidence") == "high" for row in active_code)
            else 0
        )
    if fail_on == "error":
        return (
            1
            if unbaselined_refuted
            or any(
                row.get("severity") == "error" for row in active_findings(result)
            )
            else 0
        )
    if active_code or unbaselined_refuted:
        return 1
    if not any((file_result.findings or []) for file_result in files) and any(
        file_result.verification_status == "refuted" or bool(file_result.verification_violations)
        for file_result in files
    ):
        # Direct callers may pass a result before audit reporting derives the
        # finding projection. Preserve the A-1 raw-signal classification there.
        return 1
    return 0


def sarif_document(result: AuditResult | AuditDirectoryResult) -> dict:
    """Render one audit result as a SARIF 2.1.0 document."""
    results: list[dict] = []
    baseline_states = _baseline_state_map(result)
    if isinstance(result, AuditDirectoryResult):
        for file_result in result.file_results:
            results.extend(
                _file_sarif_results(
                    file_result,
                    include_trusted_atoms=False,
                    baseline_states=baseline_states,
                )
            )
        results.extend(
            _trusted_atom_sarif_results(
                result.trusted_atoms,
                result.source_dir,
                base_dir=result.source_dir,
                baseline_states=baseline_states,
            )
        )
        results.extend(
            _finding_result(
                "mumei.audit/audit-error",
                "error",
                _redact_message(error, [result.source_dir]),
                result.source_dir,
                None,
                baseline_state=_baseline_state(
                    baseline_states,
                    _redact_message(error, [result.source_dir]),
                    result.source_dir,
                    None,
                ),
            )
            for error in result.errors
        )
    else:
        results.extend(
            _file_sarif_results(result, baseline_states=baseline_states)
        )

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
    path = Path(os.path.expanduser(os.fspath(output_path)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sarif_json(result) + "\n", encoding="utf-8")


def _file_sarif_results(
    result: AuditResult,
    *,
    include_trusted_atoms: bool = True,
    baseline_states: dict[tuple[str, str, int | None], str] | None = None,
) -> list[dict]:
    output: list[dict] = []
    baseline_states = baseline_states or {}
    output.extend(
        _finding_result(
            "mumei.audit/verification-violation",
            "error",
            _redact_message(violation, [result.source_file]),
            result.source_file,
            None,
            baseline_state=_baseline_state(
                baseline_states,
                _redact_message(violation, [result.source_file]),
                result.source_file,
                None,
            ),
        )
        for violation in result.verification_violations
    )
    output.extend(
        _finding_result(
            "mumei.audit/audit-error" if _is_malformed_extraction(issue) else "mumei.audit/spec-health",
            "error" if _is_malformed_extraction(issue) else "warning",
            _redact_message(issue, [result.source_file]),
            result.source_file,
            None,
            baseline_state=_baseline_state(
                baseline_states,
                _redact_message(issue, [result.source_file]),
                result.source_file,
                None,
            ),
        )
        for issue in result.spec_health_issues
    )
    output.extend(
        _finding_result(
            "mumei.audit/cross-validation-gap",
            "warning",
            _redact_message(gap, [result.source_file]),
            result.source_file,
            None,
            baseline_state=_baseline_state(
                baseline_states,
                _redact_message(gap, [result.source_file]),
                result.source_file,
                None,
            ),
        )
        for gap in result.cross_validation_gaps
    )
    if include_trusted_atoms:
        output.extend(
            _trusted_atom_sarif_results(
                result.trusted_atoms,
                result.source_file,
                baseline_states=baseline_states,
            )
        )
    output.extend(
        _finding_result(
            "mumei.audit/audit-error",
            "error",
            _redact_message(error, [result.source_file]),
            result.source_file,
            None,
            baseline_state=_baseline_state(
                baseline_states,
                _redact_message(error, [result.source_file]),
                result.source_file,
                None,
            ),
        )
        for error in result.errors
    )
    return output


def _baseline_state_map(
    result: AuditResult | AuditDirectoryResult,
) -> dict[tuple[str, str, int | None], str]:
    rows = list(result.findings or [])
    if isinstance(result, AuditDirectoryResult):
        rows.extend(
            row
            for file_result in result.file_results
            for row in (file_result.findings or [])
        )
    return {
        (
            str(row.get("message")),
            _stable_source_key(str(row.get("source_file") or "")),
            row.get("line") if type(row.get("line")) is int else None,
        ): str(row["baseline"])
        for row in rows
        if row.get("message") and row.get("baseline") in {"new", "suppressed"}
    }


def _baseline_state(
    states: dict[tuple[str, str, int | None], str],
    message: str,
    source_file: str,
    line: int | None,
) -> str | None:
    state = states.get(
        (str(message), _stable_source_key(source_file), line)
    )
    if state == "suppressed":
        return "unchanged"
    if state == "new":
        return "new"
    return None


def _trusted_atom_sarif_results(
    trusted_atoms: list[dict],
    fallback_source: str,
    *,
    base_dir: str | None = None,
    baseline_states: dict[tuple[str, str, int | None], str] | None = None,
) -> list[dict]:
    output: list[dict] = []
    for atom in trusted_atoms:
        if not isinstance(atom, dict):
            continue
        line = atom.get("line")
        source = str(atom.get("file") or fallback_source)
        if base_dir and atom.get("file") and not os.path.isabs(source):
            # Directory trusted-atom labels are relative to the audit root,
            # not necessarily to the process working directory used by SARIF.
            source = str(Path(base_dir) / source)
        output.append(
            _finding_result(
                "mumei.audit/trusted-atom",
                "warning",
                "trusted atom bypasses Z3 verification"
                + (f": {atom.get('atom')}" if atom.get("atom") else ""),
                source,
                line if type(line) is int and line > 0 else None,
                baseline_state=_baseline_state(
                    baseline_states or {},
                    "trusted atom bypasses Z3 verification"
                    + (f": {atom.get('atom')}" if atom.get("atom") else ""),
                    source,
                    line if type(line) is int and line > 0 else None,
                ),
            )
        )
    return output


def _finding_result(
    rule_id: str,
    level: str,
    message: str,
    source_file: str,
    line: int | None,
    *,
    baseline_state: str | None = None,
) -> dict:
    text = str(message)
    artifact_uri = _artifact_uri(source_file)
    fingerprint = hashlib.sha256(
        f"{rule_id}\0{artifact_uri}\0{line}\0{text}".encode("utf-8", errors="replace")
    ).hexdigest()
    physical_location = {"artifactLocation": {"uri": artifact_uri}}
    if line is not None:
        physical_location["region"] = {"startLine": line}
    row = {
        "ruleId": rule_id,
        "level": level,
        "message": {"text": text},
        "locations": [{"physicalLocation": physical_location}],
        "partialFingerprints": {"mumeiAuditFinding/v1": fingerprint},
    }
    if baseline_state:
        row["baselineState"] = baseline_state
    return row


_ABSOLUTE_PATH_RE = re.compile(r"(?<![\w:/])\/(?:[^\s\"'`<>|,.;:]+/)+[^\s\"'`<>|,.;:]*")


def _redact_message(text: str, known_paths: list[str]) -> str:
    """Remove machine-local absolute paths from a SARIF message.

    Audit text output may include user-supplied paths. SARIF is commonly
    uploaded outside the runner, so repo paths are relativized and all other
    absolute paths are replaced rather than copied into the artifact.
    """
    redacted = str(text)
    replacements: dict[str, str] = {}
    for value in known_paths:
        if not value:
            continue
        expanded = os.path.expanduser(value)
        for form in {value, expanded, os.path.realpath(expanded)}:
            if os.path.isabs(form):
                replacements[form] = _display_path(form)
    for form in sorted(replacements, key=len, reverse=True):
        redacted = redacted.replace(form, replacements[form])
    return _ABSOLUTE_PATH_RE.sub("<path>", redacted)


def _display_path(path: str) -> str:
    try:
        resolved = Path(path).resolve()
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except (OSError, ValueError):
        return "<path>"


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
                digest = hashlib.sha256(path.as_posix().encode("utf-8", errors="replace")).hexdigest()[:16]
                return f"external/{digest}"
    except OSError:
        pass
    return quote(path.as_posix(), safe="/:@._-~")


def _is_malformed_extraction(issue: str) -> bool:
    return issue.startswith("malformed-extraction:") or ": malformed-extraction:" in issue
