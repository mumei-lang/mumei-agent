"""Phase 2-C — Self-Healing + Forge integration loop (proliferate).

Autonomous proliferation loop that chains:
  analyze_std_gaps → propose (spec generation) → generate_code (forge) →
  blast-radius check (existing std impact) → self-healing repair → publish PR

Usage::

    python -m agent proliferate --mumei-repo /path/to/mumei [--max-proposals 3] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from agent.config import AgentConfig
from agent.gap_rules import (
    _IMPORT_RE,
    _STD_GAP_RULES,
    _TODO_MARKER_RE,
    _TRUSTED_ATOM_RE,
    _collect_todo_comments,
    _collect_trusted_atoms,
    _evaluate_rule,
    _scan_std_imports,
    analyze_gaps_local,
)
from agent.mumei_client import MumeiClient, create_mumei_client
from agent.propose import build_spec_from_proposal
from agent.publish import publish
from agent.strategies.generate_strategy import generate_code

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gap Analysis (local filesystem, no MCP required)
# ---------------------------------------------------------------------------
#
# The actual rule list, regexes, and primitive helpers now live in
# ``agent.gap_rules`` so the offline fallback path is clearly isolated
# from the MCP-delegating wrapper below.  The names are re-exported via
# the import block above so existing callers (and tests) that reference
# ``proliferate._STD_GAP_RULES`` / ``_scan_std_imports`` etc. keep
# working.

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


# ---------------------------------------------------------------------------
# Spec generation from gap proposals
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Blast radius check
# ---------------------------------------------------------------------------


def check_blast_radius(
    mumei_client: MumeiClient,
    mumei_repo_dir: Path,
    new_file_path: Path,
    code: str,
) -> dict[str, Any]:
    """Check whether adding *code* at *new_file_path* breaks existing std.

    Writes the new ``.mm`` file to *new_file_path*, then verifies every
    existing ``.mm`` file under ``std/``.  On completion the new file is
    removed so the caller decides what to persist.

    Returns::

        {"broken_files": [{"file": ..., "error": ...}], "all_passed": bool}
    """
    std_dir = mumei_repo_dir / "std"
    wrote_new = False
    result: dict[str, Any] = {"broken_files": [], "all_passed": True}

    try:
        # Write new file
        new_file_path.parent.mkdir(parents=True, exist_ok=True)
        new_file_path.write_text(code, encoding="utf-8")
        wrote_new = True

        # Verify every existing .mm file (excluding the new one)
        for mm_file in sorted(std_dir.rglob("*.mm")):
            if mm_file.resolve() == new_file_path.resolve():
                continue
            verify = mumei_client.verify(str(mm_file))
            if not verify["success"]:
                result["broken_files"].append(
                    {"file": str(mm_file), "error": verify.get("stderr", "")}
                )
        result["all_passed"] = len(result["broken_files"]) == 0
    finally:
        # Clean up: remove the new file so caller controls persistence
        if wrote_new and new_file_path.exists():
            try:
                new_file_path.unlink()
            except OSError:
                pass

    return result


# ---------------------------------------------------------------------------
# Self-healing for broken files
# ---------------------------------------------------------------------------


def attempt_heal(
    client: Any,
    model: str,
    broken_info: dict[str, Any],
    mumei_client: MumeiClient,
    max_retries: int = 3,
) -> bool:
    """Attempt to heal a broken ``.mm`` file using the fix strategy.

    Uses :func:`agent.strategies.fix_strategy.get_fix` to generate
    candidate fixes, then re-verifies.  Returns ``True`` if the file
    was successfully repaired.
    """
    from agent.strategies.fix_strategy import get_fix

    file_path = broken_info["file"]
    try:
        source_code = Path(file_path).read_text(encoding="utf-8")
    except OSError:
        logger.error("Cannot read broken file %s", file_path)
        return False

    for attempt in range(max_retries):
        verify = mumei_client.verify(file_path)
        if verify["success"]:
            return True

        error_log = verify.get("stderr", "") + verify.get("stdout", "")
        report_data = verify.get("report") or {}

        fixed_code = get_fix(
            client=client,
            model=model,
            source_code=source_code,
            error_log=error_log,
            report_data=report_data,
            mumei_client=mumei_client,
            source_path=file_path,
        )
        if not fixed_code or fixed_code == source_code:
            logger.warning(
                "Heal attempt %d/%d for %s produced no change",
                attempt + 1,
                max_retries,
                file_path,
            )
            continue

        # Write fixed code and re-verify
        Path(file_path).write_text(fixed_code, encoding="utf-8")
        source_code = fixed_code

    # Final check
    final = mumei_client.verify(file_path)
    return final["success"]


# ---------------------------------------------------------------------------
# Main proliferate loop
# ---------------------------------------------------------------------------


def _log_step(step: int, total: int, message: str) -> None:
    """Emit a ``[PROLIFERATE]`` step log line readable in CI output.

    The prefix makes each step easy to locate in GitHub Actions logs,
    where many subsystems share stdout.
    """
    logger.info("[PROLIFERATE] Step %d/%d: %s", step, total, message)


def _log_info(message: str) -> None:
    """Emit a ``[PROLIFERATE]`` info line without a step counter."""
    logger.info("[PROLIFERATE] %s", message)


def _build_pr_body_extra(
    spec: dict[str, Any],
    proposal: dict[str, Any] | None,
    health_before: dict[str, Any] | None,
    health_after: dict[str, Any] | None,
) -> str:
    """Return the extra PR description prepended to :func:`publish`'s body.

    Includes the source proposal, health delta, and a marker tag so the
    PR is easy to filter by humans reviewing autonomous runs.
    """
    lines: list[str] = [
        "## [SI-5 Autonomous Proliferation]",
        "",
        "This pull request was opened automatically by the SI-5 Phase 3-B "
        "scheduled proliferation workflow. See "
        "[`docs/ROADMAP.md`](../blob/develop/docs/ROADMAP.md) for context.",
        "",
    ]

    # Proposal context
    lines.append("### Source proposal")
    target = spec.get("target_file") or spec.get("module_name") or "?"
    lines.append(f"- **target_file**: `{target}`")
    if proposal:
        if proposal.get("reason"):
            lines.append(f"- **reason**: {proposal['reason']}")
        if proposal.get("difficulty"):
            lines.append(f"- **difficulty**: `{proposal['difficulty']}`")
        depends = proposal.get("depends_on") or []
        if depends:
            joined = ", ".join(f"`{d}`" for d in depends)
            lines.append(f"- **depends_on**: {joined}")
        if proposal.get("priority") is not None:
            lines.append(f"- **priority**: {proposal['priority']}")
    lines.append("")

    # Health delta (or baseline when post-health is not yet available)
    if health_before is not None and health_after is not None:
        before = health_before.get("health_score", 0.0)
        after = health_after.get("health_score", 0.0)
        delta = after - before
        lines.append("### Proof health")
        lines.append(
            f"- health_score: **{before:.3f} → {after:.3f}** ({delta:+.3f})"
        )
        lines.append(
            f"- files verified: {health_before.get('verified_files', 0)}/"
            f"{health_before.get('total_files', 0)} → "
            f"{health_after.get('verified_files', 0)}/"
            f"{health_after.get('total_files', 0)}"
        )
        lines.append(
            f"- trusted atoms: {health_before.get('trusted_atoms', 0)} → "
            f"{health_after.get('trusted_atoms', 0)}"
        )
        lines.append("")
    elif health_before is not None:
        before = health_before.get("health_score", 0.0)
        lines.append("### Proof health (pre-run baseline)")
        lines.append(
            f"- health_score: **{before:.3f}**"
        )
        lines.append(
            f"- files verified: {health_before.get('verified_files', 0)}/"
            f"{health_before.get('total_files', 0)}"
        )
        lines.append(
            f"- trusted atoms: {health_before.get('trusted_atoms', 0)}"
        )
        lines.append("")

    lines.append("### Verification summary")
    lines.append(
        "- Generated code passed `mumei verify --json` before blast-radius "
        "check."
    )
    lines.append(
        "- `check_blast_radius` verified every existing `std/*.mm` file "
        "with the candidate in place."
    )
    lines.append("")

    return "\n".join(lines)


def proliferate(
    mumei_repo_dir: str | Path,
    *,
    max_proposals: int = 3,
    dry_run: bool = False,
    mumei_bin: str | None = None,
    output_json: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Run the autonomous proliferation loop.

    1. Analyze std/ gaps
    2. Generate forge task specs from proposals
    3. For each spec: generate code → blast-radius check → heal → publish

    Parameters
    ----------
    mumei_repo_dir:
        Path to the mumei repository (must contain ``std/``).
    max_proposals:
        Maximum number of proposals to process.
    dry_run:
        If True, skip git/PR operations and do not persist generated files.
    mumei_bin:
        Path or command for the mumei binary.
    output_json:
        Optional path to write a structured run summary as JSON.
        Consumed by the SI-5 Phase 3-B scheduled workflow so operators
        can review pre/post health and per-proposal outcomes as a CI
        artifact.

    Returns
    -------
    List of result dicts, one per proposal.
    """
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    )
    mumei_repo = Path(mumei_repo_dir).resolve()
    std_dir = mumei_repo / "std"

    if not std_dir.exists():
        logger.error("std/ directory not found at %s", std_dir)
        results = [{"success": False, "reason": "std_dir_not_found"}]
        _write_output_json(
            output_json,
            started_at=started_at,
            pre_health=None,
            post_health=None,
            results=results,
            dry_run=dry_run,
        )
        return results

    # Optional: measure initial health.  This may fail when the mumei
    # binary is unavailable or std/ files cannot be verified; the
    # try/except ensures the proliferation loop proceeds regardless.
    health_before: dict[str, Any] | None = None
    health_client: MumeiClient | None = None
    try:
        from agent.std_health import measure_health as _measure_health

        config_for_health = AgentConfig()
        health_client = create_mumei_client(
            mumei_bin or config_for_health.mumei_bin
        )
        health_before = _measure_health(health_client, std_dir)
        _log_info(
            f"Initial health score: {health_before['health_score']:.2f} "
            f"({health_before['verified_files']}/"
            f"{health_before['total_files']} files verified)"
        )
    except Exception:
        logger.debug("Could not measure initial health", exc_info=True)

    # Step 1: Gap analysis
    _log_step(1, 4, f"Analyzing gaps in {std_dir}")
    gaps = analyze_gaps(std_dir)
    if not gaps["proposals"]:
        _log_info("No proposals found — std/ is complete or no gaps detected")
        results = [{"success": True, "reason": "no_proposals"}]
        _write_output_json(
            output_json,
            started_at=started_at,
            pre_health=health_before,
            post_health=health_before,
            results=results,
            dry_run=dry_run,
        )
        return results

    _log_info(
        f"Found {len(gaps['proposals'])} proposal(s): "
        + ", ".join(p["name"] for p in gaps["proposals"])
    )

    # Step 2: Generate specs
    _log_step(2, 4, "Generating forge task specs")
    specs = generate_specs_from_gaps(gaps, max_count=max_proposals)
    if not specs:
        results = [{"success": True, "reason": "no_specs_generated"}]
        _write_output_json(
            output_json,
            started_at=started_at,
            pre_health=health_before,
            post_health=health_before,
            results=results,
            dry_run=dry_run,
        )
        return results

    # Cache proposals by target for PR description enrichment.
    proposals_by_target: dict[str, dict[str, Any]] = {
        p["name"]: p for p in gaps["proposals"] if isinstance(p, dict)
    }

    # Step 3: Process each spec
    config = AgentConfig()
    effective_mumei_bin = mumei_bin or config.mumei_bin
    # ``USE_MCP_CLIENT=true`` opts into richer MCP-backed verification
    # for the proliferate loop; otherwise this is a plain MumeiClient.
    mumei_client = create_mumei_client(effective_mumei_bin)
    openai_client = config.create_client()

    results: list[dict[str, Any]] = []
    for idx, spec in enumerate(specs, start=1):
        spec_result: dict[str, Any] = {
            "spec": spec,
            "success": False,
        }
        target_file = spec.get("target_file", "unknown.mm")
        _log_step(3, 4, f"Forging proposal {idx}/{len(specs)}: {target_file}")

        # 3a. Generate code
        try:
            code, verified = generate_code(
                client=openai_client,
                model=config.model,
                spec=spec,
                config_max_retries=config.max_retries,
                mumei_client=mumei_client,
            )
        except Exception as exc:
            logger.error("Code generation failed for %s: %s", target_file, exc)
            spec_result["reason"] = f"generation_error: {exc}"
            results.append(spec_result)
            continue

        if not code:
            logger.warning("No code generated for %s", target_file)
            spec_result["reason"] = "empty_code"
            results.append(spec_result)
            continue

        if not verified:
            logger.warning("Generated code for %s did not pass verification", target_file)
            spec_result["reason"] = "verification_failed"
            results.append(spec_result)
            continue

        _log_info(f"Forged {target_file}: verified=True")
        spec_result["code"] = code
        spec_result["verified"] = verified

        # 3b. Blast radius check
        _log_step(4, 4, f"Blast-radius check for {target_file}")
        new_file_path = mumei_repo / target_file
        blast = check_blast_radius(mumei_client, mumei_repo, new_file_path, code)
        _log_info(
            f"Blast-radius result for {target_file}: "
            f"all_passed={blast['all_passed']}, "
            f"broken={len(blast['broken_files'])}"
        )

        # Track files that were healed so they can be committed alongside
        # the new file in the non-dry-run path.
        healed_files: dict[str, str] = {}

        if blast["broken_files"]:
            logger.warning(
                "Blast radius check: %d file(s) broken by %s",
                len(blast["broken_files"]),
                target_file,
            )

            # In dry-run mode, skip healing entirely — report breakage
            # without mutating any files on disk.
            if dry_run:
                spec_result["blast_radius"] = blast["broken_files"]
                spec_result["reason"] = "blast_radius_broken_dry_run"
                spec_result["dry_run"] = True
                results.append(spec_result)
                continue

            # 3c. Attempt to heal broken files
            # First, re-place the new file so healing operates in context
            new_file_path.parent.mkdir(parents=True, exist_ok=True)
            new_file_path.write_text(code, encoding="utf-8")

            # Snapshot originals so we can restore on partial-heal failure
            originals: dict[str, str] = {}
            for broken in blast["broken_files"]:
                bp = Path(broken["file"])
                try:
                    originals[broken["file"]] = bp.read_text(encoding="utf-8")
                except OSError:
                    pass

            all_healed = True
            try:
                for broken in blast["broken_files"]:
                    healed = attempt_heal(
                        client=openai_client,
                        model=config.model,
                        broken_info=broken,
                        mumei_client=mumei_client,
                    )
                    if not healed:
                        logger.error(
                            "Could not heal %s — skipping proposal %s",
                            broken["file"],
                            target_file,
                        )
                        all_healed = False
                        break
            except Exception:
                logger.exception(
                    "Unexpected error during healing for %s", target_file,
                )
                all_healed = False

            if not all_healed:
                # Rollback: restore modified existing files, then remove new
                for fpath, content in originals.items():
                    try:
                        Path(fpath).write_text(content, encoding="utf-8")
                    except OSError:
                        logger.warning("Could not restore %s during rollback", fpath)
                if new_file_path.exists():
                    new_file_path.unlink()
                spec_result["reason"] = "blast_radius_heal_failed"
                results.append(spec_result)
                continue

            # Collect healed file contents for later commit, then restore
            # originals so the working tree stays clean until publish time.
            for fpath, original_content in originals.items():
                try:
                    current = Path(fpath).read_text(encoding="utf-8")
                except OSError:
                    continue
                if current != original_content:
                    healed_files[fpath] = current
                # Restore original — non-dry-run publish block will write
                # both the new file and healed files atomically.
                try:
                    Path(fpath).write_text(original_content, encoding="utf-8")
                except OSError:
                    logger.warning("Could not restore %s after heal snapshot", fpath)

            # Remove the new file — publish block below handles placement
            if new_file_path.exists():
                new_file_path.unlink()

        # 3d. Publish (or dry-run)
        if dry_run:
            logger.info("Dry run — skipping publish for %s", target_file)
            spec_result["success"] = True
            spec_result["dry_run"] = True
            results.append(spec_result)
            continue

        # Non-dry-run: pass the blast-radius-tested code to publish()
        # via ``pre_generated_code`` so it commits the exact verified
        # artifact instead of re-generating from scratch.
        #
        # NOTE: healed files (if any) are written to disk before
        # publish() runs, but publish()'s git-add only stages the
        # generated ``.mm`` file and the ``katana/`` output directory.
        # A future improvement could extend publish() to accept
        # additional files to stage.
        #
        # ``_build_pr_body_extra()`` receives ``health_after=None``
        # because post-health is only measured after all proposals
        # complete.  The PR description will show the pre-run baseline
        # instead of a delta.
        new_file_path.parent.mkdir(parents=True, exist_ok=True)
        new_file_path.write_text(code, encoding="utf-8")
        for fpath, healed_content in healed_files.items():
            try:
                Path(fpath).write_text(healed_content, encoding="utf-8")
            except OSError:
                logger.warning("Could not write healed file %s", fpath)

        # Write spec to a temp file for publish().  Initialise the path
        # to ``None`` up-front so the ``finally`` cleanup stays safe even
        # when ``NamedTemporaryFile()`` itself raises before assignment.
        tmp_spec_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".json",
                delete=False,
                encoding="utf-8",
            ) as tmp:
                json.dump(spec, tmp, indent=2, ensure_ascii=False)
                tmp_spec_path = tmp.name

            proposal_meta = proposals_by_target.get(target_file)
            pub_result = publish(
                spec_path=tmp_spec_path,
                mumei_bin=effective_mumei_bin,
                repo_dir=str(mumei_repo),
                dry_run=False,
                pr_title_prefix="[SI-5 Autonomous Proliferation]",
                pr_body_extra=_build_pr_body_extra(
                    spec=spec,
                    proposal=proposal_meta,
                    health_before=health_before,
                    health_after=None,
                ),
                pre_generated_code=code,
            )
            spec_result["publish_result"] = pub_result
            spec_result["success"] = pub_result.get("success", False)
            if pub_result.get("pr_url"):
                spec_result["pr_url"] = pub_result["pr_url"]
        except Exception as exc:
            logger.error("Publish failed for %s: %s", target_file, exc)
            spec_result["reason"] = f"publish_error: {exc}"
        finally:
            if tmp_spec_path is not None:
                try:
                    Path(tmp_spec_path).unlink(missing_ok=True)
                except Exception:
                    pass

        results.append(spec_result)

    # Optional: measure final health
    health_after: dict[str, Any] | None = None
    if health_before is not None and health_client is not None:
        try:
            health_after = _measure_health(health_client, std_dir)
            delta = health_after["health_score"] - health_before["health_score"]
            succeeded_count = sum(1 for r in results if r.get("success"))
            _log_info(
                f"Result: {succeeded_count}/{len(results)} proposals "
                f"succeeded, health_score: "
                f"{health_before['health_score']:.2f} → "
                f"{health_after['health_score']:.2f} ({delta:+.2f})"
            )
        except Exception:
            logger.debug("Could not measure final health", exc_info=True)

    _write_output_json(
        output_json,
        started_at=started_at,
        pre_health=health_before,
        post_health=health_after,
        results=results,
        dry_run=dry_run,
    )

    return results


