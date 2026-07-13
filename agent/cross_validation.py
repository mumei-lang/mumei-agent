"""Cross-validation for natural-language specs and existing code."""
from __future__ import annotations

import argparse
import ast
import json
from collections.abc import Iterable
from dataclasses import asdict, replace
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Literal, cast

import z3

from agent.ambiguity_detector import AmbiguityDetector
from agent.config import AgentConfig
from agent.code_to_spec import CodeToSpecConverter
from agent.lean_bridge_helpers import run_lean_bridge_and_merge_proof_cert
from agent.llm_provider import LLMProvider, OpenAILLMProvider
from agent.mumei_client import create_mumei_client
from agent.prompts.cross_validation_code import (
    CROSS_VALIDATION_CODE_SYSTEM_PROMPT,
    build_code_cross_validation_prompt,
)
from agent.prompts.cross_validation_nl import (
    CROSS_VALIDATION_NL_SYSTEM_PROMPT,
    build_nl_cross_validation_prompt,
)
from agent.intent_tracker import IntentChange, IntentDriftResult, IntentTracker
from agent.spec_code_mapper import MappingResult, SpecCodeMapper
from agent.cross_validation_models import (
    ContradictionType,
    ContractParam,
    CrossValidationIssue,
    CrossValidationReport,
    CrossValidationResult,
    ForeignCodeValidationResult,
    ForeignCodeVerdict,
    IssueKind,
    MumeiContractAtom,
    NLSpecValidationResult,
    Severity,
    SpecCodeAlignmentResult,
    SpecDriftResult,
    SUPPORTED_FOREIGN_CODE_LANGUAGES,
)
from agent.cross_validation_foreign import (
    _absolute_value_param,
    _balanced_brace_body,
    _dedupe_strings,
    _foreign_signature_type,
    _generic_safety_requires_for_expression,
    _go_function_declarations,
    _go_nil_dereference_values,
    _go_safety_requires_for_expression,
    _infer_foreign_contracts_with_code_to_spec,
    _infer_foreign_contracts_with_patterns,
    _infer_foreign_source_line_map,
    _infer_go_contracts,
    _infer_python_contracts,
    _infer_python_source_line_map,
    _infer_regex_source_line_map,
    _infer_rust_contracts,
    _infer_typescript_contracts,
    _issue_function_from_text,
    _integer_overflow_requires_for_expression,
    _last_expression,
    _normalize_foreign_expression,
    _normalize_foreign_language,
    _normalized_python_return,
    _params_from_signature,
    _python_function_contract,
    _raw_return_statement_expression,
    _return_statement_expression,
    _rust_safety_requires_for_expression,
    _safe_identifier,
    _safety_requires_for_expression,
    _single_return_expr,
    _typescript_raw_return_expression,
    _typescript_return_type,
    _with_source_lines,
)
from agent.strategies.foreign_code_strategy_helpers import (
    build_solidity_guard_trace_proof_certificate,
)
from agent.cross_validation_payload import (
    _atom_from_mapping,
    _atoms_from_payload,
    _atoms_to_mumei_module,
    _contract_clause,
    _default_literal,
    _extract_inline_contract_atoms,
    _int_value,
    _issues_from_payload,
    _json_from_text,
    _params_from_contract_text,
    _params_from_value,
    _string_list,
    _string_value,
)
from agent.cross_validation_report import (
    _atoms_to_spec_payload,
    _atoms_to_summary,
    _code_snippet_for_line,
    _code_to_spec_gap_strings,
    _constraint_violations_from_issues,
    _cross_validation_gap_strings,
    _emit_cross_validation_result,
    _emit_result,
    _emit_validate_spec_result,
    _extra_behavior_texts,
    _extract_diff_hunks,
    _format_intent_drift_report,
    _format_validate_spec_markdown,
    _generate_cross_validation_next_steps,
    _git_diff_hunks,
    _implementation_overage_strings,
    _infer_language_from_path,
    _intent_gap_strings,
    _intent_payloads,
    _intent_payloads_for_atoms,
    _is_upstream_alignment_issue,
    _issue_lines_for_integrated_report,
    _markdown_cell,
    _matching_code_atom,
    _missing_constraint_texts,
    _read_input_file,
    _spec_code_contradiction_type,
    _spec_code_result,
    _spec_constraint_from_issue,
    _spec_drift_result,
    _suggest_fix,
    _upstream_validation_issues,
    _with_spec_code_source_lines,
)
from agent.cross_validation_z3 import (
    _alignment_contradiction_type,
    _ast_arith_to_z3,
    _ast_bool_to_z3,
    _check_atoms_with_z3,
    _clause_implied,
    _clause_to_z3,
    _classify_nl_contradiction_type,
    _combine_satisfiability,
    _compare_spec_atoms_to_code_atoms,
    _dedupe_issues,
    _detect_ambiguities,
    _detect_contradictions,
    _detect_overconstraints,
    _normalize_requirement_fragment,
    _split_requirement_fragments,
    _spec_has_matching_atom,
)
from agent.strategies.foreign_code_strategy_helpers import _detect_solidity_contract_issues










