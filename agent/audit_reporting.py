"""Audit reporting and shaping helpers."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
import re
from typing import Literal

from agent.audit_models import AuditDirectoryResult, AuditResult
from agent.prompts.report_formatter import format_counterexample
from agent.report_formatter import format_result_report
from agent.strategies.cross_validation_strategy import CrossValidationReport
from agent.strategies.spec_health_strategy import SpecHealthReport


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
    if output_format == "text":
        return _result_report(result)
    from agent.report_formatter import format_result_report

    return format_result_report(result, "markdown" if output_format == "markdown" else "human")

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
                "command": "mumei-agent validate-spec-to-code --spec <spec> --code <file> --format human",
            }
        )
    if result.spec_health_issues:
        steps.append(
            {
                "priority": "medium",
                "action": "validate-spec で仕様の矛盾を修正",
                "command": "mumei-agent validate-spec --input <spec> --format human",
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
                "action": "監査完了。追加の .mm 移行は不要",
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
                "action": "監査完了。追加の .mm 移行は不要",
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
