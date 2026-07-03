"""Cross-validation data models and shared enums."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from agent.intent_tracker import IntentDriftResult
from agent.spec_code_mapper import MappingResult

SUPPORTED_FOREIGN_CODE_LANGUAGES = {"python", "rust", "typescript", "go"}

ContradictionType = Literal[
    "",
    "spec_internal",
    "spec_overconstraint",
    "spec_vacuity",
    "spec_vs_code",
]

IssueKind = Literal[
    "contradiction",
    "ambiguity",
    "overconstraint",
    "satisfiability",
    "llm",
    "verification",
    "alignment",
    "missing_implementation",
    "postcondition_violated",
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
    source_line: int = 0
    fix_suggestion: str = ""

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
    completeness_warnings: list[str] = field(default_factory=list)
    vacuity_warnings: list[str] = field(default_factory=list)
    verification: dict[str, object] | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    contradiction_evidence: list[str] = field(default_factory=list)
    overconstraint_evidence: list[str] = field(default_factory=list)
    contradiction_type: ContradictionType = ""

@dataclass(frozen=True)
class ForeignCodeValidationResult:
    """Result of existing-code validation."""

    success: bool
    language: str
    inferred_atoms: list[MumeiContractAtom]
    mumei_source: str
    satisfiable: bool | None
    verification: dict[str, object] | None = None
    issues: list[CrossValidationIssue] = field(default_factory=list)
    source_line_map: dict[str, int] = field(default_factory=dict)
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
    missing_constraints: list[str]
    divergences: list[CrossValidationIssue]
    satisfiable: bool | None
    report: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    contradiction_type: ContradictionType = ""
    constraint_violations: list[dict[str, object]] = field(default_factory=list)
    extra_behaviors: list[str] = field(default_factory=list)
    missing_constraint_issues: list[CrossValidationIssue] = field(default_factory=list)
    cross_validation_gaps: list[str] = field(default_factory=list)
    next_steps: list[dict[str, str]] = field(default_factory=list)

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
    contradiction_type: ContradictionType = ""
    extracted_spec: str = ""
    spec_gaps: list[str] = field(default_factory=list)
    implementation_overages: list[str] = field(default_factory=list)
    cross_validation_gaps: list[str] = field(default_factory=list)
    next_steps: list[dict[str, str]] = field(default_factory=list)
    intent_drift: dict[str, object] | None = None

@dataclass(frozen=True)
class CrossValidationReport:
    """Integrated intent-drift, spec-code mapping, and verifier report."""

    success: bool
    drift_detected: bool
    validation: SpecDriftResult
    mapping: MappingResult
    intent_drift: IntentDriftResult
    issues: list[CrossValidationIssue]
    report: str = ""

CrossValidationResult = (
    NLSpecValidationResult
    | ForeignCodeValidationResult
    | SpecCodeAlignmentResult
    | SpecDriftResult
    | CrossValidationReport
)
