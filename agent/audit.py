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
from agent.mumei_client import create_mumei_client
from agent.strategies.cross_validation_strategy import CrossValidationReport, CrossValidator
from agent.strategies.foreign_code_strategy import ForeignCodeVerifier
from agent.strategies.spec_health_strategy import SpecHealthChecker, SpecHealthReport


SUPPORTED_AUDIT_LANGUAGES = ("python", "rust", "typescript")


@dataclass
class AuditResult:
    success: bool
    source_file: str
    language: str
    spec_extracted: bool
    spec_health_issues: list[str] = field(default_factory=list)
    verification_violations: list[str] = field(default_factory=list)
    cross_validation_gaps: list[str] = field(default_factory=list)
    migration_hints: list[dict] = field(default_factory=list)
    healed_files: list[str] = field(default_factory=list)
    heal_errors: list[str] = field(default_factory=list)
    report: str = ""
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
    ) -> AuditResult:
        source_path = Path(source_file).expanduser().resolve()
        source_label = str(source_path)
        normalized_language = _normalize_language(language)
        errors: list[str] = []

        try:
            source_code = source_path.read_text(encoding="utf-8")
        except OSError as exc:
            return AuditResult(
                success=False,
                source_file=source_label,
                language=normalized_language,
                spec_extracted=False,
                errors=[f"Failed to read source file: {exc}"],
                report="Audit failed before source analysis.",
            )

        if normalized_language and normalized_language not in SUPPORTED_AUDIT_LANGUAGES:
            return AuditResult(
                success=False,
                source_file=source_label,
                language=normalized_language,
                spec_extracted=False,
                errors=[
                    "language must be one of: "
                    + ", ".join(SUPPORTED_AUDIT_LANGUAGES)
                ],
                report="Audit failed because the language is unsupported.",
            )

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
            result.report = _build_report(result)
            return result

        spec_source = _forge_task_to_mumei_source(extraction.forge_task_spec)
        if not spec_source:
            errors.append("No Mumei atoms were generated from the extracted forge task spec.")

        spec_health_issues: list[str] = []
        verification_violations: list[str] = []
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
            cross_validation_gaps=cross_validation_gaps,
            errors=errors,
        )
        if (auto_migrate or auto_heal) and (verification_violations or cross_validation_gaps):
            from agent.mm_migration_advisor import suggest_migration_for_file

            hints = suggest_migration_for_file(
                source_label,
                audit_language,
                {
                    "issues": _migration_issue_dicts(
                        verification_violations,
                        cross_validation_gaps,
                    )
                },
            )
            result.migration_hints = [asdict(hint) for hint in hints]
        if auto_heal and result.migration_hints:
            healed_files, heal_errors = self._heal_migration_hints(
                result.migration_hints,
                source_path,
            )
            result.healed_files = healed_files
            result.heal_errors = heal_errors
        result.report = _build_report(result)
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
        result.report = _build_report(result)
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
        description="Audit existing code by extracting specs and verifying them.",
    )
    parser.add_argument("--code-file", required=True, help="Path to existing source code.")
    parser.add_argument(
        "--language",
        choices=SUPPORTED_AUDIT_LANGUAGES,
        help="Source language. Inferred from the file extension when omitted.",
    )
    parser.add_argument("--json", action="store_true", help="Output the full result as JSON.")
    parser.add_argument("--output", help="Optional output path.")
    parser.add_argument("--domain-hint", default="", help="Optional domain hint for spec extraction.")
    parser.add_argument(
        "--auto-migrate",
        action="store_true",
        help="Automatically generate .mm migration skeletons for functions with issues.",
    )
    parser.add_argument(
        "--auto-heal",
        action="store_true",
        help="After generating .mm skeletons (--auto-migrate), run the self-healing loop on each skeleton.",
    )
    parser.add_argument(
        "--heal-output-dir",
        default=None,
        help="Directory to write healed .mm files (default: same directory as --code-file).",
    )
    return parser


def main(args: argparse.Namespace | None = None) -> AuditResult:
    args = args or build_parser().parse_args()
    result = AuditPipeline(heal_output_dir=args.heal_output_dir).audit_file(
        args.code_file,
        args.language,
        domain_hint=args.domain_hint,
        auto_migrate=args.auto_migrate,
        auto_heal=args.auto_heal,
    )
    payload = (
        json.dumps(asdict(result), ensure_ascii=False, indent=2)
        if args.json
        else result.report
    )
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
    verification = _dict_value(result.get("verification"))
    if verification and verification.get("success") is False:
        report = _dict_value(verification.get("report"))
        status = _string_value(report.get("status"), "")
        failed = report.get("failed")
        if status or failed is not None:
            issues.append(f"mumei verify failed: status={status or 'unknown'}, failed={failed}")
        issues.extend(_diagnostic_strings(report))
        stderr = _string_value(verification.get("stderr"), "").strip()
        if stderr:
            issues.append(_shorten(stderr))
    return _dedupe_strings(issues)


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


def _build_report(result: AuditResult) -> str:
    lines = [
        f"Audit {'passed' if result.success else 'found issues'}: {result.source_file}",
        f"language: {result.language or 'unknown'}",
        f"spec_extracted: {result.spec_extracted}",
        f"spec_health_issues: {result.spec_health_issues}",
        f"verification_violations: {result.verification_violations}",
        f"cross_validation_gaps: {result.cross_validation_gaps}",
    ]
    if result.errors:
        lines.append(f"errors: {result.errors}")
    if result.migration_hints:
        lines.append("migration_hints:")
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
    if result.healed_files:
        lines.append(f"healed_files: {result.healed_files}")
    if result.heal_errors:
        lines.append(f"heal_errors: {result.heal_errors}")
    if result.verification_violations or result.cross_validation_gaps:
        lines.append(
            "next_step: Run `mumei-agent migrate-suggest --code-file <file> --language <lang>` "
            "to generate .mm migration skeletons."
        )
    return "\n".join(lines)
