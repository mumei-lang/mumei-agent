"""Reporting and result-shaping helpers for cross-validation."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Literal

from agent.intent_tracker import IntentChange
from agent.cross_validation_models import (
    ContradictionType,
    CrossValidationIssue,
    CrossValidationReport,
    CrossValidationResult,
    ForeignCodeValidationResult,
    IssueKind,
    MumeiContractAtom,
    NLSpecValidationResult,
    SpecCodeAlignmentResult,
    SpecDriftResult,
)
from agent.cross_validation_foreign import (
    _dedupe_strings,
    _issue_function_from_text,
    _normalize_foreign_language,
)

def _read_input_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Error: failed to read input file: {exc}", file=sys.stderr)
        sys.exit(2)

def _emit_result(result: CrossValidationResult, output: str | None) -> None:
    payload = json.dumps(asdict(result), indent=2, ensure_ascii=False)
    if output:
        Path(output).write_text(payload + "\n", encoding="utf-8")
    print(payload)

def _emit_validate_spec_result(
    result: NLSpecValidationResult,
    output: str | None,
    output_format: str,
) -> None:
    if output_format == "markdown":
        report = _format_validate_spec_markdown(result)
        if output:
            Path(output).write_text(report + "\n", encoding="utf-8")
        print(report)
        return
    if output_format == "human":
        from agent.report_formatter import format_cross_validation_report

        report = format_cross_validation_report(result)
        if output:
            Path(output).write_text(report + "\n", encoding="utf-8")
        print(report)
        return
    _emit_result(result, output)

def _emit_cross_validation_result(
    result: SpecCodeAlignmentResult | SpecDriftResult,
    output: str | None,
    *,
    output_format: str = "markdown",
    lang: Literal["auto", "en", "ja"] = "auto",
) -> None:
    if output_format == "json":
        _emit_result(result, output)
        return
    from agent.report_formatter import format_cross_validation_report

    report = format_cross_validation_report(result, lang=lang, output_format=output_format)
    if output:
        Path(output).write_text(report + "\n", encoding="utf-8")
    print(report)

def _matching_code_atom(
    spec_atom: MumeiContractAtom,
    code_atoms: list[MumeiContractAtom],
) -> MumeiContractAtom | None:
    for code_atom in code_atoms:
        if code_atom.name == spec_atom.name:
            return code_atom
    if spec_atom.name == "nl_spec_contract" and code_atoms:
        return code_atoms[0]
    if len(code_atoms) == 1:
        return code_atoms[0]
    return None

def _suggest_fix(
    kind: IssueKind,
    message: str,
    evidence: str,
    *,
    code: str = "",
    language: str = "",
    source_line: int = 0,
    location: str = "",
) -> str:
    """Generate a concrete remediation hint for a validation issue."""
    evidence_text = evidence.strip()
    message_text = message.strip()
    if kind == "contradiction":
        if "/" in evidence_text:
            left, right = (part.strip() for part in evidence_text.split("/", 1))
            return (
                "Choose the intended constraint and relax or delete the opposing one: "
                f"`{left}` conflicts with `{right}`."
            )
        if "requires:" in evidence_text and "ensures:" in evidence_text:
            return (
                "Z3 found the listed requires/ensures combination inconsistent; "
                "weaken the stricter precondition or loosen the postcondition so one "
                f"reachable value can satisfy both. Constraints: `{evidence_text}`."
            )
        return (
            "Remove one side of the mutually exclusive requirement, or rewrite it as an "
            f"explicit priority/exception rule. Evidence: `{evidence_text or message_text}`."
        )
    if kind == "ambiguity":
        ambiguous = f"`{evidence_text}`" if evidence_text else "the ambiguous phrase"
        return (
            f"Replace {ambiguous} with a concrete type, enum, threshold, or numeric range "
            "(for example `0 <= x <= limit` instead of vague wording)."
        )
    if kind == "overconstraint":
        if "requires:" in evidence_text or ".requires" in message_text:
            return (
                "Weaken the `requires` clause by removing the unreachable bound, splitting "
                "it into narrower cases, or changing an impossible conjunction to an "
                f"alternative. Constraint: `{evidence_text}`."
            )
        if "ensures:" in evidence_text or ".ensures" in message_text:
            return (
                "Loosen the `ensures` clause to the property callers actually need, or "
                f"move implementation-specific details into a separate lemma. Constraint: `{evidence_text}`."
            )
        return (
            "Relax the over-specific requirement, especially unused `requires`, invariants, "
            f"or effect constraints, until the spec describes only necessary behavior. Evidence: `{evidence_text}`."
        )
    if kind == "satisfiability":
        return (
            "Z3 reported this constraint set as unsatisfiable; inspect the listed clauses "
            "as the conflicting set and relax or split at least one constraint: "
            f"`{evidence_text or message_text}`."
        )
    if kind == "verification":
        suggestion = _suggest_verification_fix(message_text, evidence_text)
        diff = _verification_diff_hint(
            message_text,
            evidence_text,
            code=code,
            language=language,
            source_line=source_line,
            location=location,
        )
        return f"{suggestion}\n\n{diff}" if diff else suggestion
    return (
        "Review the finding and update the spec or implementation so the reported "
        f"constraint is explicit and verifiable. Evidence: `{evidence_text or message_text}`."
    )

def _has_stem(text: str, stem: str) -> bool:
    """Left-boundary stem match: ``divid`` hits ``divisor``/``dividing`` but
    not ``individual``."""
    return bool(re.search(rf"(?<!\w){re.escape(stem)}", text))


def _has_word(text: str, word: str) -> bool:
    """Whole-word match: ``nil`` hits a bare ``nil`` but not ``vanilla``."""
    return bool(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text))


def _verification_kind_tag(text: str) -> str:
    """Route a verification violation to its template tag. Order matters:
    more specific structural findings precede the generic satisfiability and
    amount buckets."""
    if _has_stem(text, "reentr") or "checks-effects-interactions" in text:
        return "reentrancy"
    if (
        "access-control" in text
        or "access control" in text
        or _has_stem(text, "permissionless")
        or _has_stem(text, "unauthorized")
    ):
        return "access-control"
    if _has_stem(text, "divid") or _has_stem(text, "division") or "by zero" in text:
        return "division"
    # Contract-level satisfiability failures outrank the null/balance keyword
    # buckets: serialized verify evidence often contains bare `None`/`null`
    # fields that would otherwise route an unsat finding to the null template.
    if (
        _has_stem(text, "unsatisfi")
        or _has_word(text, "inconsistent")
        or _has_stem(text, "unsat")
    ):
        return "unsatisfiable"
    if _has_stem(text, "overflow") or _has_stem(text, "underflow"):
        return "overflow"
    if (
        _has_stem(text, "index")
        or _has_stem(text, "bounds")
        or "out of range" in text
    ):
        return "bounds"
    if (
        "non-null" in text
        or "non-nil" in text
        or _has_word(text, "null")
        or _has_word(text, "nil")
        or _has_word(text, "undefined")
        or _has_word(text, "none")
    ):
        return "null-safety"
    if (
        _has_stem(text, "negative")
        or _has_stem(text, "balance")
        or _has_stem(text, "amount")
    ):
        return "amount"
    return "generic"


_VERIFICATION_FIX_TEXT = {
    "reentrancy": (
        "Apply checks-effects-interactions (move state writes before "
        "external calls) or add a reentrancy guard such as `nonReentrant`."
    ),
    "access-control": (
        "Gate the state-mutating entry point with an access-control check "
        "(`onlyOwner`-style modifier or `require(msg.sender == ...)`), or "
        "document the function as intentionally permissionless."
    ),
    "division": (
        "Add a non-zero-divisor contract (e.g. `requires: divisor != 0;`) "
        "or guard the division site."
    ),
    "unsatisfiable": (
        "The inferred contract is unsatisfiable or inconsistent; relax the "
        "conflicting requires/ensures clauses or split them into narrower "
        "cases."
    ),
    "overflow": (
        "Constrain the operands so the arithmetic cannot wrap "
        "(e.g. `requires: a <= max_value - b;`) or use a checked/widening type."
    ),
    "bounds": (
        "Add a bounds contract or guard before the indexing expression "
        "(e.g. `requires: 0 <= index && index < len(values);`)."
    ),
    "null-safety": (
        "Add a non-null/non-nil precondition (e.g. `requires: value != null;`) "
        "before dereferencing the value."
    ),
    "amount": (
        "Add a `requires` clause keeping amounts positive and balances "
        "sufficient (e.g. `requires: amount > 0 && balance >= amount;`) "
        "before the state update."
    ),
}


def _suggest_verification_fix(message: str, evidence: str) -> str:
    """Template-based per-violation fix hint for ``validate-code`` findings.

    Cheap keyword heuristics over the violation text; the suggestion is advice
    only — nothing is auto-applied.
    """
    tag = _verification_kind_tag(f"{message} {evidence}".lower())
    template = _VERIFICATION_FIX_TEXT.get(tag)
    if template is None:
        return (
            "Add a `requires` clause or an explicit guard so the reported path "
            "cannot violate the contract, or explain why the path is unreachable. "
            f"Evidence: `{(evidence or message)[:200]}`."
        )
    if tag == "unsatisfiable":
        return template + f" Evidence: `{(evidence or message)[:200]}`."
    return template


_UINT64_MAX = "18446744073709551615"
_INT64_MAX = "9223372036854775807"
_UINT256_MAX = (
    "115792089237316195423570985008687907853269984665640564039457584007913129639935"
)

_CONTRACT_COMMENT_PREFIX = {
    "python": "#",
    "rust": "//",
    "typescript": "//",
    "go": "//",
    "solidity": "//",
}

_BACKTICK_EXPR_RE = re.compile(r"`(?P<expr>[^`]+)`")


def _verification_condition(
    tag: str, message: str, language: str
) -> str | None:
    """Extract a concrete contract condition for the violation, when the
    offending expression is named in the message."""
    if tag == "bounds":
        indexed = re.search(
            r"`(?P<container>[A-Za-z_]\w*(?:\.\w+)*)\s*\[\s*(?P<index>[^\]]+)\]`",
            message,
        )
        if not indexed:
            return None
        container = indexed.group("container")
        index = indexed.group("index").strip()
        length = (
            f"{container}.length"
            if language in {"typescript", "solidity"}
            else (f"{container}.len()" if language == "rust" else f"len({container})")
        )
        return f"0 <= {index} && {index} < {length}"
    if tag == "division":
        divided = re.search(r"divide by `?(?P<divisor>[A-Za-z_]\w*)`?", message)
        if not divided:
            return None
        return f"{divided.group('divisor')} != 0"
    if tag == "overflow":
        overflowed = re.search(
            r"overflow `?(?P<left>[A-Za-z_]\w*)\s*\+\s*(?P<right>[A-Za-z_]\w*)`?",
            message,
        )
        if not overflowed:
            return None
        bound = _UINT256_MAX if language == "solidity" else _INT64_MAX
        left, right = overflowed.group("left"), overflowed.group("right")
        return f"{left} + {right} <= {bound}"
    if tag == "null-safety":
        deref = re.search(r"dereference `?(?P<value>[A-Za-z_]\w*(?:\.\w+)*)`?", message)
        if not deref:
            return None
        value = deref.group("value")
        if language == "python":
            return f"{value} is not None"
        if language == "go":
            return f"{value} != nil"
        if language == "typescript":
            return f"{value} != null && {value} != undefined"
        return f"{value} != null"
    return None


def _verification_diff_hint(
    message: str,
    evidence: str,
    *,
    code: str,
    language: str,
    source_line: int,
    location: str,
) -> str | None:
    """Render a concrete ``+``-line diff hint anchored at the violating
    function. Returns ``None`` when no concrete anchor/condition is derivable;
    callers fall back to the plain text hint."""
    if not code or not source_line:
        return None
    lines = code.splitlines()
    if not (0 < source_line <= len(lines)):
        return None
    signature = lines[source_line - 1]
    indent = signature[: len(signature) - len(signature.lstrip())]
    body_indent = indent + "    "
    tag = _verification_kind_tag(f"{message} {evidence}".lower())
    anchor = location or "the flagged function"

    if language == "solidity" and tag == "access-control":
        if signature.rstrip().endswith("{"):
            return (
                f"Suggested diff for `{anchor}` (line {source_line}):\n"
                "```diff\n"
                f"  {signature}\n"
                f"+ {body_indent}require(msg.sender == owner, \"unauthorized\");\n"
                "```"
            )
        return None
    if language == "solidity" and tag == "reentrancy":
        match = re.match(r"(?P<head>.*?)(?P<tail>\{|\breturns\b)", signature)
        if match:
            head, tail = match.group("head"), match.group("tail")
            new_signature = f"{head}nonReentrant {tail}{signature[match.end('tail'):]}"
            return (
                f"Suggested diff for `{anchor}` (line {source_line}):\n"
                "```diff\n"
                f"- {signature}\n"
                f"+ {new_signature}\n"
                "```"
            )
        return None

    condition = _verification_condition(tag, message, language)
    if condition is None:
        return None
    comment = _CONTRACT_COMMENT_PREFIX.get(language, "//")
    return (
        f"Suggested diff for `{anchor}` (line {source_line}):\n"
        "```diff\n"
        f"+ {indent}{comment} requires: {condition}\n"
        f"  {signature}\n"
        "```"
    )

def _format_validate_spec_markdown(result: NLSpecValidationResult) -> str:
    issues = [
        *result.contradictions,
        *result.ambiguities,
        *result.overconstraints,
    ]
    lines = [
        "## Natural-Language Spec Validation Report",
        "",
        f"- Status: **{'Passed' if result.success else 'Needs review'}**",
        f"- Inferred atoms: `{len(result.inferred_atoms)}`",
        f"- Satisfiable: `{result.satisfiable}`",
        f"- contradiction_type: `{result.contradiction_type}`",
        "",
        "| kind | severity | location | message | evidence | fix_suggestion |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    if issues:
        for issue in issues:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _markdown_cell(issue.kind),
                        _markdown_cell(issue.severity),
                        _markdown_cell(issue.location or "-"),
                        _markdown_cell(issue.message),
                        _markdown_cell(issue.evidence or "-"),
                        _markdown_cell(
                            issue.fix_suggestion
                            or _suggest_fix(issue.kind, issue.message, issue.evidence)
                        ),
                    ]
                )
                + " |"
            )
    else:
        lines.append("| - | - | - | No contradictions, ambiguities, or overconstraints detected. | - | - |")

    warnings = [
        *result.completeness_warnings,
        *result.vacuity_warnings,
        *result.warnings,
        *[f"ERROR: {error}" for error in result.errors],
    ]
    if warnings:
        lines.extend(["", "### Warnings"])
        lines.extend(f"- {warning}" for warning in warnings[:10])
    return "\n".join(lines)

def _markdown_cell(value: object) -> str:
    text = str(value).strip().replace("\n", "<br>")
    text = text.replace("|", "\\|")
    return text or "-"

def _atoms_to_spec_payload(atoms: list[MumeiContractAtom]) -> dict[str, object]:
    return {
        "atoms": [
            {
                "name": atom.name,
                "params": [asdict(param) for param in atom.params],
                "return_type": atom.return_type,
                "requires": atom.requires,
                "ensures": atom.ensures,
                "effects": atom.effects,
            }
            for atom in atoms
        ],
    }

def _intent_payloads(
    spec_atoms: list[MumeiContractAtom],
    code_atoms: list[MumeiContractAtom],
) -> tuple[dict[str, object], dict[str, object]]:
    aligned_code_atoms: list[MumeiContractAtom] = []
    used_code_names: set[str] = set()
    for spec_atom in spec_atoms:
        code_atom = _matching_code_atom(
            spec_atom,
            [atom for atom in code_atoms if atom.name not in used_code_names],
        )
        if code_atom is None:
            continue
        used_code_names.add(code_atom.name)
        aligned_code_atoms.append(replace(code_atom, name=spec_atom.name))
    aligned_code_atoms.extend(
        atom for atom in code_atoms if atom.name not in used_code_names
    )
    return _atoms_to_spec_payload(spec_atoms), _atoms_to_spec_payload(aligned_code_atoms)

def _format_intent_drift_report(
    result: CrossValidationReport,
    *,
    lang: Literal["auto", "en", "ja"],
) -> str:
    if lang == "ja":
        lines = [
            "## 仕様↔コード クロス検証レポート",
            "",
            f"- Status: **{'合格' if result.success else '要確認'}**",
            f"- Drift detected: `{str(result.drift_detected).lower()}`",
            f"- Mapping count: `{len(result.mapping.mappings)}`",
            f"- Intent drift score: `{result.intent_drift.drift_score:.2f}`",
            "",
            "### 検出事項",
        ]
        if result.issues:
            lines.extend(_issue_lines_for_integrated_report(result.issues))
        else:
            lines.append("- 仕様ドリフトは検出されませんでした。")
        lines.append("")
        lines.append("### Human-in-the-Loop 確認事項")
        lines.append("- drift / contradiction / overconstraint がある場合は PR マージ前に確認してください。")
        return "\n".join(lines)

    lines = [
        "## Spec↔Code Cross-Validation Report",
        "",
        f"- Status: **{'Passed' if result.success else 'Needs review'}**",
        f"- Drift detected: `{str(result.drift_detected).lower()}`",
        f"- Mapping count: `{len(result.mapping.mappings)}`",
        f"- Intent drift score: `{result.intent_drift.drift_score:.2f}`",
        "",
        "### Findings",
    ]
    if result.issues:
        lines.extend(_issue_lines_for_integrated_report(result.issues))
    else:
        lines.append("- No semantic drift detected.")
    lines.append("")
    lines.append("### Reviewer action")
    lines.append("- Review any drift, contradiction, or overconstraint before merging.")
    return "\n".join(lines)

def _issue_lines_for_integrated_report(issues: list[CrossValidationIssue]) -> list[str]:
    lines: list[str] = []
    for index, issue in enumerate(issues, start=1):
        location = f" (`{issue.location}`)" if issue.location else ""
        lines.append(f"{index}. **{issue.kind}**{location}: {issue.message}")
        if issue.evidence:
            lines.append(f"   - Evidence: `{issue.evidence}`")
    return lines

def _upstream_validation_issues(
    spec_result: NLSpecValidationResult,
    code_result: ForeignCodeValidationResult,
) -> list[CrossValidationIssue]:
    issues: list[CrossValidationIssue] = []
    for issue in [
        *spec_result.contradictions,
        *spec_result.ambiguities,
        *spec_result.overconstraints,
    ]:
        issues.append(
            CrossValidationIssue(
                kind="alignment",
                message=f"Spec validation issue: {issue.message}",
                evidence=issue.evidence,
                fix_suggestion=issue.fix_suggestion,
                location=issue.location,
                severity=issue.severity,
            )
        )
    for issue in code_result.issues:
        issues.append(
            CrossValidationIssue(
                kind="alignment",
                message=f"Code contract validation issue: {issue.message}",
                evidence=issue.evidence,
                fix_suggestion=issue.fix_suggestion,
                location=issue.location,
                severity=issue.severity,
                source_line=issue.source_line,
            )
        )
    return issues

def _is_upstream_alignment_issue(issue: CrossValidationIssue) -> bool:
    return issue.message.startswith(("Spec validation issue:", "Code contract validation issue:"))

def _with_spec_code_source_lines(
    issues: list[CrossValidationIssue],
    source_line_map: dict[str, int],
    constraint_to_line: dict[str, int],
) -> list[CrossValidationIssue]:
    enriched: list[CrossValidationIssue] = []
    fallback_line = next(iter(source_line_map.values()), 0)
    for issue in issues:
        constraint = _spec_constraint_from_issue(issue)
        system_source_line = (
            constraint_to_line.get(constraint, 0)
            or source_line_map.get(issue.location, 0)
            or source_line_map.get(_issue_function_from_text(issue.message), 0)
            or fallback_line
        )
        enriched.append(replace(issue, source_line=system_source_line))
    return enriched

def _constraint_violations_from_issues(
    issues: list[CrossValidationIssue],
    code: str,
    code_path: str,
    constraint_to_line: dict[str, int],
) -> list[dict[str, object]]:
    violations: list[dict[str, object]] = []
    seen: set[tuple[str, int, str]] = set()
    for issue in issues:
        contradiction_type = _spec_code_contradiction_type(issue)
        if contradiction_type in {"impl_stronger", "spec_internal", "code_internal"}:
            continue
        spec_constraint = _spec_constraint_from_issue(issue)
        if not spec_constraint:
            continue
        code_line = issue.source_line or constraint_to_line.get(spec_constraint, 0)
        key = (spec_constraint, code_line, contradiction_type)
        if key in seen:
            continue
        seen.add(key)
        violations.append(
            {
                "spec_constraint": spec_constraint,
                "code_path": code_path,
                "code_line": code_line,
                "code_snippet": _code_snippet_for_line(code, code_line),
                "contradiction_type": contradiction_type,
                "fix_suggestion": issue.fix_suggestion
                or _suggest_fix(issue.kind, issue.message, issue.evidence),
            }
        )
    return violations

def _missing_constraint_texts(issues: list[CrossValidationIssue]) -> list[str]:
    constraints: list[str] = []
    seen: set[str] = set()
    for issue in issues:
        constraint = _spec_constraint_from_issue(issue)
        if constraint and constraint not in seen:
            seen.add(constraint)
            constraints.append(constraint)
    return constraints

def _code_to_spec_gap_strings(issues: list[CrossValidationIssue]) -> list[str]:
    gaps: list[str] = []
    for issue in issues:
        if "not documented in the spec" in issue.message:
            gaps.append(issue.evidence)
        elif "not covered by the specification" in issue.message:
            gaps.append(issue.message)
        elif issue.kind == "drift":
            gaps.append(issue.evidence or issue.message)
    return _dedupe_strings(gaps)

def _cross_validation_gap_strings(issues: list[CrossValidationIssue]) -> list[str]:
    return _dedupe_strings(
        [issue.evidence or issue.message for issue in issues if issue.severity == "error"]
    )

def _implementation_overage_strings(issues: list[CrossValidationIssue]) -> list[str]:
    overages: list[str] = []
    for issue in issues:
        if "not covered by the specification" in issue.message:
            overages.append(issue.evidence or issue.message)
    return _dedupe_strings(overages)

def _intent_gap_strings(changes: list[IntentChange]) -> list[str]:
    return _dedupe_strings(
        [
            f"{change.field}: {change.original} -> {change.refined}"
            for change in changes
            if change.intent_impact == "violated"
        ]
    )

def _atoms_to_summary(atoms: list[MumeiContractAtom]) -> str:
    return "\n".join(
        f"{atom.name}: requires {atom.requires}; ensures {atom.ensures}."
        for atom in atoms
    )

def _intent_payloads_for_atoms(
    spec_atoms: list[MumeiContractAtom],
    code_atoms: list[MumeiContractAtom],
) -> tuple[dict[str, object], dict[str, object]]:
    if len(spec_atoms) == 1 and len(code_atoms) == 1:
        return (
            _atoms_to_spec_payload(spec_atoms),
            _atoms_to_spec_payload([replace(code_atoms[0], name=spec_atoms[0].name)]),
        )
    return _atoms_to_spec_payload(spec_atoms), _atoms_to_spec_payload(code_atoms)

def _generate_cross_validation_next_steps(
    command_name: str,
    *,
    code_path: str,
    spec_path: str,
    gaps: list[str],
) -> list[dict[str, str]]:
    if not gaps:
        return []
    if command_name == "validate-code-to-spec":
        action = "Update the natural-language spec or justify the extra implementation."
        command = (
            f"mumei-agent validate-code-to-spec --code {code_path} "
            f"--spec {spec_path} --format human"
        )
    else:
        action = "Update the implementation or refine the natural-language spec."
        command = (
            f"mumei-agent validate-spec-to-code --spec {spec_path} "
            f"--code {code_path} --format human"
        )
    return [
        {
            "priority": "high",
            "action": action,
            "command": command,
        }
    ]

def _extra_behavior_texts(issues: list[CrossValidationIssue]) -> list[str]:
    extras: list[str] = []
    for issue in issues:
        if _spec_code_contradiction_type(issue) != "impl_stronger":
            continue
        behavior = issue.evidence.strip() or issue.message.strip()
        if issue.location:
            behavior = f"{issue.location}: {behavior}"
        if behavior not in extras:
            extras.append(behavior)
    return extras

def _spec_constraint_from_issue(issue: CrossValidationIssue) -> str:
    evidence = issue.evidence.strip()
    for label in ("spec requires", "spec ensures"):
        match = re.search(rf"{label}:\s*(.*?)(?:;\s*code\s+\w+:|$)", evidence)
        if match:
            constraint = match.group(1).strip()
            if constraint:
                return constraint
    if issue.message.startswith("Spec validation issue:") and evidence:
        return evidence
    if evidence and not evidence.startswith("code "):
        return evidence
    return issue.message.strip()

def _spec_code_contradiction_type(issue: CrossValidationIssue) -> str:
    message = issue.message
    if message.startswith("Spec validation issue:"):
        return "spec_internal"
    if message.startswith("Code contract validation issue:"):
        return "code_internal"
    if message.startswith("Code atom ") and "not covered by the specification" in message:
        return "impl_stronger"
    if "does not imply the spec postcondition" in message:
        return "postcondition_violated"
    if issue.kind == "missing_implementation":
        return "spec_stronger"
    return "spec_vs_code"

def _code_snippet_for_line(code: str, line: int) -> str:
    if line <= 0:
        return ""
    lines = code.splitlines()
    if line > len(lines):
        return ""
    return lines[line - 1].strip()

def _infer_language_from_path(path: Path, language: str | None) -> str:
    if language:
        return _normalize_foreign_language(language)
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix == ".rs":
        return "rust"
    if suffix in {".ts", ".tsx", ".js", ".jsx"}:
        return "typescript"
    if suffix == ".go":
        return "go"
    return "python"

def _git_diff_hunks(code_path: Path) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    try:
        root_result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=code_path.parent,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], [f"git diff skipped: {exc}"]
    if root_result.returncode != 0:
        return [], ["git diff skipped: code path is not inside a git repository."]
    root = Path(root_result.stdout.strip())
    try:
        relative = code_path.resolve().relative_to(root.resolve())
    except ValueError:
        relative = code_path
    diff_commands: list[list[str]] = []
    base_ref = os.environ.get("GITHUB_BASE_REF")
    if base_ref:
        diff_commands.append(["git", "diff", f"origin/{base_ref}...HEAD", "--", str(relative)])
    diff_commands.append(["git", "diff", "HEAD", "--", str(relative)])
    diff_text = ""
    for command in diff_commands:
        try:
            result = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            warnings.append(f"{' '.join(command)} failed: {exc}")
            continue
        if result.returncode == 0 and result.stdout.strip():
            diff_text = result.stdout
            break
        if result.returncode != 0 and result.stderr.strip():
            warnings.append(result.stderr.strip())
    return _extract_diff_hunks(diff_text), warnings

def _extract_diff_hunks(diff_text: str) -> list[str]:
    hunks: list[str] = []
    current: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("@@"):
            if current:
                hunks.append("\n".join(current[:80]))
            current = [line]
        elif current:
            current.append(line)
    if current:
        hunks.append("\n".join(current[:80]))
    return hunks

def _spec_code_result(
    *,
    code_path: str,
    language: str,
    spec_atoms: list[MumeiContractAtom],
    code_atoms: list[MumeiContractAtom],
    missing_constraint_issues: list[CrossValidationIssue],
    missing_constraints: list[str],
    divergences: list[CrossValidationIssue],
    constraint_violations: list[dict[str, object]],
    extra_behaviors: list[str],
    satisfiable: bool | None,
    warnings: list[str],
    errors: list[str],
    lang: Literal["auto", "en", "ja"],
    contradiction_type: ContradictionType = "",
) -> SpecCodeAlignmentResult:
    cross_validation_gaps = _cross_validation_gap_strings(
        [*missing_constraint_issues, *divergences],
    )
    result = SpecCodeAlignmentResult(
        success=bool(
            not errors
            and spec_atoms
            and code_atoms
            and not missing_constraint_issues
            and not divergences
            and satisfiable is not False
        ),
        code_path=code_path,
        language=language,
        spec_atoms=spec_atoms,
        code_atoms=code_atoms,
        missing_constraints=missing_constraints,
        divergences=divergences,
        constraint_violations=constraint_violations,
        extra_behaviors=extra_behaviors,
        missing_constraint_issues=missing_constraint_issues,
        satisfiable=satisfiable,
        warnings=warnings,
        errors=errors,
        contradiction_type=contradiction_type,
        cross_validation_gaps=cross_validation_gaps,
        next_steps=_generate_cross_validation_next_steps(
            "validate-spec-to-code",
            code_path=code_path,
            spec_path="<spec>",
            gaps=cross_validation_gaps,
        ),
    )
    from agent.report_formatter import format_cross_validation_report

    return replace(result, report=format_cross_validation_report(result, lang=lang))

def _spec_drift_result(
    *,
    code_path: str,
    spec_path: str,
    language: str,
    spec_atoms: list[MumeiContractAtom],
    code_atoms: list[MumeiContractAtom],
    drift_issues: list[CrossValidationIssue],
    changed_hunks: list[str],
    warnings: list[str],
    errors: list[str],
    lang: Literal["en", "ja"],
    contradiction_type: ContradictionType = "",
    extracted_spec: str = "",
    spec_gaps: list[str] | None = None,
    implementation_overages: list[str] | None = None,
    intent_drift: dict[str, object] | None = None,
) -> SpecDriftResult:
    gap_values = _dedupe_strings(spec_gaps or [])
    overage_values = _dedupe_strings(implementation_overages or [])
    cross_validation_gaps = _dedupe_strings(
        [
            *gap_values,
            *overage_values,
            *[issue.evidence or issue.message for issue in drift_issues],
        ]
    )
    result = SpecDriftResult(
        success=bool(not errors and spec_atoms and code_atoms and not drift_issues),
        code_path=code_path,
        spec_path=spec_path,
        language=language,
        spec_atoms=spec_atoms,
        code_atoms=code_atoms,
        drift_issues=drift_issues,
        changed_hunks=changed_hunks,
        warnings=warnings,
        errors=errors,
        contradiction_type=contradiction_type,
        extracted_spec=extracted_spec,
        spec_gaps=gap_values,
        implementation_overages=overage_values,
        cross_validation_gaps=cross_validation_gaps,
        next_steps=_generate_cross_validation_next_steps(
            "validate-code-to-spec",
            code_path=code_path,
            spec_path=spec_path,
            gaps=cross_validation_gaps,
        ),
        intent_drift=intent_drift,
    )
    from agent.report_formatter import format_cross_validation_report

    return replace(result, report=format_cross_validation_report(result, lang=lang))
