"""Retry history tracker for multi-stage self-healing pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RetryAttempt:
    """Record of a single fix attempt."""

    attempt_number: int
    source_code: str
    error_log: str
    report_data: dict
    diagnosis: dict  # keys: root_cause, fix_approach, target_section


@dataclass
class RetryHistory:
    """Tracks the history of fix attempts across retries."""

    attempts: list[RetryAttempt] = field(default_factory=list)

    # Number of consecutive identical errors before triggering approach switch
    _repeat_threshold: int = 2

    def add(self, attempt: RetryAttempt) -> None:
        """Append an attempt to the history."""
        self.attempts.append(attempt)

    def format_for_prompt(self) -> str:
        """Format all previous attempts into a structured string for LLM context.

        Returns an empty string when there are no attempts.
        """
        if not self.attempts:
            return ""

        lines: list[str] = []
        for idx, att in enumerate(self.attempts):
            root_cause = att.diagnosis.get("root_cause", "unknown")
            fix_approach = att.diagnosis.get("fix_approach", "unknown")
            target_section = att.diagnosis.get("target_section", "unknown")
            failure_type = att.report_data.get("failure_type", "unknown")
            lines.append(
                f"### Attempt {att.attempt_number}\n"
                f"- Diagnosis: {root_cause}\n"
                f"- Approach: {fix_approach}\n"
                f"- Target section: {target_section}\n"
                f"- Result failure_type: {failure_type}"
            )
            # Annotate repeated errors
            if idx > 0:
                prev = self.attempts[idx - 1]
                if _same_error(prev.report_data, att.report_data):
                    lines.append("- **SAME ERROR REPEATED**")

        return "\n\n".join(lines)

    def error_diff(self) -> str:
        """Compare the latest two attempts and produce a structured diff.

        Returns an empty string when fewer than two attempts exist.
        """
        if len(self.attempts) < 2:
            return ""

        prev = self.attempts[-2].report_data
        curr = self.attempts[-1].report_data

        from agent.prompts.report_formatter import format_error_diff

        return format_error_diff(prev, curr)

    def is_same_error_repeating(self) -> bool:
        """Return True if the last N consecutive attempts share the same error.

        Uses ``_repeat_threshold`` (default 2) as the window size.
        """
        if len(self.attempts) < self._repeat_threshold:
            return False

        recent = self.attempts[-self._repeat_threshold :]
        first_report = recent[0].report_data
        return all(_same_error(first_report, att.report_data) for att in recent[1:])


def _same_error(a: dict, b: dict) -> bool:
    """Check whether two reports represent the same error."""
    if a.get("failure_type") != b.get("failure_type"):
        return False
    # Compare counterexample values (order-independent)
    ce_a = a.get("counterexample") or {}
    ce_b = b.get("counterexample") or {}
    return ce_a == ce_b
