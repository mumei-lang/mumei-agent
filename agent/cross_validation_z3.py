"""Z3 and spec-comparison reasoning helpers for cross-validation."""
from __future__ import annotations

import ast
import re
from typing import Literal, cast

import z3

from agent.ambiguity_detector import AmbiguityDetector
from agent.config import AgentConfig
from agent.cross_validation_foreign import _dedupe_strings
from agent.cross_validation_models import (
    ContradictionType,
    CrossValidationIssue,
    IssueKind,
    MumeiContractAtom,
)
from agent.cross_validation_report import _matching_code_atom, _suggest_fix

def _detect_contradictions(spec_text: str) -> list[CrossValidationIssue]:
    issues: list[CrossValidationIssue] = []
    fragments = _split_requirement_fragments(spec_text)
    seen_positive: dict[str, str] = {}
    seen_negative: dict[str, str] = {}
    for fragment in fragments:
        normalized, negated = _normalize_requirement_fragment(fragment)
        if not normalized:
            continue
        if negated and normalized in seen_positive:
            evidence = f"{seen_positive[normalized]} / {fragment.strip()}"
            message = "Requirement states both a condition and its negation."
            issues.append(
                CrossValidationIssue(
                    kind="contradiction",
                    message=message,
                    evidence=evidence,
                    fix_suggestion=_suggest_fix("contradiction", message, evidence),
                )
            )
        if not negated and normalized in seen_negative:
            evidence = f"{fragment.strip()} / {seen_negative[normalized]}"
            message = "Requirement states both a condition and its negation."
            issues.append(
                CrossValidationIssue(
                    kind="contradiction",
                    message=message,
                    evidence=evidence,
                    fix_suggestion=_suggest_fix("contradiction", message, evidence),
                )
            )
        if negated:
            seen_negative[normalized] = fragment.strip()
        else:
            seen_positive[normalized] = fragment.strip()

    for pattern in (
        r"常に(?P<target>[^。.\n]{1,40}?)(?:かつ|そして|、|,)\s*決して(?P=target)",
        r"always\s+(?P<target>[^.。\n]{1,80}?)(?:\s+and|,)\s+never\s+(?P=target)",
        r"must\s+(?P<target>[^.。\n]{1,80}?)(?:\s+and|,)\s+must\s+not\s+(?P=target)",
    ):
        for match in re.finditer(pattern, spec_text, flags=re.IGNORECASE):
            message = "Requirement combines an always/must condition with a never/must-not condition."
            evidence = match.group(0)
            issues.append(
                CrossValidationIssue(
                    kind="contradiction",
                    message=message,
                    evidence=evidence,
                    fix_suggestion=_suggest_fix("contradiction", message, evidence),
                )
            )
    return _dedupe_issues(issues)

def _split_requirement_fragments(spec_text: str) -> list[str]:
    return [
        fragment.strip()
        for fragment in re.split(r"(?:\b(?:and|but|while)\b|かつ|且つ|そして|、|。|;|\n)", spec_text)
        if fragment.strip()
    ]

def _normalize_requirement_fragment(fragment: str) -> tuple[str, bool]:
    text = fragment.strip().lower()
    negated = bool(
        re.search(r"\bnot\b|\bnever\b|\bmust\s+not\b|でない|ではない|しない|決して|禁止", text)
    )
    normalized = re.sub(r"\b(must|must\s+not|should|shall|always|never|not|the|a|an)\b", "", text)
    normalized = re.sub(r"常に|決して|である|です|ます|しない|ではない|でない|禁止|こと|もの", "", normalized)
    normalized = re.sub(r"[^0-9a-zA-Zぁ-んァ-ヶ一-龥_]+", "", normalized)
    return normalized, negated

def _detect_ambiguities(spec_text: str, config: AgentConfig) -> list[CrossValidationIssue]:
    detector = AmbiguityDetector(config)
    result = detector.detect_ambiguity(spec_text, use_llm=False)
    return [
        CrossValidationIssue(
            kind="ambiguity",
            message=f"Ambiguous {finding.ambiguity_type}: replace with a concrete condition.",
            evidence=finding.ambiguous_text,
            fix_suggestion=_suggest_fix(
                "ambiguity",
                f"Ambiguous {finding.ambiguity_type}: replace with a concrete condition.",
                finding.ambiguous_text,
            ),
            location=finding.location,
            severity="warning",
        )
        for finding in result.findings
    ]