def validate_nl_spec(
    spec_text: str,
    *,
    config: AgentConfig | None = None,
    use_llm: bool = True,
    run_mumei: bool = True,
    domain_hint: str = "",
    llm_provider: LLMProvider | None = None,
) -> NLSpecValidationResult:
    """Validate a natural-language specification for logical health."""
    config = config or AgentConfig()
    warnings: list[str] = []
    errors: list[str] = []
    if not spec_text.strip():
        return NLSpecValidationResult(
            success=False,
            contradictions=[],
            ambiguities=[],
            overconstraints=[],
            inferred_atoms=[],
            satisfiable=None,
            errors=["spec_text must be non-empty"],
        )

    contradictions = _detect_contradictions(spec_text)
    ambiguities = _detect_ambiguities(spec_text, config)
    atoms = _extract_inline_contract_atoms(spec_text)
    llm_issues: list[CrossValidationIssue] = []
    if use_llm and (config.api_key or llm_provider):
        llm_atoms, llm_issues, llm_warnings = _infer_nl_contracts_with_llm(
            spec_text, config, llm_provider=llm_provider,
        )
        warnings.extend(llm_warnings)
        if llm_atoms:
            atoms = llm_atoms
    elif use_llm:
        warnings.append("LLM conversion skipped because LLM_API_KEY/OPENAI_API_KEY is not set.")

    contradictions.extend(issue for issue in llm_issues if issue.kind == "contradiction")
    ambiguities.extend(issue for issue in llm_issues if issue.kind == "ambiguity")
    overconstraints = [
        issue for issue in llm_issues if issue.kind not in {"contradiction", "ambiguity"}
    ]
    overconstraints.extend(_detect_overconstraints(spec_text, atoms))

    satisfiable, z3_issues, z3_warnings = _check_atoms_with_z3(atoms)
    warnings.extend(z3_warnings)
    contradictions.extend(issue for issue in z3_issues if issue.kind == "contradiction")
    overconstraints.extend(issue for issue in z3_issues if issue.kind != "contradiction")

    from agent.spec_completeness_checker import check_domain_completeness, check_nl_vacuity

    completeness_warnings = (
        check_domain_completeness(spec_text, atoms, domain_hint) if domain_hint else []
    )
    vacuity_warnings = check_nl_vacuity(atoms)

    verification: dict[str, object] | None = None
    if run_mumei and atoms:
        verification, mumei_issues, mumei_warnings = _verify_atoms_with_mumei(atoms, config)
        warnings.extend(mumei_warnings)
        overconstraints.extend(mumei_issues)
        if verification is not None and verification.get("success") is False:
            satisfiable = False

    contradictions = _dedupe_issues(_with_fix_suggestions(contradictions))
    ambiguities = _dedupe_issues(_with_fix_suggestions(ambiguities))
    overconstraints = _dedupe_issues(_with_fix_suggestions(overconstraints))
    success = (
        not errors
        and not contradictions
        and not ambiguities
        and not overconstraints
        and satisfiable is not False
    )
    return NLSpecValidationResult(
        success=success,
        contradictions=contradictions,
        ambiguities=ambiguities,
        overconstraints=overconstraints,
        inferred_atoms=atoms,
        satisfiable=satisfiable,
        completeness_warnings=completeness_warnings,
        vacuity_warnings=vacuity_warnings,
        verification=verification,
        warnings=warnings,
        errors=errors,
        contradiction_evidence=_issue_evidence(contradictions),
        overconstraint_evidence=_issue_evidence(overconstraints),
        contradiction_type=_classify_nl_contradiction_type(
            contradictions,
            overconstraints,
            vacuity_warnings,
        ),
    )


def validate_nl_spec_multi(
    spec_texts: list[str],
    *,
    config: AgentConfig | None = None,
    use_llm: bool = True,
    domain_hint: str = "",
    llm_provider: LLMProvider | None = None,
) -> dict[str, object]:
    """Validate multiple NL spec documents for cross-document consistency."""
    config = config or AgentConfig()
    results = [
        validate_nl_spec(
            spec_text,
            config=config,
            use_llm=use_llm,
            run_mumei=False,
            domain_hint=domain_hint,
            llm_provider=llm_provider,
        )
        for spec_text in spec_texts
    ]
    cross_spec_conflicts = _check_nl_result_pairs_for_conflicts(results)
    return {
        "success": all(result.success for result in results) and not cross_spec_conflicts,
        "spec_count": len(spec_texts),
        "results": [asdict(result) for result in results],
        "cross_spec_conflicts": [asdict(issue) for issue in cross_spec_conflicts],
    }


