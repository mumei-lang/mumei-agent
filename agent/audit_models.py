"""Audit result models and protocols."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from agent.code_to_spec import CodeToSpecResult, Language
from agent.cross_validation_models import ForeignCodeVerdict
from agent.strategies.cross_validation_strategy import CrossValidationReport, CrossValidator
from agent.strategies.foreign_code_strategy import ForeignCodeVerifier
from agent.strategies.spec_health_strategy import SpecHealthChecker


@dataclass
class AuditResult:
    success: bool
    source_file: str
    language: str
    spec_extracted: bool
    verification_status: ForeignCodeVerdict | None = field(default=None, kw_only=True)
    spec_health_issues: list[str] = field(default_factory=list)
    verification_violations: list[str] = field(default_factory=list)
    counterexample_values: list[dict] = field(default_factory=list)
    cross_validation_gaps: list[str] = field(default_factory=list)
    migration_hints: list[dict] = field(default_factory=list)
    healed_files: list[str] = field(default_factory=list)
    heal_errors: list[str] = field(default_factory=list)
    next_steps: list[dict] = field(default_factory=list)
    proof_certificate: dict[str, object] | None = None
    lean_bridge: dict[str, object] | None = None
    report: str = ""
    errors: list[str] = field(default_factory=list)
    skipped_rate_limited: bool = False

@dataclass
class AuditDirectoryResult:
    """Result of auditing a directory of source files."""

    success: bool
    source_dir: str
    language: str
    file_results: list[AuditResult] = field(default_factory=list)
    summary: str = ""
    total_files: int = 0
    files_with_issues: int = 0
    next_steps: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped_rate_limited_files: list[str] = field(default_factory=list)

class CodeToSpecExtractorLike(Protocol):
    def extract_from_file(
        self,
        code_path: Path,
        language: Language | None = None,
        *,
        domain_hint: str = "",
        mumei_client: object | None = None,
        max_retries: int = 3,
    ) -> CodeToSpecResult:
        ...

class MumeiVerifyClientLike(Protocol):
    def verify(
        self,
        source_path: str,
        report_dir: str | None = None,
        extra_args: list[str] | None = None,
        spec_code_mapping: list[dict] | None = None,
        collect_decidable_metrics: bool = False,
    ) -> dict[str, object]:
        ...

class ForeignCodeVerifierLike(Protocol):
    def verify(self, source_code: str, language: str) -> dict[str, object]:
        ...

class CrossValidatorLike(Protocol):
    def validate_spec_vs_impl(
        self,
        spec_path: str,
        impl_path: str,
        language: str,
    ) -> CrossValidationReport:
        ...
