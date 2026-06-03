"""Phase 2-C — Self-Healing + Forge integration loop (proliferate).

Autonomous proliferation loop that chains:
  analyze_std_gaps → propose (spec generation) → generate_code (forge) →
  blast-radius check (existing std impact) → self-healing repair → publish PR

Usage::

    python -m agent proliferate --mumei-repo /path/to/mumei [--max-proposals 3] [--dry-run]
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime
import hashlib
import json
import logging
import os
import re
import tempfile
from threading import Lock
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
from agent.harness_metrics import HarnessMetrics, harness_profile_names
from agent.metrics import Metrics
from agent.mumei_client import MumeiClient, create_mumei_client
from agent.propose import build_spec_from_proposal
from agent.publish import publish
from agent.strategies.generate_strategy import generate_code
from agent.thought_log import (
    ThoughtProcess,
    describe_fix,
    summarize_code_diff,
    summarize_z3_result,
)

logger = logging.getLogger(__name__)
_FORGE_CACHE_LOCK = Lock()

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


def _metrics_payload(metrics: Metrics) -> dict[str, float | int]:
    return {
        "attempts": metrics.total_attempts,
        "tokens_to_success": metrics.llm_tokens_used,
        "solver_seconds_to_success": sum(metrics.verification_times_seconds),
        "spec_drift_score": 0.0,
    }


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
    thought_process: ThoughtProcess | None = None,
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
        if thought_process is not None:
            try:
                thought_process.add_step(
                    action="initial_verify" if attempt == 0 else "re_verify",
                    z3_result=summarize_z3_result(verify),
                    verification_success=bool(verify["success"]),
                    re_verify_success=(
                        bool(verify["success"]) if attempt > 0 else None
                    ),
                )
            except Exception:
                pass
        if verify["success"]:
            if thought_process is not None:
                try:
                    thought_process.final_success = True
                    thought_process.total_attempts = attempt + 1
                except Exception:
                    pass
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
        if thought_process is not None:
            try:
                thought_process.add_step(
                    action="llm_fix",
                    verification_success=False,
                    fix_strategy="llm",
                    fix_description=describe_fix(report_data),
                    code_diff_summary=(
                        summarize_code_diff(source_code, fixed_code)
                        if fixed_code
                        else "No candidate fix produced."
                    ),
                )
            except Exception:
                pass
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
    if thought_process is not None:
        try:
            thought_process.add_step(
                action="re_verify",
                z3_result=summarize_z3_result(final),
                verification_success=bool(final["success"]),
                re_verify_success=bool(final["success"]),
            )
            thought_process.final_success = bool(final["success"])
            thought_process.total_attempts = len(
                [
                    s
                    for s in thought_process.steps
                    if s.action in ("initial_verify", "re_verify")
                ]
            )
        except Exception:
            pass
    return final["success"]


# ---------------------------------------------------------------------------
# Main proliferate loop
# ---------------------------------------------------------------------------

def _spec_cache_key(spec: dict[str, Any]) -> str:
    payload = json.dumps(spec, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _forge_cache_path(mumei_repo_dir: Path) -> Path:
    return mumei_repo_dir / ".mumei_agent" / "proliferate_forge_cache.json"


def _cache_results(
    cache_path: str | Path,
    spec: dict[str, Any],
    result: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Read or write a verified forge result cache entry for *spec*."""
    with _FORGE_CACHE_LOCK:
        path = Path(cache_path)
        key = _spec_cache_key(spec)
        cache: dict[str, Any] = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    cache = loaded
            except (OSError, json.JSONDecodeError):
                logger.debug(
                    "Ignoring unreadable forge cache at %s",
                    path,
                    exc_info=True,
                )

        if result is None:
            entry = cache.get(key)
            return entry if isinstance(entry, dict) else None

        if not result.get("verified") or not result.get("code"):
            return None

        entry = {
            "target_file": spec.get("target_file"),
            "code": result["code"],
            "verified": True,
            "cached_at": datetime.datetime.now(datetime.timezone.utc).isoformat(
                timespec="seconds"
            ),
        }
        cache[key] = entry
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            tmp_path.write_text(
                json.dumps(cache, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp_path.replace(path)
        except OSError:
            logger.debug("Could not write forge cache at %s", path, exc_info=True)
        return entry


def _detect_diffs(
    mumei_repo_dir: str | Path,
    target_file: str | Path,
    code: str,
) -> dict[str, Any]:
    """Return content-level diff metadata for a generated target file."""
    path = Path(mumei_repo_dir) / target_file
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    old_hash = (
        hashlib.sha256(existing.encode("utf-8")).hexdigest()
        if existing is not None
        else None
    )
    new_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    return {
        "target_file": str(target_file),
        "exists": existing is not None,
        "changed": existing != code,
        "old_sha256": old_hash,
        "new_sha256": new_hash,
    }


def _forge_worker_count(spec_count: int, override: int | None = None) -> int:
    if spec_count <= 0:
        return 0
    if override is not None:
        return max(1, min(override, spec_count))
    raw = os.environ.get("PROLIFERATE_FORGE_WORKERS", "").strip()
    if raw:
        try:
            return max(1, min(int(raw), spec_count))
        except ValueError:
            logger.warning("Ignoring invalid PROLIFERATE_FORGE_WORKERS=%r", raw)
    return max(1, min(4, spec_count))


def _run_forge_generation(
    *,
    index: int,
    spec: dict[str, Any],
    config: AgentConfig,
    mumei_client: MumeiClient,
    cache_path: Path,
) -> tuple[int, dict[str, Any], Metrics]:
    target_file = spec.get("target_file", "unknown.mm")
    thought = ThoughtProcess(target_file=str(target_file))
    spec_result: dict[str, Any] = {
        "spec": spec,
        "success": False,
        "thought_process": thought,
    }
    generation_metrics = Metrics()

    cached = _cache_results(cache_path, spec)
    if cached and cached.get("verified") and cached.get("code"):
        spec_result["code"] = cached["code"]
        spec_result["verified"] = True
        spec_result["cache_hit"] = True
        return index, spec_result, generation_metrics

    try:
        code, verified = generate_code(
            client=config.create_client(),
            model=config.model,
            spec=spec,
            config_max_retries=config.max_retries,
            mumei_client=mumei_client,
            metrics=generation_metrics,
            thought_process=thought,
        )
    except Exception as exc:
        logger.error("Code generation failed for %s: %s", target_file, exc)
        spec_result["reason"] = f"generation_error: {exc}"
        try:
            thought.final_success = False
            thought.total_attempts = len(
                [
                    step
                    for step in thought.steps
                    if step.action in ("initial_verify", "re_verify")
                ]
            )
        except Exception:
            pass
        return index, spec_result, generation_metrics

    if not code:
        logger.warning("No code generated for %s", target_file)
        spec_result["reason"] = "empty_code"
    elif not verified:
        logger.warning("Generated code for %s did not pass verification", target_file)
        spec_result["reason"] = "verification_failed"
    else:
        _log_info(f"Forged {target_file}: verified=True")
        spec_result["code"] = code
        spec_result["verified"] = verified
        _cache_results(cache_path, spec, spec_result)

    if not spec_result.get("verified"):
        try:
            thought.final_success = False
            thought.total_attempts = len(
                [
                    step
                    for step in thought.steps
                    if step.action in ("initial_verify", "re_verify")
                ]
            )
        except Exception:
            pass

    return index, spec_result, generation_metrics


def _parallel_forge(
    specs: list[dict[str, Any]],
    *,
    config: AgentConfig,
    mumei_client: MumeiClient,
    harness_metrics: HarnessMetrics,
    cache_path: str | Path,
    max_workers: int | None = None,
) -> list[dict[str, Any]]:
    """Generate forge candidates concurrently and preserve input order."""
    if not specs:
        return []
    workers = _forge_worker_count(len(specs), max_workers)
    path = Path(cache_path)

    def run(index: int, spec: dict[str, Any]) -> dict[str, Any]:
        _, result, metrics = _run_forge_generation(
            index=index,
            spec=spec,
            config=config,
            mumei_client=mumei_client,
            cache_path=path,
        )
        success = bool(result.get("verified"))
        harness_metrics.record_result(
            "proliferate_generation",
            success,
            retry_class=("cache_hit" if result.get("cache_hit") else "none")
            if success
            else str(result.get("reason", "generation_error")).split(":", 1)[0],
            **_metrics_payload(metrics),
        )
        return result

    if workers == 1:
        return [run(idx, spec) for idx, spec in enumerate(specs, start=1)]

    ordered: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(run, idx, spec): idx
            for idx, spec in enumerate(specs, start=1)
        }
        for future in as_completed(futures):
            ordered[futures[future]] = future.result()
    return [ordered[idx] for idx in sorted(ordered)]


def _log_step(step: int, total: int, message: str) -> None:
    """Emit a ``[PROLIFERATE]`` step log line readable in CI output.

    The prefix makes each step easy to locate in GitHub Actions logs,
    where many subsystems share stdout.
    """
    logger.info("[PROLIFERATE] Step %d/%d: %s", step, total, message)


def _log_info(message: str) -> None:
    """Emit a ``[PROLIFERATE]`` info line without a step counter."""
    logger.info("[PROLIFERATE] %s", message)


def _close_pr_for_regression(pr_url: str, health_delta: float) -> bool:
    """Best-effort close *pr_url* with a health-regression comment.

    Used by :func:`proliferate` when the post-flight health snapshot
    regresses relative to the pre-flight baseline.  We try ``gh pr
    close`` first because the CI runner already has a configured
    ``GITHUB_TOKEN``; a missing or non-functional ``gh`` is treated as
    soft-fail so the surrounding loop keeps going.

    Returns ``True`` when ``gh`` reports success, ``False`` otherwise.
    """
    import shutil
    import subprocess

    if not pr_url:
        return False
    if shutil.which("gh") is None:
        logger.info(
            "auto-close: gh CLI not available; leaving %s open for manual review",
            pr_url,
        )
        return False
    comment = (
        f"Auto-closing: SI-5 proliferation detected proof-health regression "
        f"(delta={health_delta:+.3f}). See workflow logs for details."
    )
    try:
        subprocess.run(
            ["gh", "pr", "close", pr_url, "--comment", comment],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        logger.warning("auto-close failed for %s: %s", pr_url, exc)
        return False
    logger.info("auto-close: closed %s due to health regression", pr_url)
    return True


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


def _run_lean_fallback(
    results: list[dict[str, Any]],
    *,
    mumei_lean_repo: str | None,
) -> None:
    """Hand any ``unknown`` atoms in *results* to ``mumei-lean``.

    Mutates each ``spec_result`` in place with a ``"lean_fallback"``
    sub-dict that records what was attempted, so downstream consumers
    (the summary JSON, operators reading the run log) can audit the
    fallback without re-running the bridge.

    The Lean fallback is best-effort: any failure short-circuits the
    enrichment for that spec and leaves the rest of the run untouched.
    """
    from agent import lean_bridge

    import tempfile

    available = lean_bridge.lean_fallback_available(mumei_lean_repo)
    if not available:
        logger.info(
            "lean fallback: unavailable — MUMEI_LEAN_REPO not set or invalid"
        )

    for spec_result in results:
        publish_result = spec_result.get("publish_result") or {}
        cert = (
            publish_result.get("proof_certificate")
            or publish_result.get("certificate")
        )
        if not isinstance(cert, dict):
            continue
        unknown_atoms = lean_bridge.extract_unknown_atoms(cert)
        if not unknown_atoms:
            continue
        if not available:
            spec_result["lean_fallback"] = {
                "attempted": True,
                "unknown_count": len(unknown_atoms),
                "proved": 0,
                "failed": len(unknown_atoms),
                "success": False,
                "returncode": -1,
                "error_code": "lean_unavailable",
                "diagnostics": [
                    "MUMEI_LEAN_REPO is unset or does not point to a checkout "
                    "containing scripts/bridge.py."
                ],
            }
            continue

        with tempfile.TemporaryDirectory(prefix="mumei-lean-") as tmpdir:
            cert_path = Path(tmpdir) / "input.proof-cert.json"
            cert_path.write_text(
                json.dumps(cert, ensure_ascii=False),
                encoding="utf-8",
            )
            lean_cert_out = Path(tmpdir) / "output.lean-cert.json"
            bridge_result = lean_bridge.run_lean_bridge(
                cert_path=cert_path,
                lean_cert_out=lean_cert_out,
                mumei_lean_repo=mumei_lean_repo or "",
            )
            lean_cert = bridge_result.get("lean_cert")
            if isinstance(lean_cert, dict):
                upgraded = lean_bridge.merge_lean_cert_into_proof_cert(
                    cert, lean_cert
                )
                unknown_names = {
                    a["name"]
                    for a in unknown_atoms
                    if isinstance(a.get("name"), str)
                }
                proved = sum(
                    1
                    for a in upgraded.get("atoms", []) or []
                    if isinstance(a, dict)
                    and a.get("name") in unknown_names
                    and a.get("z3_check_result") == "lean_verified"
                )
            else:
                upgraded = cert
                proved = 0
            failed = max(len(unknown_atoms) - proved, 0)

            spec_result["lean_fallback"] = {
                "attempted": True,
                "unknown_count": len(unknown_atoms),
                "proved": proved,
                "failed": failed,
                "success": bridge_result.get("success", False),
                "returncode": bridge_result.get("returncode", -1),
                "error_code": bridge_result.get("error_code"),
                "diagnostics": bridge_result.get("diagnostics", []),
            }
            logger.info(
                "Lean fallback: %d/%d unknown atoms discharged",
                proved,
                len(unknown_atoms),
            )
            spec_result["upgraded_cert"] = upgraded


def _lean_fallback_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    attempted = 0
    proved = 0
    failed = 0
    for result in results:
        fallback = result.get("lean_fallback")
        if not isinstance(fallback, dict) or not fallback.get("attempted"):
            continue
        unknown_count = int(fallback.get("unknown_count") or 0)
        proved_count = int(fallback.get("proved") or 0)
        failed_count = fallback.get("failed")
        attempted += unknown_count
        proved += proved_count
        if isinstance(failed_count, int):
            failed += failed_count
        else:
            failed += max(unknown_count - proved_count, 0)
    success_rate = proved / attempted if attempted else None
    return {
        "lean_fallback_attempted": attempted,
        "lean_fallback_proved": proved,
        "lean_fallback_failed": failed,
        "lean_fallback_success_rate": success_rate,
    }


def _attach_dry_run_proof_certificate(
    spec_result: dict[str, Any],
    code: str,
    mumei_client: MumeiClient,
) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".mm",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp_path = tmp.name
        tmp.write(code)
    try:
        verify_result = mumei_client.verify(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    report = verify_result.get("report")
    if not isinstance(report, dict):
        return
    spec_result["publish_result"] = {
        "success": bool(verify_result.get("success", False)),
        "proof_certificate": report,
        "verified_at_generation": bool(spec_result.get("verified", False)),
    }


def proliferate(
    mumei_repo_dir: str | Path,
    *,
    max_proposals: int = 3,
    dry_run: bool = False,
    mumei_bin: str | None = None,
    output_json: str | Path | None = None,
    enable_lean_fallback: bool = True,
    harness_profile: str = "basic",
    parallel_forge_workers: int | None = None,
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
    harness_metrics = HarnessMetrics.from_profile(harness_profile)
    enable_lean_fallback = enable_lean_fallback or harness_metrics.lean_fallback_enabled
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
            harness_metrics=harness_metrics,
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
        # PR 4: in no-op early returns we reuse ``health_before`` as the
        # post snapshot (no mutation occurred), so the delta is a
        # well-defined 0.0 whenever the pre-flight measurement
        # succeeded. Emitting ``None`` here would violate the
        # _write_output_json contract that ``health_delta`` is a float
        # whenever both snapshots are non-null.
        _write_output_json(
            output_json,
            started_at=started_at,
            pre_health=health_before,
            post_health=health_before,
            health_delta=0.0 if health_before is not None else None,
            results=results,
            dry_run=dry_run,
            harness_metrics=harness_metrics,
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
        # PR 4: same rationale as the ``no_proposals`` branch above —
        # no mutation occurred, so the delta is 0.0 rather than None.
        _write_output_json(
            output_json,
            started_at=started_at,
            pre_health=health_before,
            post_health=health_before,
            health_delta=0.0 if health_before is not None else None,
            results=results,
            dry_run=dry_run,
            harness_metrics=harness_metrics,
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
    openai_client: Any | None = None

    specs = [harness_metrics.apply_to_spec(spec) for spec in specs]
    forged_results = _parallel_forge(
        specs,
        config=config,
        mumei_client=mumei_client,
        harness_metrics=harness_metrics,
        cache_path=_forge_cache_path(mumei_repo),
        max_workers=parallel_forge_workers,
    )

    results: list[dict[str, Any]] = []
    for idx, spec_result in enumerate(forged_results, start=1):
        spec = spec_result["spec"]
        target_file = spec.get("target_file", "unknown.mm")
        thought = spec_result["thought_process"]
        _log_step(3, 4, f"Publishing forged proposal {idx}/{len(specs)}: {target_file}")

        if not spec_result.get("verified"):
            results.append(spec_result)
            continue

        code = spec_result["code"]
        diff = _detect_diffs(mumei_repo, target_file, code)
        spec_result["diff"] = diff
        if not diff["changed"]:
            _log_info(f"Skipping {target_file}: generated code matches existing file")
            spec_result["success"] = True
            spec_result["reason"] = "no_diff"
            spec_result["dry_run"] = dry_run
            try:
                thought.final_success = True
            except Exception:
                pass
            results.append(spec_result)
            continue

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
                harness_metrics.record_stage(
                    "proliferate_blast_radius",
                    module="stateful_handoff",
                    verification_gate=False,
                    handoff_count=len(blast["broken_files"]),
                    retry_class="blast_radius_broken_dry_run",
                    intent_fidelity_status="untested",
                )
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
                if openai_client is None:
                    openai_client = config.create_client()
                for broken in blast["broken_files"]:
                    healed = attempt_heal(
                        client=openai_client,
                        model=config.model,
                        broken_info=broken,
                        mumei_client=mumei_client,
                        thought_process=thought,
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
                try:
                    thought.final_success = False
                    thought.total_attempts = len(
                        [
                            s
                            for s in thought.steps
                            if s.action in ("initial_verify", "re_verify")
                        ]
                    )
                except Exception:
                    pass
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
            harness_metrics.record_stage(
                "proliferate_publish",
                module="stateful_handoff",
                artifact_contract_passed=True,
                verification_gate=True,
                retry_class="dry_run",
                intent_fidelity_status="passed",
            )
            if enable_lean_fallback:
                try:
                    _attach_dry_run_proof_certificate(
                        spec_result, code, mumei_client
                    )
                except Exception:
                    logger.debug(
                        "Could not attach dry-run proof certificate for %s",
                        target_file,
                        exc_info=True,
                    )
            try:
                thought.final_success = True
                thought.total_attempts = len(
                    [
                        s
                        for s in thought.steps
                        if s.action in ("initial_verify", "re_verify")
                    ]
                )
            except Exception:
                pass
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
        # Task 2-A: skip PR creation if a previous step has marked this
        # spec for auto-close (e.g. an incremental health regression
        # gate populated ``should_close_pr`` during a future per-spec
        # health check).  The post-loop regression handler also sets
        # this flag retroactively for already-published PRs and closes
        # them via the GitHub API.
        #
        # The check is placed *before* writing the new file and healed
        # files to disk so a triggered skip leaves the working tree
        # untouched, matching the cleanup invariant of the
        # ``not all_healed`` rollback path above.
        if spec_result.get("should_close_pr"):
            logger.warning(
                "Skipping PR for %s: health regression detected (delta=%+.3f)",
                target_file,
                spec_result.get("health_delta", float("nan")),
            )
            spec_result.setdefault("reason", "health_regression")
            try:
                thought.final_success = False
                thought.total_attempts = len(
                    [
                        s
                        for s in thought.steps
                        if s.action in ("initial_verify", "re_verify")
                    ]
                )
            except Exception:
                pass
            results.append(spec_result)
            continue

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
            try:
                thought.final_success = bool(spec_result["success"])
                thought.total_attempts = len(
                    [
                        s
                        for s in thought.steps
                        if s.action in ("initial_verify", "re_verify")
                    ]
                )
            except Exception:
                pass
            if pub_result.get("pr_url"):
                spec_result["pr_url"] = pub_result["pr_url"]
        except Exception as exc:
            logger.error("Publish failed for %s: %s", target_file, exc)
            spec_result["reason"] = f"publish_error: {exc}"
            try:
                thought.final_success = False
                thought.total_attempts = len(
                    [
                        s
                        for s in thought.steps
                        if s.action in ("initial_verify", "re_verify")
                    ]
                )
            except Exception:
                pass
        finally:
            if tmp_spec_path is not None:
                try:
                    Path(tmp_spec_path).unlink(missing_ok=True)
                except Exception:
                    pass

        results.append(spec_result)

    # Task 2-C — default-on Lean fallback for unknown atoms.
    #
    # After the forge + verify pass, walk every spec_result and offer
    # any ``z3_check_result == "unknown"`` atoms to ``mumei-lean``.
    # This is purely additive: we never modify the original verify
    # result on disk and never block the run if Lean is unavailable.
    # The try/except enforces that contract — any unexpected error
    # inside ``_run_lean_fallback`` (OSError from tempfile,
    # TypeError from json.dumps, etc.) is logged and swallowed so
    # the post-loop health measurement, auto-close logic, and JSON
    # summary writing below still run.
    if enable_lean_fallback:
        try:
            _run_lean_fallback(
                results, mumei_lean_repo=config.mumei_lean_repo
            )
        except Exception:
            logger.warning(
                "Lean fallback failed unexpectedly", exc_info=True
            )

    # Optional: measure final health
    health_after: dict[str, Any] | None = None
    health_delta: float | None = None
    if health_before is not None and health_client is not None:
        try:
            health_after = _measure_health(health_client, std_dir)
            health_delta = (
                health_after["health_score"] - health_before["health_score"]
            )
            succeeded_count = sum(1 for r in results if r.get("success"))
            _log_info(
                f"Result: {succeeded_count}/{len(results)} proposals "
                f"succeeded, health_score: "
                f"{health_before['health_score']:.2f} → "
                f"{health_after['health_score']:.2f} ({health_delta:+.2f})"
            )
            # PR 4: surface a regression on the run logger as a warning
            # so operators can grep `health regression` across CI logs
            # without parsing the structured summary.
            if health_delta < -0.001:
                logger.warning(
                    "health regression: pre=%.3f post=%.3f delta=%+.3f",
                    health_before["health_score"],
                    health_after["health_score"],
                    health_delta,
                )
                # Task 2-A: auto-close PRs that were just created when
                # the run regressed proof-health.  We mark every result
                # ``should_close_pr=True`` so downstream consumers (the
                # summary JSON, the publish skip-check above, any
                # follow-up retry) can recognise the regression, and
                # best-effort close already-published PRs via the
                # GitHub API.
                if not dry_run:
                    for r in results:
                        r["should_close_pr"] = True
                        r["health_delta"] = health_delta
                        pr_url = r.get("pr_url")
                        if pr_url:
                            close_ok = _close_pr_for_regression(
                                pr_url, health_delta
                            )
                            r["pr_closed"] = bool(close_ok)
        except Exception:
            logger.debug("Could not measure final health", exc_info=True)

    _write_output_json(
        output_json,
        started_at=started_at,
        pre_health=health_before,
        post_health=health_after,
        health_delta=health_delta,
        results=results,
        dry_run=dry_run,
        harness_metrics=harness_metrics,
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
    health_delta: float | None = None,
    harness_metrics: HarnessMetrics | None = None,
) -> None:
    """Write a structured summary of the run to *output_json* (if set).

    The summary is consumed by the SI-5 Phase 3-B scheduled workflow as
    a CI artifact so operators can diff health before/after each run
    without re-reading unstructured logs.

    *health_delta* (PR 4) is the post − pre ``health_score`` value when
    both snapshots are available, or ``None`` when one (or both) is
    missing. Operators can read this field directly from the summary
    JSON instead of recomputing it from ``pre_health`` / ``post_health``.
    """
    if output_json is None:
        return
    succeeded = sum(1 for r in results if r.get("success"))
    processed = len(results)
    payload: dict[str, Any] = {
        "timestamp": started_at,
        # Task 2-A: record the LLM model used for this run so operators
        # can correlate health/success metrics with model quality across
        # historical artifacts.  We resolve via ``AgentConfig().model``
        # (which honours ``LLM_MODEL`` and falls back to the same
        # default — currently ``"gpt-4o"`` — that the actual LLM client
        # uses) so the summary JSON never disagrees with the model that
        # produced the results.
        "model": AgentConfig().model,
        "dry_run": bool(dry_run),
        "pre_health": pre_health,
        "post_health": post_health,
        "health_delta": health_delta,
        "proposals_processed": processed,
        "proposals_succeeded": succeeded,
        "proposals_failed": processed - succeeded,
        "details": [_jsonify_result(r) for r in results],
    }
    lean_metrics = _lean_fallback_metrics(results)
    payload.update(lean_metrics)
    payload["lean_fallback_metrics"] = lean_metrics
    if harness_metrics is not None:
        payload["harness_metrics"] = harness_metrics.aggregate_metrics()
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
    The Lean-upgraded proof certificate stored under ``upgraded_cert``
    can also be sizeable (one entry per atom), so it is replaced with
    an ``upgraded_cert_summary`` dict that records the atom count, the
    number of Lean-verified atoms, and the ``all_verified`` flag.
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
        elif key == "upgraded_cert":
            atoms = value.get("atoms") if isinstance(value, dict) else None
            atom_list = atoms if isinstance(atoms, list) else []
            lean_verified = sum(
                1
                for a in atom_list
                if isinstance(a, dict)
                and a.get("z3_check_result") == "lean_verified"
            )
            out["upgraded_cert_summary"] = {
                "atom_count": len(atom_list),
                "lean_verified_count": lean_verified,
                "all_verified": (
                    value.get("all_verified")
                    if isinstance(value, dict)
                    else None
                ),
            }
        elif key == "thought_process":
            if hasattr(value, "to_dict"):
                try:
                    out["thought_process"] = value.to_dict()
                except Exception:
                    # ``to_dict()`` should never raise in practice, but
                    # if it does we must not store the raw dataclass —
                    # ``json.dumps`` in ``_write_output_json`` cannot
                    # serialise it and would crash the whole run. Fall
                    # back to a JSON-safe ``repr()`` placeholder so the
                    # surrounding summary still gets written.
                    out["thought_process"] = repr(value)
            else:
                out["thought_process"] = value
        elif key == "publish_result":
            # ``publish()`` now returns the full ``proof_certificate``
            # (parsed ``mumei verify --json`` report) so the Lean
            # fallback can inspect per-atom ``z3_check_result`` values.
            # That payload can be sizeable (one entry per atom) and we
            # already store a trimmed view via ``upgraded_cert_summary``
            # when the Lean fallback runs, so here we keep just the
            # short fields plus a per-cert atom count.
            if isinstance(value, dict):
                short: dict[str, Any] = {
                    k: value.get(k)
                    for k in (
                        "success",
                        "generated_file",
                        "pr_url",
                        "pr_created",
                        "pr_error",
                        "git_error",
                        "verify_error",
                        "generation_error",
                        "verified_at_generation",
                    )
                    if k in value
                }
                cert = value.get("proof_certificate")
                if isinstance(cert, dict):
                    cert_atoms = cert.get("atoms")
                    short["proof_certificate_summary"] = {
                        "atom_count": (
                            len(cert_atoms)
                            if isinstance(cert_atoms, list)
                            else 0
                        ),
                        "all_verified": cert.get("all_verified"),
                    }
                artifacts = value.get("artifacts")
                if isinstance(artifacts, list):
                    short["artifact_targets"] = [
                        a.get("target")
                        for a in artifacts
                        if isinstance(a, dict)
                    ]
                out["publish_result"] = short
            else:
                out["publish_result"] = value
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
    parser.add_argument(
        "--enable-lean-fallback",
        action="store_true",
        default=True,
        help=(
            "Enabled by default: after forge + verify, hand any ``unknown`` "
            "atoms to mumei-lean's bridge.py for Lean 4 discharge. Requires "
            "MUMEI_LEAN_REPO to point at a mumei-lang/mumei-lean checkout."
        ),
    )
    parser.add_argument(
        "--disable-lean-fallback",
        dest="enable_lean_fallback",
        action="store_false",
        help=(
            "Disable Lean 4 fallback for local/debug runs. CI keeps the "
            "default enabled path."
        ),
    )
    parser.add_argument(
        "--harness-profile",
        choices=harness_profile_names(),
        default="basic",
        help=(
            "NLAH module-ablation profile. Heavy multi-candidate search is "
            "enabled only by self_evolution/full."
        ),
    )
    parser.add_argument(
        "--parallel-forge-workers",
        type=int,
        default=None,
        help=(
            "Maximum concurrent forge generations. Defaults to min(4, proposals) "
            "or PROLIFERATE_FORGE_WORKERS when set."
        ),
    )


def main(args: argparse.Namespace) -> None:
    """Entry point for the proliferate subcommand."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    run_kwargs: dict[str, Any] = {
        "mumei_repo_dir": args.mumei_repo,
        "max_proposals": args.max_proposals,
        "dry_run": args.dry_run,
        "mumei_bin": args.mumei_bin,
        "output_json": args.output_json,
        "enable_lean_fallback": getattr(args, "enable_lean_fallback", False),
    }
    harness_profile = getattr(args, "harness_profile", "basic")
    if isinstance(harness_profile, str) and harness_profile != "basic":
        run_kwargs["harness_profile"] = harness_profile
    parallel_forge_workers = getattr(args, "parallel_forge_workers", None)
    if parallel_forge_workers is not None:
        run_kwargs["parallel_forge_workers"] = parallel_forge_workers
    results = proliferate(**run_kwargs)

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