def validate_spec_to_code(
    spec: str,
    code_path: str,
    *,
    config: AgentConfig | None = None,
    language: str | None = None,
    use_llm: bool = True,
    run_mumei: bool = True,
    lang: Literal["auto", "en", "ja"] = "auto",
    llm_provider: LLMProvider | None = None,
) -> SpecCodeAlignmentResult:
    """Validate that code implements the requires/ensures constraints in a spec."""
    config = config or AgentConfig()
    warnings: list[str] = []
    errors: list[str] = []
    code_file = Path(code_path)
    normalized_language = _infer_language_from_path(code_file, language)
    try:
        code = code_file.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"failed to read code file: {exc}")
        return _spec_code_result(
            code_path=code_path,
            language=normalized_language,
            spec_atoms=[],
            code_atoms=[],
            missing_constraint_issues=[],
            missing_constraints=[],
            divergences=[],
            constraint_violations=[],
            extra_behaviors=[],
            satisfiable=None,
            warnings=warnings,
            errors=errors,
            lang=lang,
        )

    spec_result = validate_nl_spec(
        spec, config=config, use_llm=use_llm, run_mumei=run_mumei,
        llm_provider=llm_provider,
    )
    code_result = validate_foreign_code(
        code,
        normalized_language,
        config=config,
        use_llm=use_llm,
        run_mumei=run_mumei,
        llm_provider=llm_provider,
    )
    warnings.extend(spec_result.warnings)
    warnings.extend(code_result.warnings)
    errors.extend(spec_result.errors)
    errors.extend(code_result.errors)
    missing, divergences, compare_warnings = _compare_spec_atoms_to_code_atoms(
        spec_result.inferred_atoms,
        code_result.inferred_atoms,
        direction="spec_to_code",
    )
    divergences.extend(_upstream_validation_issues(spec_result, code_result))
    warnings.extend(compare_warnings)
    satisfiable = _combine_satisfiability(spec_result.satisfiable, code_result.satisfiable)
    mapping = SpecCodeMapper(config).build_mapping(
        _atoms_to_spec_payload(spec_result.inferred_atoms),
        code,
        verification_report=code_result.verification,
    )
    warnings.extend(mapping.warnings)
    missing = _with_spec_code_source_lines(
        _dedupe_issues(missing),
        code_result.source_line_map,
        mapping.constraint_to_line,
    )
    divergences = _with_spec_code_source_lines(
        _dedupe_issues(divergences),
        code_result.source_line_map,
        mapping.constraint_to_line,
    )
    constraint_violations = _constraint_violations_from_issues(
        [*missing, *divergences],
        code,
        code_path,
        mapping.constraint_to_line,
    )
    missing_constraint_texts = _missing_constraint_texts(missing)
    extra_behaviors = _extra_behavior_texts(divergences)

    ct = _alignment_contradiction_type(
        spec_result.contradiction_type,
        bool(missing or divergences),
    )

    return _spec_code_result(
        code_path=code_path,
        language=normalized_language,
        spec_atoms=spec_result.inferred_atoms,
        code_atoms=code_result.inferred_atoms,
        missing_constraint_issues=missing,
        missing_constraints=missing_constraint_texts,
        divergences=divergences,
        constraint_violations=constraint_violations,
        extra_behaviors=extra_behaviors,
        satisfiable=satisfiable,
        warnings=warnings,
        errors=errors,
        lang=lang,
        contradiction_type=ct,
    )


def validate_code_to_spec(
    code_path: str,
    spec_path: str,
    *,
    config: AgentConfig | None = None,
    language: str | None = None,
    use_llm: bool = True,
    run_mumei: bool = True,
    lang: Literal["auto", "en", "ja"] = "auto",
    llm_provider: LLMProvider | None = None,
) -> SpecDriftResult:
    """Validate that a specification has not drifted behind code changes."""
    config = config or AgentConfig()
    warnings: list[str] = []
    errors: list[str] = []
    spec_file = Path(spec_path)
    try:
        spec = spec_file.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"failed to read spec file: {exc}")
        return _spec_drift_result(
            code_path=code_path,
            spec_path=spec_path,
            language=_infer_language_from_path(Path(code_path), language),
            spec_atoms=[],
            code_atoms=[],
            drift_issues=[],
            changed_hunks=[],
            warnings=warnings,
            errors=errors,
            lang=lang,
        )

    alignment = validate_spec_to_code(
        spec,
        code_path,
        config=config,
        language=language,
        use_llm=use_llm,
        run_mumei=run_mumei,
        lang=lang,
        llm_provider=llm_provider,
    )
    warnings.extend(alignment.warnings)
    errors.extend(alignment.errors)
    changed_hunks, diff_warnings = _git_diff_hunks(Path(code_path))
    warnings.extend(diff_warnings)
    if not changed_hunks:
        warnings.append("No git diff hunks found for the code path; comparing current code to spec only.")
    extracted_spec = ""
    try:
        code_text = Path(code_path).read_text(encoding="utf-8")
    except OSError as exc:
        code_text = ""
        errors.append(f"failed to read code file for code-to-spec extraction: {exc}")
    if code_text:
        conversion = CodeToSpecConverter(config).convert_source(code_text, alignment.language)
        extracted_spec = conversion.natural_language_spec
        warnings.extend(conversion.warnings)
        errors.extend(conversion.errors)
    drift_missing, drift_divergences, drift_warnings = _compare_spec_atoms_to_code_atoms(
        alignment.spec_atoms,
        alignment.code_atoms,
        direction="code_to_spec",
    )
    warnings.extend(drift_warnings)
    drift_issues = [
        CrossValidationIssue(
            kind="drift",
            message=issue.message,
            evidence=issue.evidence,
            location=issue.location,
            severity=issue.severity,
        )
        for issue in [
            *drift_missing,
            *drift_divergences,
            *[
                issue
                for issue in alignment.divergences
                if _is_upstream_alignment_issue(issue)
            ],
        ]
    ]
    spec_gaps = _code_to_spec_gap_strings([*drift_missing, *drift_divergences])
    implementation_overages = _implementation_overage_strings(
        [*drift_missing, *drift_divergences],
    )
    intent_drift_payload: dict[str, object] | None = None
    if alignment.spec_atoms or alignment.code_atoms:
        original_intent, refined_intent = _intent_payloads_for_atoms(
            alignment.spec_atoms,
            alignment.code_atoms,
        )
        intent_drift = IntentTracker(config).track_intent_drift(
            original_intent,
            refined_intent,
            natural_language_intent=spec,
        )
        intent_drift_payload = asdict(intent_drift)
        warnings.extend(intent_drift.warnings)
        spec_gaps.extend(_intent_gap_strings(intent_drift.changes))
    deduped_drift_issues = _dedupe_issues(drift_issues)
    return _spec_drift_result(
        code_path=code_path,
        spec_path=spec_path,
        language=alignment.language,
        spec_atoms=alignment.spec_atoms,
        code_atoms=alignment.code_atoms,
        drift_issues=deduped_drift_issues,
        changed_hunks=changed_hunks,
        warnings=warnings,
        errors=errors,
        lang=lang,
        contradiction_type=_alignment_contradiction_type(
            alignment.contradiction_type,
            bool(deduped_drift_issues),
        ),
        extracted_spec=extracted_spec or _atoms_to_summary(alignment.code_atoms),
        spec_gaps=_dedupe_strings(spec_gaps),
        implementation_overages=_dedupe_strings(implementation_overages),
        intent_drift=intent_drift_payload,
    )


