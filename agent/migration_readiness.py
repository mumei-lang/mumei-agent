"""Build migration-readiness reports from audit migration hints."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shlex
import tempfile
from pathlib import Path
from typing import Protocol

from agent.audit_models import AuditDirectoryResult, AuditResult
from agent.secret_redaction import redact_secrets

SCHEMA = "mumei.migration-readiness/v1"
_ABSOLUTE_PATH_RE = re.compile(r"(?<![\w:/])\/(?:[^\s\"'`<>|]+/)+[^\s\"'`<>|]*")
_PRIORITY_SCORE = {"high": 60, "medium": 35, "low": 15}
_EXTERNAL_EFFECT_PATTERNS = {
    "filesystem": re.compile(r"(?<![\w])(?:open\s*\(|read_text\s*\(|write_text\s*\(|fopen\s*\(|fs\.|readFile|writeFile)"),
    "network": re.compile(r"(?<![\w])(?:requests\.|urllib|httpx|fetch\s*\(|axios|net/http|TcpStream|reqwest)"),
    "process": re.compile(r"(?<![\w])(?:subprocess|os\.system|exec\s*\(|spawn\s*\(|Command::new)"),
    "database": re.compile(r"(?<![\w])(?:sql|sqlite|postgres|mysql|db\.|database)", re.IGNORECASE),
    "nondeterminism": re.compile(r"(?<![\w])(?:random|time\.|datetime\.|now\s*\(|Date\.now|System::time)"),
}


class VerifyClient(Protocol):
    def verify(
        self,
        source_path: str,
        report_dir: str | None = None,
        extra_args: list[str] | None = None,
        spec_code_mapping: list[dict] | None = None,
        collect_decidable_metrics: bool = False,
    ) -> dict[str, object]:
        ...


def _source_payload(result: AuditResult | AuditDirectoryResult) -> tuple[str, str, str]:
    if isinstance(result, AuditDirectoryResult):
        return result.source_dir, result.language, "directory"
    return result.source_file, result.language, "file"


def _hint_file_result(
    result: AuditResult | AuditDirectoryResult,
    hint: dict[str, object],
    occurrence: int,
) -> AuditResult | None:
    """Return the per-file result for an aggregate hint occurrence.

    Directory aggregation flattens per-file lists in file order. Counting only
    exact function/skeleton matches preserves attribution when several files
    contain the same function name and generated skeleton.
    """
    if not isinstance(result, AuditDirectoryResult):
        return result
    function_name = str(hint.get("function_name") or "")
    skeleton = str(hint.get("skeleton") or "")
    matches: list[AuditResult] = []
    for file_result in result.file_results:
        for candidate in file_result.migration_hints:
            if not isinstance(candidate, dict):
                continue
            if candidate.get("function_name") == function_name and str(candidate.get("skeleton") or "") == skeleton:
                matches.append(file_result)
    if occurrence < len(matches):
        return matches[occurrence]
    return None


def _read_source(path: str) -> str:
    try:
        source = Path(path).expanduser()
        if source.is_file():
            return source.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return ""


def _python_function_source(source: str, function_name: str) -> str:
    if not source:
        return ""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    wanted = function_name.split(".")[-1]
    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == wanted:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno or node.lineno])
    return ""


def _effect_profile(source: str, language: str, function_name: str) -> dict[str, object]:
    function_source = _python_function_source(source, function_name) if language == "python" else ""
    haystack = function_source or source
    effects = sorted(name for name, pattern in _EXTERNAL_EFFECT_PATTERNS.items() if pattern.search(haystack))
    return {
        "external_effects": effects,
        "has_external_effects": bool(effects),
        "analysis": "python-ast-function" if function_source else "textual-heuristic",
    }


def _contract_health(result: AuditResult | AuditDirectoryResult) -> dict[str, object]:
    spec_issues = list(result.spec_health_issues)
    malformed = [item for item in spec_issues if item.startswith("malformed-extraction:")]
    encoding_gaps = [item for item in spec_issues if item.startswith("encoding-gap:")]
    weak_skeletons = [
        hint.get("function_name")
        for hint in result.migration_hints
        if isinstance(hint, dict) and "requires: true" in str(hint.get("skeleton", "")) and "ensures: true" in str(hint.get("skeleton", ""))
    ]
    return {
        "spec_health_issue_count": len(spec_issues),
        "malformed_extraction_count": len(malformed),
        "encoding_gap_count": len(encoding_gaps),
        "weak_skeleton_functions": sorted(str(name) for name in weak_skeletons if name),
    }


def _verification_feasibility(hint: dict[str, object], health: dict[str, object], effects: dict[str, object]) -> tuple[str, list[str]]:
    blockers: list[str] = []
    skeleton = str(hint.get("skeleton", ""))
    if health["malformed_extraction_count"]:
        blockers.append("malformed extraction must be repaired before migration")
    if health["encoding_gap_count"]:
        blockers.append("some extracted clauses could not be encoded")
    if "requires: true" in skeleton and "ensures: true" in skeleton:
        blockers.append("generated skeleton has weak true/true contracts")
    if effects["has_external_effects"]:
        blockers.append("external effects need explicit adapter/effect modeling")
    if not skeleton.strip():
        blockers.append("migration skeleton is empty")
    if not blockers:
        return "high", []
    if health["malformed_extraction_count"] or not skeleton.strip():
        return "blocked", blockers
    return "limited", blockers


def _readiness_level(priority: str, feasibility: str, verification_status: object) -> str:
    if feasibility == "blocked":
        return "not_ready"
    if priority == "high" and feasibility == "high" and verification_status in {"refuted", "unverifiable"}:
        return "ready_for_human_review"
    return "needs_spec_or_effect_refinement"


def _score(priority: str, health: dict[str, object], effects: dict[str, object], feasibility: str) -> int:
    score = _PRIORITY_SCORE.get(priority, 10)
    score += min(int(health["spec_health_issue_count"]), 5) * 3
    score += 12 if not effects["has_external_effects"] else 0
    score += {"high": 20, "limited": 6, "blocked": -30}[feasibility]
    return max(0, min(100, score))


def _redact_report_text(text: str) -> str:
    return _ABSOLUTE_PATH_RE.sub("<path>", redact_secrets(text))


def _redact_known_paths(text: str, sensitive_paths: tuple[Path, ...]) -> str:
    redacted = text
    for path in sorted((str(item) for item in sensitive_paths), key=len, reverse=True):
        if path:
            redacted = redacted.replace(path, "<path>")
    return _redact_report_text(redacted)


def _diagnostic_json(value: object, sensitive_paths: tuple[Path, ...]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return _redact_known_paths(raw, sensitive_paths)[:500]


def _diagnostics(verify_result: dict[str, object], sensitive_paths: tuple[Path, ...] = ()) -> list[str]:
    diagnostics: list[str] = []
    report = verify_result.get("report")
    if isinstance(report, dict):
        for key in ("status", "message", "error", "reason"):
            value = report.get(key)
            if isinstance(value, str) and value.strip():
                diagnostics.append(value.strip())
        for key in ("counterexample", "counter_example"):
            value = report.get(key)
            if value:
                diagnostics.append(f"{key}: {_diagnostic_json(value, sensitive_paths)}")
        atoms = report.get("atoms")
        if isinstance(atoms, list):
            for atom in atoms:
                if not isinstance(atom, dict) or atom.get("status") in {"pass", "passed", "success", "verified"}:
                    continue
                atom_name = atom.get("name") or atom.get("atom") or "unknown"
                reason = atom.get("reason") or atom.get("error") or atom.get("status") or "failed"
                diagnostics.append(f"{atom_name}: {reason}")
                counterexample = atom.get("counterexample") or atom.get("counter_example")
                if counterexample:
                    diagnostics.append(
                        f"{atom_name} counterexample: {_diagnostic_json(counterexample, sensitive_paths)}"
                    )
        feedback = report.get("structured_feedback") or verify_result.get("loss_vector")
        if isinstance(feedback, dict):
            for key in ("failure_type", "message", "summary"):
                value = feedback.get(key)
                if isinstance(value, str) and value.strip():
                    diagnostics.append(value.strip())
    stderr = str(verify_result.get("stderr") or "").strip()
    failed = verify_result.get("success") is not True
    if failed and stderr:
        diagnostics.extend(line for line in stderr.splitlines()[-3:] if line.strip())
    return [_redact_known_paths(item, sensitive_paths) for item in dict.fromkeys(diagnostics)][:8]


def _artifact_directory(output_path: Path) -> Path:
    """Allocate a fresh generated-artifact directory without taking over checkout content."""
    base = output_path.parent / f"{output_path.stem}.migration-readiness"
    marker_name = ".mumei-generated-artifacts"
    for index in range(1000):
        candidate = base if index == 0 else output_path.parent / f"{output_path.stem}.migration-readiness-{index}"
        if candidate.exists() or candidate.is_symlink():
            continue
        try:
            candidate.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue
        try:
            with (candidate / marker_name).open("x", encoding="utf-8") as marker:
                marker.write("generated by mumei-agent migration readiness\n")
        except FileExistsError:
            continue
        return candidate
    raise OSError("could not allocate a migration-readiness artifact directory")


def _verify_critical(
    critical: dict[str, object],
    artifact_dir: Path,
    mumei_client: VerifyClient | None,
) -> dict[str, object]:
    skeleton = str(critical.get("skeleton") or "")
    function_name = str(critical["function_name"])
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", function_name).strip("._-") or "critical_function"
    artifact_stem = safe_name + "-" + hashlib.sha256(skeleton.encode("utf-8")).hexdigest()[:12]
    skeleton_path = artifact_dir / f"{artifact_stem}.mm"
    proof_path = artifact_dir / f"{artifact_stem}.proof.json"
    sarif_path = artifact_dir / f"{artifact_stem}.sarif"
    verify_command = " ".join(
        [
            "mumei verify --json --emit sarif --report-dir",
            shlex.quote(str(artifact_dir)),
            "--proof-cert --output",
            shlex.quote(str(proof_path)),
            shlex.quote(str(skeleton_path)),
        ]
    )
    verification: dict[str, object] = {
        "attempted": False,
        "status": "not_attempted",
        "skeleton_path": str(skeleton_path),
        "proof_certificate_path": str(proof_path),
        "diagnostics": [],
        "verify_command": verify_command,
        "sarif_path": str(sarif_path),
        "next_fix_command": "python -m agent heal " + shlex.quote(str(skeleton_path)),
        "proof_certificate_written": False,
        "sarif_written": False,
    }
    if not skeleton.strip() or mumei_client is None:
        verification["status"] = "unavailable" if mumei_client is None else "not_attempted"
        verification["diagnostics"] = ["migration skeleton or verifier client is unavailable"]
        return verification
    with skeleton_path.open("x", encoding="utf-8") as skeleton_file:
        skeleton_file.write(skeleton + "\n")
    verification["attempted"] = True
    try:
        result = mumei_client.verify(
            str(skeleton_path),
            report_dir=str(artifact_dir),
            extra_args=["--emit", "sarif", "--proof-cert", "--output", str(proof_path)],
        )
    except Exception as exc:  # verifier construction/process failures are operational diagnostics
        verification["status"] = "operational_error"
        verification["diagnostics"] = [type(exc).__name__]
        return verification
    report = result.get("report") if isinstance(result.get("report"), dict) else {}
    verification.update(
        {
            "success": result.get("success") is True,
            "status": report.get("status") or ("verified" if result.get("success") is True else "failed"),
            "diagnostics": _diagnostics(
                result,
                (
                    artifact_dir,
                    skeleton_path,
                    proof_path,
                    artifact_dir.resolve(),
                    skeleton_path.resolve(),
                    proof_path.resolve(),
                ),
            ),
        }
    )
    generated_sarif = artifact_dir / "report.sarif"
    if generated_sarif.exists() and not sarif_path.exists():
        os.rename(generated_sarif, sarif_path)
    verification["proof_certificate_written"] = proof_path.exists()
    verification["sarif_written"] = sarif_path.exists()
    return verification


def build_migration_readiness(
    result: AuditResult | AuditDirectoryResult,
    *,
    output_path: Path,
    mumei_client: VerifyClient | None = None,
    verify_critical: bool = True,
) -> dict[str, object]:
    """Build and write the additive migration-readiness report."""
    source_path, language, source_kind = _source_payload(result)
    source = _read_source(source_path) if source_kind == "file" else ""
    entries: list[dict[str, object]] = []
    hint_occurrences: dict[tuple[str, str], int] = {}
    for hint in result.migration_hints:
        if not isinstance(hint, dict):
            continue
        function_name = str(hint.get("function_name") or "unknown")
        priority = str(hint.get("priority") or "review")
        occurrence_key = (function_name, str(hint.get("skeleton") or ""))
        occurrence = hint_occurrences.get(occurrence_key, 0)
        hint_occurrences[occurrence_key] = occurrence + 1
        file_result = _hint_file_result(result, hint, occurrence)
        hint_source_path = file_result.source_file if file_result is not None else source_path
        hint_language = file_result.language if file_result is not None else language
        health = _contract_health(file_result) if file_result is not None else _contract_health(result)
        entry_source = source if hint_source_path == source_path else _read_source(hint_source_path)
        effects = _effect_profile(entry_source, hint_language, function_name)
        feasibility, blockers = _verification_feasibility(hint, health, effects)
        hint_status = file_result.verification_status if file_result is not None else result.verification_status
        entries.append(
            {
                "function_name": function_name,
                "source_file": hint_source_path,
                "priority": priority,
                "readiness": _readiness_level(priority, feasibility, hint_status),
                "readiness_score": _score(priority, health, effects, feasibility),
                "reason": str(hint.get("reason") or ""),
                "verification_feasibility": feasibility,
                "readiness_blockers": blockers,
                "finding_severity": priority,
                "contract_health": health,
                **effects,
                "skeleton": str(hint.get("skeleton") or ""),
                "next_step": str(hint.get("next_step") or ""),
            }
        )
    entries.sort(key=lambda item: (-int(item["readiness_score"]), str(item["function_name"])))
    for rank, entry in enumerate(entries, start=1):
        entry["rank"] = rank
    critical = entries[0] if entries else None
    artifact_dir = _artifact_directory(output_path)
    critical_report: dict[str, object] | None = None
    if critical is not None:
        critical_report = {
            key: critical[key]
            for key in ("rank", "function_name", "priority", "readiness", "readiness_score", "readiness_blockers", "next_step")
        }
        critical_report["selection_reason"] = "highest readiness_score migration candidate"
        critical_report["verification"] = (
            _verify_critical(critical, artifact_dir, mumei_client)
            if verify_critical
            else {"attempted": False, "status": "disabled", "diagnostics": []}
        )
    report: dict[str, object] = {
        "schema": SCHEMA,
        "source": {"path": source_path, "language": language, "kind": source_kind},
        "audit": {
            "success": result.success,
            "verification_status": result.verification_status,
            "finding_counts": result.finding_counts,
            "migration_candidate_count": len(entries),
        },
        "migration_plan": entries,
        "critical_function": critical_report,
        "artifact_paths": {"migration_readiness": str(output_path), "critical_artifacts": str(artifact_dir)},
        "evidence_boundary": [
            "This report prioritizes human migration review; it is not proof that host-language code implements a .mm contract.",
            "Generated skeletons are migration scaffolds even when mumei verifies their weakened contracts.",
            "External-effect and dependency analysis is heuristic and must be reviewed before migration.",
        ],
    }
    fd, temporary_name = tempfile.mkstemp(prefix=output_path.name + ".", dir=output_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output_file:
            output_file.write(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(temporary_name, output_path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
    return report


def append_next_step_summary(
    result: AuditResult | AuditDirectoryResult,
    report: dict[str, object],
    output_path: Path,
) -> None:
    """Expose migration readiness through the fixed human-review handoff key."""
    critical = report.get("critical_function")
    if isinstance(critical, dict):
        blockers = critical.get("readiness_blockers")
        blocker_text = "; ".join(str(item) for item in blockers) if isinstance(blockers, list) and blockers else "none"
        action = (
            "migration readiness を確認: "
            f"{critical.get('function_name')} ({critical.get('readiness')}, "
            f"score {critical.get('readiness_score')}/100; blockers: {blocker_text}); "
            f"report: {output_path}"
        )
        priority = "high" if critical.get("readiness") == "not_ready" else "medium"
    else:
        action = f"migration readiness を確認: migration candidates なし; report: {output_path}"
        priority = "info"
    step = {
        "priority": priority,
        "action": action,
        "command": "",
        "migration_readiness_report": str(output_path),
    }
    if not any(existing.get("migration_readiness_report") == str(output_path) for existing in result.next_steps):
        result.next_steps.append(step)
