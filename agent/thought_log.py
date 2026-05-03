"""Structured thought process log for verification loops."""
from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class VerificationStep:
    """検証ループの1ステップを記録する構造体。"""

    step_number: int
    timestamp: str
    action: str
    z3_result: dict[str, Any] | None = None
    verification_success: bool = False
    fix_strategy: str | None = None
    fix_description: str | None = None
    code_diff_summary: str | None = None
    re_verify_success: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class ThoughtProcess:
    """検証ループ全体の思考プロセスを記録する構造体。"""

    target_file: str
    started_at: str = field(
        default_factory=lambda: datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(timespec="seconds")
    )
    steps: list[VerificationStep] = field(default_factory=list)
    final_success: bool = False
    total_attempts: int = 0

    def add_step(self, **kwargs: Any) -> VerificationStep:
        step = VerificationStep(
            step_number=len(self.steps) + 1,
            timestamp=datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat(timespec="seconds"),
            **kwargs,
        )
        self.steps.append(step)
        return step

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_file": self.target_file,
            "started_at": self.started_at,
            "final_success": self.final_success,
            "total_attempts": self.total_attempts,
            "steps": [s.to_dict() for s in self.steps],
        }


def summarize_z3_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    report = result.get("report") or {}
    if not isinstance(report, dict):
        report = {}
    summary: dict[str, Any] = {}
    for key in (
        "violation_type",
        "failure_type",
        "counterexample",
        "failing_atoms",
        "unsat_core",
        "z3_check_result",
        "status",
        "reason",
    ):
        if key in report:
            summary[key] = report[key]
    if "success" in result:
        summary["success"] = bool(result.get("success"))
    if not summary and report:
        summary["report"] = report
    return summary or None


def summarize_code_diff(before: str, after: str) -> str:
    if before == after:
        return "No code changes."
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    prefix = 0
    while (
        prefix < len(before_lines)
        and prefix < len(after_lines)
        and before_lines[prefix] == after_lines[prefix]
    ):
        prefix += 1
    suffix = 0
    while (
        suffix < len(before_lines) - prefix
        and suffix < len(after_lines) - prefix
        and before_lines[len(before_lines) - 1 - suffix]
        == after_lines[len(after_lines) - 1 - suffix]
    ):
        suffix += 1
    removed = len(before_lines) - prefix - suffix
    added = len(after_lines) - prefix - suffix
    start_line = prefix + 1
    return f"Changed around line {start_line}: +{added} / -{removed} lines."


def infer_fix_strategy(report_data: dict[str, Any] | None) -> str:
    if isinstance(report_data, dict) and report_data.get("spec_refinement"):
        return "spec_refinement"
    return "llm"


def describe_fix(report_data: dict[str, Any] | None) -> str:
    if not isinstance(report_data, dict):
        return "Generated a candidate verification fix."
    violation = report_data.get("violation_type") or report_data.get("failure_type")
    if violation:
        return f"Generated a candidate fix for {violation}."
    return "Generated a candidate verification fix."
