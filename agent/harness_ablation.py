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


def _overall_metrics(aggregate: Mapping[str, Any]) -> dict[str, float]:
    """Sum module_comparison buckets into run-level totals and rates."""
    comparison = aggregate.get("module_comparison") or {}
    totals = {metric: 0.0 for metric in _OVERALL_METRICS}
    rate_sum = 0.0
    rate_count = 0
    for bucket in comparison.values():
        if not isinstance(bucket, Mapping):
            continue
        records = float(bucket.get("records", 0) or 0)
        if records > 0:
            rate_sum += float(bucket.get("success_rate", 0.0) or 0.0) * records
            rate_count += int(records)
        for metric in _OVERALL_METRICS:
            if metric in ("success_rate", "average_spec_drift_score"):
                continue
            totals[metric] += float(bucket.get(metric, 0) or 0)
        totals["average_spec_drift_score"] = max(
            totals["average_spec_drift_score"],
            float(bucket.get("average_spec_drift_score", 0.0) or 0.0),
        )
    totals["success_rate"] = rate_sum / rate_count if rate_count else 0.0
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