def _detect_overconstraints(
    spec_text: str,
    atoms: list[MumeiContractAtom],
) -> list[CrossValidationIssue]:
    issues: list[CrossValidationIssue] = []
    if re.search(r"\b(impossible|cannot be implemented|実装不可能)\b", spec_text, flags=re.IGNORECASE):
        message = "The specification explicitly describes an impossible implementation."
        evidence = "impossible/実装不可能"
        issues.append(
            CrossValidationIssue(
                kind="overconstraint",
                message=message,
                evidence=evidence,
                fix_suggestion=_suggest_fix("overconstraint", message, evidence),
            )
        )
    for atom in atoms:
        for label, clause in (("requires", atom.requires), ("ensures", atom.ensures)):
            if clause.strip().lower() == "false":
                message = f"{atom.name}.{label} is explicitly false."
                issues.append(
                    CrossValidationIssue(
                        kind="overconstraint",
                        message=message,
                        evidence=clause,
                        fix_suggestion=_suggest_fix("overconstraint", message, clause),
                    )
                )
    return issues

def _check_atoms_with_z3(
    atoms: list[MumeiContractAtom],
) -> tuple[bool | None, list[CrossValidationIssue], list[str]]:
    if not atoms:
        return None, [], []
    issues: list[CrossValidationIssue] = []
    warnings: list[str] = []
    any_checked = False
    all_satisfiable = True
    for atom in atoms:
        symbols: dict[str, z3.IntNumRef | z3.ArithRef] = {}
        requires_exprs, requires_warnings = _clause_to_z3(atom.requires, symbols)
        ensures_exprs, ensures_warnings = _clause_to_z3(atom.ensures, symbols)
        warnings.extend(requires_warnings)
        warnings.extend(ensures_warnings)
        exprs = [*requires_exprs, *ensures_exprs]
        requirements_are_satisfiable = True
        if requires_exprs:
            any_checked = True
            requires_solver = z3.Solver()
            requires_solver.add(*requires_exprs)
            requires_status = requires_solver.check()
            if requires_status == z3.unsat:
                requirements_are_satisfiable = False
                all_satisfiable = False
                issues.append(
                    CrossValidationIssue(
                        kind="overconstraint",
                        message=f"Precondition for atom `{atom.name}` is unsatisfiable.",
                        evidence=f"requires: {atom.requires}",
                        fix_suggestion=_suggest_fix(
                            "overconstraint",
                            f"Precondition for atom `{atom.name}` is unsatisfiable.",
                            f"requires: {atom.requires}",
                        ),
                        location=atom.name,
                    )
                )
            elif requires_status == z3.unknown:
                warnings.append(f"Z3 returned unknown for precondition `{atom.name}`.")
        if not exprs:
            continue
        if not requirements_are_satisfiable:
            continue
        any_checked = True
        solver = z3.Solver()
        solver.add(*exprs)
        status = solver.check()
        if status == z3.unsat:
            all_satisfiable = False
            kind: IssueKind = (
                "contradiction"
                if requirements_are_satisfiable and ensures_exprs
                else "satisfiability"
            )
            message = (
                f"`{atom.name}` requires and ensures cannot both hold."
                if kind == "contradiction"
                else f"Inferred contract for atom `{atom.name}` is unsatisfiable."
            )
            issues.append(
                CrossValidationIssue(
                    kind=kind,
                    message=message,
                    evidence=f"requires: {atom.requires}; ensures: {atom.ensures}",
                    fix_suggestion=_suggest_fix(
                        kind,
                        message,
                        f"requires: {atom.requires}; ensures: {atom.ensures}",
                    ),
                    location=atom.name,
                )
            )
        elif status == z3.unknown:
            warnings.append(f"Z3 returned unknown for atom `{atom.name}`.")
    return (all_satisfiable if any_checked else None), issues, warnings

