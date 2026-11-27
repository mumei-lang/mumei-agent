"""Stable machine-readable finding and triage projection for audit results.

The projection is derived from the fixed audit keys; those keys remain the
source of truth. It adds category, confidence and verification-basis metadata
so CI consumers do not have to re-implement string-based dogfood triage.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

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


def _root_relative_source_key(source_file: str, source_dir: str) -> str:
    key = _stable_source_key(source_file)
    if key.startswith(("git:", "git-remote:")):
        return key
    try:
        return Path(os.path.expanduser(source_file)).resolve().relative_to(
            Path(os.path.expanduser(source_dir)).resolve()
        ).as_posix()
    except (OSError, ValueError):
        return key


def _refingerprint_for_audit_root(row: dict, source_dir: str) -> None:
    row["fingerprint"] = _fingerprint(
        str(row["category"]),
        str(row["verification_basis"]),
        str(row["message"]),
        _root_relative_source_key(str(row["source_file"]), source_dir),
        row.get("line") if type(row.get("line")) is int else None,
    )


def build_directory_findings(result: AuditDirectoryResult) -> list[dict]:
    rows = [
        finding
        for file_result in result.file_results
        for finding in (file_result.findings or build_file_findings(file_result))
    ]
    for row in rows:
        # Directory baselines are keyed relative to the audited root. This keeps
        # identical diagnostics in independent nested checkouts distinct while
        # remaining stable across invocation subdirectories.
        _refingerprint_for_audit_root(row, result.source_dir)
    seen = {finding["fingerprint"] for finding in rows}
    for atom in result.trusted_atoms:
        source_file = (
            str(atom.get("file") or result.source_dir)
            if isinstance(atom, dict)
            else result.source_dir
        )
        if isinstance(atom, dict) and atom.get("file") and not os.path.isabs(source_file):
            source_file = str(Path(result.source_dir) / source_file)
        row = _trusted_atom_finding(source_file, atom)
        _refingerprint_for_audit_root(row, result.source_dir)
        if row["fingerprint"] not in seen:
            seen.add(row["fingerprint"])
            rows.append(row)
    rows.extend(
        _finding(
            result.source_dir,
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
        "message": _redact_message(str(message), [source_file]),
        "source_file": source_file,
        "line": line,
        "triage_bucket": triage_bucket,
        "fingerprint": _fingerprint(
            category,
            verification_basis,
            _redact_message(str(message), [source_file]),
            _stable_source_key(source_file),
            line,
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
    if (
        "counterexample" in lowered
        or "counter-example" in lowered
        or "status=refuted" in lowered
        or "status=failed" in lowered
    ):
        return "z3"
    return "deterministic-static-analysis"


def _violation_confidence(message: str) -> str:
    basis = _violation_basis(message)
    if basis == "native-replay":
        return "high"
    if basis == "body-port":
        return "medium"
    if basis == "z3":
        return "high" if "counterexample" in message.lower() or "counter-example" in message.lower() else "medium"
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
    lowered_errors = [issue.lower() for issue in result.errors]
    if (
        result.skipped_rate_limited
        or (
            directory is not None
            and result.source_file in directory.skipped_rate_limited_files
        )
        or any(marker in issue for issue in lowered_errors for marker in _RATE_LIMIT_MARKERS)
    ):
        return "skipped_rate_limited"
    if any(marker in issue for issue in lowered_errors for marker in _TIMEOUT_MARKERS):
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

_ABSOLUTE_PATH_RE = re.compile(r"(?<![\w:/])\/(?:[^\s\"'`<>|,.;:]+/)+[^\s\"'`<>|,.;:]*")


def _display_path(path: str) -> str:
    try:
        resolved = Path(path).resolve()
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except (OSError, ValueError):
        return "<path>"


def _redact_message(text: str, known_paths: list[str]) -> str:
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


def _canonical_remote_key(remote_url: str) -> str:
    scp_like = re.match(r"^[^@\s]+@([^:\s]+):(.+)$", remote_url)
    if scp_like:
        host, path = scp_like.groups()
    else:
        parsed = urlsplit(remote_url)
        host = (parsed.hostname or parsed.netloc).lower()
        path = parsed.path
    path = path.removeprefix("/").removesuffix(".git").strip("/")
    return f"{host}/{path}"


_GIT_IDENTITY_CACHE: dict[str, str | None] = {}


def _git_identity(checkout_root: Path) -> str | None:
    """Return a clone-stable identity for a valid git checkout, if available."""
    cache_key = str(checkout_root)
    if cache_key in _GIT_IDENTITY_CACHE:
        return _GIT_IDENTITY_CACHE[cache_key]
    identity = None
    try:
        remote = subprocess.run(
            ["git", "-C", str(checkout_root), "config", "--get", "remote.origin.url"],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
        remote_url = remote.stdout.strip()
        if remote.returncode == 0 and remote_url:
            # Hash rather than expose the URL: credential-bearing remotes must
            # never leak into findings, while the digest remains clone-stable.
            digest = hashlib.sha256(
                _canonical_remote_key(remote_url).encode("utf-8", errors="replace")
            ).hexdigest()[:20]
            identity = f"git-remote:{digest}"
        else:
            completed = subprocess.run(
                ["git", "-C", str(checkout_root), "rev-list", "--max-parents=0", "HEAD"],
                capture_output=True,
                check=False,
                text=True,
                timeout=2,
            )
            root_commits = sorted(line for line in completed.stdout.splitlines() if line)
            if completed.returncode == 0 and root_commits:
                digest = hashlib.sha256(
                    "\n".join(root_commits).encode("utf-8", errors="replace")
                ).hexdigest()[:20]
                identity = f"git:{digest}"
    except (OSError, subprocess.TimeoutExpired):
        pass
    _GIT_IDENTITY_CACHE[cache_key] = identity
    return identity


def _stable_source_key(source_file: str) -> str:
    """Use a repository-scoped source key when possible for stable CI fingerprints."""
    try:
        path = Path(os.path.expanduser(source_file)).resolve()
        start = path if path.is_dir() else path.parent
        nearest_checkout = None
        outermost_checkout = None
        for candidate in (start, *start.parents):
            if (candidate / ".git").exists():
                if nearest_checkout is None:
                    nearest_checkout = candidate
                outermost_checkout = candidate
        if nearest_checkout is not None:
            identity = _git_identity(nearest_checkout)
            if identity is not None:
                return (
                    f"{identity}:"
                    f"{path.relative_to(nearest_checkout).as_posix()}"
                )
            # A bare .git marker in tests or an unborn checkout has no stable
            # repository identity. Keep the outermost path shape there so
            # nested markers do not collapse distinct files into one key.
            return path.relative_to(outermost_checkout).as_posix()
        return path.relative_to(Path.cwd().resolve()).as_posix()
    except (OSError, ValueError):
        pass
    return Path(source_file).as_posix()


def _fingerprint(
    category: str, basis: str, message: str, source_file: str, line: int | None
) -> str:
    return hashlib.sha256(
        f"{category}\0{basis}\0{message}\0{source_file}\0{line}".encode(
            "utf-8", errors="replace"
        )
    ).hexdigest()
