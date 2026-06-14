"""Suggest .mm migration skeletons for foreign-code functions."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Iterable

from agent.strategies.foreign_code_strategy import (
    ForeignCodeExtractor,
    ForeignCodeSpec,
    to_mumei_atom,
)


@dataclass
class MigrationHint:
    function_name: str
    priority: str
    reason: str
    skeleton: str
    next_step: str


def suggest_migration(
    function_name: str,
    source_code: str,
    language: str,
    issues: list[dict],
) -> MigrationHint:
    """Generate a .mm migration skeleton for a function with issues."""
    specs = ForeignCodeExtractor().extract(source_code, language)
    spec = _find_spec(function_name, specs)
    relevant_issues = _issues_for_function(function_name, issues)
    priority = _priority_for_issues(relevant_issues)
    skeleton = _trusted_atom_to_atom(to_mumei_atom(spec))
    reason = _reason_for_issues(relevant_issues)
    return MigrationHint(
        function_name=spec.function_name,
        priority=priority,
        reason=reason,
        skeleton=skeleton,
        next_step=(
            "Save this skeleton as a .mm atom, then run "
            "uv run python -m agent generate --spec-file <extracted_spec.json>"
        ),
    )


def suggest_migration_for_file(
    code_file: str,
    language: str,
    validation_result: dict,
) -> list[MigrationHint]:
    """Generate migration hints for all functions with issues in a file."""
    source_path = Path(code_file).expanduser().resolve()
    source_code = source_path.read_text(encoding="utf-8")
    specs = ForeignCodeExtractor().extract(source_code, language)
    issues = _issue_dicts(validation_result.get("issues", []))
    function_names = _function_names_with_issues(specs, issues)
    return [
        suggest_migration(name, source_code, language, issues)
        for name in function_names
    ]


def hints_to_dicts(hints: Iterable[MigrationHint]) -> list[dict[str, str]]:
    return [asdict(hint) for hint in hints]


def _find_spec(function_name: str, specs: list[ForeignCodeSpec]) -> ForeignCodeSpec:
    normalized = _safe_name(function_name)
    for spec in specs:
        if spec.function_name == normalized:
            return spec
    if specs:
        return specs[0]
    raise ValueError(f"function not found: {function_name}")


def _trusted_atom_to_atom(skeleton: str) -> str:
    return skeleton.replace("trusted atom ", "atom ", 1)


def _priority_for_issues(issues: list[dict]) -> str:
    kinds = {str(issue.get("kind", "")) for issue in issues}
    severities = {str(issue.get("severity", "")) for issue in issues}
    if kinds & {"postcondition_violated", "contradiction", "verification", "alignment"}:
        return "high"
    if "error" in severities or kinds & {"drift", "satisfiability", "overconstraint"}:
        return "medium"
    return "low"


def _reason_for_issues(issues: list[dict]) -> str:
    if not issues:
        return "No validation issue was provided; generated a low-priority migration skeleton."
    messages = [
        str(issue.get("message") or issue.get("kind") or "verification issue")
        for issue in issues
    ]
    return "; ".join(messages)


def _issue_dicts(raw_issues: object) -> list[dict]:
    if not isinstance(raw_issues, list):
        return []
    return [issue for issue in raw_issues if isinstance(issue, dict)]


def _function_names_with_issues(
    specs: list[ForeignCodeSpec],
    issues: list[dict],
) -> list[str]:
    spec_names = [spec.function_name for spec in specs]
    names: list[str] = []
    for issue in issues:
        candidate = _safe_name(str(issue.get("function_name") or issue.get("location") or ""))
        if not candidate:
            candidate = _name_from_text(str(issue.get("message") or ""))
        if candidate in spec_names and candidate not in names:
            names.append(candidate)
    if names:
        return names
    return spec_names if issues else []


def _issues_for_function(function_name: str, issues: list[dict]) -> list[dict]:
    if not issues:
        return []
    relevant: list[dict] = []
    for issue in issues:
        candidate = _safe_name(str(issue.get("function_name") or issue.get("location") or ""))
        message = str(issue.get("message") or "")
        if candidate == function_name or function_name in message:
            relevant.append(issue)
    return relevant or issues


def _name_from_text(text: str) -> str:
    match = re.search(r"`(?P<name>[A-Za-z_][A-Za-z0-9_]*)`", text)
    return _safe_name(match.group("name")) if match else ""


def _safe_name(name: str) -> str:
    stripped = name.strip()
    if not stripped:
        return ""
    safe = re.sub(r"\W+", "_", stripped)
    if safe and safe[0].isdigit():
        return f"fn_{safe}"
    return safe