def detect_intent_drift(
    natural_language_spec: str,
    generated_code: str,
    *,
    config: AgentConfig | None = None,
    language: str = "python",
    use_llm: bool = True,
    run_mumei: bool = True,
    lang: Literal["en", "ja"] = "en",
    llm_provider: LLMProvider | None = None,
) -> CrossValidationReport:
    """Detect semantic drift between natural-language intent and generated code."""
    config = config or AgentConfig()
    spec_result = validate_nl_spec(
        natural_language_spec,
        config=config,
        use_llm=use_llm,
        run_mumei=run_mumei,
        llm_provider=llm_provider,
    )
    code_result = validate_foreign_code(
        generated_code,
        language,
        config=config,
        use_llm=use_llm,
        run_mumei=run_mumei,
        llm_provider=llm_provider,
    )
    drift_missing, drift_divergences, drift_warnings = _compare_spec_atoms_to_code_atoms(
        spec_result.inferred_atoms,
        code_result.inferred_atoms,
        direction="code_to_spec",
    )
    drift_issues = _dedupe_issues(
        [
            CrossValidationIssue(
                kind="drift",
                message=issue.message,
                evidence=issue.evidence,
                location=issue.location,
                severity=issue.severity,
            )
            for issue in [*drift_missing, *drift_divergences]
        ]
    )
    validation = _spec_drift_result(
        code_path="<generated>",
        spec_path="<natural-language>",
        language=language.strip().lower(),
        spec_atoms=spec_result.inferred_atoms,
        code_atoms=code_result.inferred_atoms,
        drift_issues=drift_issues,
        changed_hunks=[],
        warnings=[*spec_result.warnings, *code_result.warnings, *drift_warnings],
        errors=[*spec_result.errors, *code_result.errors],
        lang=lang,
        contradiction_type=_alignment_contradiction_type(
            spec_result.contradiction_type,
            bool(drift_issues),
        ),
    )
    spec_payload, code_payload = _intent_payloads(
        spec_result.inferred_atoms,
        code_result.inferred_atoms,
    )
    intent_drift = IntentTracker(config).track_intent_drift(
        spec_payload,
        code_payload,
        natural_language_intent=natural_language_spec,
    )
    mapping = SpecCodeMapper(config).build_mapping(
        spec_payload,
        generated_code,
        verification_report=code_result.verification,
        intent_drift_result=intent_drift,
    )
    intent_issues = [
        CrossValidationIssue(
            kind="drift",
            message=f"Intent drift in {change.field}: {change.change_type} ({change.intent_impact}).",
            evidence=f"original={change.original}; refined={change.refined}",
            location=change.field,
            severity="error" if change.intent_impact == "violated" else "warning",
        )
        for change in intent_drift.changes
        if change.intent_impact in {"violated", "weakened", "strengthened"}
    ]
    issues = _dedupe_issues([*validation.drift_issues, *intent_issues])
    success = (
        validation.success
        and mapping.success
        and intent_drift.intent_preserved
        and not issues
    )
    report = CrossValidationReport(
        success=success,
        drift_detected=bool(issues) or not intent_drift.intent_preserved,
        validation=replace(validation, drift_issues=issues),
        mapping=mapping,
        intent_drift=intent_drift,
        issues=issues,
    )
    return replace(report, report=_format_intent_drift_report(report, lang=lang))


