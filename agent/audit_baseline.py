"""Baseline loading/writing and fail-on policy helpers for audit CI."""
from __future__ import annotations

import json
import os
from pathlib import Path

from agent.audit_models import AuditDirectoryResult, AuditResult

BASELINE_SCHEMA = "mumei.audit-baseline/v1"
FAIL_ON_CHOICES = ("refuted", "error", "high-confidence", "never")


def load_baseline(path: str | os.PathLike[str]) -> set[str]:
    """Load a baseline fingerprint set, rejecting malformed files."""
    try:
        payload = json.loads(
            Path(os.path.expanduser(os.fspath(path))).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid audit baseline: {type(exc).__name__}") from exc
    if not isinstance(payload, dict) or payload.get("version") != BASELINE_SCHEMA:
        raise ValueError("invalid audit baseline: unsupported schema")
    fingerprints = payload.get("fingerprints")
    if not isinstance(fingerprints, list) or not all(
        type(item) is str and item for item in fingerprints
    ):
        raise ValueError("invalid audit baseline: fingerprints must be non-empty strings")
    return set(fingerprints)


def apply_baseline(result: AuditResult | AuditDirectoryResult, fingerprints: set[str]) -> int:
    """Annotate findings as ``new`` or ``suppressed`` and return suppressed count."""
    suppressed = 0
    seen_rows: set[int] = set()
    for row in _finding_rows(result):
        if id(row) in seen_rows:
            continue
        seen_rows.add(id(row))
        is_suppressed = row.get("fingerprint") in fingerprints
        row["baseline"] = "suppressed" if is_suppressed else "new"
        suppressed += int(is_suppressed)
    return suppressed


def write_baseline(
    result: AuditResult | AuditDirectoryResult, path: str | os.PathLike[str]
) -> None:
    """Write the current finding fingerprint set in a stable, diff-friendly form."""
    output = Path(os.path.expanduser(os.fspath(path)))
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": BASELINE_SCHEMA,
        "fingerprints": sorted(
            {
                row["fingerprint"]
                for row in _finding_rows(result)
                if row.get("fingerprint")
            }
        ),
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def active_findings(result: AuditResult | AuditDirectoryResult) -> list[dict]:
    """Return non-suppressed findings across file and directory results."""
    return [row for row in _finding_rows(result) if row.get("baseline") != "suppressed"]


def active_code_findings(result: AuditResult | AuditDirectoryResult) -> list[dict]:
    """Return non-suppressed code findings across file and directory results."""
    return [
        row
        for row in _finding_rows(result)
        if row.get("category") == "code" and row.get("baseline") != "suppressed"
    ]


def has_unbaselined_refuted_without_findings(
    result: AuditResult | AuditDirectoryResult,
) -> bool:
    """True for a refuted file that has no code rows a baseline could suppress."""
    files = result.file_results if isinstance(result, AuditDirectoryResult) else [result]
    for file_result in files:
        if file_result.verification_status != "refuted":
            continue
        rows = [
            row
            for row in (file_result.findings or [])
            if row.get("category") == "code"
        ]
        if not rows:
            return True
    return False


def _finding_rows(result: AuditResult | AuditDirectoryResult) -> list[dict]:
    rows = list(result.findings or [])
    if isinstance(result, AuditDirectoryResult):
        rows.extend(
            row
            for file_result in result.file_results
            for row in (file_result.findings or [])
        )
    return rows
