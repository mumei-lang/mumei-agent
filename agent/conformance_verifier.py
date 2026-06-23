"""Structured conformance verification from natural-language specs to code."""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from agent.config import AgentConfig
from agent.cross_validation import (
    CrossValidationIssue,
    MumeiContractAtom,
    SpecCodeAlignmentResult,
    validate_spec_to_code,
)


ConformanceStatus = Literal["implemented", "missing", "violated", "undocumented"]


@dataclass(frozen=True)
class ConformanceFinding:
    condition: str
    source: str
    evidence: str
    implementation_symbol: str = ""
    status: ConformanceStatus = "missing"
    code_line: int = 0
    severity: str = "error"
    fix_suggestion: str = ""


@dataclass(frozen=True)
class TraceabilityRow:
    spec_item_id: str
    spec_condition: str
    implementation_symbol: str
    code_line: int
    status: ConformanceStatus
    evidence: str


@dataclass(frozen=True)
class ConformanceVerificationResult:
    success: bool
    code_path: str
    language: str
    unimplemented_conditions: list[ConformanceFinding]
    hidden_specifications: list[ConformanceFinding]
    traceability_matrix: list[TraceabilityRow]
    verification_violations: list[str]
    cross_validation_gaps: list[str]
    next_steps: list[dict[str, str]]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    report: str = ""


def verify_conformance(
    spec: str,
    code_path: str,
    *,
    config: AgentConfig | None = None,
    language: str | None = None,
    use_llm: bool = True,
    run_mumei: bool = True,
    alignment: SpecCodeAlignmentResult | None = None,
) -> ConformanceVerificationResult:
    config = config or AgentConfig()
    if alignment is None:
        alignment = validate_spec_to_code(
            spec,
            code_path,
            config=config,
            language=language,
            use_llm=use_llm,
            run_mumei=run_mumei,
        )
    code = _read_code(code_path)
    source_lines = _source_line_map(code, alignment.language)
    unimplemented = _unimplemented_conditions(alignment, source_lines)
    hidden = _hidden_specifications(alignment, source_lines)
    matrix = _traceability_matrix(alignment, unimplemented, hidden, source_lines)
    violations = _verification_violations(unimplemented, alignment.divergences)
    gaps = _dedupe_strings(
        [
            *alignment.cross_validation_gaps,
            *violations,
            *[finding.evidence or finding.condition for finding in hidden],
        ]
    )
    next_steps = _next_steps(code_path, bool(unimplemented), bool(hidden), gaps)
    result = ConformanceVerificationResult(
        success=alignment.success and not unimplemented and not hidden,
        code_path=code_path,
        language=alignment.language,
        unimplemented_conditions=unimplemented,
        hidden_specifications=hidden,
        traceability_matrix=matrix,
        verification_violations=violations,
        cross_validation_gaps=gaps,
        next_steps=next_steps,
        warnings=alignment.warnings,
        errors=alignment.errors,
    )
    return replace(result, report=format_conformance_report(result))


def format_conformance_report(result: ConformanceVerificationResult) -> str:
    from agent.report_formatter import format_result_report

    return format_result_report(result, "human")


def _read_code(code_path: str) -> str:
    try:
        return Path(code_path).read_text(encoding="utf-8")
    except OSError:
        return ""


def _unimplemented_conditions(
    alignment: SpecCodeAlignmentResult,
    source_lines: dict[str, int],
) -> list[ConformanceFinding]:
    findings = [
        _finding_from_issue(issue, source_lines, status="missing")
        for issue in alignment.missing_constraint_issues
    ]
    findings.extend(
        _finding_from_issue(issue, source_lines, status="violated")
        for issue in alignment.divergences
        if "does not imply the spec postcondition" in issue.message
    )
    return _dedupe_findings(findings)


def _hidden_specifications(
    alignment: SpecCodeAlignmentResult,
    source_lines: dict[str, int],
) -> list[ConformanceFinding]:
    findings: list[ConformanceFinding] = []
    for issue in alignment.divergences:
        if "not covered by the specification" not in issue.message:
            continue
        findings.append(_finding_from_issue(issue, source_lines, status="undocumented"))
    findings.extend(_hidden_contracts_from_atoms(alignment, source_lines))
    return _dedupe_findings(findings)


def _hidden_contracts_from_atoms(
    alignment: SpecCodeAlignmentResult,
    source_lines: dict[str, int],
) -> list[ConformanceFinding]:
    findings: list[ConformanceFinding] = []
    for code_atom in alignment.code_atoms:
        spec_atom = _matched_spec_atom(code_atom, alignment.spec_atoms)
        if spec_atom is None:
            findings.append(
                ConformanceFinding(
                    condition=f"{code_atom.requires}; {code_atom.ensures}",
                    source="implementation",
                    evidence="code atom has no matching spec atom",
                    implementation_symbol=code_atom.name,
                    status="undocumented",
                    code_line=source_lines.get(code_atom.name, 0),
                    severity="warning",
                )
            )
            continue
        if _is_hidden_precondition(spec_atom.requires, code_atom.requires):
            findings.append(
                ConformanceFinding(
                    condition=code_atom.requires,
                    source="implementation",
                    evidence=(
                        f"spec requires: {spec_atom.requires}; "
                        f"code requires: {code_atom.requires}"
                    ),
                    implementation_symbol=code_atom.name,
                    status="undocumented",
                    code_line=source_lines.get(code_atom.name, 0),
                    severity="warning",
                )
            )
    return findings


