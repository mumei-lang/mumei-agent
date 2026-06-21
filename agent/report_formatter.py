"""Human-facing cross-validation report formatting."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Literal


def format_cross_validation_report(result: object, lang: Literal["en", "ja"] = "en") -> str:
    """Format spec/code cross-validation output for humans and PR comments."""
    payload = _payload(result)
    is_nl = "inferred_atoms" in payload and "contradictions" in payload
    if is_nl:
        return _format_nl_ja(payload) if lang == "ja" else _format_nl_en(payload)
    is_drift = "drift_issues" in payload
    return _format_ja(payload, is_drift) if lang == "ja" else _format_en(payload, is_drift)


def format_human_review_queue(queue: object, lang: str = "en") -> str:
    """Format contradiction, counterexample, and drift items for human review."""
    payload = _queue_payload(queue)
    atoms = _dict_list(payload.get("atoms"))
    title = "Human-in-the-Loop Review Queue" if lang != "ja" else "Human-in-the-Loop レビューキュー"
    lines = [
        f"## {title}",
        "",
        f"- Source: `{payload.get('source_file', payload.get('file', '-'))}`",
        f"- Pending items: `{len(atoms)}`",
        "",
        "### Review items" if lang != "ja" else "### 確認項目",
    ]
    if not atoms:
        lines.append("- No pending human-review items." if lang != "ja" else "- 確認待ち項目はありません。")
        return "\n".join(lines)

    for index, atom in enumerate(atoms, start=1):
        name = atom.get("name", atom.get("atom_name", f"item_{index}"))
        reason = atom.get("reason", atom.get("kind", "review"))
        status = atom.get("status", "pending")
        priority = atom.get("priority", "medium")
        lines.append(f"{index}. **{name}** — `{reason}` / `{status}` / priority `{priority}`")
        for label, key in (
            ("Summary", "summary"),
            ("Contradiction", "contradiction"),
            ("Counterexample", "counterexample"),
            ("Drift", "drift"),
            ("Evidence", "evidence"),
            ("Spec", "spec_text"),
            ("Suggested action", "suggested_action"),
        ):
            value = atom.get(key)
            if value:
                lines.append(f"   - {label}: `{_inline_value(value)}`")
    lines.append("")
    lines.append("### GitHub PR action" if lang != "ja" else "### GitHub PR 確認アクション")
    lines.append("- Confirm whether each item is acceptable before merge.")
    return "\n".join(lines)


def _payload(result: object) -> dict[str, object]:
    if is_dataclass(result) and not isinstance(result, type):
        value = asdict(result)
        return {str(key): item for key, item in value.items()}
    if isinstance(result, dict):
        return {str(key): item for key, item in result.items()}
    raise TypeError("cross-validation result must be a dataclass or dict")


def _queue_payload(queue: object) -> dict[str, object]:
    if isinstance(queue, dict):
        return {str(key): value for key, value in queue.items()}
    payload = _payload(queue)
    data = payload.get("data")
    if isinstance(data, dict):
        return {str(key): item for key, item in data.items()}
    return payload


def _format_en(payload: dict[str, object], is_drift: bool) -> str:
    title = "Code-to-Spec Drift Report" if is_drift else "Spec-to-Code Alignment Report"
    issue_key = "drift_issues" if is_drift else "missing_constraints"
    secondary_key = "" if is_drift else "divergences"
    lines = [f"## {title}", ""]
    lines.extend(_summary_lines(payload, ok_label="Passed", fail_label="Needs review"))
    ct = str(payload.get("contradiction_type", "") or "")
    if ct:
        lines.append(f"- contradiction_type: `{ct}`")
    lines.append("")
    issues = _dict_list(payload.get(issue_key))
    secondary = _dict_list(payload.get(secondary_key)) if secondary_key else []
    constraint_violations = _dict_list(payload.get("constraint_violations")) if not is_drift else []
    missing_constraint_strings = _string_list(payload.get("missing_constraints")) if not is_drift else []
    extra_behaviors = [str(item) for item in _object_list(payload.get("extra_behaviors"))]
    if constraint_violations or missing_constraint_strings or issues or secondary or extra_behaviors:
        lines.append("### Findings")
        if constraint_violations:
            lines.extend(_constraint_violation_lines(constraint_violations))
            if extra_behaviors:
                lines.append("")
                lines.append("### Extra behaviors")
                lines.extend(f"- `{behavior}`" for behavior in extra_behaviors)
        elif missing_constraint_strings:
            lines.extend(
                f"{index}. **spec_stronger**: spec `{constraint}`"
                for index, constraint in enumerate(missing_constraint_strings, start=1)
            )
            if secondary:
                lines.extend(_issue_lines(secondary))
        elif is_drift:
            lines.extend(_issue_lines(issues + secondary))
        else:
            lines.extend(_spec_code_issue_lines(issues, secondary))
        lines.append("")
        lines.append("### Reviewer action")
        lines.append("- Confirm whether each finding is an intentional spec/code change.")
        lines.append("- Update the implementation or the specification before merging if it is drift.")
    else:
        lines.append("### Findings")
        lines.append("- No spec drift or missing implementation constraints detected.")
        lines.append("")
        lines.append("### Reviewer action")
        lines.append("- No human intervention required.")
    lines.extend(_hunk_lines(payload, heading="Changed code hunks"))
    lines.extend(_warning_lines(payload, heading="Warnings"))
    return "\n".join(lines)


def _format_nl_en(payload: dict[str, object]) -> str:
    lines = ["## Natural-Language Spec Validation Report", ""]
    status = "Passed" if bool(payload.get("success")) else "Needs review"
    atoms = _dict_list(payload.get("inferred_atoms"))
    lines.extend(
        [
            f"- Status: **{status}**",
            f"- Inferred atoms: `{len(atoms)}`",
            f"- Satisfiable: `{payload.get('satisfiable')}`",
            "",
            "### Findings",
        ]
    )
    ct = str(payload.get("contradiction_type", "") or "")
    if ct:
        lines.append(f"- contradiction_type: `{ct}`")
    issues = (
        _dict_list(payload.get("contradictions"))
        + _dict_list(payload.get("ambiguities"))
        + _dict_list(payload.get("overconstraints"))
    )
    if issues:
        lines.extend(_issue_lines(issues))
    else:
        lines.append("- No contradictions, ambiguities, or overconstraints detected.")
    warnings = [
        *[str(item) for item in _object_list(payload.get("completeness_warnings"))],
        *[str(item) for item in _object_list(payload.get("vacuity_warnings"))],
        *[str(item) for item in _object_list(payload.get("warnings"))],
    ]
    errors = [str(item) for item in _object_list(payload.get("errors"))]
    if warnings or errors:
        lines.extend(["", "### Warnings"])
        for warning in warnings[:10]:
            lines.append(f"- {warning}")
        for error in errors[:10]:
            lines.append(f"- ERROR: {error}")
    return "\n".join(lines)


def _format_nl_ja(payload: dict[str, object]) -> str:
    lines = ["## 自然言語仕様バリデーションレポート", ""]
    status = "合格" if bool(payload.get("success")) else "要確認"
    atoms = _dict_list(payload.get("inferred_atoms"))
    lines.extend(
        [
            f"- Status: **{status}**",
            f"- 抽出 atom 数: `{len(atoms)}`",
            f"- Z3 充足可能性: `{payload.get('satisfiable')}`",
            "",
            "### 検出事項",
        ]
    )
    ct = str(payload.get("contradiction_type", "") or "")
    if ct:
        lines.append(f"- contradiction_type: `{ct}`")
    issues = (
        _dict_list(payload.get("contradictions"))
        + _dict_list(payload.get("ambiguities"))
        + _dict_list(payload.get("overconstraints"))
    )
    if issues:
        lines.extend(_issue_lines(issues))
    else:
        lines.append("- 矛盾・曖昧さ・過制約は検出されませんでした。")
    warnings = [
        *[str(item) for item in _object_list(payload.get("completeness_warnings"))],
        *[str(item) for item in _object_list(payload.get("vacuity_warnings"))],
        *[str(item) for item in _object_list(payload.get("warnings"))],
    ]
    errors = [str(item) for item in _object_list(payload.get("errors"))]
    if warnings or errors:
        lines.extend(["", "### 警告"])
        for warning in warnings[:10]:
            lines.append(f"- {warning}")
        for error in errors[:10]:
            lines.append(f"- ERROR: {error}")
    return "\n".join(lines)


def _format_ja(payload: dict[str, object], is_drift: bool) -> str:
    title = "コード→仕様ドリフトレポート" if is_drift else "仕様→コード整合性レポート"
    issue_key = "drift_issues" if is_drift else "missing_constraints"
    secondary_key = "" if is_drift else "divergences"
    lines = [f"## {title}", ""]
    lines.extend(_summary_lines(payload, ok_label="合格", fail_label="要確認"))
    ct = str(payload.get("contradiction_type", "") or "")
    if ct:
        lines.append(f"- contradiction_type: `{ct}`")
    lines.append("")
    issues = _dict_list(payload.get(issue_key))
    secondary = _dict_list(payload.get(secondary_key)) if secondary_key else []
    constraint_violations = _dict_list(payload.get("constraint_violations")) if not is_drift else []
    missing_constraint_strings = _string_list(payload.get("missing_constraints")) if not is_drift else []
    extra_behaviors = [str(item) for item in _object_list(payload.get("extra_behaviors"))]
    if constraint_violations or missing_constraint_strings or issues or secondary or extra_behaviors:
        lines.append("### 検出事項")
        if constraint_violations:
            lines.extend(_constraint_violation_lines(constraint_violations))
            if extra_behaviors:
                lines.append("")
                lines.append("### 仕様外のコード動作")
                lines.extend(f"- `{behavior}`" for behavior in extra_behaviors)
        elif missing_constraint_strings:
            lines.extend(
                f"{index}. **spec_stronger**: spec `{constraint}`"
                for index, constraint in enumerate(missing_constraint_strings, start=1)
            )
            if secondary:
                lines.extend(_issue_lines(secondary))
        elif is_drift:
            lines.extend(_issue_lines(issues + secondary))
        else:
            lines.extend(_spec_code_issue_lines(issues, secondary))
        lines.append("")
        lines.append("### Human-in-the-Loop 確認事項")
        lines.append("- 各検出事項が意図した仕様変更または実装変更か確認してください。")
        lines.append("- 仕様ドリフトの場合は、マージ前に実装または仕様を更新してください。")
    else:
        lines.append("### 検出事項")
        lines.append("- 実装漏れ・仕様ドリフトは検出されませんでした。")
        lines.append("")
        lines.append("### Human-in-the-Loop 確認事項")
        lines.append("- 追加の確認は不要です。")
    lines.extend(_hunk_lines(payload, heading="変更差分"))
    lines.extend(_warning_lines(payload, heading="警告"))
    return "\n".join(lines)


def _summary_lines(payload: dict[str, object], *, ok_label: str, fail_label: str) -> list[str]:
    status = ok_label if bool(payload.get("success")) else fail_label
    lines = [
        f"- Status: **{status}**",
        f"- Code: `{payload.get('code_path', '-')}`",
        f"- Language: `{payload.get('language', '-')}`",
    ]
    spec_path = payload.get("spec_path")
    if spec_path:
        lines.append(f"- Spec: `{spec_path}`")
    spec_atoms = _dict_list(payload.get("spec_atoms"))
    code_atoms = _dict_list(payload.get("code_atoms"))
    if spec_atoms or code_atoms:
        lines.append(f"- Compared atoms: spec={len(spec_atoms)}, code={len(code_atoms)}")
    return lines


def _issue_lines(issues: list[dict[str, object]]) -> list[str]:
    lines: list[str] = []
    for index, issue in enumerate(issues, start=1):
        kind = issue.get("kind", "issue")
        message = issue.get("message", "")
        evidence = issue.get("evidence", "")
        location = issue.get("location", "")
        source_line = int(issue.get("source_line") or 0)
        prefix = f"{index}. **{kind}**"
        if location:
            prefix += f" (`{location}`)"
        if source_line:
            prefix += f" line {source_line}"
        lines.append(f"{prefix}: {message}")
        if evidence:
            lines.append(f"   - Evidence: `{evidence}`")
        fix_suggestion = issue.get("fix_suggestion", "")
        if fix_suggestion:
            lines.append(f"   - Fix suggestion: `{fix_suggestion}`")
    return lines


def _constraint_violation_lines(violations: list[dict[str, object]]) -> list[str]:
    lines: list[str] = []
    for index, violation in enumerate(violations, start=1):
        spec_constraint = violation.get("spec_constraint", "")
        code_line = int(violation.get("code_line") or 0)
        contradiction_type = violation.get("contradiction_type", "spec_vs_code")
        line_suffix = f" line {code_line}" if code_line else ""
        lines.append(
            f"{index}. **{contradiction_type}**{line_suffix}: spec `{spec_constraint}`"
        )
        snippet = violation.get("code_snippet", "")
        if snippet:
            lines.append(f"   - Code: `{snippet}`")
        fix_suggestion = violation.get("fix_suggestion", "")
        if fix_suggestion:
            lines.append(f"   - Fix suggestion: `{fix_suggestion}`")
    return lines


def _string_list(value: object) -> list[str]:
    return [str(item) for item in _object_list(value) if str(item).strip()]


def _spec_code_issue_lines(
    missing_constraints: list[dict[str, object]],
    divergences: list[dict[str, object]],
) -> list[str]:
    typed_issues = [
        (_spec_code_issue_type(issue, is_missing=True), issue) for issue in missing_constraints
    ]
    typed_issues.extend(
        (_spec_code_issue_type(issue, is_missing=False), issue) for issue in divergences
    )
    lines: list[str] = []
    for index, (issue_type, issue) in enumerate(typed_issues, start=1):
        typed_issue = dict(issue)
        typed_issue["kind"] = issue_type
        issue_lines = _issue_lines([typed_issue])
        issue_lines[0] = issue_lines[0].replace("1. ", f"{index}. ", 1)
        lines.extend(issue_lines)
    return lines


def _spec_code_issue_type(issue: dict[str, object], *, is_missing: bool) -> str:
    message = str(issue.get("message", ""))
    if message.startswith("Spec validation issue:"):
        return "spec_internal"
    if message.startswith("Code atom ") and "not covered by the specification" in message:
        return "impl_stronger"
    if is_missing or "does not imply the spec postcondition" in message:
        return "spec_stronger"
    return "spec_vs_code"


def _hunk_lines(payload: dict[str, object], *, heading: str) -> list[str]:
    hunks = [str(item) for item in _object_list(payload.get("changed_hunks")) if str(item).strip()]
    if not hunks:
        return []
    lines = ["", f"### {heading}"]
    for hunk in hunks[:3]:
        lines.append("")
        lines.append("```diff")
        lines.append(hunk)
        lines.append("```")
    return lines


def _warning_lines(payload: dict[str, object], *, heading: str) -> list[str]:
    warnings = [str(item) for item in _object_list(payload.get("warnings")) if str(item).strip()]
    errors = [str(item) for item in _object_list(payload.get("errors")) if str(item).strip()]
    if not warnings and not errors:
        return []
    lines = ["", f"### {heading}"]
    for warning in warnings[:10]:
        lines.append(f"- {warning}")
    for error in errors[:10]:
        lines.append(f"- ERROR: {error}")
    return lines


def _object_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _inline_value(value: object) -> str:
    text = str(value).strip().replace("\n", " ")
    return text[:280] + "…" if len(text) > 280 else text


def _dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    dicts: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, dict):
            dicts.append({str(key): val for key, val in item.items()})
    return dicts