def validate_foreign_code(
    code: str,
    language: str,
    *,
    config: AgentConfig | None = None,
    use_llm: bool = True,
    run_mumei: bool = True,
    enable_lean_bridge: bool = False,
    llm_provider: LLMProvider | None = None,
) -> ForeignCodeValidationResult:
    """Validate Python, Rust, TypeScript, or Go code by inferring contracts."""
    config = config or AgentConfig()
    normalized_language = _normalize_foreign_language(language)
    warnings: list[str] = []
    errors: list[str] = []
    if normalized_language not in SUPPORTED_FOREIGN_CODE_LANGUAGES:
        errors.append("language must be one of: python, rust, typescript, go, solidity")
    if not code.strip():
        errors.append("code must be non-empty")
    if errors:
        return ForeignCodeValidationResult(
            success=False,
            verdict="unverifiable",
            language=normalized_language,
            inferred_atoms=[],
            mumei_source="",
            satisfiable=None,
            errors=errors,
        )

    source_line_map = _infer_foreign_source_line_map(code, normalized_language)
    atoms = _infer_foreign_contracts_with_code_to_spec(code, normalized_language, config)
    llm_issues: list[CrossValidationIssue] = []
    if use_llm and (config.api_key or llm_provider):
        llm_atoms, llm_issues, llm_warnings = _infer_code_contracts_with_llm(
            code,
            normalized_language,
            config,
            llm_provider=llm_provider,
        )
        warnings.extend(llm_warnings)
        if llm_atoms:
            atoms = llm_atoms
    elif use_llm:
        warnings.append("LLM contract inference skipped because LLM_API_KEY/OPENAI_API_KEY is not set.")

    if not atoms:
        warnings.append("No functions were inferable from the input code.")
    satisfiable, z3_issues, z3_warnings = _check_atoms_with_z3(atoms)
    warnings.extend(z3_warnings)
    issues = _with_source_lines(_dedupe_issues([*llm_issues, *z3_issues]), source_line_map)
    if normalized_language == "solidity":
        issues.extend(_solidity_advisory_issues(code))
    mumei_source = _atoms_to_mumei_module(atoms) if atoms else ""
    verification: dict[str, object] | None = None
    if run_mumei and atoms:
        skipped_clause_warnings = [
            warning
            for warning in z3_warnings
            if warning.startswith("Skipped unsupported Z3 clause:")
        ]
        verification, mumei_issues, mumei_warnings = _verify_atoms_with_mumei(
            atoms,
            config,
            skipped_clause_warnings=skipped_clause_warnings,
        )
        warnings.extend(mumei_warnings)
        issues = _with_source_lines(_dedupe_issues([*issues, *mumei_issues]), source_line_map)
        if verification is not None and verification.get("success") is False:
            satisfiable = False

    proof_certificate = _build_solidity_guard_trace_proof_certificate(
        code,
        language=normalized_language,
    )
    lean_bridge_result: dict[str, object] | None = None
    if proof_certificate is not None and enable_lean_bridge:
        proof_certificate, lean_bridge_result = _run_solidity_guard_trace_lean_bridge(
            proof_certificate,
            config,
        )
        if lean_bridge_result is not None:
            warnings.extend(lean_bridge_result.get("diagnostics", []))
            if not lean_bridge_result.get("success", False):
                warnings.append(
                    str(lean_bridge_result.get("stderr") or lean_bridge_result.get("error_code") or "lean bridge failed")
                )

    verdict = _validate_foreign_code_verdict(
        atoms=atoms,
        errors=errors,
        issues=issues,
        satisfiable=satisfiable,
        verification=verification,
        warnings=warnings,
    )
    success = verdict == "verified"
    return ForeignCodeValidationResult(
        success=success,
        verdict=verdict,
        language=normalized_language,
        inferred_atoms=atoms,
        mumei_source=mumei_source,
        satisfiable=satisfiable,
        verification=verification,
        proof_certificate=proof_certificate,
        lean_bridge=lean_bridge_result,
        issues=issues,
        source_line_map=source_line_map,
        warnings=warnings,
        errors=errors,
    )


def _build_solidity_guard_trace_proof_certificate(
    code: str,
    *,
    language: str,
) -> dict[str, object] | None:
    if language != "solidity":
        return None
    cert = build_solidity_guard_trace_proof_certificate(
        code,
        source_file="<inline:solidity>",
        package_name="solidity",
        package_version="0",
        mumei_version="agent",
    )
    if not cert.get("atoms"):
        return None
    return cert


def _run_solidity_guard_trace_lean_bridge(
    proof_certificate: dict[str, object],
    config: AgentConfig,
) -> tuple[dict[str, object], dict[str, object] | None]:
    if not config.mumei_lean_repo:
        return proof_certificate, None
    return run_lean_bridge_and_merge_proof_cert(
        proof_certificate,
        config.mumei_lean_repo,
    )


def _solidity_advisory_issues(code: str) -> list[CrossValidationIssue]:
    return [
        CrossValidationIssue(
            kind="verification",
            message=issue.message,
            location=issue.function_name,
            severity="warning",
        )
        for issue in _detect_solidity_contract_issues(code)
    ]


