"""Reporting and serialization helpers for proliferation."""
from __future__ import annotations

import datetime
import json
import tempfile
from pathlib import Path
from typing import Any

from agent.metrics import Metrics
from agent.mumei_client import MumeiClient
from agent.proofcert import Z3CheckResult


def _metrics_payload(metrics: Metrics) -> dict[str, float | int]:
    return {
        "attempts": metrics.total_attempts,
        "tokens_to_success": metrics.llm_tokens_used,
        "solver_seconds_to_success": sum(metrics.verification_times_seconds),
        "spec_drift_score": 0.0,
    }


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


def _lean_fallback_not_attempted(
    *,
    success: bool = False,
    error_code: str | None = "not_attempted",
    diagnostics: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "attempted": False,
        "unknown_count": 0,
        "proved": 0,
        "failed": 0,
        "success": success,
        "returncode": None,
        "error_code": error_code,
        "primary_error_code": error_code,
        "retryable": False,
        "diagnostics": diagnostics or [],
        "duration_seconds": 0.0,
        "partial_success": False,
        "fallback_strategy": None,
    }


def _duration_distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "avg": None,
            "p50": None,
            "p95": None,
        }
    ordered = sorted(values)

    def percentile(frac: float) -> float:
        index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * frac)))
        return ordered[index]

    return {
        "count": len(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "avg": sum(ordered) / len(ordered),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
    }


def _lean_fallback_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    attempted = 0
    proved = 0
    failed = 0
    attempted_specs = 0
    partial_successes = 0
    retryable_failures = 0
    durations: list[float] = []
    error_code_counts: dict[str, int] = {}
    for result in results:
        fallback = result.get("lean_fallback")
        if not isinstance(fallback, dict) or not fallback.get("attempted"):
            continue
        attempted_specs += 1
        unknown_count = int(fallback.get("unknown_count") or 0)
        proved_count = int(fallback.get("proved") or 0)
        failed_count = fallback.get("failed")
        attempted += unknown_count
        proved += proved_count
        if isinstance(failed_count, int):
            failed += failed_count
        else:
            failed += max(unknown_count - proved_count, 0)
        if fallback.get("partial_success"):
            partial_successes += 1
        duration = fallback.get("duration_seconds")
        if isinstance(duration, int | float):
            durations.append(float(duration))
        error_code = fallback.get("error_code")
        if failed_count or fallback.get("success") is False:
            key = str(error_code or "unknown")
            error_code_counts[key] = error_code_counts.get(key, 0) + 1
            if fallback.get("retryable"):
                retryable_failures += 1
    success_rate = proved / attempted if attempted else None
    duration_stats = _duration_distribution(durations)
    failure_rates = {
        code: count / attempted_specs if attempted_specs else 0.0
        for code, count in sorted(error_code_counts.items())
    }
    return {
        "lean_fallback_attempted": attempted,
        "lean_fallback_proved": proved,
        "lean_fallback_failed": failed,
        "lean_fallback_success_rate": success_rate,
        "lean_fallback_attempted_specs": attempted_specs,
        "lean_fallback_partial_successes": partial_successes,
        "lean_fallback_retryable_failures": retryable_failures,
        "lean_fallback_error_code_counts": dict(sorted(error_code_counts.items())),
        "lean_fallback_failure_rate_by_error_code": failure_rates,
        "lean_fallback_duration_seconds": duration_stats,
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


def _jsonify_result(
    result: dict[str, Any],
    *,
    lean_fallback_enabled: bool = False,
) -> dict[str, Any]:
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
                and a.get("z3_check_result") == Z3CheckResult.LEAN_VERIFIED.value
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
                    cert_atom_list = (
                        cert_atoms if isinstance(cert_atoms, list) else []
                    )
                    short["proof_certificate_summary"] = {
                        "atom_count": len(cert_atom_list),
                        "lean_verified_count": sum(
                            1
                            for atom in cert_atom_list
                            if isinstance(atom, dict)
                            and atom.get("z3_check_result")
                            == Z3CheckResult.LEAN_VERIFIED.value
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
    if lean_fallback_enabled and "lean_fallback" not in out:
        out["lean_fallback"] = _lean_fallback_not_attempted()
    return out
