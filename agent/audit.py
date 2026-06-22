"""Audit existing foreign-language code through the Mumei verification stack."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol, cast

from agent.code_to_spec import CodeToSpecExtractor, CodeToSpecResult, Language
from agent.config import AgentConfig
from agent.extract_spec import _collect_code_files
from agent.mumei_client import create_mumei_client
from agent.prompts.report_formatter import format_counterexample
from agent.strategies.cross_validation_strategy import CrossValidationReport, CrossValidator
from agent.strategies.foreign_code_strategy import ForeignCodeVerifier
from agent.strategies.spec_health_strategy import SpecHealthChecker, SpecHealthReport


SUPPORTED_AUDIT_LANGUAGES = ("python", "rust", "typescript")
AUDIT_EXTENSION_MAP: dict[str, Language] = {
    ".py": "python",
    ".rs": "rust",
    ".ts": "typescript",
}

AUDIT_SCHEMA_KEYS = [
    "spec_health_issues",
    "verification_violations",
    "cross_validation_gaps",
    "next_steps",
    "migration_hints",
    "healed_files",
    "heal_errors",
]

AUDIT_CONTRACT_TERMS = {
    "spec_health_issues": "spec-only contradictions, overconstraints, vacuity, or ambiguity",
    "verification_violations": "existing-code bugs or unsafe paths found before .mm migration",
    "cross_validation_gaps": "spec/code mismatches or cross-spec drift discovered during audit",
    "next_steps": "ranked commands for audit -> migrate-suggest -> heal",
    "migration_hints": "generated .mm skeleton advice from migrate-suggest or audit --auto-migrate",
    "healed_files": "generated .mm skeletons accepted or rewritten by the self-healing loop",
    "heal_errors": "per-skeleton self-healing failures and diagnostics",
    "contradiction_type": "stable spec contradiction classifier",
}


@dataclass
class AuditResult:
    success: bool
    source_file: str
    language: str
    spec_extracted: bool
    spec_health_issues: list[str] = field(default_factory=list)
    verification_violations: list[str] = field(default_factory=list)
    counterexample_values: list[dict] = field(default_factory=list)
    cross_validation_gaps: list[str] = field(default_factory=list)
    migration_hints: list[dict] = field(default_factory=list)
    healed_files: list[str] = field(default_factory=list)
    heal_errors: list[str] = field(default_factory=list)
    next_steps: list[dict] = field(default_factory=list)
    report: str = ""
    errors: list[str] = field(default_factory=list)


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
    ) -> None:
        self.config = config or AgentConfig()
        self.mumei_client = mumei_client or create_mumei_client(self.config.mumei_bin)
        self.code_to_spec_extractor = code_to_spec_extractor or CodeToSpecExtractor(self.config)
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
    ) -> AuditResult | AuditDirectoryResult:
        source_path = Path(source_file).expanduser().resolve()
        if source_path.is_dir():
            return self.audit_directory(
                source_path,
                language,
                domain_hint=domain_hint,
                auto_migrate=auto_migrate,
                auto_heal=auto_heal,
            )
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
                errors=[f"Failed to read source file: {exc}"],
            )
            return _finalize_audit_result(result)

        if normalized_language and normalized_language not in SUPPORTED_AUDIT_LANGUAGES:
            result = AuditResult(
                success=False,
                source_file=source_label,
                language=normalized_language,
                spec_extracted=False,
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
                errors=errors,
            )
            return _finalize_audit_result(result)

        spec_source = _forge_task_to_mumei_source(extraction.forge_task_spec)
        if not spec_source:
            errors.append("No Mumei atoms were generated from the extracted forge task spec.")

        spec_health_issues: list[str] = []
        verification_violations: list[str] = []
        counterexample_values: list[dict] = []
        cross_validation_gaps: list[str] = []

        with tempfile.TemporaryDirectory(prefix="mumei-audit-") as tmp:
            spec_path = Path(tmp) / "audit_spec.mm"
            if spec_source:
                spec_path.write_text(spec_source, encoding="utf-8")
                health_report = self._check_spec_health(spec_path, tmp)
                spec_health_issues = _spec_health_issue_strings(health_report)

            try:
                foreign_result = self.foreign_code_verifier.verify(source_code, audit_language)
                verification_violations = _verification_issue_strings(foreign_result)
                counterexample_values = _counterexample_value_dicts(foreign_result)
            except ValueError as exc:
                verification_violations.append(str(exc))
            except FileNotFoundError as exc:
                verification_violations.append(f"mumei verify failed to start: {exc}")

            if spec_source:
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
            spec_health_issues=spec_health_issues,
            verification_violations=verification_violations,
            counterexample_values=counterexample_values,
            cross_validation_gaps=cross_validation_gaps,
            errors=errors,
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
    ) -> AuditDirectoryResult:
        """Audit all supported source files in a directory."""
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
        with tempfile.TemporaryDirectory(prefix="mumei-audit-source-") as tmp:
            source_path = Path(tmp) / f"inline_source{extension}"
            source_path.write_text(source_code, encoding="utf-8")
            result = self.audit_file(
                source_path,
                normalized_language,
                domain_hint=domain_hint,
            )
        result.source_file = f"<inline:{normalized_language}>"
        result = _finalize_audit_result(result)
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
    parser = parser or argparse.ArgumentParser(
        description=(
            "Audit existing code by extracting specs, verifying contracts, "
            "emitting cross_validation_gaps, and optionally producing migration_hints."
        ),
        epilog=(
            "One-command migration/heal contract: "
            "mumei-agent audit --code-file <file-or-dir> --auto-migrate --auto-heal. "
            "The MCP scan_and_fix tool uses the same audit -> migrate-suggest -> heal flow."
        ),
    )
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
        choices=["text", "markdown", "json"],
        default="text",
        help="Output format (default: text).",
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
    return parser


def main(args: argparse.Namespace | None = None) -> AuditResult | AuditDirectoryResult:
    args = args or build_parser().parse_args()
    result = AuditPipeline(heal_output_dir=args.heal_output_dir).audit_file(
        args.code_file,
        args.language,
        domain_hint=args.domain_hint,
        auto_migrate=args.auto_migrate,
        auto_heal=args.auto_heal,
    )
    output_format = "json" if args.json else args.format
    payload = _format_result(result, output_format)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return result


def _normalize_language(language: str | None) -> str:
    if language is None:
        return ""
    normalized = language.strip().lower()
    aliases = {
        "py": "python",
        "rs": "rust",
        "ts": "typescript",
        "javascript": "typescript",
        "js": "typescript",
    }
    return aliases.get(normalized, normalized)


def _extension_for_language(language: str) -> str:
    if language == "rust":
        return ".rs"
    if language == "typescript":
        return ".ts"
    return ".py"


def _forge_task_to_mumei_source(spec: dict[str, object]) -> str:
    atoms = _dict_list(spec.get("atoms"))
    if not atoms and "name" in spec:
        atoms = [spec]
    blocks = [_forge_atom_to_mumei(atom) for atom in atoms]
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _forge_atom_to_mumei(atom: dict[str, object]) -> str:
    name = _safe_identifier(_string_value(atom.get("name"), "audited_atom"))
    params = _format_params(atom.get("params") or atom.get("inputs"))
    return_type = _string_value(atom.get("return_type"), "i64")
    requires = _contract_text(atom.get("requires"), "true")
    ensures = _contract_text(atom.get("ensures"), "true")
    default_value = _default_literal(return_type)
    return "\n".join(
        [
            f"trusted atom {name}({params}) -> {return_type} {{",
            f"    requires: {requires};",
            f"    ensures: {ensures};",
            "    body: {",
            f"        {default_value}",
            "    }",
            "}",
        ]
    )


def _format_params(value: object) -> str:
    if not isinstance(value, list):
        return ""
    params: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _safe_identifier(_string_value(item.get("name"), "arg"))
        type_name = _string_value(item.get("type"), "i64")
        params.append(f"{name}: {type_name}")
    return ", ".join(params)


def _contract_text(value: object, default: str) -> str:
    if isinstance(value, str):
        text = value.strip()
        return text or default
    if isinstance(value, list):
        parts = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        return " && ".join(parts) if parts else default
    return default


def _spec_health_issue_strings(report: SpecHealthReport) -> list[str]:
    issues: list[str] = []
    for item in report.contradictions:
        detail = f": {item.details}" if item.details else ""
        issues.append(f"contradiction: {item.atom}{detail}")
    for item in report.over_constrained:
        unused = [
            *item.unused_requires,
            *item.unused_invariants,
            *item.unused_effect_constraints,
        ]
        suffix = f" ({'; '.join(unused)})" if unused else ""
        issues.append(f"over-constrained: {item.atom}{suffix}")
    for item in report.vacuous:
        detail = f": {item.message}" if item.message else ""
        issues.append(f"vacuous: {item.atom}{detail}")
    return issues


def _verification_issue_strings(result: dict[str, object]) -> list[str]:
    issues: list[str] = []
    for item in _string_list(result.get("errors")):
        issues.append(item)
    top_level_counterexample = format_counterexample(result)
    if top_level_counterexample:
        issues.append(top_level_counterexample)
    verification = _dict_value(result.get("verification"))
    report = _dict_value(verification.get("report"))
    report_counterexample = format_counterexample(report)
    if report_counterexample:
        issues.append(report_counterexample)
    if verification and verification.get("success") is False:
        status = _string_value(report.get("status"), "")
        failed = report.get("failed")
        if status or failed is not None:
            issues.append(f"mumei verify failed: status={status or 'unknown'}, failed={failed}")
        issues.extend(_diagnostic_strings(report))
        stderr = _string_value(verification.get("stderr"), "").strip()
        if stderr:
            issues.append(_shorten(stderr))
    return _dedupe_strings(issues)


def _counterexample_value_dicts(result: dict[str, object]) -> list[dict]:
    values: list[dict] = []
    for report in _counterexample_reports(result):
        counterexample = report.get("counterexample")
        if not isinstance(counterexample, dict):
            continue
        values.append(
            {
                "function_name": _counterexample_function_name(result, report),
                "counterexample": dict(counterexample),
            }
        )
    return _dedupe_counterexample_values(values)


def _counterexample_reports(result: dict[str, object]) -> list[dict[str, object]]:
    reports: list[dict[str, object]] = []
    if isinstance(result.get("counterexample"), dict):
        reports.append(result)
    verification = _dict_value(result.get("verification"))
    report = _dict_value(verification.get("report"))
    if isinstance(report.get("counterexample"), dict):
        reports.append(report)
    return reports


def _counterexample_function_name(
    result: dict[str, object],
    report: dict[str, object],
) -> str:
    for source in (report, result):
        for key in ("function_name", "atom", "name"):
            value = _string_value(source.get(key), "")
            if value:
                return value
    specs = _dict_list(result.get("specs"))
    if len(specs) == 1:
        spec = specs[0]
        value = _string_value(spec.get("function_name"), "")
        if value:
            return value
        value = _string_value(spec.get("name"), "")
        if value:
            return value
    return "unknown"


def _dedupe_counterexample_values(values: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[str] = set()
    for value in values:
        marker = json.dumps(value, sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(value)
    return deduped


def _cross_validation_gap_strings(report: CrossValidationReport) -> list[str]:
    gaps: list[str] = []
    for atom in report.spec_stronger_than_impl:
        gaps.append(f"spec stronger than implementation: {atom}")
    for atom in report.impl_stronger_than_spec:
        gaps.append(f"implementation stronger than spec: {atom}")
    for atom in report.uncovered_atoms:
        gaps.append(f"spec atom has no matching implementation: {atom}")
    if report.drift_detected:
        gaps.append("spec drift detected")
    gaps.extend(report.details)
    return _dedupe_strings(gaps)


def _migration_issue_dicts(
    verification_violations: list[str],
    cross_validation_gaps: list[str],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    issues.extend(
        {
            "kind": "verification",
            "severity": "error",
            "message": violation,
        }
        for violation in verification_violations
    )
    issues.extend(
        {
            "kind": "alignment",
            "severity": "warning",
            "message": gap,
        }
        for gap in cross_validation_gaps
    )
    return issues


def _diagnostic_strings(report: dict[str, object]) -> list[str]:
    diagnostics = report.get("diagnostics")
    if not isinstance(diagnostics, list):
        return []
    return [_shorten(item) for item in diagnostics if isinstance(item, str)]


def _read_json_dict(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _dict_value(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _string_value(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _safe_identifier(value: str) -> str:
    safe = re.sub(r"\W+", "_", value.strip()).strip("_")
    if not safe:
        return "audited_atom"
    if safe[0].isdigit():
        return f"atom_{safe}"
    return safe


def _default_literal(return_type: str) -> str:
    normalized = return_type.strip().lower()
    if normalized in {"bool", "boolean"}:
        return "true"
    if normalized in {"str", "string"}:
        return '""'
    return "0"


def _shorten(text: str, limit: int = 500) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _result_report(result: AuditResult | AuditDirectoryResult) -> str:
    if isinstance(result, AuditDirectoryResult):
        return result.summary
    return result.report


def _format_result(result: AuditResult | AuditDirectoryResult, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(asdict(result), ensure_ascii=False, indent=2)
    if output_format == "markdown":
        return _result_to_markdown(result)
    return _result_report(result)


def _finalize_audit_result(result: AuditResult) -> AuditResult:
    result.next_steps = _generate_next_steps(result)
    result.report = _build_report(result)
    return result


def _generate_next_steps(result: AuditResult) -> list[dict]:
    steps: list[dict] = []
    if result.verification_violations:
        steps.append(
            {
                "priority": "high",
                "action": "migrate-suggest で .mm スケルトンを生成",
                "command": (
                    "mumei-agent migrate-suggest --code-file <file> "
                    "--language <lang> --output generated/mm"
                ),
            }
        )
    if result.cross_validation_gaps:
        steps.append(
            {
                "priority": "high",
                "action": "validate-spec-to-code で制約の対応を確認",
                "command": "mumei-agent validate-spec-to-code --spec <spec> --code <file>",
            }
        )
    if result.spec_health_issues:
        steps.append(
            {
                "priority": "medium",
                "action": "validate-spec で仕様の矛盾を修正",
                "command": "mumei-agent validate-spec --input <spec>",
            }
        )
    if result.migration_hints:
        steps.append(
            {
                "priority": "medium",
                "action": "heal で .mm スケルトンを自動修正",
                "command": "mumei-agent heal <mm_file>",
            }
        )
    if not steps and result.success:
        steps.append(
            {
                "priority": "info",
                "action": "監査完了。.mm 移行不要",
                "command": "",
            }
        )
    return steps


def _generate_directory_next_steps(result: AuditDirectoryResult) -> list[dict]:
    aggregated: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for file_result in result.file_results:
        file_steps = file_result.next_steps or _generate_next_steps(file_result)
        for step in file_steps:
            key = (
                _string_value(step.get("priority"), ""),
                _string_value(step.get("action"), ""),
                _string_value(step.get("command"), ""),
            )
            if key in seen:
                continue
            seen.add(key)
            aggregated.append(step)
    actionable = [
        step for step in aggregated if _string_value(step.get("priority"), "") != "info"
    ]
    if actionable:
        return actionable
    if result.success:
        return [
            {
                "priority": "info",
                "action": "監査完了。.mm 移行不要",
                "command": "",
            }
        ]
    return aggregated


def _aggregate_directory_next_steps(result: AuditDirectoryResult) -> list[dict]:
    return _generate_directory_next_steps(result)


def _build_directory_report(result: AuditDirectoryResult) -> str:
    lines = [f"Audit directory: {result.source_dir}"]
    for file_result in result.file_results:
        violations = len(file_result.verification_violations)
        gaps = len(file_result.cross_validation_gaps)
        source_label = _directory_file_label(result.source_dir, file_result.source_file)
        lines.append(
            "  "
            f"{source_label}: "
            f"{violations} {_pluralize('violation', violations)}, "
            f"{gaps} {_pluralize('gap', gaps)}"
        )
    lines.append(
        "Summary: "
        f"{result.total_files} {_pluralize('file', result.total_files)}, "
        f"{result.files_with_issues} {_pluralize('file', result.files_with_issues)} "
        "with issues"
    )
    if result.errors:
        lines.append(f"errors: {result.errors}")
    if result.next_steps:
        lines.append("next_steps:")
        for step in result.next_steps:
            _append_text_next_step(lines, step)
    return "\n".join(lines)


def _pluralize(word: str, count: int) -> str:
    return word if count == 1 else f"{word}s"


def _directory_file_label(source_dir: str, source_file: str) -> str:
    try:
        return Path(source_file).relative_to(Path(source_dir)).as_posix()
    except ValueError:
        return source_file


def _build_report(result: AuditResult) -> str:
    next_steps = result.next_steps or _generate_next_steps(result)
    lines = [
        f"Audit {'passed' if result.success else 'found issues'}: {result.source_file}",
        f"language: {result.language or 'unknown'}",
        f"spec_extracted: {result.spec_extracted}",
        f"spec_health_issues: {result.spec_health_issues}",
        f"verification_violations: {result.verification_violations}",
        f"counterexample_values: {result.counterexample_values}",
        f"cross_validation_gaps: {result.cross_validation_gaps}",
    ]
    if result.errors:
        lines.append(f"errors: {result.errors}")
    lines.append("migration_hints:")
    if result.migration_hints:
        for hint in result.migration_hints:
            function_name = _string_value(hint.get("function_name"), "unknown")
            priority = _string_value(hint.get("priority"), "unknown")
            skeleton = _string_value(hint.get("skeleton"), "")
            skeleton_preview = skeleton.splitlines()[:3]
            lines.append(f"  - function_name: {function_name}")
            lines.append(f"    priority: {priority}")
            lines.append("    skeleton:")
            for preview_line in skeleton_preview:
                lines.append(f"      {preview_line}")
    else:
        lines.append("  []")
    lines.append(f"healed_files: {result.healed_files}")
    lines.append(f"heal_errors: {result.heal_errors}")
    if next_steps:
        lines.append("next_steps:")
        for step in next_steps:
            _append_text_next_step(lines, step)
    return "\n".join(lines)


def _append_text_next_step(lines: list[str], step: dict) -> None:
    priority = _string_value(step.get("priority"), "unknown")
    action = _string_value(step.get("action"), "")
    command = _string_value(step.get("command"), "")
    lines.append(f"  - priority: {priority}")
    lines.append(f"    action: {action}")
    lines.append(f"    command: {command}")


def _result_to_markdown(result: AuditResult | AuditDirectoryResult) -> str:
    if isinstance(result, AuditDirectoryResult):
        return _directory_result_to_markdown(result)
    return _file_result_to_markdown(result)


def _build_markdown_report(result: AuditResult | AuditDirectoryResult) -> str:
    return _result_to_markdown(result)


def _file_result_to_markdown(result: AuditResult) -> str:
    next_steps = result.next_steps or _generate_next_steps(result)
    lines = [
        f"## Audit: {result.source_file}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| language | {_markdown_cell(result.language or 'unknown')} |",
        f"| spec_extracted | {result.spec_extracted} |",
        f"| success | {result.success} |",
        "",
        "### Issues",
        "",
    ]
    lines.extend(
        _markdown_issue_lines(
            [
                ("⚠️", "spec_health_issues", result.spec_health_issues),
                ("❌", "verification_violations", result.verification_violations),
                ("⚠️", "cross_validation_gaps", result.cross_validation_gaps),
                ("❌", "errors", result.errors),
            ]
        )
    )
    if result.counterexample_values:
        lines.append(
            "- ❌ counterexample_values: "
            f"{_markdown_cell(_markdown_items_text(result.counterexample_values))}"
        )
    if result.migration_hints:
        lines.append(
            "- ⚠️ migration_hints: "
            f"{_markdown_cell(_markdown_items_text(result.migration_hints))}"
        )
    if result.healed_files:
        lines.append(
            "- ⚠️ healed_files: "
            f"{_markdown_cell(_markdown_items_text(result.healed_files))}"
        )
    if result.heal_errors:
        lines.append(
            "- ❌ heal_errors: "
            f"{_markdown_cell(_markdown_items_text(result.heal_errors))}"
        )
    lines.extend(["", "### Next Steps", ""])
    lines.extend(_markdown_next_step_lines(next_steps))
    return "\n".join(lines)


def _directory_result_to_markdown(result: AuditDirectoryResult) -> str:
    lines = [
        f"## Audit Directory: {result.source_dir}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| language | {_markdown_cell(result.language or 'mixed')} |",
        f"| success | {result.success} |",
        f"| total_files | {result.total_files} |",
        f"| files_with_issues | {result.files_with_issues} |",
        "",
        "### Files",
        "",
        "| File | Status | Violations | Gaps |",
        "|---|---|---:|---:|",
    ]
    for file_result in result.file_results:
        source_label = _directory_file_label(result.source_dir, file_result.source_file)
        lines.append(
            "| "
            f"`{_markdown_cell(source_label)}` | "
            f"{'passed' if file_result.success else 'found issues'} | "
            f"{len(file_result.verification_violations)} | "
            f"{len(file_result.cross_validation_gaps)} |"
        )
    if result.errors:
        lines.extend(["", "### Issues", "", *_markdown_bullet_lines(result.errors)])
    lines.extend(["", "### Next Steps", ""])
    lines.extend(_markdown_next_step_lines(result.next_steps))
    return "\n".join(lines)


def _markdown_issue_lines(issue_groups: list[tuple[str, str, list]]) -> list[str]:
    lines: list[str] = []
    for marker, category, items in issue_groups:
        if not items:
            continue
        lines.append(
            f"- {marker} {category}: {_markdown_cell(_markdown_items_text(items))}"
        )
    if not lines:
        return ["- No issues found."]
    return lines


def _markdown_findings_row(category: str, items: list) -> str:
    return (
        f"| `{category}` | {len(items)} | "
        f"{_markdown_cell(_markdown_items_text(items))} |"
    )


def _markdown_items_text(items: list) -> str:
    if not items:
        return "—"
    return "<br>".join(str(item) for item in items)


def _markdown_next_step_lines(next_steps: list[dict]) -> list[str]:
    if not next_steps:
        return ["- [ ] No recommended next steps."]
    lines: list[str] = []
    for step in next_steps:
        priority = _string_value(step.get("priority"), "unknown")
        action = _string_value(step.get("action"), "")
        command = _string_value(step.get("command"), "")
        checkbox = "x" if priority == "info" and not command else " "
        if command:
            lines.append(f"- [{checkbox}] ({priority}) Run `{command}`")
        else:
            lines.append(f"- [{checkbox}] ({priority}) {action}")
    return lines


def _markdown_bullet_lines(items: list[str]) -> list[str]:
    return [f"- {_markdown_cell(item)}" for item in items]


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")
