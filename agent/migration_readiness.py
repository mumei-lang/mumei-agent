"""Build migration-readiness reports from audit migration hints."""
from __future__ import annotations

import ast
import json
import re
import shlex
from pathlib import Path
from typing import Protocol

from agent.audit_models import AuditDirectoryResult, AuditResult
from agent.secret_redaction import redact_secrets

SCHEMA = "mumei.migration-readiness/v1"
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


def _hint_source(result: AuditResult | AuditDirectoryResult, hint: dict[str, object], default_source: str) -> str:
    if not isinstance(result, AuditDirectoryResult):
        return default_source
    function_name = str(hint.get("function_name") or "")
    skeleton = str(hint.get("skeleton") or "")
    for file_result in result.file_results:
        for candidate in file_result.migration_hints:
            if not isinstance(candidate, dict):
                continue
            if candidate.get("function_name") == function_name and str(candidate.get("skeleton") or "") == skeleton:
                return file_result.source_file
    return default_source


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


def _diagnostics(verify_result: dict[str, object]) -> list[str]:
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
                diagnostics.append(f"{key}: {json.dumps(value, ensure_ascii=False, sort_keys=True)[:500]}")
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
                        f"{atom_name} counterexample: {json.dumps(counterexample, ensure_ascii=False, sort_keys=True)[:500]}"
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
    return [redact_secrets(item) for item in dict.fromkeys(diagnostics)][:8]


def _verify_critical(
    critical: dict[str, object],
    artifact_dir: Path,
    mumei_client: VerifyClient | None,
) -> dict[str, object]:
    skeleton = str(critical.get("skeleton") or "")
    function_name = str(critical["function_name"])
    artifact_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", function_name).strip("._-") or "critical_function"
    skeleton_path = artifact_dir / f"{artifact_stem}.mm"
    proof_path = artifact_dir / f"{artifact_stem}.proof.json"
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
        "sarif_path": str(artifact_dir / "report.sarif"),
        "next_fix_command": "python -m agent heal " + shlex.quote(str(skeleton_path)),
        "proof_certificate_written": False,
        "sarif_written": False,
    }
    if not skeleton.strip() or mumei_client is None:
        verification["status"] = "unavailable" if mumei_client is None else "not_attempted"
        verification["diagnostics"] = ["migration skeleton or verifier client is unavailable"]
        return verification
    skeleton_path.write_text(skeleton + "\n", encoding="utf-8")
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
            "diagnostics": _diagnostics(result),
        }
    )
    verification["proof_certificate_written"] = proof_path.exists()
    verification["sarif_written"] = (artifact_dir / "report.sarif").exists()
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
    health = _contract_health(result)
    entries: list[dict[str, object]] = []
    for hint in result.migration_hints:
        if not isinstance(hint, dict):
            continue
        function_name = str(hint.get("function_name") or "unknown")
        priority = str(hint.get("priority") or "review")
        hint_source_path = _hint_source(result, hint, source_path)
        entry_source = source if hint_source_path == source_path else _read_source(hint_source_path)
        effects = _effect_profile(entry_source, language, function_name)
        feasibility, blockers = _verification_feasibility(hint, health, effects)
        entries.append(
            {
                "function_name": function_name,
                "source_file": hint_source_path,
                "priority": priority,
                "readiness": _readiness_level(priority, feasibility, result.verification_status),
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
    artifact_dir = output_path.parent / f"{output_path.stem}.migration-readiness"
    artifact_dir.mkdir(parents=True, exist_ok=True)
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
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
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
