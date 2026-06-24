"""Bidirectional traceability summary for spec/code verification."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import tempfile
from typing import Literal

from agent.conformance_verifier import (
    ConformanceFinding,
    ConformanceVerificationResult,
    TraceabilityRow,
    verify_conformance,
)
from agent.config import AgentConfig
from agent.cross_validation import CrossValidationIssue, SpecDriftResult, validate_code_to_spec

ReportLang = Literal["auto", "en", "ja"]


@dataclass(frozen=True)
class TraceabilityResult:
    next_steps: list[dict[str, str]]
    success: bool
    code_path: str
    spec_path: str
    language: str
    conformance: dict[str, list[ConformanceFinding] | list[TraceabilityRow]]
    drift: dict[str, list[str] | list[CrossValidationIssue]]
    cross_validation_gaps: list[str]
    drift_score: float
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    report: str = ""


def verify_traceability(
    spec: str,
    code_path: str,
    *,
    config: AgentConfig | None = None,
    language: str | None = None,
    use_llm: bool = True,
    run_mumei: bool = True,
    spec_path: str | None = None,
    lang: ReportLang = "auto",
) -> TraceabilityResult:
    """Combine V1-C spec→code conformance and V1-D code→spec drift checks."""
    config = config or AgentConfig()
    conformance = verify_conformance(
        spec,
        code_path,
        config=config,
        language=language,
        use_llm=use_llm,
        run_mumei=run_mumei,
    )
    drift = _validate_drift(
        spec,
        code_path,
        config=config,
        language=language,
        use_llm=use_llm,
        run_mumei=run_mumei,
        spec_path=spec_path,
        lang=lang,
    )
    gaps = _combined_gaps(conformance, drift)
    resolved_spec_path = spec_path or drift.spec_path
    result = TraceabilityResult(
        next_steps=_next_steps(code_path, resolved_spec_path, gaps),
        success=conformance.success and drift.success and not gaps,
        code_path=code_path,
        spec_path=resolved_spec_path,
        language=drift.language or conformance.language,
        conformance={
            "unimplemented_conditions": conformance.unimplemented_conditions,
            "hidden_specifications": conformance.hidden_specifications,
            "traceability_matrix": conformance.traceability_matrix,
        },
        drift={
            "spec_gaps": drift.spec_gaps,
            "drift_issues": drift.drift_issues,
        },
        cross_validation_gaps=gaps,
        drift_score=_drift_score(drift),
        warnings=_dedupe_strings([*conformance.warnings, *drift.warnings]),
        errors=_dedupe_strings([*conformance.errors, *drift.errors]),
    )
    return replace(result, report=_format_report(result, lang))


def _validate_drift(
    spec: str,
    code_path: str,
    *,
    config: AgentConfig,
    language: str | None,
    use_llm: bool,
    run_mumei: bool,
    spec_path: str | None,
    lang: ReportLang,
) -> SpecDriftResult:
    if spec_path:
        return validate_code_to_spec(
            code_path,
            spec_path,
            config=config,
            language=language,
            use_llm=use_llm,
            run_mumei=run_mumei,
            lang=lang,
        )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as tmp:
        tmp.write(spec)
        generated_spec_path = tmp.name
    try:
        return validate_code_to_spec(
            code_path,
            generated_spec_path,
            config=config,
            language=language,
            use_llm=use_llm,
            run_mumei=run_mumei,
            lang=lang,
        )
    finally:
        try:
            Path(generated_spec_path).unlink()
        except OSError:
            pass


def _combined_gaps(
    conformance: ConformanceVerificationResult,
    drift: SpecDriftResult,
) -> list[str]:
    drift_issue_texts = [issue.evidence or issue.message for issue in drift.drift_issues]
    return _dedupe_strings(
        [
            *conformance.cross_validation_gaps,
            *drift.cross_validation_gaps,
            *drift.spec_gaps,
            *drift_issue_texts,
        ]
    )


def _drift_score(drift: SpecDriftResult) -> float:
    payload = drift.intent_drift or {}
    raw = payload.get("drift_score", 1.0)
    if isinstance(raw, int | float):
        return max(0.0, min(1.0, float(raw)))
    return 1.0


def _next_steps(code_path: str, spec_path: str, gaps: list[str]) -> list[dict[str, str]]:
    if not gaps:
        return []
    return [
        {
            "priority": "high",
            "action": "Review bidirectional traceability gaps before merge.",
            "command": (
                f"mumei-agent verify-traceability --code {code_path} "
                f"--spec {spec_path} --format human"
            ),
        }
    ]


def _format_report(result: TraceabilityResult, lang: ReportLang) -> str:
    from agent.report_formatter import format_result_report

    return format_result_report(result, "human", lang=lang)


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        stripped = value.strip()
        if stripped and stripped not in deduped:
            deduped.append(stripped)
    return deduped
