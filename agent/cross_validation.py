"""Cross-validation for natural-language specs and foreign-language code."""
from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass, field, replace
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Literal

import z3

from agent.ambiguity_detector import AmbiguityDetector
from agent.config import AgentConfig
from agent.mumei_client import create_mumei_client
from agent.prompts.cross_validation_code import (
    CROSS_VALIDATION_CODE_SYSTEM_PROMPT,
    build_code_cross_validation_prompt,
)
from agent.prompts.cross_validation_nl import (
    CROSS_VALIDATION_NL_SYSTEM_PROMPT,
    build_nl_cross_validation_prompt,
)


IssueKind = Literal[
    "contradiction",
    "ambiguity",
    "overconstraint",
    "satisfiability",
    "llm",
    "verification",
    "alignment",
    "missing_implementation",
    "drift",
]
Severity = Literal["warning", "error"]


@dataclass(frozen=True)
class CrossValidationIssue:
    """Issue found during cross validation."""

    kind: IssueKind
    message: str
    evidence: str = ""
    location: str = ""
    severity: Severity = "error"


@dataclass(frozen=True)
class ContractParam:
    """Mumei atom parameter inferred from NL specs or foreign code."""

    name: str
    type: str = "i64"


@dataclass(frozen=True)
class MumeiContractAtom:
    """Minimal Mumei contract atom used for satisfiability checks."""

    name: str
    params: list[ContractParam] = field(default_factory=list)
    return_type: str = "i64"
    requires: str = "true"
    ensures: str = "true"
    effects: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NLSpecValidationResult:
    """Result of natural-language spec validation."""

    success: bool
    contradictions: list[CrossValidationIssue]
    ambiguities: list[CrossValidationIssue]
    overconstraints: list[CrossValidationIssue]
    inferred_atoms: list[MumeiContractAtom]
    satisfiable: bool | None
    verification: dict[str, object] | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ForeignCodeValidationResult:
    """Result of foreign-code validation."""

    success: bool
    language: str
    inferred_atoms: list[MumeiContractAtom]
    mumei_source: str
    satisfiable: bool | None
    verification: dict[str, object] | None = None
    issues: list[CrossValidationIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SpecCodeAlignmentResult:
    """Result of validating that code implements a specification."""

    success: bool
    code_path: str
    language: str
    spec_atoms: list[MumeiContractAtom]
    code_atoms: list[MumeiContractAtom]
    missing_constraints: list[CrossValidationIssue]
    divergences: list[CrossValidationIssue]
    satisfiable: bool | None
    report: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SpecDriftResult:
    """Result of validating that a specification still matches code."""

    success: bool
    code_path: str
    spec_path: str
    language: str
    spec_atoms: list[MumeiContractAtom]
    code_atoms: list[MumeiContractAtom]
    drift_issues: list[CrossValidationIssue]
    changed_hunks: list[str]
    report: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


CrossValidationResult = (
    NLSpecValidationResult | ForeignCodeValidationResult | SpecCodeAlignmentResult | SpecDriftResult
)


def validate_nl_spec(
    spec_text: str,
    *,
    config: AgentConfig | None = None,
    use_llm: bool = True,
    run_mumei: bool = True,
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
    if use_llm and config.api_key:
        llm_atoms, llm_issues, llm_warnings = _infer_nl_contracts_with_llm(spec_text, config)
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
    overconstraints.extend(z3_issues)

    verification: dict[str, object] | None = None
    if run_mumei and atoms:
        verification, mumei_issues, mumei_warnings = _verify_atoms_with_mumei(atoms, config)
        warnings.extend(mumei_warnings)
        overconstraints.extend(mumei_issues)
        if verification is not None and verification.get("success") is False:
            satisfiable = False

    contradictions = _dedupe_issues(contradictions)
    ambiguities = _dedupe_issues(ambiguities)
    overconstraints = _dedupe_issues(overconstraints)
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
        verification=verification,
        warnings=warnings,
        errors=errors,
    )


def validate_spec_to_code(
    spec: str,
    code_path: str,
    *,
    config: AgentConfig | None = None,
    language: str | None = None,
    use_llm: bool = True,
    run_mumei: bool = True,
    lang: Literal["en", "ja"] = "en",
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
            missing_constraints=[],
            divergences=[],
            satisfiable=None,
            warnings=warnings,
            errors=errors,
            lang=lang,
        )

    spec_result = validate_nl_spec(spec, config=config, use_llm=use_llm, run_mumei=run_mumei)
    code_result = validate_foreign_code(
        code,
        normalized_language,
        config=config,
        use_llm=use_llm,
        run_mumei=run_mumei,
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
    warnings.extend(compare_warnings)
    satisfiable = _combine_satisfiability(spec_result.satisfiable, code_result.satisfiable)
    return _spec_code_result(
        code_path=code_path,
        language=normalized_language,
        spec_atoms=spec_result.inferred_atoms,
        code_atoms=code_result.inferred_atoms,
        missing_constraints=_dedupe_issues(missing),
        divergences=_dedupe_issues(divergences),
        satisfiable=satisfiable,
        warnings=warnings,
        errors=errors,
        lang=lang,
    )


def validate_code_to_spec(
    code_path: str,
    spec_path: str,
    *,
    config: AgentConfig | None = None,
    language: str | None = None,
    use_llm: bool = True,
    run_mumei: bool = True,
    lang: Literal["en", "ja"] = "en",
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
    )
    warnings.extend(alignment.warnings)
    errors.extend(alignment.errors)
    changed_hunks, diff_warnings = _git_diff_hunks(Path(code_path))
    warnings.extend(diff_warnings)
    if not changed_hunks:
        warnings.append("No git diff hunks found for the code path; comparing current code to spec only.")
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
        for issue in [*drift_missing, *drift_divergences]
    ]
    return _spec_drift_result(
        code_path=code_path,
        spec_path=spec_path,
        language=alignment.language,
        spec_atoms=alignment.spec_atoms,
        code_atoms=alignment.code_atoms,
        drift_issues=_dedupe_issues(drift_issues),
        changed_hunks=changed_hunks,
        warnings=warnings,
        errors=errors,
        lang=lang,
    )


def validate_foreign_code(
    code: str,
    language: str,
    *,
    config: AgentConfig | None = None,
    use_llm: bool = True,
    run_mumei: bool = True,
) -> ForeignCodeValidationResult:
    """Validate Rust, Python, or Go code by inferring and verifying contracts."""
    config = config or AgentConfig()
    normalized_language = language.strip().lower()
    warnings: list[str] = []
    errors: list[str] = []
    if normalized_language not in {"python", "rust", "go"}:
        errors.append("language must be one of: python, rust, go")
    if not code.strip():
        errors.append("code must be non-empty")
    if errors:
        return ForeignCodeValidationResult(
            success=False,
            language=normalized_language,
            inferred_atoms=[],
            mumei_source="",
            satisfiable=None,
            errors=errors,
        )

    atoms = _infer_foreign_contracts_with_patterns(code, normalized_language)
    llm_issues: list[CrossValidationIssue] = []
    if use_llm and config.api_key:
        llm_atoms, llm_issues, llm_warnings = _infer_code_contracts_with_llm(
            code,
            normalized_language,
            config,
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
    issues = _dedupe_issues([*llm_issues, *z3_issues])
    mumei_source = _atoms_to_mumei_module(atoms) if atoms else ""
    verification: dict[str, object] | None = None
    if run_mumei and atoms:
        verification, mumei_issues, mumei_warnings = _verify_atoms_with_mumei(atoms, config)
        warnings.extend(mumei_warnings)
        issues = _dedupe_issues([*issues, *mumei_issues])
        if verification is not None and verification.get("success") is False:
            satisfiable = False

    success = not errors and not issues and atoms and satisfiable is not False
    return ForeignCodeValidationResult(
        success=bool(success),
        language=normalized_language,
        inferred_atoms=atoms,
        mumei_source=mumei_source,
        satisfiable=satisfiable,
        verification=verification,
        issues=issues,
        warnings=warnings,
        errors=errors,
    )


def build_validate_spec_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    """Add validate-spec arguments to an argparse parser."""
    parser = parser or argparse.ArgumentParser(description="Validate natural-language specs.")
    parser.add_argument("--input", required=True, help="Path to the natural-language spec file.")
    parser.add_argument("--format", choices=["nl"], default="nl", help="Input format.")
    parser.add_argument("--output", help="Optional JSON report path.")
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
    parser.add_argument("--language", choices=["python", "rust", "go"], help="Source language.")
    parser.add_argument("--lang", choices=["en", "ja"], default="en", help="Report language.")
    parser.add_argument("--output", help="Optional report path.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown.")
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
    parser.add_argument("--language", choices=["python", "rust", "go"], help="Source language.")
    parser.add_argument("--lang", choices=["en", "ja"], default="en", help="Report language.")
    parser.add_argument("--output", help="Optional report path.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown.")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM contract inference.")
    parser.add_argument("--no-mumei", action="store_true", help="Skip mumei verify.")
    return parser


def build_validate_code_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    """Add validate-code arguments to an argparse parser."""
    parser = parser or argparse.ArgumentParser(description="Validate foreign-language code.")
    parser.add_argument("--input", required=True, help="Path to source code.")
    parser.add_argument("--language", required=True, choices=["python", "rust", "go"])
    parser.add_argument("--output", help="Optional JSON report path.")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM contract inference.")
    parser.add_argument("--no-mumei", action="store_true", help="Skip mumei verify.")
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
    )
    _emit_result(result, args.output)
    if not result.success:
        sys.exit(1)
    return result


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
    _emit_cross_validation_result(result, args.output, json_output=args.json)
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
    _emit_cross_validation_result(result, args.output, json_output=args.json)
    if not result.success:
        sys.exit(1)
    return result


def main_validate_code(args: argparse.Namespace | None = None) -> ForeignCodeValidationResult:
    """CLI entrypoint for validate-code."""
    if args is None:
        args = build_validate_code_parser().parse_args()
    code = _read_input_file(args.input)
    result = validate_foreign_code(
        code,
        args.language,
        use_llm=not args.no_llm,
        run_mumei=not args.no_mumei,
    )
    _emit_result(result, args.output)
    if not result.success:
        sys.exit(1)
    return result


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


def _emit_cross_validation_result(
    result: SpecCodeAlignmentResult | SpecDriftResult,
    output: str | None,
    *,
    json_output: bool = False,
) -> None:
    if json_output:
        _emit_result(result, output)
        return
    if output:
        Path(output).write_text(result.report + "\n", encoding="utf-8")
    print(result.report)


def _infer_nl_contracts_with_llm(
    spec_text: str,
    config: AgentConfig,
) -> tuple[list[MumeiContractAtom], list[CrossValidationIssue], list[str]]:
    prompt = build_nl_cross_validation_prompt(spec_text)
    return _infer_contracts_with_llm(config, CROSS_VALIDATION_NL_SYSTEM_PROMPT, prompt)


def _infer_code_contracts_with_llm(
    code: str,
    language: str,
    config: AgentConfig,
) -> tuple[list[MumeiContractAtom], list[CrossValidationIssue], list[str]]:
    prompt = build_code_cross_validation_prompt(code, language)
    return _infer_contracts_with_llm(config, CROSS_VALIDATION_CODE_SYSTEM_PROMPT, prompt)


def _infer_contracts_with_llm(
    config: AgentConfig,
    system_prompt: str,
    user_prompt: str,
) -> tuple[list[MumeiContractAtom], list[CrossValidationIssue], list[str]]:
    warnings: list[str] = []
    try:
        client = config.create_client()
        response = client.chat.completions.create(
            model=config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content or ""
        payload = _json_from_text(content)
        return _atoms_from_payload(payload), _issues_from_payload(payload), warnings
    except Exception as exc:
        warnings.append(f"LLM contract inference skipped or failed: {exc}")
        return [], [], warnings


def _json_from_text(text: str) -> dict[str, object]:
    stripped = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL)
    if fence_match:
        stripped = fence_match.group(1)
    elif not stripped.startswith("{"):
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            stripped = stripped[start : end + 1]
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise json.JSONDecodeError("expected JSON object", stripped, 0)
    return payload


def _atoms_from_payload(payload: dict[str, object]) -> list[MumeiContractAtom]:
    atoms_value = payload.get("atoms")
    if not isinstance(atoms_value, list):
        return []
    atoms: list[MumeiContractAtom] = []
    for index, atom_value in enumerate(atoms_value):
        if isinstance(atom_value, dict):
            atoms.append(_atom_from_mapping(atom_value, index))
    return atoms


def _atom_from_mapping(value: dict[object, object], index: int) -> MumeiContractAtom:
    name = _safe_identifier(_string_value(value, "name", f"cross_validation_{index}"))
    params = _params_from_value(value.get("params") or value.get("inputs"))
    return_type = _string_value(value, "return_type", "i64")
    requires = _contract_clause(value.get("requires"))
    ensures = _contract_clause(value.get("ensures"))
    effects = _string_list(value.get("effects"))
    return MumeiContractAtom(
        name=name,
        params=params,
        return_type=return_type,
        requires=requires,
        ensures=ensures,
        effects=effects,
    )


def _issues_from_payload(payload: dict[str, object]) -> list[CrossValidationIssue]:
    issues_value = payload.get("issues")
    if not isinstance(issues_value, list):
        return []
    issues: list[CrossValidationIssue] = []
    valid_kinds = {
        "contradiction",
        "ambiguity",
        "overconstraint",
        "satisfiability",
        "llm",
        "verification",
        "alignment",
        "missing_implementation",
        "drift",
    }
    for issue_value in issues_value:
        if not isinstance(issue_value, dict):
            continue
        kind_text = str(issue_value.get("kind") or "llm")
        kind: IssueKind = kind_text if kind_text in valid_kinds else "llm"
        severity_text = str(issue_value.get("severity") or "error")
        severity: Severity = "warning" if severity_text == "warning" else "error"
        issues.append(
            CrossValidationIssue(
                kind=kind,
                message=str(issue_value.get("message") or "LLM reported a cross-validation issue."),
                evidence=str(issue_value.get("evidence") or ""),
                location=str(issue_value.get("location") or ""),
                severity=severity,
            )
        )
    return issues


def _string_value(value: dict[object, object], key: str, default: str) -> str:
    raw = value.get(key)
    if raw is None:
        return default
    text = str(raw).strip()
    return text or default


def _params_from_value(value: object) -> list[ContractParam]:
    if not isinstance(value, list):
        return []
    params: list[ContractParam] = []
    for index, raw_param in enumerate(value):
        if isinstance(raw_param, dict):
            name = _safe_identifier(str(raw_param.get("name") or f"arg{index}"))
            type_name = str(raw_param.get("type") or "i64").strip() or "i64"
            params.append(ContractParam(name=name, type=type_name))
    return params


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _contract_clause(value: object) -> str:
    if isinstance(value, list):
        parts = [str(item).strip().rstrip(";") for item in value if str(item).strip()]
        return " && ".join(parts) if parts else "true"
    text = str(value or "true").strip().rstrip(";")
    return text or "true"


def _extract_inline_contract_atoms(spec_text: str) -> list[MumeiContractAtom]:
    requires_match = re.search(r"requires\s*:\s*([^;\n]+)", spec_text, flags=re.IGNORECASE)
    ensures_match = re.search(r"ensures\s*:\s*([^;\n]+)", spec_text, flags=re.IGNORECASE)
    if not requires_match and not ensures_match:
        return []
    return [
        MumeiContractAtom(
            name="nl_spec_contract",
            params=_params_from_contract_text(spec_text),
            return_type="i64",
            requires=requires_match.group(1).strip() if requires_match else "true",
            ensures=ensures_match.group(1).strip() if ensures_match else "true",
        )
    ]


def _params_from_contract_text(text: str) -> list[ContractParam]:
    names = sorted(
        name
        for name in set(re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", text))
        if name
        not in {
            "and",
            "or",
            "true",
            "false",
            "requires",
            "ensures",
            "result",
            "i64",
            "MAX",
            "MIN",
        }
    )
    return [ContractParam(name=name, type="i64") for name in names[:8]]


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
            issues.append(
                CrossValidationIssue(
                    kind="contradiction",
                    message="Requirement states both a condition and its negation.",
                    evidence=f"{seen_positive[normalized]} / {fragment.strip()}",
                )
            )
        if not negated and normalized in seen_negative:
            issues.append(
                CrossValidationIssue(
                    kind="contradiction",
                    message="Requirement states both a condition and its negation.",
                    evidence=f"{fragment.strip()} / {seen_negative[normalized]}",
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
            issues.append(
                CrossValidationIssue(
                    kind="contradiction",
                    message="Requirement combines an always/must condition with a never/must-not condition.",
                    evidence=match.group(0),
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
        issues.append(
            CrossValidationIssue(
                kind="overconstraint",
                message="The specification explicitly describes an impossible implementation.",
                evidence="impossible/実装不可能",
            )
        )
    for atom in atoms:
        for label, clause in (("requires", atom.requires), ("ensures", atom.ensures)):
            if clause.strip().lower() == "false":
                issues.append(
                    CrossValidationIssue(
                        kind="overconstraint",
                        message=f"{atom.name}.{label} is explicitly false.",
                        evidence=clause,
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
        exprs: list[z3.BoolRef] = []
        symbols: dict[str, z3.IntNumRef | z3.ArithRef] = {}
        atom_warnings: list[str] = []
        for clause in (atom.requires, atom.ensures):
            parsed, clause_warnings = _clause_to_z3(clause, symbols)
            atom_warnings.extend(clause_warnings)
            exprs.extend(parsed)
        warnings.extend(atom_warnings)
        if not exprs:
            continue
        any_checked = True
        solver = z3.Solver()
        solver.add(*exprs)
        status = solver.check()
        if status == z3.unsat:
            all_satisfiable = False
            issues.append(
                CrossValidationIssue(
                    kind="satisfiability",
                    message=f"Inferred contract for atom `{atom.name}` is unsatisfiable.",
                    evidence=f"requires: {atom.requires}; ensures: {atom.ensures}",
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


def _infer_language_from_path(path: Path, language: str | None) -> str:
    if language:
        return language.strip().lower()
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix == ".rs":
        return "rust"
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
    base_ref = None
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
    missing_constraints: list[CrossValidationIssue],
    divergences: list[CrossValidationIssue],
    satisfiable: bool | None,
    warnings: list[str],
    errors: list[str],
    lang: Literal["en", "ja"],
) -> SpecCodeAlignmentResult:
    result = SpecCodeAlignmentResult(
        success=bool(
            not errors
            and spec_atoms
            and code_atoms
            and not missing_constraints
            and not divergences
            and satisfiable is not False
        ),
        code_path=code_path,
        language=language,
        spec_atoms=spec_atoms,
        code_atoms=code_atoms,
        missing_constraints=missing_constraints,
        divergences=divergences,
        satisfiable=satisfiable,
        warnings=warnings,
        errors=errors,
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
) -> SpecDriftResult:
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
    )
    from agent.report_formatter import format_cross_validation_report

    return replace(result, report=format_cross_validation_report(result, lang=lang))


def _clause_to_z3(
    clause: str,
    symbols: dict[str, z3.IntNumRef | z3.ArithRef],
) -> tuple[list[z3.BoolRef], list[str]]:
    normalized = clause.strip().rstrip(";")
    if not normalized or normalized.lower() == "true":
        return [], []
    if normalized.lower() == "false":
        return [z3.BoolVal(False)], []
    warnings: list[str] = []
    expressions: list[z3.BoolRef] = []
    for part in re.split(r"\s*&&\s*|\s+\band\b\s+", normalized):
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


def _infer_foreign_contracts_with_patterns(code: str, language: str) -> list[MumeiContractAtom]:
    if language == "python":
        return _infer_python_contracts(code)
    if language == "rust":
        return _infer_rust_contracts(code)
    if language == "go":
        return _infer_go_contracts(code)
    return []


def _infer_python_contracts(code: str) -> list[MumeiContractAtom]:
    atoms: list[MumeiContractAtom] = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return atoms
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            params = [ContractParam(name=arg.arg, type="i64") for arg in node.args.args]
            return_expr = _single_return_expr(node)
            ensures = f"result == {return_expr}" if return_expr else "true"
            requires = _safety_requires_for_expression(return_expr)
            atoms.append(
                MumeiContractAtom(
                    name=_safe_identifier(node.name),
                    params=params,
                    return_type="i64",
                    requires=requires,
                    ensures=ensures,
                )
            )
    return atoms


def _single_return_expr(function_node: ast.FunctionDef) -> str:
    returns = [node for node in ast.walk(function_node) if isinstance(node, ast.Return)]
    if len(returns) != 1:
        return ""
    value = returns[0].value
    if value is None:
        return ""
    try:
        return ast.unparse(value)
    except ValueError:
        return ""


def _safety_requires_for_expression(expression: str) -> str:
    if not expression:
        return "true"
    requirements: list[str] = []
    try:
        tree = ast.parse(expression, mode="eval")
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)):
                divisor = ast.unparse(node.right)
                requirements.append(f"{divisor} != 0")
    except (SyntaxError, ValueError):
        return "true"
    return " && ".join(requirements) if requirements else "true"


def _infer_rust_contracts(code: str) -> list[MumeiContractAtom]:
    atoms: list[MumeiContractAtom] = []
    pattern = re.compile(
        r"fn\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\((?P<params>[^)]*)\)\s*(?:->\s*(?P<ret>[A-Za-z0-9_:<>]+))?\s*\{(?P<body>.*?)\}",
        flags=re.DOTALL,
    )
    for match in pattern.finditer(code):
        params = _params_from_signature(match.group("params"))
        return_expr = _last_expression(match.group("body"))
        atoms.append(
            MumeiContractAtom(
                name=_safe_identifier(match.group("name")),
                params=params,
                return_type="i64" if match.group("ret") else "bool",
                requires=_safety_requires_for_expression(return_expr),
                ensures=f"result == {return_expr}" if return_expr else "true",
            )
        )
    return atoms


def _infer_go_contracts(code: str) -> list[MumeiContractAtom]:
    atoms: list[MumeiContractAtom] = []
    pattern = re.compile(
        r"func\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\((?P<params>[^)]*)\)\s*(?P<ret>[A-Za-z0-9_]+)?\s*\{(?P<body>.*?)\}",
        flags=re.DOTALL,
    )
    for match in pattern.finditer(code):
        params = _params_from_signature(match.group("params"))
        return_expr = _return_statement_expression(match.group("body"))
        atoms.append(
            MumeiContractAtom(
                name=_safe_identifier(match.group("name")),
                params=params,
                return_type="i64" if match.group("ret") else "bool",
                requires=_safety_requires_for_expression(return_expr),
                ensures=f"result == {return_expr}" if return_expr else "true",
            )
        )
    return atoms


def _params_from_signature(params_text: str) -> list[ContractParam]:
    params: list[ContractParam] = []
    for index, raw in enumerate(part.strip() for part in params_text.split(",") if part.strip()):
        pieces = raw.split(":")
        name = pieces[0].strip().split()[0] if pieces[0].strip() else f"arg{index}"
        params.append(ContractParam(name=_safe_identifier(name), type="i64"))
    return params


def _last_expression(body: str) -> str:
    stripped = body.strip().rstrip(";")
    if not stripped:
        return ""
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if not lines:
        return ""
    return _normalize_foreign_expression(lines[-1].removeprefix("return ").strip())


def _return_statement_expression(body: str) -> str:
    match = re.search(r"\breturn\s+([^;\n}]+)", body)
    return _normalize_foreign_expression(match.group(1).strip()) if match else ""


def _normalize_foreign_expression(expression: str) -> str:
    return expression.replace("&&", "and").replace("||", "or")


def _verify_atoms_with_mumei(
    atoms: list[MumeiContractAtom],
    config: AgentConfig,
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
        issues.append(
            CrossValidationIssue(
                kind="verification",
                message="mumei verify reported an unsatisfied or inconsistent inferred contract.",
                evidence=str(result.get("stderr") or result.get("stdout") or result.get("report") or ""),
            )
        )
    return result, issues, warnings


def _atoms_to_mumei_module(atoms: list[MumeiContractAtom]) -> str:
    blocks: list[str] = []
    for atom in atoms:
        params = ", ".join(f"{param.name}: {param.type}" for param in atom.params)
        default_value = _default_literal(atom.return_type)
        blocks.append(
            "\n".join(
                [
                    f"trusted atom {atom.name}({params}) -> {atom.return_type} {{",
                    f"    requires: {atom.requires};",
                    f"    ensures: {atom.ensures};",
                    "    body: {",
                    f"        {default_value}",
                    "    }",
                    "}",
                ]
            )
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _default_literal(return_type: str) -> str:
    normalized = return_type.strip().lower()
    if normalized in {"bool", "boolean"}:
        return "true"
    if normalized in {"str", "string"}:
        return '""'
    return "0"


def _safe_identifier(value: str) -> str:
    safe = re.sub(r"\W+", "_", value.strip())
    safe = safe.strip("_")
    if not safe:
        return "cross_validation_atom"
    if safe[0].isdigit():
        return f"atom_{safe}"
    return safe


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