def _compare_spec_atoms_to_code_atoms(
    spec_atoms: list[MumeiContractAtom],
    code_atoms: list[MumeiContractAtom],
    *,
    direction: Literal["spec_to_code", "code_to_spec"],
) -> tuple[list[CrossValidationIssue], list[CrossValidationIssue], list[str]]:
    missing: list[CrossValidationIssue] = []
    divergences: list[CrossValidationIssue] = []
    warnings: list[str] = []
    if not spec_atoms:
        missing.append(
            CrossValidationIssue(
                kind="missing_implementation" if direction == "spec_to_code" else "drift",
                message="No mumei contract atoms could be extracted from the specification.",
                evidence="requires/ensures extraction returned no atoms",
            )
        )
        return missing, divergences, warnings
    if not code_atoms:
        missing.append(
            CrossValidationIssue(
                kind="missing_implementation" if direction == "spec_to_code" else "drift",
                message="No contract atoms could be inferred from the target code.",
                evidence="code contract inference returned no atoms",
            )
        )
        return missing, divergences, warnings

    matched_code_names: set[str] = set()
    for spec_atom in spec_atoms:
        code_atom = _matching_code_atom(spec_atom, code_atoms)
        if code_atom is None:
            missing.append(
                CrossValidationIssue(
                    kind="missing_implementation" if direction == "spec_to_code" else "drift",
                    message=f"Spec atom `{spec_atom.name}` has no matching code implementation.",
                    evidence=f"spec requires: {spec_atom.requires}; spec ensures: {spec_atom.ensures}",
                    location=spec_atom.name,
                )
            )
            continue
        matched_code_names.add(code_atom.name)
        if direction == "spec_to_code":
            req_antecedents = [code_atom.requires]
            req_consequent = spec_atom.requires
            req_message = f"Spec precondition is not enforced by `{code_atom.name}`."
        else:
            req_antecedents = [spec_atom.requires]
            req_consequent = code_atom.requires
            req_message = f"Code precondition for `{code_atom.name}` is not documented in the spec."
        req_implied, req_warnings = _clause_implied(
            req_antecedents,
            req_consequent,
            context=f"{spec_atom.name}.requires",
        )
        warnings.extend(req_warnings)
        if not req_implied:
            missing.append(
                CrossValidationIssue(
                    kind="missing_implementation" if direction == "spec_to_code" else "drift",
                    message=req_message,
                    evidence=f"spec requires: {spec_atom.requires}; code requires: {code_atom.requires}",
                    location=code_atom.name,
                )
            )

        ensures_implied, ensures_warnings = _clause_implied(
            [spec_atom.requires, code_atom.requires, code_atom.ensures],
            spec_atom.ensures,
            context=f"{spec_atom.name}.ensures",
        )
        warnings.extend(ensures_warnings)
        if not ensures_implied:
            divergences.append(
                CrossValidationIssue(
                    kind="alignment" if direction == "spec_to_code" else "drift",
                    message=f"Code behavior for `{code_atom.name}` does not imply the spec postcondition.",
                    evidence=f"spec ensures: {spec_atom.ensures}; code ensures: {code_atom.ensures}",
                    location=code_atom.name,
                )
            )

    unmatched_code = [
        code_atom
        for code_atom in code_atoms
        if code_atom.name not in matched_code_names and not _spec_has_matching_atom(code_atom, spec_atoms)
    ]
    for code_atom in unmatched_code:
        divergences.append(
            CrossValidationIssue(
                kind="alignment" if direction == "spec_to_code" else "drift",
                message=f"Code atom `{code_atom.name}` is not covered by the specification.",
                evidence=f"code requires: {code_atom.requires}; code ensures: {code_atom.ensures}",
                location=code_atom.name,
                severity="warning",
            )
        )
    return missing, divergences, warnings

def _spec_has_matching_atom(code_atom: MumeiContractAtom, spec_atoms: list[MumeiContractAtom]) -> bool:
    if len(spec_atoms) == 1:
        return True
    return any(spec_atom.name == code_atom.name for spec_atom in spec_atoms)

def _clause_implied(
    antecedent_clauses: list[str],
    consequent_clause: str,
    *,
    context: str,
) -> tuple[bool, list[str]]:
    symbols: dict[str, z3.IntNumRef | z3.ArithRef] = {}
    warnings: list[str] = []
    consequent_exprs, consequent_warnings = _clause_to_z3(consequent_clause, symbols)
    warnings.extend(f"{context}: {warning}" for warning in consequent_warnings)
    if not consequent_exprs:
        return True, warnings
    antecedent_exprs: list[z3.BoolRef] = []
    for clause in antecedent_clauses:
        parsed, clause_warnings = _clause_to_z3(clause, symbols)
        warnings.extend(f"{context}: {warning}" for warning in clause_warnings)
        antecedent_exprs.extend(parsed)
    for consequent in consequent_exprs:
        solver = z3.Solver()
        if antecedent_exprs:
            solver.add(*antecedent_exprs)
        solver.add(z3.Not(consequent))
        status = solver.check()
        if status == z3.sat:
            return False, warnings
        if status == z3.unknown:
            warnings.append(f"{context}: Z3 returned unknown while checking implication.")
            return False, warnings
    return True, warnings

