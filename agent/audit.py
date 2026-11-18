"""Audit existing foreign-language code through the Mumei verification stack."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
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
    _aggregate_directory_fixed_keys,
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
    _finding_counts,
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
from agent.attempt_schedule import MAX_SCHEDULE_ATTEMPTS, run_attempt_schedule
from agent.code_to_spec import CodeToSpecExtractor, CodeToSpecResult, Language
from agent.config import AgentConfig
from agent.extract_spec import _collect_code_files
from agent.extract_spec_helpers import _is_test_file
from agent.gap_rules import _TRUSTED_ATOM_RE
from agent.lean_bridge_helpers import run_lean_bridge_and_merge_proof_cert
from agent.body_port import BodyPorter, body_port_violations
from agent.native_replay import NativeReplayer, native_replay_violations, reconcile_body_ports
from agent.llm_provider import LLMProvider, openai_client_adapter
from agent.mumei_client import create_mumei_client
from agent.prompts.report_formatter import format_counterexample
from agent.spec_ambiguity import classify_spec_ambiguity
from agent.strategies.cross_validation_strategy import CrossValidationReport, CrossValidator
from agent.strategies.foreign_code_strategy import (
    ForeignCodeVerifier,
    _source_has_function_declarations,
)
from agent.strategies.foreign_code_strategy_helpers import (
    _hash_guard_trace_payload,
    build_solidity_guard_trace_proof_certificate,
    extract_solidity_access_control_atoms,
    extract_solidity_cei_atoms,
)
from agent.spec_completeness_checker import check_forge_spec_domain_completeness
from agent.strategies.spec_health_strategy import SpecHealthChecker, SpecHealthReport
from agent.verification_planner import (
    AdapterRegistry,
    PlannerPolicy,
    RouteRequirements,
    RuntimeObservation,
)
from agent.verify_schedule import (
    SOURCE_INPUT_FORMAT,
    _load_argv_map,
    _load_observations,
    _load_policy,
    _load_registry,
    _load_request,
    _redact_declared_paths,
)

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
    "trusted_atoms",
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
    "trusted_atoms": "trusted atom declarations in .mm sources that bypass Z3 verification (advisory warnings)",
    "contradiction_type": "stable spec contradiction classifier",
}

def _mm_code_lines(source: str) -> list[str]:
    """``.mm`` lines with ``//`` comments and string-literal contents removed.

    Mumei has line comments only (no block comments); ``"`` opens a string
    that may span lines, so string state carries across the scan. A
    ``trusted atom`` text inside a literal or comment is documentation, not
    a real declaration — masking it keeps the advisory honest.
    """
    in_string = False
    code_lines: list[str] = []
    for line in source.splitlines():
        out: list[str] = []
        index = 0
        while index < len(line):
            char = line[index]
            if in_string:
                if char == "\\" and index + 1 < len(line):
                    index += 2
                    continue
                if char == '"':
                    in_string = False
                index += 1
                continue
            if char == "/" and index + 1 < len(line) and line[index + 1] == "/":
                break
            if char == '"':
                in_string = True
                index += 1
                continue
            out.append(char)
            index += 1
        code_lines.append("".join(out))
    return code_lines


def _trusted_atom_entries(
    source: str, file_label: str
) -> list[dict[str, object]]:
    """Advisory findings for ``trusted atom`` declarations in a .mm source.

    ``trusted`` atoms skip Z3 verification entirely, so a security audit
    must surface each one — file, name, and line — instead of silently
    passing over the escape hatch. Advisory only: entries never affect
    ``success`` or ``files_with_issues``.
    """
    entries: list[dict[str, object]] = []
    for lineno, line in enumerate(_mm_code_lines(source), start=1):
        match = _TRUSTED_ATOM_RE.match(line)
        if match is None:
            continue
        name = match.group(1)
        entries.append(
            {
                "file": file_label,
                "atom": name,
                "line": lineno,
                "severity": "warning",
                "message": (
                    f"trusted atom `{name}` skips Z3 verification — "
                    "its contracts are unproven"
                ),
            }
        )
    return entries


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
        body_porter: BodyPorter | None = None,
        native_replayer: NativeReplayer | None = None,
    ) -> None:
        self.config = config or AgentConfig()
        if llm_provider is not None and client is None:
            client = openai_client_adapter(llm_provider)
        self._llm_client = client
        self._body_porter = body_porter
        self._native_replayer = native_replayer
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
        enable_body_port: bool = False,
        enable_native_replay: bool = False,
        include_tests: bool = False,
        enable_summaries: bool = False,
        go_types: str | None = None,
        summaries_manifest_map: dict | None = None,
        enable_summary_attempts: bool = False,
        summary_attempt_timeout_ms: int | None = None,
        enable_summary_plan: bool = False,
        summary_plan_stamp: int = 1,
        summary_plan_tool_version: str | None = None,
        summary_plan_histories: str | None = None,
        scheduled_verification: "_ScheduledVerification | None" = None,
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
                enable_body_port=enable_body_port,
                enable_native_replay=enable_native_replay,
                include_tests=include_tests,
                enable_summaries=enable_summaries,
                go_types=go_types,
                summaries_manifest_map=summaries_manifest_map,
                enable_summary_attempts=enable_summary_attempts,
                summary_attempt_timeout_ms=summary_attempt_timeout_ms,
                enable_summary_plan=enable_summary_plan,
                summary_plan_stamp=summary_plan_stamp,
                summary_plan_tool_version=summary_plan_tool_version,
                summary_plan_histories=summary_plan_histories,
                scheduled_verification=scheduled_verification,
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
                enable_body_port=enable_body_port,
                enable_native_replay=enable_native_replay,
                scheduled_verification=scheduled_verification,
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
        enable_body_port: bool = False,
        enable_native_replay: bool = False,
        scheduled_verification: "_ScheduledVerification | None" = None,
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
        except (OSError, UnicodeDecodeError) as exc:
            result = AuditResult(
                success=False,
                source_file=source_label,
                language=normalized_language,
                spec_extracted=False,
                verification_status="unverifiable",
                errors=[f"Failed to read source file: {exc}"],
            )
            return _finalize_audit_result(result)

        # .mm sources are not audit targets themselves, but any
        # ``trusted atom`` they declare bypasses Z3 verification — surface
        # the escape hatches as advisory findings on the result.
        trusted_atoms = (
            _trusted_atom_entries(source_code, source_label)
            if source_path.suffix == ".mm"
            else []
        )

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
                trusted_atoms=trusted_atoms,
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
                trusted_atoms=trusted_atoms,
            )
            return _finalize_audit_result(result)

        malformed_extraction_issues = _malformed_extraction_issue_strings(
            extraction.forge_task_spec
        )
        spec_source = _forge_task_to_mumei_source(extraction.forge_task_spec)
        if not spec_source:
            if _source_has_function_declarations(source_code, audit_language) is not False:
                errors.append(
                    "No Mumei atoms were generated from the extracted forge task spec."
                )

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
            scheduled_document = (
                _run_scheduled_verification(scheduled_verification, spec_path)
                if scheduled_verification is not None and spec_path.is_file()
                else None
            )

            # V1-A-2: with a domain hint the extracted spec is also checked
            # against the domain's required-condition checklist; missing
            # conditions land in spec_health_issues as domain-completeness
            # entries. next_steps remains the only human-review entrypoint.
            if domain_hint:
                spec_health_issues = [
                    *spec_health_issues,
                    *check_forge_spec_domain_completeness(
                        extraction.forge_task_spec,
                        domain_hint,
                        spec_text=extraction.natural_language_spec or "",
                    ),
                ]

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
            if proof_certificate is not None:
                # Access-control obligations ride the same certificate as the
                # reentrancy guard-trace atoms so both escalate to Lean together.
                access_control_atoms = extract_solidity_access_control_atoms(
                    source_code,
                    source_file=source_label,
                )
                cei_atoms = extract_solidity_cei_atoms(
                    source_code,
                    source_file=source_label,
                )
                existing_atoms = proof_certificate.get("atoms")
                proof_certificate["atoms"] = [
                    *(existing_atoms if isinstance(existing_atoms, list) else []),
                    *access_control_atoms,
                    *cei_atoms,
                ]
                # Recompute the integrity fingerprint over the merged atom list;
                # the builder hashed only the guard-trace subset.
                proof_certificate["certificate_hash"] = _hash_guard_trace_payload(
                    source_label,
                    proof_certificate["atoms"],
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
                foreign_result = self.foreign_code_verifier.verify(
                    source_code, audit_language, source_file=str(source_path)
                )
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

            body_ports: list[dict] = []
            port_counterexamples: list[dict] = []
            status_before_ports = verification_status
            if enable_body_port and spec_source and not malformed_extraction_issues:
                body_ports = self._port_bodies(
                    source_code, audit_language, extraction.forge_task_spec
                )
                refuted = body_port_violations(body_ports)
                verification_violations.extend(refuted)
                port_counterexamples = [
                    {"function_name": port["function"], "counterexample": port["counterexample"]}
                    for port in body_ports
                    if port.get("outcome") == "refuted" and port.get("counterexample")
                ]
                counterexample_values.extend(port_counterexamples)
                if refuted:
                    verification_status = "refuted"

            native_replays: list[dict] = []
            if enable_native_replay and spec_source and not malformed_extraction_issues:
                replayer = self._native_replayer or NativeReplayer(self.mumei_client)
                native_replays = replayer.replay(
                    source_path, source_code, audit_language, extraction.forge_task_spec,
                    body_ports, counterexample_values,
                )
                # A refuted port the native code does not reproduce is a
                # translation error, not a finding against the code.
                for name in reconcile_body_ports(body_ports, native_replays):
                    verification_violations[:] = [
                        v for v in verification_violations if not v.startswith(f"body-port: {name}:")
                    ]
                    # By identity: a foreign verifier may report the same values independently.
                    dropped = [id(c) for c in port_counterexamples if c["function_name"] == name]
                    counterexample_values[:] = [c for c in counterexample_values if id(c) not in dropped]
                confirmed = native_replay_violations(native_replays)
                verification_violations.extend(confirmed)
                if confirmed or any(v.startswith("body-port: ") for v in verification_violations):
                    verification_status = "refuted"
                elif verification_status == "refuted" and enable_body_port:
                    verification_status = status_before_ports

            if spec_source and not malformed_extraction_issues:
                cross_report = self.cross_validator.validate_spec_vs_impl(
                    str(spec_path),
                    str(source_path),
                    audit_language,
                )
                cross_validation_gaps = _cross_validation_gap_strings(cross_report)

        # Ambiguity is reported, never resolved. A requirement the prose never
        # states is a gap in what was verified, so it lands in
        # ``cross_validation_gaps`` and blocks a `verified` verdict; intent that
        # is stated but not pinned down is not evidence against the code, so it
        # is raised for human review through ``next_steps`` instead of being
        # completed with a guessed clause.
        spec_ambiguities = classify_spec_ambiguity(
            extraction.natural_language_spec,
            extraction.forge_task_spec,
            self.config,
        )
        missing_requirements = [
            ambiguity
            for ambiguity in spec_ambiguities
            if ambiguity.classification == "missing_requirement"
        ]
        cross_validation_gaps.extend(
            ambiguity.as_gap() for ambiguity in missing_requirements
        )
        if missing_requirements and verification_status == "verified":
            verification_status = "unverifiable"

        # Spec diagnostics (spec_health_issues, cross_validation_gaps) are
        # evidence against the extracted spec, not the code, so they are
        # counted in finding_counts["spec"] but do not fail the audit. A
        # malformed extraction still does: the code was never checked.
        success = (
            not errors
            and not verification_violations
            and not malformed_extraction_issues
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
            trusted_atoms=trusted_atoms,
            body_ports=body_ports,
            native_replays=native_replays,
            scheduled_verification=scheduled_document,
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
        return _finalize_audit_result(result, spec_ambiguities)

    def audit_directory(
        self,
        source_dir: str | Path,
        language: str | None = None,
        *,
        domain_hint: str = "",
        auto_migrate: bool = False,
        auto_heal: bool = False,
        enable_lean_bridge: bool = False,
        enable_body_port: bool = False,
        enable_native_replay: bool = False,
        include_tests: bool = False,
        enable_summaries: bool = False,
        go_types: str | None = None,
        summaries_manifest_map: dict | None = None,
        enable_summary_attempts: bool = False,
        summary_attempt_timeout_ms: int | None = None,
        enable_summary_plan: bool = False,
        summary_plan_stamp: int = 1,
        summary_plan_tool_version: str | None = None,
        summary_plan_histories: str | None = None,
        scheduled_verification: "_ScheduledVerification | None" = None,
    ) -> AuditDirectoryResult:
        """Audit all supported source files in a directory.

        Wrapped in a ``mumei.audit.directory`` span; the per-file
        :meth:`audit_file` calls nest as ``mumei.audit.file`` child spans.

        Test files (``*_test.go``, ``*.test.ts``, ``test_*.py``, ``tests/``,
        ...) are skipped by default; pass ``include_tests=True`` to audit them.
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
                enable_body_port=enable_body_port,
                enable_native_replay=enable_native_replay,
                include_tests=include_tests,
                enable_summaries=enable_summaries,
                go_types=go_types,
                summaries_manifest_map=summaries_manifest_map,
                enable_summary_attempts=enable_summary_attempts,
                summary_attempt_timeout_ms=summary_attempt_timeout_ms,
                enable_summary_plan=enable_summary_plan,
                summary_plan_stamp=summary_plan_stamp,
                summary_plan_tool_version=summary_plan_tool_version,
                summary_plan_histories=summary_plan_histories,
                scheduled_verification=scheduled_verification,
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
        enable_body_port: bool = False,
        enable_native_replay: bool = False,
        include_tests: bool = False,
        enable_summaries: bool = False,
        go_types: str | None = None,
        summaries_manifest_map: dict | None = None,
        enable_summary_attempts: bool = False,
        summary_attempt_timeout_ms: int | None = None,
        enable_summary_plan: bool = False,
        summary_plan_stamp: int = 1,
        summary_plan_tool_version: str | None = None,
        summary_plan_histories: str | None = None,
        scheduled_verification: "_ScheduledVerification | None" = None,
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
            result.finding_counts = _finding_counts([], [], [], errors)
            result.next_steps = _generate_directory_next_steps(result)
            result.summary = _build_directory_report(result)
            return result

        code_files = _collect_code_files(
            source_path,
            AUDIT_EXTENSION_MAP,
            normalized_language or None,
            include_tests=include_tests,
        )

        # .mm files are not audit targets, but ``trusted atom`` declarations
        # inside them bypass Z3 verification — surface each as an advisory.
        trusted_atoms: list[dict] = []
        unreadable_mm: list[str] = []
        for mm_path in sorted(
            (path for path in source_path.rglob("*.mm") if path.is_file()),
            key=lambda path: path.relative_to(source_path).as_posix(),
        ):
            if not include_tests and _is_test_file(mm_path, source_path):
                continue
            mm_label = _directory_file_label(source_label, str(mm_path))
            try:
                mm_source = mm_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                unreadable_mm.append(mm_label)
                continue
            trusted_atoms.extend(
                _trusted_atom_entries(mm_source, mm_label)
            )

        if not code_files:
            errors.append(f"no supported source-code files found in directory: {source_label}")

        summary_audits = (
            _collect_summary_audits(
                source_path,
                code_files,
                go_types,
                manifest_map=summaries_manifest_map,
                attempt_timeout_ms=(
                    (
                        summary_attempt_timeout_ms
                        if summary_attempt_timeout_ms is not None
                        else _SUMMARY_ROUTE_TIMEOUT_SECONDS * 1000
                    )
                    if enable_summary_attempts
                    else None
                ),
            )
            if enable_summaries and code_files
            else []
        )

        summary_plans = (
            _collect_summary_plans(
                source_path,
                code_files,
                stamp=summary_plan_stamp,
                tool_version=summary_plan_tool_version,
                histories_path=summary_plan_histories,
            )
            if enable_summary_plan and code_files
            else []
        )

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
                    enable_body_port=enable_body_port,
                    enable_native_replay=enable_native_replay,
                    scheduled_verification=scheduled_verification,
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
            trusted_atoms=trusted_atoms,
            summary_audits=summary_audits,
            summary_plans=summary_plans,
        )
        _aggregate_directory_fixed_keys(result)
        result.next_steps = _generate_directory_next_steps(result)
        if unreadable_mm:
            # An unreadable .mm source leaves a silent hole in the
            # trusted-atom scan — surface it on the human-review
            # entrypoint instead of passing over it.
            result.next_steps = [
                step
                for step in result.next_steps
                if step.get("priority") != "info"
            ]
            result.next_steps.append(
                {
                    "priority": "medium",
                    "action": (
                        "unreadable .mm sources skipped by the "
                        "trusted-atom scan — review them manually: "
                        + ", ".join(unreadable_mm)
                    ),
                    "command": "",
                }
            )
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

    def _port_bodies(
        self, source_code: str, language: str, forge_task_spec: dict[str, object]
    ) -> list[dict]:
        porter = self._body_porter
        if porter is None:
            client = self._llm_client
            if client is None and self.config.api_key:
                client = self.config.create_client()
            if client is None:
                return [
                    {
                        "function": "",
                        "outcome": "not_ported",
                        "reason": "body porting needs an LLM; LLM_API_KEY/OPENAI_API_KEY is not set",
                        "body": "",
                    }
                ]
            porter = BodyPorter(client, self.config.model, self.mumei_client)
        return porter.port(source_code, language, forge_task_spec)

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
        "cross_validation_gaps, next_steps, migration_hints, healed_files, heal_errors, "
        "trusted_atoms."
    )
    parser = parser or argparse.ArgumentParser(
        description=(
            "Audit existing code by extracting specs, verifying contracts, "
            "emitting cross_validation_gaps, optionally producing migration_hints, "
            "and surfacing trusted_atoms escape hatches found in .mm sources."
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
    parser.add_argument(
        "--enable-body-port",
        action="store_true",
        help=(
            "Have the LLM port each function body to Mumei and verify it against the "
            "extracted contract; refuted ports count as code findings (needs an LLM). "
            "Sensitive environment values and credential-shaped literals are redacted "
            "from the source sent to the LLM and from the stored body, diagnostics and "
            "counterexamples; the redaction is pattern-based, so review code that holds "
            "unusual credentials before enabling it."
        ),
    )
    parser.add_argument(
        "--enable-native-replay",
        action="store_true",
        help=(
            "Run each extracted Python, TypeScript, Go or Rust function natively on its "
            "counterexamples and a few boundary inputs, and check the extracted contract on "
            "the result; a violation is a confirmed code finding, and a refuted body port "
            "the native code does not reproduce is dropped. Executes the audited code locally."
        ),
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help=(
            "Also audit test files (e.g. *_test.go, *.test.ts, test_*.py, "
            "tests/ dirs), which are skipped by default for directory audits."
        ),
    )
    parser.add_argument(
        "--enable-summaries",
        action="store_true",
        help=(
            "Directory audits only: invoke each declared *-summaries "
            "produce route on the collected source units and record "
            "declared manifest metadata (route, unit, status, context "
            "key, function count) under summary_audits — advisory; "
            "manifest bytes are not stored."
        ),
    )
    parser.add_argument(
        "--summaries-manifest-map",
        default=None,
        metavar="<PATH>",
        help=(
            "Directory audits only, requires --enable-summaries: JSON "
            "object mapping each unit label (as emitted under "
            "summary_audits) to a prior summary manifest. Units with a "
            "declared manifest run their *-summaries-reuse route and "
            "report mode/reused/derived counts; a stale or rejected "
            "manifest falls back to the produce route."
        ),
    )
    parser.add_argument(
        "--enable-summary-attempts",
        action="store_true",
        help=(
            "Directory audits only, requires --enable-summaries: run "
            "each summary unit through its declared <route>-attempt "
            "route and record the attempt report's acceptance envelope "
            "(mode/accepted/check_outcome/manifest_sha256) instead of "
            "manifest metadata — advisory; report bytes are not stored. "
            "Cannot combine with --summaries-manifest-map."
        ),
    )
    parser.add_argument(
        "--summary-attempt-timeout",
        type=int,
        default=_SUMMARY_ROUTE_TIMEOUT_SECONDS * 1000,
        metavar="<MS>",
        help=(
            "Declared attempt bound in milliseconds passed to each "
            "<route>-attempt unit (default: %(default)s)."
        ),
    )
    parser.add_argument(
        "--enable-summary-plan",
        action="store_true",
        help=(
            "Directory audits only, requires --enable-summaries: run "
            "the probe-boundary planner once per summary profile "
            "present among the collected units and record the advisory "
            "mumei.summaries-plan/v1 documents under summary_plans — "
            "routing only; no summary is derived. Planning executes "
            "each adapter's declared probe command."
        ),
    )
    parser.add_argument(
        "--summary-plan-stamp",
        type=int,
        default=1,
        metavar="<N>",
        help=(
            "Host-declared observation stamp for the probe requests "
            "--enable-summary-plan records (default: %(default)s)."
        ),
    )
    parser.add_argument(
        "--summary-plan-tool-version",
        default=None,
        metavar="<VERSION>",
        help=(
            "Optional declared tool version the --enable-summary-plan "
            "planner pins against."
        ),
    )
    parser.add_argument(
        "--summary-plan-histories",
        default=None,
        metavar="<PATH>",
        help=(
            "Optional JSON array of persisted mumei.adapter-probe-history "
            "records the --enable-summary-plan planner resumes."
        ),
    )
    parser.add_argument(
        "--go-types",
        default=None,
        metavar="<PATH>",
        help=(
            "Path to the provisioned tools/go-types helper binary; Go "
            "summary units record skipped_no_helper when "
            "--enable-summaries is set without it."
        ),
    )
    parser.add_argument(
        "--enable-scheduled-verification",
        action="store_true",
        default=False,
        help=(
            "Dispatch each unit's generated .mm spec through "
            "run_attempt_schedule against the declared "
            "--schedule-request/--schedule-adapters/--schedule-argv-map/"
            "--schedule-policy inputs and record the "
            "mumei.attempt-schedule/v1 descriptor per unit. Dispatch "
            "record only — never a verdict. Requires the four declared "
            "input paths."
        ),
    )
    parser.add_argument(
        "--schedule-request",
        default=None,
        metavar="<PATH>",
        help=(
            "Declared RouteRequirements JSON for "
            "--enable-scheduled-verification (source input contract "
            "required)."
        ),
    )
    parser.add_argument(
        "--schedule-adapters",
        default=None,
        metavar="<PATH>",
        help=(
            "Declared JSON array of adapter manifests for "
            "--enable-scheduled-verification."
        ),
    )
    parser.add_argument(
        "--schedule-argv-map",
        default=None,
        metavar="<PATH>",
        help=(
            "Declared JSON object mapping adapter_id to its argv prefix "
            "for --enable-scheduled-verification; the unit's generated "
            "spec path is appended as the final argument."
        ),
    )
    parser.add_argument(
        "--schedule-policy",
        default=None,
        metavar="<PATH>",
        help=(
            "Declared planner policy JSON for "
            "--enable-scheduled-verification; allowed_permissions must "
            "be declared."
        ),
    )
    parser.add_argument(
        "--schedule-observations",
        default=None,
        metavar="<PATH>",
        help=(
            "Optional declared JSON array of runtime observations for "
            "--enable-scheduled-verification."
        ),
    )
    parser.add_argument(
        "--schedule-max-attempts",
        type=int,
        default=MAX_SCHEDULE_ATTEMPTS,
        metavar="<N>",
        help=(
            "Bounded schedule attempts per unit for "
            "--enable-scheduled-verification (default: %(default)s)."
        ),
    )
    parser.add_argument(
        "--schedule-success-exit-code",
        type=int,
        action="append",
        default=None,
        metavar="<N>",
        help=(
            "Declared exit code counting as a scheduling success for "
            "--enable-scheduled-verification (repeatable; default {0})."
        ),
    )
    parser.add_argument(
        "--schedule-memory-bound-mb",
        type=int,
        default=None,
        metavar="<MB>",
        help=(
            "Optional declared POSIX RLIMIT_AS ceiling per scheduled "
            "attempt child."
        ),
    )
    return parser

@dataclass(frozen=True)
class _ScheduledVerification:
    """Host-declared scheduling inputs for ``--enable-scheduled-verification``.

    The planner request/registry/argv-map/policy/observations are loaded once
    and shared across audit units. ``declared`` lists the supplied input paths
    so per-unit failure text can redact them."""

    request: RouteRequirements
    registry: AdapterRegistry
    argv_map: dict[str, tuple[str, ...]]
    policy: PlannerPolicy
    observations: tuple[RuntimeObservation, ...] | None
    max_attempts: int
    success_exit_codes: frozenset[int]
    memory_bound_mb: int | None
    declared: tuple[str, ...]


def _scheduled_verification_declared_paths(args: argparse.Namespace) -> tuple[str, ...]:
    paths = [
        args.schedule_request,
        args.schedule_adapters,
        args.schedule_argv_map,
        args.schedule_policy,
    ]
    if getattr(args, "schedule_observations", None) is not None:
        paths.append(args.schedule_observations)
    return tuple(paths)


def _load_scheduled_verification(args: argparse.Namespace) -> _ScheduledVerification:
    request = _load_request(args.schedule_request)
    if (
        request.input_format != SOURCE_INPUT_FORMAT
        or request.result_contract is None
    ):
        raise ValueError(
            "scheduled verification requires the source input contract and format"
        )
    return _ScheduledVerification(
        request=request,
        registry=_load_registry(args.schedule_adapters),
        argv_map=_load_argv_map(args.schedule_argv_map),
        policy=_load_policy(args.schedule_policy),
        observations=_load_observations(args.schedule_observations),
        max_attempts=args.schedule_max_attempts,
        success_exit_codes=(
            frozenset({0})
            if args.schedule_success_exit_code is None
            else frozenset(args.schedule_success_exit_code)
        ),
        memory_bound_mb=args.schedule_memory_bound_mb,
        declared=_scheduled_verification_declared_paths(args),
    )


def _run_scheduled_verification(
    context: _ScheduledVerification,
    source_path: Path,
) -> dict:
    """Dispatch one unit's generated .mm spec through ``run_attempt_schedule``.

    Each declared argv is a prefix: the unit's spec path is appended as the
    final argument so the adapter receives the source under audit. The result
    is the ``mumei.attempt-schedule/v1`` dispatch record — outcome/terminal
    states, never a verification verdict or an Evidence acceptance."""
    source = source_path.read_bytes()

    def argv_for(adapter_id: str) -> tuple[str, ...] | None:
        argv = context.argv_map.get(adapter_id)
        if argv is None:
            return None
        return (*argv, str(source_path))

    try:
        schedule = run_attempt_schedule(
            context.registry,
            context.request,
            context.policy,
            source,
            hashlib.sha256(source).hexdigest(),
            argv_for,
            observations=context.observations,
            max_attempts=context.max_attempts,
            success_exit_codes=context.success_exit_codes,
            memory_bound_mb=context.memory_bound_mb,
        )
    except (OSError, ValueError) as exc:
        # A scheduling failure is not evidence against the audited code, so it
        # records on the field instead of failing the audit.
        return {
            "status": "error",
            "error": _redact_declared_paths(str(exc), context.declared),
        }
    return schedule.to_dict()


def main(args: argparse.Namespace | None = None) -> AuditResult | AuditDirectoryResult:
    args = args or build_parser().parse_args()
    if getattr(args, "enable_summary_attempts", False) and not getattr(
        args, "enable_summaries", False
    ):
        print(
            "audit: --enable-summary-attempts requires --enable-summaries",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if getattr(args, "enable_summary_attempts", False) and getattr(
        args, "summaries_manifest_map", None
    ) is not None:
        print(
            "audit: --enable-summary-attempts cannot combine with "
            "--summaries-manifest-map",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if getattr(args, "enable_summary_plan", False) and not getattr(
        args, "enable_summaries", False
    ):
        print(
            "audit: --enable-summary-plan requires --enable-summaries",
            file=sys.stderr,
        )
        raise SystemExit(2)
    manifest_map = None
    manifest_map_path = getattr(args, "summaries_manifest_map", None)
    if manifest_map_path is not None:
        if not getattr(args, "enable_summaries", False):
            print(
                "audit: --summaries-manifest-map requires --enable-summaries",
                file=sys.stderr,
            )
            raise SystemExit(2)
        try:
            manifest_map = _read_summary_manifest_map(
                Path(manifest_map_path)
            )
        except (OSError, ValueError) as exc:
            print(f"audit: {exc}", file=sys.stderr)
            raise SystemExit(2)
    scheduled_requested = (
        any(
            getattr(args, name, None) is not None
            for name in (
                "schedule_request",
                "schedule_adapters",
                "schedule_argv_map",
                "schedule_policy",
                "schedule_observations",
                "schedule_success_exit_code",
                "schedule_memory_bound_mb",
            )
        )
        or getattr(args, "schedule_max_attempts", MAX_SCHEDULE_ATTEMPTS)
        != MAX_SCHEDULE_ATTEMPTS
    )
    enable_scheduled = bool(getattr(args, "enable_scheduled_verification", False))
    if scheduled_requested and not enable_scheduled:
        print(
            "audit: --schedule-* options require "
            "--enable-scheduled-verification",
            file=sys.stderr,
        )
        raise SystemExit(2)
    scheduled_verification = None
    if enable_scheduled:
        missing = [
            f"--schedule-{name}"
            for name in ("request", "adapters", "argv-map", "policy")
            if getattr(args, f"schedule_{name.replace('-', '_')}", None) is None
        ]
        if missing:
            print(
                "audit: --enable-scheduled-verification requires "
                + ", ".join(missing),
                file=sys.stderr,
            )
            raise SystemExit(2)
        if getattr(args, "output", None) is not None:
            target = os.path.realpath(args.output)
            if any(
                os.path.realpath(path) == target
                for path in _scheduled_verification_declared_paths(args)
            ):
                print(
                    "audit: --output must not overwrite a declared "
                    "schedule input",
                    file=sys.stderr,
                )
                raise SystemExit(2)
        try:
            scheduled_verification = _load_scheduled_verification(args)
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            print(
                "audit: "
                + _redact_declared_paths(
                    str(exc),
                    _scheduled_verification_declared_paths(args),
                ),
                file=sys.stderr,
            )
            raise SystemExit(2)
    config = AgentConfig(mumei_lean_repo=getattr(args, "mumei_lean_repo", None))
    result = AuditPipeline(config=config, heal_output_dir=args.heal_output_dir).audit_file(
        args.code_file,
        args.language,
        domain_hint=args.domain_hint,
        auto_migrate=args.auto_migrate,
        auto_heal=args.auto_heal,
        enable_lean_bridge=bool(getattr(args, "enable_lean_bridge", False)),
        include_tests=bool(getattr(args, "include_tests", False)),
        enable_body_port=bool(getattr(args, "enable_body_port", False)),
        enable_native_replay=bool(getattr(args, "enable_native_replay", False)),
        enable_summaries=bool(getattr(args, "enable_summaries", False)),
        go_types=getattr(args, "go_types", None),
        summaries_manifest_map=manifest_map,
        enable_summary_attempts=bool(
            getattr(args, "enable_summary_attempts", False)
        ),
        summary_attempt_timeout_ms=getattr(
            args, "summary_attempt_timeout", None
        ),
        enable_summary_plan=bool(getattr(args, "enable_summary_plan", False)),
        summary_plan_stamp=getattr(args, "summary_plan_stamp", 1),
        summary_plan_tool_version=getattr(
            args, "summary_plan_tool_version", None
        ),
        summary_plan_histories=getattr(args, "summary_plan_histories", None),
        scheduled_verification=scheduled_verification,
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


# Declared produce routes ``audit --enable-summaries`` invokes per
# collected unit. Go's unit is the package directory (one manifest per
# directory); the other languages summarize one file each.
_SUMMARY_ROUTE_BY_EXTENSION = {
    ".go": "go-summaries",
    ".ts": "ts-summaries",
    ".tsx": "ts-summaries",
    ".rs": "rust-summaries",
    ".sol": "sol-summaries",
}

_SUMMARY_ROUTE_TIMEOUT_SECONDS = 120
_SUMMARY_ERROR_TAIL_CHARS = 400
MAX_SUMMARY_MANIFEST_BYTES = 1024 * 1024
MAX_SUMMARY_MANIFEST_MAP_BYTES = 1024 * 1024


def _summary_audit_units(
    source_path: Path, code_files: list[Path]
) -> list[tuple[str, str, list[str]]]:
    """Group collected code files into (route, unit label, argv tail) units."""
    units: list[tuple[str, str, list[str]]] = []
    go_dirs: dict[Path, list[Path]] = {}
    for code_path in sorted(code_files):
        route = _SUMMARY_ROUTE_BY_EXTENSION.get(code_path.suffix.lower())
        if route is None:
            continue
        if route == "go-summaries":
            go_dirs.setdefault(code_path.parent, []).append(code_path)
        else:
            units.append((route, str(code_path), [str(code_path)]))
    for directory, files in sorted(go_dirs.items()):
        units.append(
            (
                "go-summaries",
                str(directory),
                [
                    arg
                    for f in files
                    for arg in ("--source", str(f))
                ],
            )
        )
    return units


def _collect_summary_plans(
    source_path: Path,
    code_files: list[Path],
    *,
    stamp: int,
    tool_version: str | None,
    histories_path: str | None,
    runner=None,
) -> list[dict]:
    """Plan the summary route once per profile present among the
    collected units and keep each advisory ``mumei.summaries-plan/v1``
    document.

    Routing only — no summary is derived and a selected adapter is a
    routing decision, not an accepted manifest. Advisory by
    construction: a declared planner failure (an unreadable histories
    file, an invalid stamp, a probe-runner error) records its status
    without failing the audit.
    """
    from agent.summaries_adapters import (
        GO_SUMMARY_PROFILE,
        RUST_SUMMARY_PROFILE,
        SOL_SUMMARY_PROFILE,
        TS_SUMMARY_PROFILE,
        build_plan_document,
        load_plan_histories,
        plan_summary_route,
    )
    from agent.verification_planner import PlannerPolicy

    route_profile = {
        "go-summaries": GO_SUMMARY_PROFILE,
        "rust-summaries": RUST_SUMMARY_PROFILE,
        "sol-summaries": SOL_SUMMARY_PROFILE,
        "ts-summaries": TS_SUMMARY_PROFILE,
    }
    profiles = sorted(
        {
            route_profile[route]
            for route, _unit, _argv in _summary_audit_units(
                source_path, code_files
            )
        }
    )
    try:
        histories = load_plan_histories(histories_path)
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        detail = str(exc)
        if histories_path is not None:
            detail = detail.replace(str(histories_path), "<histories>")
        return [
            {
                "profile": profile,
                "status": "failed",
                "error": _summary_error_text(detail, source_path, None),
            }
            for profile in profiles
        ]
    entries: list[dict] = []
    for profile in profiles:
        entry: dict = {"profile": profile}
        try:
            probe_plan = plan_summary_route(
                profile,
                PlannerPolicy(),
                stamp=stamp,
                tool_version=tool_version,
                histories=histories,
                runner=runner,
            )
        except (
            OSError,
            ValueError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
        ) as exc:
            detail = str(exc)
            if histories_path is not None:
                detail = detail.replace(str(histories_path), "<histories>")
            entry["status"] = "failed"
            entry["error"] = _summary_error_text(detail, source_path, None)
        else:
            entry["status"] = "planned"
            entry["plan"] = build_plan_document(profile, probe_plan)
        entries.append(entry)
    return entries


def _read_summary_manifest_map(path: Path) -> dict:
    """Load a ``--summaries-manifest-map`` document: a JSON object
    mapping each audit's emitted ``unit`` label to the prior summary
    manifest that unit should reuse."""
    with open(path, "rb") as handle:
        data = handle.read(MAX_SUMMARY_MANIFEST_MAP_BYTES + 1)
    if len(data) > MAX_SUMMARY_MANIFEST_MAP_BYTES:
        raise ValueError("summaries manifest map exceeds the bounded read limit")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ValueError("summaries manifest map is not UTF-8 JSON") from exc
    if type(value) is not dict or any(
        type(k) is not str or type(v) is not str for k, v in value.items()
    ):
        raise ValueError(
            "summaries manifest map must be an object of unit label to "
            "manifest path"
        )
    return value


def _summary_record_id(record: dict) -> str | None:
    """The identity field a manifest's record is keyed on: `name` for
    the rust/ts/sol families, `binding_id` for the go family."""
    for field in ("name", "binding_id"):
        value = record.get(field)
        if type(value) is str:
            return value
    return None


def _count_reused_functions(merged: dict, prior: dict) -> tuple[int, int]:
    """Partition the merged manifest's records: how many equal the
    prior manifest's record for the same function identity."""
    merged_functions = merged.get("functions")
    prior_functions = prior.get("functions")
    if not isinstance(merged_functions, list) or not isinstance(
        prior_functions, list
    ):
        return 0, 0
    prior_by_id = {
        _summary_record_id(record): record
        for record in prior_functions
        if type(record) is dict and _summary_record_id(record) is not None
    }
    reused = sum(
        1
        for record in merged_functions
        if type(record) is dict and record == prior_by_id.get(_summary_record_id(record))
    )
    return reused, len(merged_functions) - reused


def _collect_summary_audits(
    source_path: Path,
    code_files: list[Path],
    go_types: str | None,
    *,
    manifest_map: dict | None = None,
    attempt_timeout_ms: int | None = None,
    runner: Callable[[list[str]], subprocess.CompletedProcess] | None = None,
) -> list[dict]:
    """Run each declared produce route on its unit and keep only the
    manifest's declared metadata (context key + function count).

    Advisory by construction: a failed or skipped unit records its
    status without failing the audit, and manifest bytes are never
    stored in the report.

    With ``manifest_map`` (unit label -> prior manifest path, from
    ``--summaries-manifest-map``) a unit runs its ``*-summaries-reuse``
    route instead of the produce route: the merged manifest is keyed
    to the fresh context and the entry reports `mode: "reuse"` with
    `reused_function_count`/`derived_function_count` — merged records
    matched to the prior manifest's by `name`, or `binding_id` for the
    go family. A unit whose
    declared manifest is unreadable, malformed or rejected by the
    reuse route records `reuse_status: "stale_manifest"` and falls
    back to the produce route — a bad prior manifest can never
    weaken the audit.
    """
    run = runner or _run_summary_route
    entries: list[dict] = []
    for route, unit, argv_tail in _summary_audit_units(source_path, code_files):
        label = _directory_file_label(str(source_path), unit)
        entry: dict = {"route": route, "unit": label}
        if route == "go-summaries" and not go_types:
            entry["status"] = "skipped_no_helper"
            entries.append(entry)
            continue
        argv = [route]
        if route == "go-summaries":
            argv += ["--go-types", cast(str, go_types)]
        argv += argv_tail

        if attempt_timeout_ms is not None:
            # Attempt mode: the <route>-attempt lifecycle — the report's
            # acceptance envelope is recorded instead of manifest
            # metadata. There is no attempt variant of *-summaries-reuse,
            # so manifest replay stays out of this mode.
            attempt_argv = [f"{route}-attempt"]
            if route == "go-summaries":
                attempt_argv += ["--go-types", cast(str, go_types)]
            attempt_argv += argv_tail + [
                "--attempt-timeout",
                str(attempt_timeout_ms),
            ]
            try:
                completed = run(attempt_argv)
            except Exception as exc:  # runner failure (spawn, timeout)
                entry["status"] = "failed"
                entry["error"] = _summary_error_text(exc, source_path, go_types)
                entries.append(entry)
                continue
            if completed.returncode != 0:
                entry["status"] = "failed"
                entry["error"] = _summary_error_text(
                    _route_failure_text(completed), source_path, go_types
                )
                entries.append(entry)
                continue
            try:
                report = json.loads(completed.stdout)
                if type(report) is not dict:
                    raise ValueError("attempt report is not a JSON object")
            except (json.JSONDecodeError, ValueError) as exc:
                entry["status"] = "failed"
                entry["error"] = _summary_error_text(
                    str(exc), source_path, go_types
                )
                entries.append(entry)
                continue
            sequence = report.get("sequence")
            selected = (
                type(sequence) is dict
                and sequence.get("selected_result") is not None
            )
            entry["status"] = "emitted"
            entry["mode"] = "attempt"
            entry["selected"] = bool(selected)
            normalized = report.get("normalized")
            if type(normalized) is dict:
                stdout_meta = normalized.get("stdout")
                if type(stdout_meta) is dict and type(
                    stdout_meta.get("sha256")
                ) is str:
                    entry["manifest_sha256"] = stdout_meta["sha256"]
            evidence_check = report.get("evidence_check")
            if type(evidence_check) is dict and type(
                evidence_check.get("outcome")
            ) is str:
                entry["check_outcome"] = evidence_check["outcome"]
            acceptance = report.get("acceptance")
            if type(acceptance) is dict:
                entry["accepted"] = acceptance.get("accepted")
            entries.append(entry)
            continue

        prior_manifest: dict | None = None
        manifest_path = (manifest_map or {}).get(label)
        if manifest_path is not None:
            try:
                with open(manifest_path, "rb") as handle:
                    data = handle.read(MAX_SUMMARY_MANIFEST_BYTES + 1)
                if len(data) > MAX_SUMMARY_MANIFEST_BYTES:
                    raise ValueError("manifest exceeds the bounded read limit")
                candidate = json.loads(data.decode("utf-8"))
                if type(candidate) is not dict:
                    raise ValueError("manifest is not a JSON object")
                prior_manifest = candidate
            except (OSError, UnicodeDecodeError, ValueError, RecursionError) as exc:
                entry["reuse_status"] = "stale_manifest"
                entry["reuse_error"] = _summary_error_text(
                    str(exc).replace(manifest_path, "<manifest>"),
                    source_path,
                    go_types,
                )
            if prior_manifest is not None:
                reuse_argv = [f"{route}-reuse"]
                if route == "go-summaries":
                    reuse_argv += ["--go-types", cast(str, go_types)]
                reuse_argv += argv_tail + ["--manifest", manifest_path]
                reuse_manifest: dict | None = None
                try:
                    completed = run(reuse_argv)
                    if completed.returncode == 0:
                        reuse_manifest = json.loads(completed.stdout)
                        if type(reuse_manifest) is not dict:
                            reuse_manifest = None
                    else:
                        entry["reuse_error"] = _summary_error_text(
                            _route_failure_text(completed).replace(
                                manifest_path, "<manifest>"
                            ),
                            source_path,
                            go_types,
                        )
                except Exception as exc:
                    entry["reuse_error"] = _summary_error_text(
                        str(exc).replace(manifest_path, "<manifest>"),
                        source_path,
                        go_types,
                    )
                if reuse_manifest is not None:
                    reused, derived = _count_reused_functions(
                        reuse_manifest, prior_manifest
                    )
                    functions = reuse_manifest.get("functions")
                    entry["status"] = "emitted"
                    entry["mode"] = "reuse"
                    entry["context_key"] = reuse_manifest.get("context_key")
                    entry["function_count"] = (
                        len(functions) if isinstance(functions, list) else 0
                    )
                    entry["reused_function_count"] = reused
                    entry["derived_function_count"] = derived
                    entries.append(entry)
                    continue
                entry["reuse_status"] = "stale_manifest"
            # Stale or failed reuse falls back to the produce route.

        try:
            completed = run(argv)
        except Exception as exc:  # runner failure (spawn, timeout)
            entry["status"] = "failed"
            entry["error"] = _summary_error_text(exc, source_path, go_types)
            entries.append(entry)
            continue
        if completed.returncode != 0:
            entry["status"] = "failed"
            entry["error"] = _summary_error_text(
                _route_failure_text(completed), source_path, go_types
            )
            entries.append(entry)
            continue
        try:
            manifest = json.loads(completed.stdout)
            functions = manifest.get("functions")
            entry["context_key"] = manifest.get("context_key")
            entry["function_count"] = len(functions) if isinstance(functions, list) else 0
            entry["status"] = "emitted"
            if manifest_map is not None:
                entry["mode"] = "produce"
        except (json.JSONDecodeError, AttributeError):
            entry["status"] = "failed"
            entry["error"] = "produce route emitted no manifest JSON"
        entries.append(entry)
    return entries


def _route_failure_text(completed: subprocess.CompletedProcess) -> str:
    """Failure text for a refused produce route.

    The routes report refusals as an ``{"error": {...}}`` JSON document
    on stdout (often with empty stderr), so stdout's declared error is
    read first; stderr is the fallback.
    """
    try:
        document = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        document = None
    if isinstance(document, dict):
        error = document.get("error")
        if isinstance(error, dict):
            reason = error.get("reason") or error.get("message")
            if isinstance(reason, str) and reason:
                return reason
            return json.dumps(error, sort_keys=True)
        if isinstance(error, str) and error:
            return error
    return completed.stderr.strip() or f"produce route failed (exit {completed.returncode})"


def _summary_error_text(
    detail: object, source_path: Path, go_types: str | None
) -> str:
    text = detail if isinstance(detail, str) else str(detail)
    # Failure text reaches the report — keep checkout-local and
    # declared helper paths out.
    text = text.replace(str(source_path), ".")
    if go_types:
        text = text.replace(go_types, "<go-types>")
    executable = sys.executable
    if executable:
        text = text.replace(executable, "<python>")
    return text.strip()[-_SUMMARY_ERROR_TAIL_CHARS:]


def _run_summary_route(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "agent", *argv],
        capture_output=True,
        text=True,
        timeout=_SUMMARY_ROUTE_TIMEOUT_SECONDS,
        check=False,
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
