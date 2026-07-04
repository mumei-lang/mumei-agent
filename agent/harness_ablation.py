"""Ablation comparison across harness runs (NLAH measurement foundation).

Consumes the ``harness_metrics`` aggregates emitted by forge/proliferate run
summaries (``HarnessMetrics.aggregate_metrics()``) and compares runs executed
under different harness profiles against a baseline run, quantifying what each
ablated module contributes in success rate and cost.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent.harness_metrics import HARNESS_MODULES

_OVERALL_METRICS = (
    "success_rate",
    "attempts_to_success",
    "handoff_count",
    "tokens_to_success",
    "solver_seconds_to_success",
    "average_spec_drift_score",
)


def extract_harness_aggregate(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the harness aggregate from a run summary or a bare aggregate.

    Accepts either a forge/proliferate run summary JSON (which nests the
    aggregate under ``harness_metrics``) or the aggregate dict itself.
    """
    nested = payload.get("harness_metrics")
    if isinstance(nested, Mapping):
        return dict(nested)
    if "module_comparison" in payload or "module_enabled" in payload:
        return dict(payload)
    raise ValueError(
        "payload does not contain harness metrics "
        "(expected a 'harness_metrics' key or an aggregate with 'module_comparison')"
    )


def load_run_aggregate(path: str | Path) -> dict[str, Any]:
    """Load a run summary JSON file and extract its harness aggregate."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"{path}: expected a JSON object")
    return extract_harness_aggregate(data)


def _record_outcome(record: Mapping[str, Any]) -> bool | None:
    if record.get("artifact_contract_passed") is not None:
        return bool(record["artifact_contract_passed"])
    if record.get("verification_gate") is not None:
        return bool(record["verification_gate"])
    status = record.get("intent_fidelity_status")
    if status == "passed":
        return True
    if status in ("failed", "drifted"):
        return False
    return None


def _overall_metrics(aggregate: Mapping[str, Any]) -> dict[str, float]:
    """Reduce raw records into run-level totals and a stage success rate.

    ``HarnessMetrics.record_result`` fans one observation out into several
    module records that all carry the same cost values, so costs are
    deduplicated per stage (max across the stage's records) rather than
    summed across module buckets.
    """
    records = aggregate.get("records") or []
    totals = {metric: 0.0 for metric in _OVERALL_METRICS}
    stage_costs: dict[str, dict[str, float]] = {}
    stage_outcomes: dict[str, bool] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        stage = str(record.get("stage", ""))
        costs = stage_costs.setdefault(
            stage,
            {metric: 0.0 for metric in _OVERALL_METRICS if metric != "success_rate"},
        )
        for metric in costs:
            record_key = "spec_drift_score" if metric == "average_spec_drift_score" else metric
            costs[metric] = max(costs[metric], float(record.get(record_key, 0) or 0))
        outcome = _record_outcome(record)
        if outcome is not None:
            stage_outcomes[stage] = stage_outcomes.get(stage, True) and outcome
    for costs in stage_costs.values():
        for metric, value in costs.items():
            if metric == "average_spec_drift_score":
                totals[metric] = max(totals[metric], value)
            else:
                totals[metric] += value
    totals["success_rate"] = (
        sum(stage_outcomes.values()) / len(stage_outcomes) if stage_outcomes else 0.0
    )
    return totals


def _module_flags(aggregate: Mapping[str, Any]) -> dict[str, bool]:
    flags = aggregate.get("module_enabled") or {}
    return {module: bool(flags.get(module, False)) for module in HARNESS_MODULES}


def compare_ablation_runs(
    runs: Mapping[str, Mapping[str, Any]],
    baseline: str,
) -> dict[str, Any]:
    """Compare harness aggregates across runs against a baseline run.

    ``runs`` maps a run label (typically the harness profile name) to a
    harness aggregate. Returns per-run module-flag diffs and metric deltas
    (run − baseline) at both the overall and per-module level.
    """
    if baseline not in runs:
        valid = ", ".join(sorted(runs))
        raise ValueError(f"baseline run {baseline!r} not found; available runs: {valid}")

    base_aggregate = runs[baseline]
    base_flags = _module_flags(base_aggregate)
    base_overall = _overall_metrics(base_aggregate)
    base_comparison = base_aggregate.get("module_comparison") or {}

    comparisons: dict[str, Any] = {}
    for label, aggregate in runs.items():
        if label == baseline:
            continue
        flags = _module_flags(aggregate)
        overall = _overall_metrics(aggregate)
        run_comparison = aggregate.get("module_comparison") or {}

        ablated = [m for m in HARNESS_MODULES if base_flags[m] and not flags[m]]
        added = [m for m in HARNESS_MODULES if flags[m] and not base_flags[m]]

        per_module: dict[str, Any] = {}
        for module in HARNESS_MODULES:
            base_bucket = base_comparison.get(module) or {}
            run_bucket = run_comparison.get(module) or {}
            per_module[module] = {
                "module_enabled": flags[module],
                "baseline_enabled": base_flags[module],
                "success_rate_delta": float(run_bucket.get("success_rate", 0.0) or 0.0)
                - float(base_bucket.get("success_rate", 0.0) or 0.0),
                "tokens_to_success_delta": float(
                    run_bucket.get("tokens_to_success", 0) or 0
                )
                - float(base_bucket.get("tokens_to_success", 0) or 0),
                "solver_seconds_to_success_delta": float(
                    run_bucket.get("solver_seconds_to_success", 0.0) or 0.0
                )
                - float(base_bucket.get("solver_seconds_to_success", 0.0) or 0.0),
                "attempts_to_success_delta": float(
                    run_bucket.get("attempts_to_success", 0) or 0
                )
                - float(base_bucket.get("attempts_to_success", 0) or 0),
            }

        comparisons[label] = {
            "profile": aggregate.get("profile"),
            "ablated_modules": ablated,
            "added_modules": added,
            "overall": overall,
            "overall_delta": {
                metric: overall[metric] - base_overall[metric]
                for metric in _OVERALL_METRICS
            },
            "per_module": per_module,
        }

    return {
        "baseline": {
            "label": baseline,
            "profile": base_aggregate.get("profile"),
            "module_enabled": base_flags,
            "overall": base_overall,
        },
        "runs": comparisons,
    }


def format_ablation_report_markdown(report: Mapping[str, Any]) -> str:
    """Render an ablation comparison as a compact markdown report."""
    baseline = report.get("baseline") or {}
    lines = [
        "# Harness Ablation Report",
        "",
        f"Baseline: `{baseline.get('label')}`"
        + (f" (profile `{baseline.get('profile')}`)" if baseline.get("profile") else ""),
        "",
        "| run | ablated modules | Δ success rate | Δ tokens | Δ solver s | Δ attempts |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for label, run in (report.get("runs") or {}).items():
        delta = run.get("overall_delta") or {}
        ablated = ", ".join(run.get("ablated_modules") or []) or "—"
        lines.append(
            "| {label} | {ablated} | {sr:+.3f} | {tok:+.0f} | {solver:+.2f} | {att:+.0f} |".format(
                label=label,
                ablated=ablated,
                sr=delta.get("success_rate", 0.0),
                tok=delta.get("tokens_to_success", 0.0),
                solver=delta.get("solver_seconds_to_success", 0.0),
                att=delta.get("attempts_to_success", 0.0),
            )
        )
    return "\n".join(lines) + "\n"


def build_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "runs",
        nargs="+",
        metavar="LABEL=SUMMARY_JSON",
        help=(
            "Run summary JSON files produced with --harness-profile, "
            "labelled as LABEL=path (e.g. full=out/full.json basic=out/basic.json)."
        ),
    )
    parser.add_argument(
        "--baseline",
        required=True,
        help="Label of the baseline run to compare against.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        dest="output_format",
        help="Report output format (default: json).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write the report to this path instead of stdout.",
    )
    return parser


def main(args: argparse.Namespace) -> None:
    runs: dict[str, dict[str, Any]] = {}
    for item in args.runs:
        label, sep, path = item.partition("=")
        if not sep or not label or not path:
            raise SystemExit(f"invalid run spec {item!r}; expected LABEL=SUMMARY_JSON")
        runs[label] = load_run_aggregate(path)

    report = compare_ablation_runs(runs, args.baseline)
    if args.output_format == "markdown":
        rendered = format_ablation_report_markdown(report)
    else:
        rendered = json.dumps(report, indent=2, ensure_ascii=False)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