def build_validate_spec_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    """Add validate-spec arguments to an argparse parser."""
    parser = parser or argparse.ArgumentParser(description="Validate natural-language specs.")
    parser.add_argument("--input", required=True, help="Path to the natural-language spec file.")
    parser.add_argument(
        "--format",
        choices=["nl", "human", "json", "markdown"],
        default="nl",
        help="Output format (nl/json default, human, or markdown table).",
    )
    parser.add_argument(
        "--domain",
        default="",
        help="Domain hint (financial/security/crypto/data_structure).",
    )
    parser.add_argument("--output", help="Optional report output path.")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM contract extraction.")
    parser.add_argument("--no-mumei", action="store_true", help="Skip mumei verify.")
    return parser


def build_validate_spec_to_code_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    """Add validate-spec-to-code arguments to an argparse parser."""
    parser = parser or argparse.ArgumentParser(description="Validate spec-to-code alignment.")
    parser.add_argument("--spec", "--input", dest="spec", required=True, help="Path to spec file.")
    parser.add_argument("--code", required=True, help="Path to source code.")
    parser.add_argument(
        "--language",
        choices=["python", "rust", "typescript", "go", "solidity"],
        help="Source language.",
    )
    parser.add_argument(
        "--lang",
        choices=["auto", "en", "ja"],
        default="auto",
        help="Report language.",
    )
    parser.add_argument("--output", help="Optional report path.")
    parser.add_argument(
        "--format",
        choices=["human", "json", "markdown"],
        default="markdown",
        help="Output format (default: markdown).",
    )
    parser.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM contract inference.")
    parser.add_argument("--no-mumei", action="store_true", help="Skip mumei verify.")
    return parser


def build_validate_code_to_spec_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    """Add validate-code-to-spec arguments to an argparse parser."""
    parser = parser or argparse.ArgumentParser(description="Validate code-to-spec drift.")
    parser.add_argument("--code", required=True, help="Path to source code.")
    parser.add_argument("--spec", required=True, help="Path to spec file.")
    parser.add_argument(
        "--language",
        choices=["python", "rust", "typescript", "go", "solidity"],
        help="Source language.",
    )
    parser.add_argument(
        "--lang",
        choices=["auto", "en", "ja"],
        default="auto",
        help="Report language.",
    )
    parser.add_argument("--output", help="Optional report path.")
    parser.add_argument(
        "--format",
        choices=["human", "json", "markdown"],
        default="markdown",
        help="Output format (default: markdown).",
    )
    parser.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM contract inference.")
    parser.add_argument("--no-mumei", action="store_true", help="Skip mumei verify.")
    return parser


def build_validate_code_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    """Add validate-code arguments to an argparse parser."""
    parser = parser or argparse.ArgumentParser(
        description="Infer and verify contracts from existing code (Python, Rust, TypeScript, Go, Solidity)."
    )
    source_arg = parser.add_mutually_exclusive_group(required=True)
    source_arg.add_argument("--input", dest="input", help="Path to source code.")
    source_arg.add_argument("--file", dest="input", help=argparse.SUPPRESS)
    parser.add_argument(
        "--language",
        choices=["python", "rust", "typescript", "go", "solidity"],
        default=None,
        help="Target language. 省略時は --input の拡張子から推定する。",
    )
    parser.add_argument("--output", help="Optional JSON report path.")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM contract inference.")
    parser.add_argument("--no-mumei", action="store_true", help="Skip mumei verify.")
    parser.add_argument(
        "--enable-lean-bridge",
        action="store_true",
        help="Run the optional mumei-lean bridge for Solidity guard-trace certificates.",
    )
    parser.add_argument(
        "--mumei-lean-repo",
        default=None,
        help="Path to the mumei-lean checkout used by --enable-lean-bridge.",
    )
    return parser


def main_validate_spec(args: argparse.Namespace | None = None) -> NLSpecValidationResult:
    """CLI entrypoint for validate-spec."""
    if args is None:
        args = build_validate_spec_parser().parse_args()
    spec_text = _read_input_file(args.input)
    result = validate_nl_spec(
        spec_text,
        use_llm=not args.no_llm,
        run_mumei=not args.no_mumei,
        domain_hint=getattr(args, "domain", ""),
    )
    _emit_validate_spec_result(result, args.output, getattr(args, "format", "nl"))
    if not result.success:
        sys.exit(1)
    return result


def _check_nl_result_pairs_for_conflicts(
    results: list[NLSpecValidationResult],
) -> list[CrossValidationIssue]:
    conflicts: list[CrossValidationIssue] = []
    for left_index, left in enumerate(results):
        for right_index in range(left_index + 1, len(results)):
            right = results[right_index]
            combined_atoms = [*left.inferred_atoms, *right.inferred_atoms]
            if not combined_atoms:
                continue
            params = {
                param.name: param.type
                for atom in combined_atoms
                for param in atom.params
            }
            combined = MumeiContractAtom(
                name=f"nl_spec_{left_index + 1}_vs_{right_index + 1}",
                params=[
                    ContractParam(name=name, type=param_type)
                    for name, param_type in sorted(params.items())
                ],
                requires=_join_clauses(atom.requires for atom in combined_atoms),
                ensures=_join_clauses(atom.ensures for atom in combined_atoms),
            )
            _, pair_issues, _ = _check_atoms_with_z3([combined])
            for issue in pair_issues:
                conflicts.append(
                    CrossValidationIssue(
                        kind=issue.kind,
                        message=(
                            f"NL spec documents {left_index + 1} and {right_index + 1} "
                            f"are inconsistent: {issue.message}"
                        ),
                        evidence=issue.evidence,
                        fix_suggestion=_suggest_fix(issue.kind, issue.message, issue.evidence),
                        location=f"spec[{left_index}],spec[{right_index}]",
                        severity=issue.severity,
                    )
                )
    return _dedupe_issues(conflicts)


