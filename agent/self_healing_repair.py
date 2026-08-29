"""Self-healing repair helpers."""
from __future__ import annotations

import datetime
from pathlib import Path

from agent.config import AgentConfig
from agent.meta_architect import MetaArchitect
from agent.strategies.cegis_loop import (
    CEGISLoop,
    apply_invariant,
    escalate_to_lean,
    normalize_loop_line,
)
from agent.strategies.refactor_strategy import apply_refactoring_proposal
from agent.strategies.retry_history import RetryHistory
from agent.self_healing_report import _retry_history_to_dict
from agent.thought_log import ThoughtProcess, VerificationStep, summarize_code_diff


def _try_cegis_repair(
    *,
    config: AgentConfig,
    mumei,
    source_file: str,
    source: str,
    report: dict,
    thought: ThoughtProcess,
) -> tuple[str | None, object] | None:
    failure_type = str(report.get("failure_type") or report.get("violation_type") or "")
    if not config.enable_cegis_loop or "invariant_violated" not in failure_type:
        return None
    loop_info = report.get("loop_info")
    if not isinstance(loop_info, dict):
        return None
    loop_line = normalize_loop_line(source, int(loop_info.get("line") or 0))
    if loop_line <= 0:
        return None
    loop_context = loop_info.get("context")
    if not isinstance(loop_context, dict):
        loop_context = {}
    cegis = CEGISLoop(config, mumei, max_iterations=config.cegis_max_iterations)
    result = cegis.run(source_file, loop_line, loop_context)
    if result.success and result.final_invariant:
        fixed_code = apply_invariant(source, result.final_invariant, loop_line)
        try:
            thought.steps.append(
                VerificationStep(
                    step_number=len(thought.steps) + 1,
                    timestamp=datetime.datetime.now(
                        datetime.timezone.utc
                    ).isoformat(timespec="seconds"),
                    action="cegis_invariant_generated",
                    fix_strategy="cegis_loop",
                    fix_description=f"Generated invariant: {result.final_invariant}",
                    code_diff_summary=summarize_code_diff(source, fixed_code),
                    verification_success=False,
                )
            )
        except Exception:
            pass
        return fixed_code, result

    if config.cegis_escalate_to_lean:
        bundle_path = escalate_to_lean(source_file, loop_info)
        try:
            thought.steps.append(
                VerificationStep(
                    step_number=len(thought.steps) + 1,
                    timestamp=datetime.datetime.now(
                        datetime.timezone.utc
                    ).isoformat(timespec="seconds"),
                    action="cegis_failed_escalate_to_lean",
                    fix_strategy="cegis_loop",
                    fix_description=f"Escalated to Lean bundle: {bundle_path}",
                    verification_success=False,
                )
            )
        except Exception:
            pass
    return None


def _record_review_only_proposal(
    thought: ThoughtProcess,
    proposal: dict,
) -> None:
    """Log a proposal that reports constraints instead of rewriting source.

    Session-protocol repairs span several specifications, so they are surfaced
    for review rather than applied automatically.
    """
    missing_constraints = proposal.get("missing_constraints")
    if not isinstance(missing_constraints, list) or not missing_constraints:
        return
    changes = proposal.get("changes")
    suggested_fix = ""
    if isinstance(changes, dict):
        suggested_fix = str(changes.get("suggested_fix") or "")
    description = str(proposal.get("description", "review-only proposal"))
    details = "; ".join(str(constraint) for constraint in missing_constraints)
    if suggested_fix:
        details = f"{details} | suggested fix: {suggested_fix}"
    try:
        thought.add_step(
            action="meta_architect_review_only",
            verification_success=False,
            fix_strategy=str(proposal.get("refactoring_type", "meta_architect")),
            fix_description=f"{description}. Missing constraints: {details}",
        )
    except Exception:
        pass


def _try_meta_architect_refactor(
    *,
    client,
    model: str,
    mumei,
    config: AgentConfig,
    source_files: list[Path],
    source: str,
    retry_history: RetryHistory,
    thought: ThoughtProcess,
) -> str | None:
    try:
        meta_architect = MetaArchitect(client, model, mumei, config)
        analysis = meta_architect.analyze_architecture(
            source_files,
            _retry_history_to_dict(retry_history),
        )
    except Exception as exc:
        try:
            thought.add_step(
                action="meta_architect_refactor",
                verification_success=False,
                fix_strategy="meta_architect_unavailable",
                fix_description=f"Meta-Architect analysis failed: {exc}",
            )
        except Exception:
            pass
        return None

    proposals = analysis.get("refactoring_proposals", [])
    if not isinstance(proposals, list):
        return None

    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        modified_code = apply_refactoring_proposal(proposal, source)
        if modified_code == source:
            _record_review_only_proposal(thought, proposal)
            continue
        try:
            thought.steps.append(
                VerificationStep(
                    step_number=len(thought.steps) + 1,
                    timestamp=datetime.datetime.now(
                        datetime.timezone.utc
                    ).isoformat(timespec="seconds"),
                    action="meta_architect_refactor",
                    fix_strategy=str(proposal.get("refactoring_type", "meta_architect")),
                    fix_description=str(proposal.get("description", "interface refactoring")),
                    code_diff_summary=summarize_code_diff(source, modified_code),
                    verification_success=False,
                )
            )
        except Exception:
            pass
        return modified_code
    return None