def _write_output_json(
    output_json: str | Path | None,
    *,
    started_at: str,
    pre_health: dict[str, Any] | None,
    post_health: dict[str, Any] | None,
    results: list[dict[str, Any]],
    dry_run: bool,
) -> None:
    """Write a structured summary of the run to *output_json* (if set).

    The summary is consumed by the SI-5 Phase 3-B scheduled workflow as
    a CI artifact so operators can diff health before/after each run
    without re-reading unstructured logs.
    """
    if output_json is None:
        return
    succeeded = sum(1 for r in results if r.get("success"))
    processed = len(results)
    payload: dict[str, Any] = {
        "timestamp": started_at,
        "dry_run": bool(dry_run),
        "pre_health": pre_health,
        "post_health": post_health,
        "proposals_processed": processed,
        "proposals_succeeded": succeeded,
        "proposals_failed": processed - succeeded,
        "details": [_jsonify_result(r) for r in results],
    }
    path = Path(output_json)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _log_info(f"Wrote run summary to {path}")
    except OSError as exc:
        logger.warning("Could not write output JSON %s: %s", path, exc)


def _jsonify_result(result: dict[str, Any]) -> dict[str, Any]:
    """Strip non-JSON-serialisable fields from a proliferate result.

    Generated code can be large and is already committed (or discarded
    in dry-run mode), so we only keep short summary-friendly fields.
    """
    out: dict[str, Any] = {}
    for key, value in result.items():
        if key == "code":
            out["code_length"] = len(value) if isinstance(value, str) else 0
        elif key == "spec":
            out["spec"] = {
                k: value.get(k)
                for k in (
                    "task_id",
                    "target_file",
                    "mode",
                    "module_name",
                    "name",
                )
                if isinstance(value, dict) and k in value
            }
        else:
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser(parser: argparse.ArgumentParser) -> None:
    """Add proliferate-specific arguments to *parser*."""
    parser.add_argument(
        "--mumei-repo",
        required=True,
        help="Path to the mumei repository (must contain std/)",
    )
    parser.add_argument(
        "--max-proposals",
        type=int,
        default=3,
        help="Maximum number of proposals to process (default: 3)",
    )
    parser.add_argument(
        "--mumei-bin",
        default=None,
        help="Path to the mumei binary (default: MUMEI_BIN env or 'mumei')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip git/PR operations and do not persist generated files",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help=(
            "Optional path to write a structured run summary as JSON "
            "(used by the SI-5 Phase 3-B scheduled workflow)."
        ),
    )


def main(args: argparse.Namespace) -> None:
    """Entry point for the proliferate subcommand."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    results = proliferate(
        mumei_repo_dir=args.mumei_repo,
        max_proposals=args.max_proposals,
        dry_run=args.dry_run,
        mumei_bin=args.mumei_bin,
        output_json=args.output_json,
    )

    succeeded = sum(1 for r in results if r.get("success"))
    total = len(results)
    print(f"\nproliferate: {succeeded}/{total} proposal(s) succeeded")

    for r in results:
        spec = r.get("spec", {})
        target = spec.get("target_file", r.get("reason", "?"))
        status = "OK" if r.get("success") else "FAIL"
        reason = r.get("reason", "")
        pr_url = r.get("pr_url", "")
        line = f"  [{status}] {target}"
        if reason:
            line += f" — {reason}"
        if pr_url:
            line += f" — PR: {pr_url}"
        print(line)

    if succeeded == 0 and total > 0:
        import sys

        sys.exit(1)
