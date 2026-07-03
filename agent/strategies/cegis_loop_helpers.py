"""Pure loop-invariant helpers and result dataclasses for the CEGIS loop."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


@dataclass
class InvariantCandidate:
    """A candidate loop invariant expression."""

    expression: str
    source: str
    iteration: int
    counterexamples: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CEGISResult:
    """Result of CEGIS loop execution."""

    success: bool
    final_invariant: str | None
    iterations: int
    total_counterexamples: int
    reason: str


def apply_invariant(source_code: str, invariant: str, loop_line: int) -> str:
    """Apply a generated invariant to a loop statement."""
    lines = source_code.split("\n")
    if loop_line <= 0:
        return source_code
    for index, line in enumerate(lines):
        if index + 1 == loop_line:
            stripped = line.lstrip()
            if stripped.startswith("invariant:") or _loop_has_invariant(lines, index):
                return source_code
            indent = len(line) - len(stripped)
            lines.insert(index + 1, f"{' ' * indent}invariant: {invariant}")
            break
    return "\n".join(lines)


def _loop_has_invariant(lines: list[str], loop_index: int) -> bool:
    if " invariant:" in lines[loop_index]:
        return True
    for line in lines[loop_index + 1 :]:
        stripped = line.strip()
        if not stripped:
            continue
        return stripped.startswith("invariant:")
    return False


def escalate_to_lean(source_file: str, loop_info: dict[str, Any]) -> Path:
    """Write a Lean escalation bundle for a CEGIS exhaustion."""
    source_path = Path(source_file)
    bundle_path = source_path.with_suffix(".escalation-bundle.json")
    escalation_bundle = {
        "source_file": source_file,
        "loop_line": loop_info.get("line", 0),
        "loop_context": loop_info.get("context", {}),
        "reason": "cegis_max_iterations_reached",
    }
    bundle_path.write_text(
        json.dumps(escalation_bundle, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _logger.info("CEGIS exhausted iterations, escalated to Lean: %s", bundle_path)
    return bundle_path


def _extract_counterexample(report: dict[str, Any]) -> dict[str, Any]:
    for key in ("counterexample", "model"):
        value = report.get(key)
        if isinstance(value, dict):
            return value
    semantic_feedback = report.get("semantic_feedback")
    if isinstance(semantic_feedback, dict):
        value = semantic_feedback.get("counterexample")
        if isinstance(value, dict):
            return value
    return {}


def _clean_invariant(content: str) -> str:
    text = content.strip()
    if "```" in text:
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        text = text.removeprefix("mumei").strip()
    return text.strip().rstrip(";").strip()


def normalize_loop_line(source_code: str, reported_line: int) -> int:
    """Map a reported loop line to a 1-indexed line in the source text."""
    if reported_line > 0:
        lines = source_code.splitlines()
        if reported_line <= len(lines) and _is_loop_line(lines[reported_line - 1]):
            return reported_line
    return find_loop_line(source_code, reported_line)


def find_loop_line(source_code: str, hint_line: int = 0) -> int:
    """Find the nearest while-loop line, returning 0 when none is found."""
    lines = source_code.splitlines()
    candidates = [
        index + 1
        for index, line in enumerate(lines)
        if _is_loop_line(line)
    ]
    if not candidates:
        return 0
    if hint_line <= 0:
        return candidates[0]
    return min(candidates, key=lambda candidate: abs(candidate - hint_line))


def _is_loop_line(line: str) -> bool:
    return re.search(r"(^|\s)while\s+", line) is not None