def _join_clauses(clauses: Iterable[str]) -> str:
    parts = [
        str(clause).strip().rstrip(";")
        for clause in clauses
        if str(clause).strip() and str(clause).strip().lower() != "true"
    ]
    return " && ".join(parts) if parts else "true"


def main_validate_spec_to_code(args: argparse.Namespace | None = None) -> SpecCodeAlignmentResult:
    """CLI entrypoint for validate-spec-to-code."""
    if args is None:
        args = build_validate_spec_to_code_parser().parse_args()
    spec_text = _read_input_file(args.spec)
    result = validate_spec_to_code(
        spec_text,
        args.code,
        language=args.language,
        use_llm=not args.no_llm,
        run_mumei=not args.no_mumei,
        lang=args.lang,
    )
    output_format = "json" if getattr(args, "json", False) else args.format
    _emit_cross_validation_result(
        result,
        args.output,
        output_format=output_format,
        lang=args.lang,
    )
    if not result.success:
        sys.exit(1)
    return result


def main_validate_code_to_spec(args: argparse.Namespace | None = None) -> SpecDriftResult:
    """CLI entrypoint for validate-code-to-spec."""
    if args is None:
        args = build_validate_code_to_spec_parser().parse_args()
    result = validate_code_to_spec(
        args.code,
        args.spec,
        language=args.language,
        use_llm=not args.no_llm,
        run_mumei=not args.no_mumei,
        lang=args.lang,
    )
    output_format = "json" if getattr(args, "json", False) else args.format
    _emit_cross_validation_result(
        result,
        args.output,
        output_format=output_format,
        lang=args.lang,
    )
    if not result.success:
        sys.exit(1)
    return result


def _infer_validate_code_language(input_path: str, language: str | None) -> str:
    """Infer language for validate-code from the file extension.

    Unlike ``_infer_language_from_path`` (which falls back to ``python``),
    this helper raises a clear error for unsupported extensions so that
    users are never silently assigned a wrong language.
    """
    if language:
        return _normalize_foreign_language(language)
    suffix = Path(input_path).suffix.lower()
    ext_map: dict[str, str] = {
        ".py": "python",
        ".rs": "rust",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "typescript",
        ".jsx": "typescript",
        ".go": "go",
        ".sol": "solidity",
    }
    detected = ext_map.get(suffix)
    if detected is None:
        supported = sorted(SUPPORTED_FOREIGN_CODE_LANGUAGES)
        print(
            f"Error: cannot infer language from extension '{suffix}'. "
            f"Supported languages: {', '.join(supported)}. "
            f"Use --language to specify explicitly.",
            file=sys.stderr,
        )
        sys.exit(1)
    return detected


def main_validate_code(args: argparse.Namespace | None = None) -> ForeignCodeValidationResult:
    """CLI entrypoint for validate-code."""
    if args is None:
        args = build_validate_code_parser().parse_args()
    language = _infer_validate_code_language(args.input, args.language)
    code = _read_input_file(args.input)
    config = AgentConfig(mumei_lean_repo=getattr(args, "mumei_lean_repo", None))
    result = validate_foreign_code(
        code,
        language,
        config=config,
        use_llm=not args.no_llm,
        run_mumei=not args.no_mumei,
        enable_lean_bridge=bool(getattr(args, "enable_lean_bridge", False)),
    )
    _emit_result(result, args.output)
    if result.verdict == "refuted":
        sys.exit(1)
    if result.verdict == "unverifiable":
        sys.exit(2)
    return result










def _infer_nl_contracts_with_llm(
    spec_text: str,
    config: AgentConfig,
    *,
    llm_provider: LLMProvider | None = None,
) -> tuple[list[MumeiContractAtom], list[CrossValidationIssue], list[str]]:
    prompt = build_nl_cross_validation_prompt(spec_text)
    return _infer_contracts_with_llm(
        config, CROSS_VALIDATION_NL_SYSTEM_PROMPT, prompt, llm_provider=llm_provider,
    )


def _infer_code_contracts_with_llm(
    code: str,
    language: str,
    config: AgentConfig,
    *,
    llm_provider: LLMProvider | None = None,
) -> tuple[list[MumeiContractAtom], list[CrossValidationIssue], list[str]]:
    prompt = build_code_cross_validation_prompt(code, language)
    return _infer_contracts_with_llm(
        config, CROSS_VALIDATION_CODE_SYSTEM_PROMPT, prompt, llm_provider=llm_provider,
    )