def _matched_spec_atom(
    code_atom: MumeiContractAtom,
    spec_atoms: list[MumeiContractAtom],
) -> MumeiContractAtom | None:
    for spec_atom in spec_atoms:
        if spec_atom.name == code_atom.name:
            return spec_atom
    if len(spec_atoms) == 1:
        return spec_atoms[0]
    return None


def _is_hidden_precondition(spec_requires: str, code_requires: str) -> bool:
    spec_text = spec_requires.strip().lower()
    code_text = code_requires.strip().lower()
    if code_text in {"", "true"}:
        return False
    if spec_text in {"", "true"}:
        return True
    return code_text != spec_text and code_text not in spec_text


def _finding_from_issue(
    issue: CrossValidationIssue,
    source_lines: dict[str, int],
    *,
    status: ConformanceStatus,
) -> ConformanceFinding:
    symbol = issue.location
    return ConformanceFinding(
        condition=_condition_from_issue(issue),
        source="implementation" if status == "undocumented" else "natural_language_spec",
        evidence=issue.evidence,
        implementation_symbol=symbol,
        status=status,
        code_line=issue.source_line or source_lines.get(symbol, 0),
        severity=issue.severity,
        fix_suggestion=issue.fix_suggestion,
    )


def _condition_from_issue(issue: CrossValidationIssue) -> str:
    for label in ("spec requires:", "spec ensures:", "code requires:", "code ensures:"):
        if label in issue.evidence:
            return issue.evidence.split(label, 1)[1].split(";", 1)[0].strip()
    return issue.evidence or issue.message


def _traceability_matrix(
    alignment: SpecCodeAlignmentResult,
    unimplemented: list[ConformanceFinding],
    hidden: list[ConformanceFinding],
    source_lines: dict[str, int],
) -> list[TraceabilityRow]:
    rows: list[TraceabilityRow] = []
    issue_symbols = {finding.implementation_symbol for finding in unimplemented}
    for index, atom in enumerate(alignment.spec_atoms, start=1):
        symbol = _matched_symbol(atom, alignment.code_atoms)
        status: ConformanceStatus = "missing" if symbol in issue_symbols else "implemented"
        rows.extend(_rows_for_atom(index, atom, symbol, source_lines.get(symbol, 0), status))
    for finding in hidden:
        rows.append(
            TraceabilityRow(
                spec_item_id=f"impl-{finding.implementation_symbol}",
                spec_condition=finding.condition,
                implementation_symbol=finding.implementation_symbol,
                code_line=finding.code_line,
                status="undocumented",
                evidence=finding.evidence,
            )
        )
    return rows


def _rows_for_atom(
    index: int,
    atom: MumeiContractAtom,
    symbol: str,
    code_line: int,
    status: ConformanceStatus,
) -> list[TraceabilityRow]:
    rows: list[TraceabilityRow] = []
    for clause_name, clause in (("requires", atom.requires), ("ensures", atom.ensures)):
        rows.append(
            TraceabilityRow(
                spec_item_id=f"spec-{index}-{clause_name}",
                spec_condition=clause,
                implementation_symbol=symbol,
                code_line=code_line,
                status=status,
                evidence=f"{atom.name}.{clause_name}",
            )
        )
    return rows


def _matched_symbol(atom: MumeiContractAtom, code_atoms: list[MumeiContractAtom]) -> str:
    if any(code_atom.name == atom.name for code_atom in code_atoms):
        return atom.name
    if len(code_atoms) == 1:
        return code_atoms[0].name
    return atom.name


def _verification_violations(
    unimplemented: list[ConformanceFinding],
    divergences: list[CrossValidationIssue],
) -> list[str]:
    return _dedupe_strings(
        [
            *[finding.evidence or finding.condition for finding in unimplemented],
            *[
                issue.evidence or issue.message
                for issue in divergences
                if issue.severity == "error"
            ],
        ]
    )


def _next_steps(
    code_path: str,
    has_unimplemented: bool,
    has_hidden: bool,
    gaps: list[str],
) -> list[dict[str, str]]:
    if not gaps:
        return []
    steps: list[dict[str, str]] = []
    if has_unimplemented:
        steps.append(
            {
                "priority": "high",
                "action": "Review missing implementation conditions.",
                "command": f"mumei-agent validate-spec-to-code --spec <spec> --code {code_path}",
            }
        )
    if has_hidden:
        steps.append(
            {
                "priority": "medium",
                "action": "Review hidden implementation behavior before updating the spec.",
                "command": f"mumei-agent validate-code-to-spec --code {code_path} --spec <spec>",
            }
        )
    return steps


def _source_line_map(code: str, language: str) -> dict[str, int]:
    if language == "python":
        return _python_source_line_map(code)
    if language == "rust":
        return _regex_source_line_map(code, r"(?:pub\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)")
    if language == "go":
        return _regex_source_line_map(code, r"func\s+([A-Za-z_][A-Za-z0-9_]*)")
    return {}


def _python_source_line_map(code: str) -> dict[str, int]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {}
    line_map: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            line_map[node.name] = node.lineno
    return line_map


def _regex_source_line_map(code: str, pattern: str) -> dict[str, int]:
    line_map: dict[str, int] = {}
    for match in re.finditer(pattern, code):
        line_map[match.group(1)] = code[: match.start(1)].count("\n") + 1
    return line_map


def _dedupe_findings(findings: list[ConformanceFinding]) -> list[ConformanceFinding]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[ConformanceFinding] = []
    for finding in findings:
        key = (finding.condition, finding.implementation_symbol, finding.status)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return deduped


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        stripped = value.strip()
        if stripped and stripped not in deduped:
            deduped.append(stripped)
    return deduped
