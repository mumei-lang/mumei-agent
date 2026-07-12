"""Audit existing foreign-language code through the Mumei verification stack."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import cast

from agent import telemetry
from agent.audit_models import (
    AuditDirectoryResult,
    AuditResult,
    CodeToSpecExtractorLike,
    CrossValidatorLike,
    ForeignCodeVerifierLike,
    MumeiVerifyClientLike,
)
from agent.audit_reporting import (
    _append_text_next_step,
    _aggregate_directory_next_steps,
    _build_directory_report,
    _build_markdown_report,
    _build_report,
    _contract_text,
    _counterexample_function_name,
    _counterexample_reports,
    _counterexample_value_dicts,
    _dedupe_counterexample_values,
    _cross_validation_gap_strings,
    _diagnostic_strings,
    _default_literal,
    _directory_file_label,
    _directory_result_to_markdown,
    _dedupe_strings,
    _dict_list,
    _dict_value,
    _file_result_to_markdown,
    _finalize_audit_result,
    _forge_atom_to_mumei,
    _forge_task_to_mumei_source,
    _format_params,
    _format_result,
    _generate_directory_next_steps,
    _generate_next_steps,
    _markdown_bullet_lines,
    _markdown_cell,
    _markdown_findings_row,
    _markdown_items_text,
    _markdown_issue_lines,
    _markdown_next_step_lines,
    _malformed_extraction_issue_strings,
    _migration_issue_dicts,
    _pluralize,
    _read_json_dict,
    _result_report,
    _result_to_markdown,
    _safe_identifier,
    _shorten,
    _spec_health_issue_strings,
    _string_list,
    _string_value,
    _verification_issue_strings,
    _verification_status_from_foreign_result,
)
from agent.code_to_spec import CodeToSpecExtractor, CodeToSpecResult, Language
from agent.config import AgentConfig
from agent.extract_spec import _collect_code_files
from agent.lean_bridge_helpers import run_lean_bridge_and_merge_proof_cert
from agent.llm_provider import LLMProvider
from agent.mumei_client import create_mumei_client
from agent.prompts.report_formatter import format_counterexample
from agent.strategies.cross_validation_strategy import CrossValidationReport, CrossValidator
from agent.strategies.foreign_code_strategy import ForeignCodeVerifier
from agent.strategies.foreign_code_strategy_helpers import (
    build_solidity_guard_trace_proof_certificate,
)
from agent.strategies.spec_health_strategy import SpecHealthChecker, SpecHealthReport

SUPPORTED_AUDIT_LANGUAGES = ("python", "rust", "typescript", "go", "solidity")

AUDIT_EXTENSION_MAP: dict[str, Language] = {
    ".py": "python",
    ".rs": "rust",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".sol": "solidity",
}

AUDIT_SCHEMA_KEYS = [
    "spec_health_issues",
    "verification_violations",
    "verification_status",
    "cross_validation_gaps",
    "next_steps",
    "migration_hints",
    "healed_files",
    "heal_errors",
]

AUDIT_CONTRACT_TERMS = {
    "spec_health_issues": "spec-only contradictions, overconstraints, vacuity, or ambiguity",
    "verification_violations": "existing-code bugs or unsafe paths found before .mm migration",
    "verification_status": "machine-readable code-safety verdict for the audited source: verified, refuted, or unverifiable",
    "cross_validation_gaps": "spec/code mismatches or cross-spec drift discovered during audit",
    "next_steps": "human-review entrypoint for audit -> migrate-suggest -> heal",
    "migration_hints": "generated .mm skeleton advice from migrate-suggest or audit --auto-migrate",
    "healed_files": "generated .mm skeletons accepted or rewritten by the self-healing loop",
    "heal_errors": "per-skeleton self-healing failures and diagnostics",
    "contradiction_type": "stable spec contradiction classifier",
}

class AuditPipeline:
    """Run code-to-spec, spec-health, foreign verification, and cross-validation."""

    def __init__(
        self,
        config: AgentConfig | None = None,
        *,
        code_to_spec_extractor: CodeToSpecExtractorLike | None = None,
        spec_health_checker: SpecHealthChecker | None = None,
        foreign_code_verifier: ForeignCodeVerifierLike | None = None,
        cross_validator: CrossValidatorLike | None = None,
        mumei_client: MumeiVerifyClientLike | None = None,
        heal_output_dir: str | None = None,
        client: object | None = None,
        llm_provider: LLMProvider | None = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.mumei_client = mumei_client or create_mumei_client(self.config.mumei_bin)
        self.code_to_spec_extractor = code_to_spec_extractor or CodeToSpecExtractor(
            self.config, client=client, llm_provider=llm_provider,
        )
        self.spec_health_checker = spec_health_checker or SpecHealthChecker()
        self.foreign_code_verifier = foreign_code_verifier or ForeignCodeVerifier(
            mumei_bin=self.config.mumei_bin,
        )
        self.cross_validator = cross_validator or CrossValidator()
        self.heal_output_dir = Path(heal_output_dir).expanduser() if heal_output_dir else None

    def audit_file(
        self,
        source_file: str | Path,
        language: str | None = None,
        *,
        domain_hint: str = "",
        auto_migrate: bool = False,
        auto_heal: bool = False,
        enable_lean_bridge: bool = False,
    ) -> AuditResult | AuditDirectoryResult:
        source_path = Path(source_file).expanduser().resolve()
        if source_path.is_dir():
            return self.audit_directory(
                source_path,
                language,
                domain_hint=domain_hint,
                auto_migrate=auto_migrate,
                auto_heal=auto_heal,
                enable_lean_bridge=enable_lean_bridge,
            )
        with telemetry.start_span(
            "mumei.audit.file",
            **{"mumei.audit.language": _normalize_language(language) or None},
        ) as _span:
            result = self._audit_file_inner(
                source_path,
                language,
                domain_hint=domain_hint,
                auto_migrate=auto_migrate,
                auto_heal=auto_heal,
                enable_lean_bridge=enable_lean_bridge,
            )
            telemetry.set_span_attributes(
                _span,
                {
                    "mumei.audit.language": result.language or None,
                    "mumei.audit.success": result.success,
                    "mumei.audit.violations": len(result.verification_violations),
                },
            )
            return result

    def _audit_file_inner(
        self,
        source_path: Path,
        language: str | None = None,
        *,
        domain_hint: str = "",
        auto_migrate: bool = False,
        auto_heal: bool = False,
        enable_lean_bridge: bool = False,
    ) -> AuditResult:
        source_label = str(source_path)
        normalized_language = _normalize_language(language)
        errors: list[str] = []
        show_step_logs = auto_migrate or auto_heal
        if show_step_logs:
            print(
                "[Step 1/3] Extracting spec and verifying contracts...",
                file=sys.stderr,
            )

        try:
            source_code = source_path.read_text(encoding="utf-8")
        except OSError as exc:
            result = AuditResult(
                success=False,
                source_file=source_label,
                language=normalized_language,
                spec_extracted=False,
                verification_status="unverifiable",
                errors=[f"Failed to read source file: {exc}"],
            )
            return _finalize_audit_result(result)

        if normalized_language and normalized_language not in SUPPORTED_AUDIT_LANGUAGES:
            result = AuditResult(
                success=False,
                source_file=source_label,
                language=normalized_language,
                spec_extracted=False,
                verification_status="unverifiable",
                errors=[
                    "language must be one of: "
                    + ", ".join(SUPPORTED_AUDIT_LANGUAGES)
                ],
            )
            return _finalize_audit_result(result)

        language_hint = cast(Language | None, normalized_language or None)
        extraction = self.code_to_spec_extractor.extract_from_file(
            source_path,
            language_hint,
            domain_hint=domain_hint,
            mumei_client=self.mumei_client,
            max_retries=self.config.max_retries,
        )
        audit_language = _normalize_language(extraction.detected_language) or normalized_language
        if not extraction.success or extraction.forge_task_spec is None:
            errors.extend(extraction.errors)
            result = AuditResult(
                success=False,
                source_file=source_label,
                language=audit_language,
                spec_extracted=False,
                verification_status="unverifiable",
                errors=errors,
                skipped_rate_limited=_errors_indicate_rate_limit(extraction.errors),
            )
            return _finalize_audit_result(result)

        malformed_extraction_issues = _malformed_extraction_issue_strings(
            extraction.forge_task_spec
        )
        spec_source = _forge_task_to_mumei_source(extraction.forge_task_spec)
        if not spec_source:
            errors.append("No Mumei atoms were generated from the extracted forge task spec.")

        spec_health_issues: list[str] = malformed_extraction_issues
        verification_violations: list[str] = []
        counterexample_values: list[dict] = []
        cross_validation_gaps: list[str] = []
        verification_status: str | None = None

        with tempfile.TemporaryDirectory(prefix="mumei-audit-") as tmp:
            spec_path = Path(tmp) / "audit_spec.mm"
            if spec_source and not malformed_extraction_issues:
                spec_path.write_text(spec_source, encoding="utf-8")
                health_report = self._check_spec_health(spec_path, tmp)
                spec_health_issues = _spec_health_issue_strings(health_report)

            proof_certificate = (
                build_solidity_guard_trace_proof_certificate(
                    source_code,
                    source_file=source_label,
                    package_name=source_path.stem,
                    package_version="0",
                    mumei_version="agent",
                )
                if audit_language == "solidity"
                else None
            )
            lean_bridge_result: dict[str, object] | None = None
            if enable_lean_bridge and proof_certificate is not None and self.config.mumei_lean_repo:
                proof_certificate, lean_bridge_result = (
                    run_lean_bridge_and_merge_proof_cert(
                        proof_certificate,
                        self.config.mumei_lean_repo,
                    )
                )

            try:
                foreign_result = self.foreign_code_verifier.verify(source_code, audit_language)
                verification_violations = _verification_issue_strings(foreign_result)
                counterexample_values = _counterexample_value_dicts(foreign_result)
                verification_status = _verification_status_from_foreign_result(
                    foreign_result,
                    counterexample_values=counterexample_values,
                    verification_violations=verification_violations,
                    spec_health_issues=spec_health_issues,
                )
            except ValueError as exc:
                verification_violations.append(str(exc))
                verification_status = "unverifiable"
            except FileNotFoundError as exc:
                verification_violations.append(f"mumei verify failed to start: {exc}")
                verification_status = "unverifiable"

            if malformed_extraction_issues and not counterexample_values:
                verification_status = "unverifiable"

            if spec_source and not malformed_extraction_issues:
                cross_report = self.cross_validator.validate_spec_vs_impl(
                    str(spec_path),
                    str(source_path),
                    audit_language,
                )
                cross_validation_gaps = _cross_validation_gap_strings(cross_report)

        success = (
            not errors
            and not spec_health_issues
            and not verification_violations
            and not cross_validation_gaps
        )
        result = AuditResult(
            success=success,
            source_file=source_label,
            language=audit_language,
            spec_extracted=True,
            verification_status=verification_status
            or _verification_status_from_foreign_result(None),
            spec_health_issues=spec_health_issues,
            verification_violations=verification_violations,
            counterexample_values=counterexample_values,
            cross_validation_gaps=cross_validation_gaps,
            errors=errors,
            proof_certificate=proof_certificate,
            lean_bridge=lean_bridge_result,
        )
        if (auto_migrate or auto_heal) and (verification_violations or cross_validation_gaps):
            from agent.mm_migration_advisor import suggest_migration_for_file

            migration_issues = _migration_issue_dicts(
                verification_violations,
                cross_validation_gaps,
            )
            hints = suggest_migration_for_file(
                source_label,
                audit_language,
                {"issues": migration_issues},
            )
            if show_step_logs:
                print(
                    "[Step 2/3] Generating .mm migration skeletons for "
                    f"{len(hints)} functions with issues...",
                    file=sys.stderr,
                )
            result.migration_hints = [asdict(hint) for hint in hints]
        if auto_heal and result.migration_hints:
            if show_step_logs:
                print(
                    "[Step 3/3] Running self-healing loop on generated skeletons...",
                    file=sys.stderr,
                )
            healed_files, heal_errors = self._heal_migration_hints(
                result.migration_hints,
                source_path,
            )
            result.healed_files = healed_files
            result.heal_errors = heal_errors
        return _finalize_audit_result(result)

    def audit_directory(
        self,
        source_dir: str | Path,
        language: str | None = None,
        *,
        domain_hint: str = "",
        auto_migrate: bool = False,
        auto_heal: bool = False,
        enable_lean_bridge: bool = False,
    ) -> AuditDirectoryResult:
        """Audit all supported source files in a directory.

        Wrapped in a ``mumei.audit.directory`` span; the per-file
        :meth:`audit_file` calls nest as ``mumei.audit.file`` child spans.
        """
        with telemetry.start_span(
            "mumei.audit.directory",
            **{"mumei.audit.language": _normalize_language(language) or None},
        ) as _span:
            result = self._audit_directory_inner(
                source_dir,
                language,
                domain_hint=domain_hint,
                auto_migrate=auto_migrate,
                auto_heal=auto_heal,
                enable_lean_bridge=enable_lean_bridge,
            )
            telemetry.set_span_attributes(
                _span,
                {
                    "mumei.audit.language": result.language or None,
                    "mumei.audit.success": result.success,
                    "mumei.audit.files_with_issues": result.files_with_issues,
                },
            )
            return result

    def _audit_directory_inner(
        self,
        source_dir: str | Path,
        language: str | None = None,
        *,
        domain_hint: str = "",
        auto_migrate: bool = False,
        auto_heal: bool = False,
        enable_lean_bridge: bool = False,
    ) -> AuditDirectoryResult:
        source_path = Path(source_dir).expanduser().resolve()
        source_label = str(source_path)
        normalized_language = _normalize_language(language)
        errors: list[str] = []

        if not source_path.exists():
            errors.append(f"code_file does not exist: {source_label}")
        elif not source_path.is_dir():
            errors.append(f"code_file is not a directory: {source_label}")

        if normalized_language and normalized_language not in SUPPORTED_AUDIT_LANGUAGES:
            errors.append(
                "language must be one of: " + ", ".join(SUPPORTED_AUDIT_LANGUAGES)
            )

        if errors:
            result = AuditDirectoryResult(
                success=False,
                source_dir=source_label,
                language=normalized_language or "mixed",
                errors=errors,
            )
            result.next_steps = _generate_directory_next_steps(result)
            result.summary = _build_directory_report(result)
            return result

        code_files = _collect_code_files(
            source_path,
            AUDIT_EXTENSION_MAP,
            normalized_language or None,
        )
        if not code_files:
            errors.append(f"no supported source-code files found in directory: {source_label}")

        file_results: list[AuditResult] = []
        for code_path in code_files:
            audit_language = normalized_language or AUDIT_EXTENSION_MAP.get(
                code_path.suffix.lower(),
                "",
            )
            try:
                file_result = self.audit_file(
                    code_path,
                    audit_language,
                    domain_hint=domain_hint,
                    auto_migrate=auto_migrate,
                    auto_heal=auto_heal,
                    enable_lean_bridge=enable_lean_bridge,
                )
            except Exception as exc:
                file_result = AuditResult(
                    success=False,
                    source_file=str(code_path),
                    language=audit_language,
                    spec_extracted=False,
                    errors=[f"audit failed: {exc}"],
                )
                file_result = _finalize_audit_result(file_result)
            if isinstance(file_result, AuditDirectoryResult):
                errors.append(f"nested directory returned unexpectedly: {code_path}")
                continue
            file_results.append(file_result)

        files_with_issues = sum(1 for file_result in file_results if not file_result.success)
        result = AuditDirectoryResult(
            success=not errors and files_with_issues == 0,
            source_dir=source_label,
            language=normalized_language or "mixed",
            file_results=file_results,
            total_files=len(file_results),
            files_with_issues=files_with_issues,
            errors=errors,
            skipped_rate_limited_files=[
                file_result.source_file
                for file_result in file_results
                if file_result.skipped_rate_limited
            ],
        )
        result.next_steps = _generate_directory_next_steps(result)
        result.summary = _build_directory_report(result)
        return result

    def _heal_migration_hints(
        self,
        migration_hints: list[dict],
        source_path: Path,
    ) -> tuple[list[str], list[str]]:
        output_dir = (self.heal_output_dir or source_path.parent).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        healed_files: list[str] = []
        heal_errors: list[str] = []
        for hint in migration_hints:
            function_name = _safe_identifier(_string_value(hint.get("function_name"), "audited_atom"))
            skeleton = _string_value(hint.get("skeleton"), "")
            if not skeleton.strip():
                heal_errors.append(f"{function_name}: migration skeleton is empty")
                continue
            target = output_dir / f"{function_name}.mm"
            target.write_text(skeleton.rstrip() + "\n", encoding="utf-8")
            try:
                self._run_heal_loop(target)
            except Exception as exc:
                heal_errors.append(f"{target}: {exc}")
                continue
            healed_files.append(str(target))
        return healed_files, heal_errors

    def _run_heal_loop(self, source_path: Path) -> None:
        from agent.self_healing import main as heal_main

        old_argv = sys.argv[:]
        stdout = io.StringIO()
        stderr = io.StringIO()
        sys.argv = [
            "mumei-agent",
            str(source_path),
            "--max-retries",
            str(self.config.max_retries),
        ]
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                heal_main()
        except SystemExit as exc:
            if exc.code not in (0, None):
                output = "\n".join(
                    part for part in (stdout.getvalue(), stderr.getvalue()) if part
                )
                raise RuntimeError(
                    _shorten(output or f"heal exited with status {exc.code}")
                ) from exc
        finally:
            sys.argv = old_argv
        backup_path = Path(str(source_path) + ".bak")
        try:
            backup_path.unlink()
        except FileNotFoundError:
            pass

    def audit_source(
        self,
        source_code: str,
        language: str,
        *,
        domain_hint: str = "",
    ) -> AuditResult:
        normalized_language = _normalize_language(language)
        extension = _extension_for_language(normalized_language)
        with telemetry.start_span(
            "mumei.audit.source",
            **{"mumei.audit.language": normalized_language or None},
        ) as _span:
            with tempfile.TemporaryDirectory(prefix="mumei-audit-source-") as tmp:
                source_path = Path(tmp) / f"inline_source{extension}"
                source_path.write_text(source_code, encoding="utf-8")
                result = self.audit_file(
                    source_path,
                    normalized_language,
                    domain_hint=domain_hint,
                )
            result = cast(AuditResult, result)
            result.source_file = f"<inline:{normalized_language}>"
            result = _finalize_audit_result(result)
            telemetry.set_span_attributes(
                _span,
                {
                    "mumei.audit.language": result.language or None,
                    "mumei.audit.success": result.success,
                    "mumei.audit.violations": len(result.verification_violations),
                },
            )
            return result

    def _check_spec_health(self, spec_path: Path, report_dir: str) -> SpecHealthReport:
        cert_path = str(Path(report_dir) / "audit_spec.proof.json")
        verify_result = self.mumei_client.verify(
            str(spec_path),
            report_dir=report_dir,
            extra_args=[
                "--enable-vacuity-check",
                "--proof-cert",
                "--output",
                cert_path,
            ],
        )
        proof_cert = _read_json_dict(Path(cert_path))
        return self.spec_health_checker.check_all(verify_result, proof_cert)

def build_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    _epilog = (
        "One-command migration/heal contract: "
        "mumei-agent audit --code-file <file-or-dir> --auto-migrate --auto-heal. "
        "The MCP scan_and_fix tool uses the same audit -> migrate-suggest -> heal flow. "
        "Fixed output keys: spec_health_issues, verification_violations, verification_status, "
        "cross_validation_gaps, next_steps, migration_hints, healed_files, heal_errors."
    )
    parser = parser or argparse.ArgumentParser(
        description=(
            "Audit existing code by extracting specs, verifying contracts, "
            "emitting cross_validation_gaps, and optionally producing migration_hints."
        ),
        epilog=_epilog,
    )
    if not parser.epilog:
        parser.epilog = _epilog
    parser.add_argument(
        "--code-file",
        required=True,
        help="Path to existing source code file or directory.",
    )
    parser.add_argument(
        "--language",
        choices=SUPPORTED_AUDIT_LANGUAGES,
        help="Source language. Inferred from the file extension when omitted.",
    )
    parser.add_argument("--json", action="store_true", help="Output the full result as JSON.")
    parser.add_argument(
        "--format",
        choices=["human", "markdown", "json", "text"],
        default="human",
        help="Output format (default: human).",
    )
    parser.add_argument("--output", help="Optional output path.")
    parser.add_argument("--domain-hint", default="", help="Optional domain hint for spec extraction.")
    parser.add_argument(
        "--auto-migrate",
        action="store_true",
        help="Emit migration_hints by generating .mm migration skeletons for functions with issues.",
    )
    parser.add_argument(
        "--auto-heal",
        action="store_true",
        help="Run the self-healing loop on each skeleton produced by --auto-migrate.",
    )
    parser.add_argument(
        "--heal-output-dir",
        default=None,
        help="Directory to write healed .mm files (default: same directory as --code-file).",
    )
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

def main(args: argparse.Namespace | None = None) -> AuditResult | AuditDirectoryResult:
    args = args or build_parser().parse_args()
    config = AgentConfig(mumei_lean_repo=getattr(args, "mumei_lean_repo", None))
    result = AuditPipeline(config=config, heal_output_dir=args.heal_output_dir).audit_file(
        args.code_file,
        args.language,
        domain_hint=args.domain_hint,
        auto_migrate=args.auto_migrate,
        auto_heal=args.auto_heal,
        enable_lean_bridge=bool(getattr(args, "enable_lean_bridge", False)),
    )
    output_format = "json" if args.json else args.format
    payload = _format_result(result, output_format)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return result

_RATE_LIMIT_MARKERS = (
    "error code: 429",
    "rate limit",
    "rate_limit",
    "tokens per min",
    "too many requests",
    "retry-after",
)


def _errors_indicate_rate_limit(errors: list[str]) -> bool:
    """True when an extraction error looks like an exhausted LLM rate limit.

    When the SDK's retries (which honor ``Retry-After``) are exhausted on a
    429, the failure surfaces as an opaque error string. Recognizing it lets a
    file be marked ``skipped_rate_limited`` instead of silently degrading into
    a generic unverifiable result (#285).
    """
    for error in errors:
        lowered = error.lower()
        if any(marker in lowered for marker in _RATE_LIMIT_MARKERS):
            return True
    return False


def _normalize_language(language: str | None) -> str:
    if language is None:
        return ""
    normalized = language.strip().lower()
    aliases = {
        "py": "python",
        "rs": "rust",
        "ts": "typescript",
        "tsx": "typescript",
        "javascript": "typescript",
        "js": "typescript",
        "jsx": "typescript",
        "golang": "go",
        "sol": "solidity",
    }
    return aliases.get(normalized, normalized)

def _extension_for_language(language: str) -> str:
    if language == "rust":
        return ".rs"
    if language == "typescript":
        return ".ts"
    if language == "go":
        return ".go"
    if language == "solidity":
        return ".sol"
    return ".py"