def _infer_contracts_with_llm(
    config: AgentConfig,
    system_prompt: str,
    user_prompt: str,
    *,
    llm_provider: LLMProvider | None = None,
) -> tuple[list[MumeiContractAtom], list[CrossValidationIssue], list[str]]:
    warnings: list[str] = []
    try:
        provider = llm_provider or OpenAILLMProvider(config)
        content = provider.complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            config.model,
        )
        payload = _json_from_text(content)
        return _atoms_from_payload(payload), _issues_from_payload(payload), warnings
    except Exception as exc:
        warnings.append(f"LLM contract inference skipped or failed: {exc}")
        return [], [], warnings
























def _issue_evidence(issues: list[CrossValidationIssue]) -> list[str]:
    return [issue.evidence for issue in issues if issue.evidence]


def _fix_suggestions(issues: Iterable[CrossValidationIssue]) -> list[str]:
    suggestions: list[str] = []
    seen: set[str] = set()
    for issue in issues:
        suggestion = issue.fix_suggestion.strip() or _suggest_fix(
            issue.kind,
            issue.message,
            issue.evidence,
        )
        if suggestion and suggestion not in seen:
            seen.add(suggestion)
            suggestions.append(suggestion)
    return suggestions


def _with_fix_suggestions(issues: list[CrossValidationIssue]) -> list[CrossValidationIssue]:
    return [
        issue
        if issue.fix_suggestion
        else replace(
            issue,
            fix_suggestion=_suggest_fix(issue.kind, issue.message, issue.evidence),
        )
        for issue in issues
    ]








































































def _verify_atoms_with_mumei(
    atoms: list[MumeiContractAtom],
    config: AgentConfig,
    *,
    skipped_clause_warnings: list[str] | None = None,
) -> tuple[dict[str, object] | None, list[CrossValidationIssue], list[str]]:
    source = _atoms_to_mumei_module(atoms)
    warnings: list[str] = []
    issues: list[CrossValidationIssue] = []
    with tempfile.TemporaryDirectory(prefix="mumei-cross-validation-") as tmp:
        module_path = Path(tmp) / "cross_validation.mm"
        report_dir = Path(tmp) / "report"
        module_path.write_text(source, encoding="utf-8")
        try:
            result = create_mumei_client(config.mumei_bin).verify(
                str(module_path),
                report_dir=str(report_dir),
            )
        except FileNotFoundError:
            warnings.append(f"mumei verify skipped because `{config.mumei_bin}` was not found.")
            return None, issues, warnings
    if result.get("success") is False:
        # A genuine mumei refutation (status "failed" / failed > 0) must be
        # reported as a real failure even when the agent skipped some clauses:
        # skipped clauses are removed from the module, so any mumei failure is a
        # genuine refutation of the clauses that *were* included (#304). Only when
        # mumei did not actually fail is the result truly inconclusive.
        mumei_failed = _mumei_report_has_failures(result.get("report"))
        inconclusive_due_to_skipped_clauses = (
            bool(skipped_clause_warnings) and not mumei_failed
        )
        if inconclusive_due_to_skipped_clauses:
            message = (
                "mumei verify returned an inconclusive result because unsupported "
                "Z3 clauses were skipped."
            )
        else:
            message = "mumei verify reported an unsatisfied or inconsistent inferred contract."
            if skipped_clause_warnings:
                message += (
                    f" ({len(skipped_clause_warnings)} additional clause(s) could "
                    "not be lowered and were not checked.)"
                )
        issues.append(
            CrossValidationIssue(
                kind="verification",
                message=message,
                evidence=str(result.get("stderr") or result.get("stdout") or result.get("report") or ""),
            )
        )
    return result, issues, warnings


def _mumei_report_has_failures(report: object) -> bool:
    """True when a mumei verify report is a genuine refutation, not just skips."""
    if not isinstance(report, dict):
        return False
    try:
        failed = int(report.get("failed") or 0)
    except (TypeError, ValueError):
        failed = 0
    return failed > 0 or report.get("status") == "failed"


def _has_skipped_z3_clause_warnings(warnings: list[str]) -> bool:
    return any(warning.startswith("Skipped unsupported Z3 clause:") for warning in warnings)


def _validate_foreign_code_verdict(
    *,
    atoms: list[MumeiContractAtom],
    errors: list[str],
    issues: list[CrossValidationIssue],
    satisfiable: bool | None,
    verification: dict[str, object] | None,
    warnings: list[str],
) -> ForeignCodeVerdict:
    if errors or not atoms:
        return "unverifiable"
    skipped_clause_warnings = _has_skipped_z3_clause_warnings(warnings)
    verification_failed = verification is not None and verification.get("success") is False
    mumei_genuinely_failed = verification is not None and _mumei_report_has_failures(
        verification.get("report")
    )
    if (
        verification is not None
        and verification_failed
        and skipped_clause_warnings
        and not mumei_genuinely_failed
        and not any(issue.kind != "verification" for issue in issues)
    ):
        return "unverifiable"
    if issues or satisfiable is False or verification_failed:
        return "refuted"
    return "verified"