def _combine_satisfiability(left: bool | None, right: bool | None) -> bool | None:
    if left is False or right is False:
        return False
    if left is True and right is True:
        return True
    if left is True or right is True:
        return True
    return None

def _classify_nl_contradiction_type(
    contradictions: list[CrossValidationIssue],
    overconstraints: list[CrossValidationIssue],
    vacuity_warnings: list[str],
) -> ContradictionType:
    if contradictions:
        return "spec_internal"
    if overconstraints:
        return "spec_overconstraint"
    if vacuity_warnings:
        return "spec_vacuity"
    return ""

def _alignment_contradiction_type(
    upstream_type: str,
    has_spec_code_gap: bool,
) -> ContradictionType:
    if upstream_type in {"spec_internal", "spec_overconstraint", "spec_vacuity"}:
        return cast(ContradictionType, upstream_type)
    if has_spec_code_gap:
        return "spec_vs_code"
    return ""

def _split_top_level_conjuncts(expr: str) -> list[str]:
    """Split ``expr`` on top-level ``&&`` / ``and`` conjunctions only.

    Paren/bracket/brace-aware, so a compound clause such as
    ``(a && b) || (c && d)`` (whose top-level operator is ``||``) is returned
    whole instead of being shredded into unbalanced fragments like ``(a`` and
    ``b) || (c``. Mirrors mumei's ``split_top_level_conjunctions``.
    """
    parts: list[str] = []
    depth = 0
    start = 0
    i = 0
    n = len(expr)
    while i < n:
        ch = expr[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0 and ch == "&" and i + 1 < n and expr[i + 1] == "&":
            parts.append(expr[start:i])
            i += 2
            start = i
            continue
        elif (
            depth == 0
            and expr[i : i + 3] == "and"
            and (i == 0 or not (expr[i - 1].isalnum() or expr[i - 1] == "_"))
            and (i + 3 >= n or not (expr[i + 3].isalnum() or expr[i + 3] == "_"))
        ):
            parts.append(expr[start:i])
            i += 3
            start = i
            continue
        i += 1
    parts.append(expr[start:])
    return parts


def _normalize_boolean_operators(clause: str) -> str:
    """Rewrite foreign boolean syntax to the Python operators ``ast.parse`` accepts.

    ``||`` used to reach ``ast.parse`` as invalid Python, so any disjunctive clause
    (used by Go/TS/Solidity/Rust) was silently dropped even though
    ``_ast_bool_to_z3`` already lowers ``ast.Or``. Normalize both boolean operators,
    plus the strict-equality spellings, so disjunctions are checked instead of
    skipped. ``&&``/``and`` and ``||``/``or`` share the same relative precedence in
    both C-family languages and Python, so the parsed tree keeps its meaning.
    """
    normalized = clause.replace("===", "==").replace("!==", "!=")
    normalized = normalized.replace("&&", " and ").replace("||", " or ")
    return normalized


def _has_top_level_disjunction(expr: str) -> bool:
    """True when ``expr`` has a depth-0 ``||``/``or`` disjunction.

    Such a clause must be lowered whole because its lowest-precedence operator is
    the disjunction; splitting on top-level ``&&`` would mis-bind precedence, e.g.
    ``a && b || c`` means ``(a && b) || c`` (not ``a && (b || c)``).
    """
    depth = 0
    i = 0
    n = len(expr)
    while i < n:
        ch = expr[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0 and ch == "|" and i + 1 < n and expr[i + 1] == "|":
            return True
        elif (
            depth == 0
            and expr[i : i + 2] == "or"
            and (i == 0 or not (expr[i - 1].isalnum() or expr[i - 1] == "_"))
            and (i + 2 >= n or not (expr[i + 2].isalnum() or expr[i + 2] == "_"))
        ):
            return True
        i += 1
    return False


def _clause_to_z3(
    clause: str,
    symbols: dict[str, z3.IntNumRef | z3.ArithRef],
) -> tuple[list[z3.BoolRef], list[str]]:
    normalized = _normalize_boolean_operators(clause).strip().rstrip(";")
    if not normalized or normalized.lower() == "true":
        return [], []
    if normalized.lower() == "false":
        return [z3.BoolVal(False)], []
    warnings: list[str] = []
    expressions: list[z3.BoolRef] = []
    # A clause whose lowest-precedence operator is ``||`` must be lowered whole so
    # ``ast`` builds the correct And/Or tree; only pure conjunctions are split into
    # independent constraints (which lets a single unsupported conjunct be skipped
    # while the rest survive).
    parts = (
        [normalized]
        if _has_top_level_disjunction(normalized)
        else _split_top_level_conjuncts(normalized)
    )
    for part in parts:
        part = part.strip()
        if not part or part.lower() == "true":
            continue
        try:
            tree = ast.parse(part, mode="eval")
            parsed = _ast_bool_to_z3(tree.body, symbols)
            expressions.append(parsed)
        except (SyntaxError, ValueError, TypeError, KeyError):
            warnings.append(f"Skipped unsupported Z3 clause: {part}")
    return expressions, warnings


def _mumei_safe_clause(clause: str) -> str:
    """Return a clause string that mumei can parse by dropping unsupported fragments.

    Z3 already knows which fragments it can lower.  Fragments that Z3 cannot
    lower are likely to use foreign syntax (``len(x)``, ``for all``, ``new T``,
    method calls, etc.) that mumei will also reject, so remove them before
    emitting the ``.mm`` module.  This prevents ``mumei verify`` false
    refutations while still preserving the lowerable arithmetic/comparison
    clauses that mumei can trust.
    """
    normalized = _normalize_boolean_operators(clause).strip().rstrip(";")
    if not normalized or normalized.lower() == "true":
        return "true"
    if normalized.lower() == "false":
        return "false"
    parts = (
        [normalized]
        if _has_top_level_disjunction(normalized)
        else _split_top_level_conjuncts(normalized)
    )
    kept: list[str] = []
    for part in parts:
        part = part.strip()
        if not part or part.lower() == "true":
            continue
        try:
            tree = ast.parse(part, mode="eval")
            _ast_bool_to_z3(tree.body, {})
            kept.append(part)
        except (SyntaxError, ValueError, TypeError, KeyError):
            continue
    if not kept:
        return "true"
    return " && ".join(kept)


def _ast_bool_to_z3(
    node: ast.AST,
    symbols: dict[str, z3.IntNumRef | z3.ArithRef],
) -> z3.BoolRef:
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise ValueError("chained comparisons are unsupported")
        left = _ast_arith_to_z3(node.left, symbols)
        right = _ast_arith_to_z3(node.comparators[0], symbols)
        op = node.ops[0]
        if isinstance(op, ast.Eq):
            return left == right
        if isinstance(op, ast.NotEq):
            return left != right
        if isinstance(op, ast.Gt):
            return left > right
        if isinstance(op, ast.GtE):
            return left >= right
        if isinstance(op, ast.Lt):
            return left < right
        if isinstance(op, ast.LtE):
            return left <= right
    if isinstance(node, ast.BoolOp):
        values = [_ast_bool_to_z3(value, symbols) for value in node.values]
        if isinstance(node.op, ast.And):
            return z3.And(*values)
        if isinstance(node.op, ast.Or):
            return z3.Or(*values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return z3.Not(_ast_bool_to_z3(node.operand, symbols))
    raise ValueError("unsupported boolean expression")

def _ast_arith_to_z3(
    node: ast.AST,
    symbols: dict[str, z3.IntNumRef | z3.ArithRef],
) -> z3.IntNumRef | z3.ArithRef:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return z3.IntVal(node.value)
    if isinstance(node, ast.Name):
        if node.id not in symbols:
            symbols[node.id] = z3.Int(node.id)
        return symbols[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_ast_arith_to_z3(node.operand, symbols)
    if isinstance(node, ast.BinOp):
        left = _ast_arith_to_z3(node.left, symbols)
        right = _ast_arith_to_z3(node.right, symbols)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.FloorDiv):
            return left / right
        if isinstance(node.op, ast.Mod):
            return left % right
    raise ValueError("unsupported arithmetic expression")

def _dedupe_issues(issues: list[CrossValidationIssue]) -> list[CrossValidationIssue]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[CrossValidationIssue] = []
    for issue in issues:
        key = (issue.kind, issue.message, issue.evidence)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped
