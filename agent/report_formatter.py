"""Human-facing validation and no-.mm audit report formatting."""
from __future__ import annotations

import json
from typing import Literal

from agent.report_formatter_core import (
    ReportFormat,
    ReportLang,
    _JA_RE,
    _collect_fix_suggestions,
    _collect_next_steps,
    _component_status,
    _contains_japanese,
    _copy_paste_fix_lines,
    _dedupe,
    _dedupe_steps,
    _dict_list,
    _fenced_block,
    _finding_lines,
    _format_markdown,
    _human_review_entrypoint_lines,
    _importance_badge,
    _inline_value,
    _item_line,
    _kind,
    _labels,
    _next_step_lines,
    _object_list,
    _payload,
    _payload_success,
    _priority,
    _queue_payload,
    _resolve_lang,
    _scan_and_fix_role_lines,
    _source_payload,
    _status_lines,
    _string_list,
    _title,
    _warning_lines,
)


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
