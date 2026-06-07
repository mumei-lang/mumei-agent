"""Human-facing cross-validation report formatting."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Literal


def format_cross_validation_report(result: object, lang: Literal["en", "ja"] = "en") -> str:
    """Format spec/code cross-validation output for humans and PR comments."""
    payload = _payload(result)
    is_drift = "drift_issues" in payload
    return _format_ja(payload, is_drift) if lang == "ja" else _format_en(payload, is_drift)


def _payload(result: object) -> dict[str, object]:
    if is_dataclass(result) and not isinstance(result, type):
        value = asdict(result)
        return {str(key): item for key, item in value.items()}
    if isinstance(result, dict):
        return {str(key): item for key, item in result.items()}
    raise TypeError("cross-validation result must be a dataclass or dict")


def _format_en(payload: dict[str, object], is_drift: bool) -> str:
    title = "Code-to-Spec Drift Report" if is_drift else "Spec-to-Code Alignment Report"
    issue_key = "drift_issues" if is_drift else "missing_constraints"
    secondary_key = "" if is_drift else "divergences"
    lines = [f"## {title}", ""]
    lines.extend(_summary_lines(payload, ok_label="Passed", fail_label="Needs review"))
    lines.append("")
    issues = _dict_list(payload.get(issue_key))
    secondary = _dict_list(payload.get(secondary_key)) if secondary_key else []
    if issues or secondary:
        lines.append("### Findings")
        lines.extend(_issue_lines(issues + secondary))
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


def _format_ja(payload: dict[str, object], is_drift: bool) -> str:
    title = "コード→仕様ドリフトレポート" if is_drift else "仕様→コード整合性レポート"
    issue_key = "drift_issues" if is_drift else "missing_constraints"
    secondary_key = "" if is_drift else "divergences"
    lines = [f"## {title}", ""]
    lines.extend(_summary_lines(payload, ok_label="合格", fail_label="要確認"))
    lines.append("")
    issues = _dict_list(payload.get(issue_key))
    secondary = _dict_list(payload.get(secondary_key)) if secondary_key else []
    if issues or secondary:
        lines.append("### 検出事項")
        lines.extend(_issue_lines(issues + secondary))
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
        prefix = f"{index}. **{kind}**"
        if location:
            prefix += f" (`{location}`)"
        lines.append(f"{prefix}: {message}")
        if evidence:
            lines.append(f"   - Evidence: `{evidence}`")
    return lines


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


def _dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    dicts: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, dict):
            dicts.append({str(key): val for key, val in item.items()})
    return dicts
