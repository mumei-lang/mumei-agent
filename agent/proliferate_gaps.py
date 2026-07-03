"""Gap-analysis helpers for proliferation."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from agent.gap_rules import analyze_gaps_local
from agent.propose import build_spec_from_proposal

logger = logging.getLogger(__name__)


def _prefer_mcp_gaps_enabled() -> bool:
    """Return True when ``PREFER_MCP_GAPS`` env var opts into MCP delegation."""
    return os.environ.get("PREFER_MCP_GAPS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def analyze_gaps(std_dir: Path) -> dict[str, Any]:
    """Analyze the mumei std/ directory for missing components.

    By default this runs the local-filesystem analyzer in
    :mod:`agent.gap_rules`.  When ``PREFER_MCP_GAPS=true`` is set in the
    environment **and** the mumei repo's ``mcp_server`` module is
    importable, the analysis is delegated to the MCP-side
    ``analyze_std_gaps`` tool instead so the rule set always matches
    the compiler repo.  Any failure to reach the MCP path silently
    falls back to the local analyzer.

    Returns a dict with keys:
        dependency_graph, trusted_atoms, todo_comments, proposals
    """
    if _prefer_mcp_gaps_enabled():
        try:
            from agent.propose import _load_gaps_from_mcp

            mcp_gaps = _load_gaps_from_mcp()
            if isinstance(mcp_gaps, dict) and "proposals" in mcp_gaps:
                logger.info(
                    "analyze_gaps: delegated to mumei MCP server (PREFER_MCP_GAPS=true)"
                )
                return mcp_gaps
            logger.debug(
                "analyze_gaps: MCP payload missing 'proposals'; using local fallback"
            )
        except SystemExit as exc:
            # _load_gaps_from_mcp raises SystemExit when the mumei repo
            # is not importable.  Treat that as a soft fallback.
            logger.debug(
                "analyze_gaps: MCP delegation unavailable (%s); falling back to local analysis",
                exc,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "analyze_gaps: MCP delegation raised %s; falling back to local analysis",
                exc,
            )

    return analyze_gaps_local(std_dir)


def generate_specs_from_gaps(
    gaps: dict[str, Any],
    max_count: int = 3,
) -> list[dict[str, Any]]:
    """Convert gap analysis proposals into forge task specs.

    Re-uses :func:`agent.propose.build_spec_from_proposal` for
    format compatibility with the existing forge runner.
    """
    proposals = gaps.get("proposals") or []
    if not isinstance(proposals, list):
        return []
    specs: list[dict[str, Any]] = []
    for idx, proposal in enumerate(proposals[:max_count], start=1):
        if not isinstance(proposal, dict):
            continue
        raw_priority = proposal.get("priority")
        spec = build_spec_from_proposal(
            proposal,
            priority=raw_priority if raw_priority is not None else idx,
        )
        specs.append(spec)
    return specs
