"""Human-facing validation and no-.mm audit report formatting."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
import re
from typing import Literal

ReportFormat = Literal["human", "json", "markdown"]
ReportLang = Literal["auto", "en", "ja"]

_JA_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")


def format_result_report(
    result: object,
    output_format: ReportFormat = "human",
    *,
    lang: ReportLang = "auto",
) -> str:
    """Format audit, conformance, cross-validation, and scan_and_fix results."""
    payload = _payload(result)
    if output_format == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2)
    resolved_lang = _resolve_lang(payload, lang)
    return _format_markdown(payload, resolved_lang)


def format_cross_validation_report(
    result: object,
    lang: ReportLang = "auto",
    output_format: Literal["human", "markdown"] = "human",
) -> str:
    """Format spec/code cross-validation output for humans and PR comments."""
    payload = _payload(result)
    resolved_lang = _resolve_lang(payload, lang)
    return _format_markdown(payload, resolved_lang)


def format_human_review_queue(queue: object, lang: ReportLang = "auto") -> str:
    """Format contradiction, counterexample, and drift items for human review."""
    payload = _queue_payload(queue)
    resolved_lang = _resolve_lang(payload, lang)
    atoms = _dict_list(payload.get("atoms"))
    if resolved_lang == "ja":
        title = "Human-in-the-Loop レビューキュー"
        review_heading = "レビュー項目"
        empty = "- 人手レビュー待ちの項目はありません。"
        action_heading = "GitHub PR 確認アクション"
        confirm = "- マージ前に各項目を受け入れるか確認してください。"
    else:
        title = "Human-in-the-Loop Review Queue"
        review_heading = "Review items"
        empty = "- No pending human-review items."
        action_heading = "GitHub PR action"
        confirm = "- Confirm whether each item is acceptable before merge."
    lines = [
        f"## {title}",
        "",
        f"- Source: `{payload.get('source_file', payload.get('file', '-'))}`",
        f"- Pending items: `{len(atoms)}`",
        "",
        f"### {review_heading}",
    ]
    if not atoms:
        lines.append(empty)
        return "\n".join(lines)

    labels = _labels(resolved_lang)
    for index, atom in enumerate(atoms, start=1):
        name = atom.get("name", atom.get("atom_name", f"item_{index}"))
        reason = atom.get("reason", atom.get("kind", "review"))
        status = atom.get("status", "pending")
        priority = _priority(atom)
        lines.append(f"{index}. **{name}** — `{reason}` / `{status}` / {_importance_badge(priority, resolved_lang)}")
        for label_key, key in (
            ("summary", "summary"),
            ("contradiction", "contradiction"),
            ("counterexample", "counterexample"),
            ("drift", "drift"),
            ("evidence", "evidence"),
            ("spec", "spec_text"),
            ("fix", "suggested_action"),
        ):
            value = atom.get(key)
            if value:
                lines.append(f"   - {labels[label_key]}: `{_inline_value(value)}`")
    lines.append("")
    lines.append(f"### {action_heading}")
    lines.append(confirm)
    return "\n".join(lines)


def format_scan_and_fix_report(payload: object, lang: ReportLang = "auto") -> str:
    """Format MCP scan_and_fix payloads without changing their JSON contract."""
    return format_result_report(payload, "human", lang=lang)


def _format_markdown(payload: dict[str, object], lang: Literal["en", "ja"]) -> str:
    title = _title(payload, lang)
    labels = _labels(lang)
    lines = [f"## {title}", ""]
    lines.extend(_status_lines(payload, lang))
    role_lines = _scan_and_fix_role_lines(payload, lang)
    if role_lines:
        lines.append("")
        lines.extend(role_lines)
    lines.append("")
    lines.append(f"### {labels['next_steps']} (V1-E-1)")
    lines.extend(_next_step_lines(payload, lang))
    lines.append("")
    lines.append(f"### {labels['human_review_entrypoints']}")
    lines.extend(_human_review_entrypoint_lines(payload, lang))
    findings = _finding_lines(payload, lang)
    lines.append("")
    lines.append(f"### {labels['findings']}")
    lines.extend(findings)
    fixes = _copy_paste_fix_lines(payload, lang)
    if fixes:
        lines.append("")
        lines.append(f"### {labels['copy_paste_fixes']}")
        lines.extend(fixes)
    warnings = _warning_lines(payload, lang)
    if warnings:
        lines.append("")
        lines.append(f"### {labels['warnings']}")
        lines.extend(warnings)
    return "\n".join(lines).rstrip()


def _payload(result: object) -> dict[str, object]:
    if is_dataclass(result) and not isinstance(result, type):
        value = asdict(result)
        return {str(key): item for key, item in value.items()}
    if isinstance(result, dict):
        return {str(key): item for key, item in result.items()}
    raise TypeError("result must be a dataclass or dict")


def _queue_payload(queue: object) -> dict[str, object]:
    if isinstance(queue, dict):
        return {str(key): value for key, value in queue.items()}
    payload = _payload(queue)
    data = payload.get("data")
    if isinstance(data, dict):
        return {str(key): item for key, item in data.items()}
    return payload


def _resolve_lang(payload: dict[str, object], lang: ReportLang) -> Literal["en", "ja"]:
    if lang in {"en", "ja"}:
        return lang
    return "ja" if _contains_japanese(payload) else "en"


def _contains_japanese(value: object) -> bool:
    if isinstance(value, str):
        return bool(_JA_RE.search(value))
    if isinstance(value, dict):
        return any(_contains_japanese(item) for item in value.values())
    if isinstance(value, list | tuple | set):
        return any(_contains_japanese(item) for item in value)
    return False


def _labels(lang: Literal["en", "ja"]) -> dict[str, str]:
    if lang == "ja":
        return {
            "status": "ステータス",
            "passed": "合格",
            "needs_review": "要レビュー",
            "code": "コード",
            "spec": "仕様",
            "language": "言語",
            "next_steps": "次の手順",
            "human_review_entrypoints": "人手レビュー入口",
            "findings": "検出事項",
            "copy_paste_fixes": "コピペ可能な修正提案",
            "warnings": "警告",
            "summary": "概要",
            "contradiction": "矛盾",
            "counterexample": "反例",
            "drift": "ドリフト",
            "evidence": "根拠",
            "fix": "修正提案",
        }
    return {
        "status": "Status",
        "passed": "Passed",
        "needs_review": "Needs review",
        "code": "Code",
        "spec": "Spec",
        "language": "Language",
        "next_steps": "next_steps",
        "human_review_entrypoints": "Human review entrypoints",
        "findings": "Findings",
        "copy_paste_fixes": "Copy-pasteable fix suggestions",
        "warnings": "Warnings",
        "summary": "Summary",
        "contradiction": "Contradiction",
        "counterexample": "Counterexample",
        "drift": "Drift",
        "evidence": "Evidence",
        "fix": "Fix suggestion",
    }


def _title(payload: dict[str, object], lang: Literal["en", "ja"]) -> str:
    kind = _kind(payload)
    titles = {
        "ja": {
            "scan_and_fix": "scan_and_fix レポート",
            "audit_directory": "No-.mm ディレクトリ監査レポート",
            "audit": "No-.mm 監査レポート",
            "conformance": "Conformance 検証レポート",
            "traceability": "双方向トレーサビリティレポート",
            "nl": "自然言語仕様検証レポート",
            "drift": "コード→仕様ドリフトレポート",
            "alignment": "仕様→コード適合レポート",
            "generic": "Mumei レポート",
        },
        "en": {
            "scan_and_fix": "scan_and_fix Report",
            "audit_directory": "No-.mm Directory Audit Report",
            "audit": "No-.mm Audit Report",
            "conformance": "Conformance Verification Report",
            "traceability": "Bidirectional Traceability Report",
            "nl": "Natural-Language Spec Validation Report",
            "drift": "Code-to-Spec Drift Report",
            "alignment": "Spec-to-Code Alignment Report",
            "generic": "Mumei Report",
        },
    }
    return titles[lang][kind]


def _kind(payload: dict[str, object]) -> str:
    if "audit" in payload and "contract_terms" in payload:
        return "scan_and_fix"
    if "file_results" in payload and "source_dir" in payload:
        return "audit_directory"
    if "source_file" in payload and "verification_violations" in payload:
        return "audit"
    if "conformance" in payload and "drift" in payload and "drift_score" in payload:
        return "traceability"
    if "unimplemented_conditions" in payload and "hidden_specifications" in payload:
        return "conformance"
    if "inferred_atoms" in payload and "contradictions" in payload:
        return "nl"
    if "drift_issues" in payload:
        return "drift"
    if "missing_constraints" in payload or "divergences" in payload:
        return "alignment"
    return "generic"


def _status_lines(payload: dict[str, object], lang: Literal["en", "ja"]) -> list[str]:
    labels = _labels(lang)
    success = _payload_success(payload)
    status = labels["passed"] if success else labels["needs_review"]
    lines = [f"- {labels['status']}: **{status}**"]
    source_payload = _source_payload(payload)
    for label_key, keys in (
        ("code", ("code_path", "source_file")),
        ("spec", ("spec_path",)),
        ("language", ("language",)),
    ):
        for key in keys:
            value = payload.get(key) or source_payload.get(key)
            if value:
                lines.append(f"- {labels[label_key]}: `{value}`")
                break
    source_dir = payload.get("source_dir") or source_payload.get("source_dir")
    if source_dir:
        lines.append(f"- Source: `{source_dir}`")
    if "contradiction_type" in payload and payload.get("contradiction_type"):
        lines.append(f"- contradiction_type: `{payload['contradiction_type']}`")
    summary = payload.get("summary")
    if summary:
        lines.append(f"- Summary: {_inline_value(summary)}")
    return lines


def _scan_and_fix_role_lines(payload: dict[str, object], lang: Literal["en", "ja"]) -> list[str]:
    if _kind(payload) != "scan_and_fix":
        return []
    if lang == "ja":
        heading = "### scan_and_fix の役割分担"
        labels = {
            "audit": "既存コード監査と no-.mm migration/heal の入口",
            "spec_alignment": "spec→code の差分検出",
            "conformance_verification": "traceability と `next_steps` 起点の human review",
            "emits": "emits",
        }
    else:
        heading = "### scan_and_fix role split"
        labels = {
            "audit": "existing-code audit and no-.mm migration/heal entrypoint",
            "spec_alignment": "spec-to-code gap detection",
            "conformance_verification": "traceability plus `next_steps`-first human review",
            "emits": "emits",
        }
    audit_terms = (
        "`spec_health_issues`, `verification_violations`, `cross_validation_gaps`, "
        "`next_steps`, `migration_hints`, `healed_files`, `heal_errors`"
    )
    lines = [heading]
    audit_status = _component_status(payload.get("audit"), lang)
    alignment_status = _component_status(payload.get("spec_alignment"), lang)
    conformance_status = _component_status(payload.get("conformance_verification"), lang)
    lines.append(
        f"- `audit`: {audit_status} — {labels['audit']}; "
        f"{labels['emits']} {audit_terms}."
    )
    lines.append(
        f"- `spec_alignment`: {alignment_status} — {labels['spec_alignment']}."
    )
    lines.append(
        f"- `conformance_verification`: {conformance_status} — "
        f"{labels['conformance_verification']}."
    )
    return lines


def _component_status(value: object, lang: Literal["en", "ja"]) -> str:
    if not isinstance(value, dict):
        return "未実行" if lang == "ja" else "not requested"
    labels = _labels(lang)
    if "success" not in value:
        return labels["needs_review"]
    return labels["passed"] if bool(value["success"]) else labels["needs_review"]


def _payload_success(payload: dict[str, object]) -> bool:
    if "success" in payload:
        return bool(payload["success"])
    nested_successes: list[bool] = []
    for key in ("audit", "spec_alignment", "conformance_verification"):
        value = payload.get(key)
        if isinstance(value, dict) and "success" in value:
            nested_successes.append(bool(value["success"]))
    return all(nested_successes) if nested_successes else False


def _source_payload(payload: dict[str, object]) -> dict[str, object]:
    audit = payload.get("audit")
    if isinstance(audit, dict):
        return {str(key): value for key, value in audit.items()}
    return {}


def _next_step_lines(payload: dict[str, object], lang: Literal["en", "ja"]) -> list[str]:
    steps = _collect_next_steps(payload)
    if not steps:
        return ["- []"]
    lines: list[str] = []
    for index, step in enumerate(steps, start=1):
        priority = _priority(step)
        action = str(step.get("action", "")).strip()
        command = str(step.get("command", "")).strip()
        suffix = "human review first" if lang == "en" else "人手レビュー優先"
        lines.append(f"{index}. {_importance_badge(priority, lang)} {action or suffix}")
        if command:
            lines.extend(_fenced_block(command, "bash", indent="   "))
        fix = str(step.get("fix_suggestion", step.get("suggested_action", ""))).strip()
        if fix:
            lines.extend(_fenced_block(fix, "text", indent="   "))
    return lines


def _collect_next_steps(payload: dict[str, object]) -> list[dict[str, object]]:
    steps = _dict_list(payload.get("next_steps"))
    if _kind(payload) == "scan_and_fix":
        for key in ("audit", "spec_alignment", "conformance_verification"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                steps.extend(_dict_list(nested.get("next_steps")))
        return _dedupe_steps(steps)
    if steps:
        return steps
    audit = payload.get("audit")
    if isinstance(audit, dict):
        return _dict_list(audit.get("next_steps"))
    conformance = payload.get("conformance_verification")
    if isinstance(conformance, dict):
        return _dict_list(conformance.get("next_steps"))
    spec_alignment = payload.get("spec_alignment")
    if isinstance(spec_alignment, dict):
        return _dict_list(spec_alignment.get("next_steps"))
    return []


def _human_review_entrypoint_lines(payload: dict[str, object], lang: Literal["en", "ja"]) -> list[str]:
    labels = {
        "ja": {
            "intro": "- `next_steps` が human review の最初の入口です。",
            "gaps": "- `cross_validation_gaps`: ",
            "drift": "- `drift_issues`: ",
            "violations": "- `verification_violations`: ",
        },
        "en": {
            "intro": "- `next_steps` is the first human-review entrypoint.",
            "gaps": "- `cross_validation_gaps`: ",
            "drift": "- `drift_issues`: ",
            "violations": "- `verification_violations`: ",
        },
    }[lang]
    lines = [labels["intro"]]
    entries = [
        ("cross_validation_gaps", labels["gaps"], _string_list(payload.get("cross_validation_gaps"))),
        ("drift_issues", labels["drift"], _object_list(payload.get("drift_issues"))),
        ("verification_violations", labels["violations"], _object_list(payload.get("verification_violations"))),
    ]
    audit = payload.get("audit")
    if isinstance(audit, dict):
        entries.extend(
            [
                ("audit.cross_validation_gaps", labels["gaps"], _string_list(audit.get("cross_validation_gaps"))),
                (
                    "audit.verification_violations",
                    labels["violations"],
                    _object_list(audit.get("verification_violations")),
                ),
            ]
        )
    for nested_key in ("spec_alignment", "conformance_verification", "conformance", "drift"):
        nested = payload.get(nested_key)
        if isinstance(nested, dict):
            entries.extend(
                [
                    (
                        f"{nested_key}.cross_validation_gaps",
                        labels["gaps"],
                        _string_list(nested.get("cross_validation_gaps")),
                    ),
                    (
                        f"{nested_key}.verification_violations",
                        labels["violations"],
                        _object_list(nested.get("verification_violations")),
                    ),
                ]
            )
    for _key, prefix, values in entries:
        if values:
            lines.append(prefix + _inline_value(values[:3]))
    if len(lines) == 1:
        lines.append("- No review-only gaps were emitted." if lang == "en" else "- レビュー専用のギャップはありません。")
    return lines


def _finding_lines(payload: dict[str, object], lang: Literal["en", "ja"]) -> list[str]:
    items: list[str] = []
    for key in (
        "unimplemented_conditions",
        "hidden_specifications",
        "verification_violations",
        "cross_validation_gaps",
        "spec_health_issues",
        "constraint_violations",
        "missing_constraints",
        "divergences",
        "missing_constraint_issues",
        "extra_behaviors",
        "drift_issues",
        "spec_gaps",
        "implementation_overages",
        "contradictions",
        "ambiguities",
        "overconstraints",
        "migration_hints",
        "healed_files",
        "heal_errors",
    ):
        values = _object_list(payload.get(key))
        if values:
            items.append(f"- `{key}`")
            items.extend(f"  - {_item_line(value)}" for value in values[:10])
    audit = payload.get("audit")
    if isinstance(audit, dict):
        audit_lines = _finding_lines({str(key): value for key, value in audit.items()}, lang)
        if audit_lines and audit_lines != ["- No findings."] and audit_lines != ["- 検出事項はありません。"]:
            items.append("- `audit`")
            items.extend(f"  {line}" for line in audit_lines)
    for nested_key in ("spec_alignment", "conformance_verification", "conformance", "drift"):
        nested = payload.get(nested_key)
        if isinstance(nested, dict):
            nested_lines = _finding_lines({str(key): value for key, value in nested.items()}, lang)
            if nested_lines and nested_lines != ["- No findings."] and nested_lines != ["- 検出事項はありません。"]:
                items.append(f"- `{nested_key}`")
                items.extend(f"  {line}" for line in nested_lines)
    if not items:
        return ["- No findings." if lang == "en" else "- 検出事項はありません。"]
    return items


def _copy_paste_fix_lines(payload: dict[str, object], lang: Literal["en", "ja"]) -> list[str]:
    suggestions: list[str] = []
    _collect_fix_suggestions(payload, suggestions)
    if not suggestions:
        return []
    lines: list[str] = []
    for index, suggestion in enumerate(_dedupe(suggestions), start=1):
        lines.append(f"{index}.")
        lines.extend(_fenced_block(suggestion, "text", indent="   "))
    return lines


def _collect_fix_suggestions(value: object, suggestions: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"fix_suggestion", "suggested_action"} and item:
                suggestions.append(str(item))
            else:
                _collect_fix_suggestions(item, suggestions)
    elif isinstance(value, list | tuple):
        for item in value:
            _collect_fix_suggestions(item, suggestions)


def _warning_lines(payload: dict[str, object], lang: Literal["en", "ja"]) -> list[str]:
    warnings = [
        *_string_list(payload.get("warnings")),
        *_string_list(payload.get("errors")),
        *_string_list(payload.get("completeness_warnings")),
        *_string_list(payload.get("vacuity_warnings")),
    ]
    return [f"- {warning}" for warning in warnings[:20]]


def _priority(step: dict[str, object]) -> str:
    raw = str(step.get("priority", step.get("severity", "medium"))).strip().lower()
    if raw in {"critical", "blocker"}:
        return "critical"
    if raw in {"high", "error", "important"}:
        return "high"
    if raw in {"low", "info", "warning", "medium"}:
        return raw
    return "medium"


def _importance_badge(priority: str, lang: Literal["en", "ja"]) -> str:
    labels = {
        "critical": ("critical", "最重要"),
        "high": ("high", "重要"),
        "medium": ("medium", "通常"),
        "warning": ("warning", "注意"),
        "low": ("low", "低"),
        "info": ("info", "情報"),
    }
    en_label, ja_label = labels.get(priority, labels["medium"])
    label = ja_label if lang == "ja" else en_label
    return f"**[V1-E-1:{label}]**"


def _fenced_block(text: str, language: str, *, indent: str = "") -> list[str]:
    return [f"{indent}```{language}", *[f"{indent}{line}" for line in text.splitlines()], f"{indent}```"]


def _item_line(value: object) -> str:
    if isinstance(value, dict):
        kind = value.get("kind", value.get("status", value.get("priority", "item")))
        message = value.get("message", value.get("condition", value.get("evidence", value)))
        location = value.get("location", value.get("implementation_symbol", ""))
        prefix = f"**{kind}**"
        if location:
            prefix += f" `{location}`"
        return f"{prefix}: {_inline_value(message)}"
    return _inline_value(value)


def _inline_value(value: object) -> str:
    if isinstance(value, str):
        return value.replace("\n", "\\n")
    if isinstance(value, dict | list | tuple):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _string_list(value: object) -> list[str]:
    return [str(item) for item in _object_list(value) if str(item).strip()]


def _object_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


def _dict_list(value: object) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for item in _object_list(value):
        if is_dataclass(item) and not isinstance(item, type):
            item = asdict(item)
        if isinstance(item, dict):
            items.append({str(key): val for key, val in item.items()})
    return items


def _dedupe_steps(steps: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    deduped: list[dict[str, object]] = []
    for step in steps:
        marker = json.dumps(step, ensure_ascii=False, sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(step)
    return deduped


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped
