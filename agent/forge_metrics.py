"""Forge metrics, result shaping, and deterministic rendering helpers."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent.metrics import metrics_quarter
from agent.prompts.report_formatter import (
    format_actionable_fix_hint,
    format_counterexample,
    format_structured_unsat_core,
)

_logger = logging.getLogger(__name__)


def _render_deterministic_atom(atom: dict[str, Any]) -> list[str]:
    name = str(atom.get("name", "generated_atom"))
    params = atom.get("inputs") or atom.get("params") or []
    param_text = ", ".join(
        f"{param.get('name', 'arg')}: {param.get('type', 'i64')}"
        for param in params
        if isinstance(param, dict)
    )
    requires = str(atom.get("requires", "true"))
    ensures = str(atom.get("ensures", "true"))
    body = str(atom.get("body") or atom.get("body_expr") or "0").strip()
    lines: list[str] = [f"// --- {name} ---"]
    lines.extend(
        [
            f"atom {name}({param_text})",
            f"    requires: {requires};",
            f"    ensures: {ensures};",
            "    body: {",
        ]
    )
    for body_line in body.splitlines():
        lines.append(f"        {body_line.strip()}")
    lines.append("    };")
    return lines


def _count_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    counts: dict[str, int] = {}
    for key, raw_count in value.items():
        if isinstance(key, str):
            try:
                counts[key] = int(raw_count)
            except (TypeError, ValueError):
                counts[key] = 0
    return counts


def _merge_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key, count in source.items():
        target[key] = target.get(key, 0) + count


def _success_counts_by_reason(
    value: Any,
    by_reason: dict[str, int],
    lean_successes: int,
) -> dict[str, int]:
    successes_by_reason = _count_mapping(value)
    if successes_by_reason:
        return successes_by_reason
    if len(by_reason) == 1:
        reason, attempts = next(iter(by_reason.items()))
        return {reason: min(lean_successes, attempts)}
    return {}


def _low_success_categories(
    by_reason: dict[str, int],
    successes_by_reason: dict[str, int],
) -> list[str]:
    categories = [
        reason
        for reason, attempts in by_reason.items()
        if attempts > 0 and successes_by_reason.get(reason, 0) / attempts < 0.5
    ]
    return sorted(categories)


def collect_escalation_metrics(bundle_path: str) -> dict[str, Any]:
    bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
    summary = bundle.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    candidates = bundle.get("candidates", [])
    if not isinstance(candidates, list):
        candidates = []

    by_reason = _count_mapping(summary.get("by_reason"))
    by_logic_fragment = _count_mapping(summary.get("by_logic_fragment"))
    lean_successes = 0
    successes_by_reason: dict[str, int] = {}
    partial_translation = 0
    manual_required = 0

    if candidates:
        by_reason = {}
        by_logic_fragment = {}
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            reason = candidate.get("escalation_reason")
            if isinstance(reason, str):
                by_reason[reason] = by_reason.get(reason, 0) + 1
            tags = candidate.get("logic_fragment_tags", [])
            if isinstance(tags, list):
                for tag in tags:
                    if isinstance(tag, str):
                        by_logic_fragment[tag] = by_logic_fragment.get(tag, 0) + 1
            lean_metadata = candidate.get("lean_metadata")
            status = lean_metadata.get("status") if isinstance(lean_metadata, dict) else None
            if status == "lean_verified":
                lean_successes += 1
                if isinstance(reason, str):
                    successes_by_reason[reason] = successes_by_reason.get(reason, 0) + 1
            elif status == "partial_translation":
                partial_translation += 1
            elif candidate.get("manual_lemma_reason") is not None:
                manual_required += 1

    candidate_count = int(summary.get("candidate_count", len(candidates)) or 0)
    total_atoms = int(summary.get("total_atoms", 0) or 0)
    if not candidates:
        lean_successes = int(summary.get("lean_successes", 0) or 0)
        successes_by_reason = _success_counts_by_reason(
            summary.get("successes_by_failure_reason"),
            by_reason,
            lean_successes,
        )
    success_rate = lean_successes / candidate_count if candidate_count else 0.0
    return {
        "total_atoms": total_atoms,
        "candidate_count": candidate_count,
        "escalation_attempts": candidate_count,
        "lean_successes": lean_successes,
        "partial_translation": partial_translation,
        "manual_required": manual_required,
        "success_rate": success_rate,
        "by_reason": by_reason,
        "by_failure_reason": by_reason,
        "successes_by_failure_reason": successes_by_reason,
        "by_logic_fragment": by_logic_fragment,
        "low_success_categories": _low_success_categories(by_reason, successes_by_reason),
    }


def track_escalation_trends(metrics_history: list[dict[str, Any]]) -> dict[str, Any]:
    quarters: dict[str, dict[str, Any]] = {}
    aggregate_by_reason: dict[str, int] = {}
    aggregate_by_logic_fragment: dict[str, int] = {}
    aggregate_successes_by_reason: dict[str, int] = {}
    aggregate_attempts = 0
    aggregate_successes = 0
    aggregate_partial_translation = 0
    aggregate_manual_required = 0

    for metrics in metrics_history:
        quarter = str(
            metrics.get("quarter")
            or metrics.get("metrics_quarter")
            or metrics_quarter()
        )
        quarter_metrics = quarters.setdefault(
            quarter,
            {
                "escalation_attempts": 0,
                "lean_successes": 0,
                "partial_translation": 0,
                "manual_required": 0,
                "by_reason": {},
                "successes_by_failure_reason": {},
                "by_logic_fragment": {},
                "low_success_categories": [],
            },
        )
        attempts = int(metrics.get("escalation_attempts", metrics.get("candidate_count", 0)) or 0)
        successes = int(metrics.get("lean_successes", 0) or 0)
        partial = int(metrics.get("partial_translation", 0) or 0)
        manual = int(metrics.get("manual_required", 0) or 0)
        by_reason = _count_mapping(
            metrics.get("by_failure_reason", metrics.get("by_reason", {}))
        )
        by_logic_fragment = _count_mapping(metrics.get("by_logic_fragment"))
        successes_by_reason = _success_counts_by_reason(
            metrics.get("successes_by_failure_reason"),
            by_reason,
            successes,
        )

        quarter_metrics["escalation_attempts"] += attempts
        quarter_metrics["lean_successes"] += successes
        quarter_metrics["partial_translation"] += partial
        quarter_metrics["manual_required"] += manual
        _merge_counts(quarter_metrics["by_reason"], by_reason)
        _merge_counts(quarter_metrics["successes_by_failure_reason"], successes_by_reason)
        _merge_counts(quarter_metrics["by_logic_fragment"], by_logic_fragment)

        aggregate_attempts += attempts
        aggregate_successes += successes
        aggregate_partial_translation += partial
        aggregate_manual_required += manual
        _merge_counts(aggregate_by_reason, by_reason)
        _merge_counts(aggregate_successes_by_reason, successes_by_reason)
        _merge_counts(aggregate_by_logic_fragment, by_logic_fragment)

    for quarter_metrics in quarters.values():
        attempts = quarter_metrics["escalation_attempts"]
        successes = quarter_metrics["lean_successes"]
        partial = quarter_metrics["partial_translation"]
        quarter_metrics["success_rate"] = successes / attempts if attempts else 0.0
        quarter_metrics["partial_translation_rate"] = partial / attempts if attempts else 0.0
        quarter_metrics["low_success_categories"] = _low_success_categories(
            quarter_metrics["by_reason"],
            quarter_metrics["successes_by_failure_reason"],
        )

    return {
        "quarters": dict(sorted(quarters.items())),
        "overall": {
            "escalation_attempts": aggregate_attempts,
            "lean_successes": aggregate_successes,
            "partial_translation": aggregate_partial_translation,
            "manual_required": aggregate_manual_required,
            "success_rate": aggregate_successes / aggregate_attempts if aggregate_attempts else 0.0,
            "partial_translation_rate": (
                aggregate_partial_translation / aggregate_attempts if aggregate_attempts else 0.0
            ),
            "by_reason": aggregate_by_reason,
            "successes_by_failure_reason": aggregate_successes_by_reason,
            "by_logic_fragment": aggregate_by_logic_fragment,
            "low_success_categories": _low_success_categories(
                aggregate_by_reason,
                aggregate_successes_by_reason,
            ),
        },
    }


@dataclass
class ForgeResult:
    """Outcome of forging a single task."""

    task_id: str
    status: str  # "success" | "failed" | "skipped"
    attempts: int = 0
    target_file: str | None = None
    atoms_added: list[str] = field(default_factory=list)
    logic_fragment_tags: list[str] = field(default_factory=list)
    outside_decidable_fragment: bool = False
    metrics_quarter: str | None = None
    commit_sha: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _enrich_error_with_report(
    raw_error: str,
    report: dict[str, Any] | None,
) -> str:
    """Augment a raw verifier error log with structured fix hints.

    Re-uses the existing ``report_formatter`` helpers so forge retries
    receive the same counterexample / unsat-core / actionable-fix-hint
    information that the heal and generate strategies already rely on.
    """
    if not report or not isinstance(report, dict):
        return raw_error

    structured_parts: list[str] = []
    try:
        hint = format_actionable_fix_hint(report)
        if hint:
            structured_parts.append(f"Actionable fix hint: {hint}")
    except Exception as exc:  # noqa: BLE001 — formatter must not break retry
        _logger.debug("format_actionable_fix_hint failed: %s", exc)

    try:
        ce = format_counterexample(report)
        if ce:
            structured_parts.append(ce)
    except Exception as exc:  # noqa: BLE001
        _logger.debug("format_counterexample failed: %s", exc)

    try:
        suc = format_structured_unsat_core(report)
        if suc:
            structured_parts.append(f"Structured unsat core:\n{suc}")
    except Exception as exc:  # noqa: BLE001
        _logger.debug("format_structured_unsat_core failed: %s", exc)

    if not structured_parts:
        return raw_error

    return (
        raw_error.rstrip()
        + "\n\n# Structured Analysis:\n"
        + "\n".join(structured_parts)
    )
