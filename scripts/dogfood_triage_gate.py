#!/usr/bin/env python3
"""Aggregate directory/corpus dogfood audits into existing verdict buckets.

Runs a directory audit per input path, buckets each file with
``agent.dogfood_triage.triage_directory_result`` (``refuted`` / ``unverifiable`` /
``verified`` — no new verdicts or aliases), and emits:

- a JSON report per directory plus a combined roll-up (``--json-output``),
- a Markdown job summary (``--markdown-output``, appended to
  ``$GITHUB_STEP_SUMMARY`` when that variable is set),
- a verdict-bucket time series plus `refuted` spike / `unverifiable` skew
  alerts when ``--history-file`` points at a persisted history,
- exit code 1 when ``--fail-on-refuted`` is passed and any file is ``refuted``.

With ``--per-file-timeout`` each file is audited in a supervised child process,
so one expensive file (large function, inline assembly, deeply nested generics)
is abandoned as ``unverifiable`` / ``timeout`` instead of consuming the whole
CI budget.

Only ``refuted`` files are surfaced for human review, through the existing
``next_steps`` entrypoint. ``unverifiable`` files are folded into their cause
subcategory counts. The eight fixed audit-contract keys (``AUDIT_SCHEMA_KEYS``)
are reported as-is; this layer adds no keys to them.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from agent.audit import (
    AUDIT_EXTENSION_MAP,
    AUDIT_SCHEMA_KEYS,
    AuditPipeline,
    _aggregate_directory_fixed_keys,
    _build_directory_report,
    _collect_code_files,
    _generate_directory_next_steps,
    _normalize_language,
)
from agent.audit_models import AuditDirectoryResult
from agent.config import AgentConfig
from agent.dogfood_timeout import (
    FileAuditTiming,
    audit_file_with_timeout,
    format_timing_markdown,
)
from agent.dogfood_triage import (
    DogfoodTriageReport,
    format_triage_markdown,
    triage_directory_result,
)
from agent.dogfood_trend import (
    DEFAULT_HISTORY_LIMIT,
    DEFAULT_SKEW_SHARE,
    DEFAULT_SPIKE_MIN_DELTA,
    detect_refuted_spike,
    detect_unverifiable_skew,
    format_trend_markdown,
    load_history,
    save_history,
    snapshot_from_totals,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Bucket directory/corpus dogfood audit output by the existing "
            "verification_status verdicts and gate on refuted files."
        )
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Directories (or files) to audit.",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Force a source language; inferred per file when omitted.",
    )
    parser.add_argument(
        "--json-output",
        default=None,
        help="Write the combined triage report as JSON to this path.",
    )
    parser.add_argument(
        "--markdown-output",
        default=None,
        help="Write the Markdown job summary to this path.",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Also audit test files (skipped by default for directory audits).",
    )
    parser.add_argument(
        "--fail-on-refuted",
        action="store_true",
        help="Exit non-zero when any audited file is refuted.",
    )
    parser.add_argument(
        "--per-file-timeout",
        type=float,
        default=0.0,
        help=(
            "Seconds a single file may take before it is abandoned as "
            "unverifiable/timeout; 0 disables supervision."
        ),
    )
    parser.add_argument(
        "--slow-file-threshold",
        type=float,
        default=0.0,
        help="Report files slower than this many seconds in the job summary.",
    )
    parser.add_argument(
        "--history-file",
        default=None,
        help=(
            "JSON file holding the verdict-bucket time series; this run is "
            "appended and spike/skew alerts are computed against it."
        ),
    )
    parser.add_argument(
        "--run-id",
        default=os.environ.get("GITHUB_RUN_ID", ""),
        help="Label for this run in the time series (defaults to $GITHUB_RUN_ID).",
    )
    parser.add_argument(
        "--history-limit",
        type=int,
        default=DEFAULT_HISTORY_LIMIT,
        help="Snapshots to keep in the history file.",
    )
    parser.add_argument(
        "--refuted-spike-min-delta",
        type=int,
        default=DEFAULT_SPIKE_MIN_DELTA,
        help="Minimum refuted-count increase over the baseline to alert on.",
    )
    parser.add_argument(
        "--unverifiable-skew-share",
        type=float,
        default=DEFAULT_SKEW_SHARE,
        help="Share of unverifiable files one cause may hold before alerting.",
    )
    return parser


def _fixed_keys(result: AuditDirectoryResult) -> dict[str, object]:
    """Echo the eight fixed audit-contract keys without renaming any of them."""
    payload: dict[str, object] = {}
    for key in AUDIT_SCHEMA_KEYS:
        value = getattr(result, key, None)
        payload[key] = value.value if hasattr(value, "value") else value
    return payload


def _audit_directory_supervised(
    path: Path, args: argparse.Namespace
) -> tuple[AuditDirectoryResult, list[FileAuditTiming]]:
    """Audit a directory file-by-file under a per-file timeout.

    File discovery and result aggregation reuse the audit pipeline's own
    helpers, so the only behavioural difference from ``audit_directory`` is the
    supervision of each file.
    """
    normalized_language = _normalize_language(args.language)
    code_files = _collect_code_files(
        path,
        AUDIT_EXTENSION_MAP,
        normalized_language or None,
        include_tests=args.include_tests,
    )
    errors: list[str] = []
    if not code_files:
        errors.append(f"no supported source-code files found in directory: {path}")

    file_results = []
    timings: list[FileAuditTiming] = []
    for code_path in code_files:
        language = normalized_language or AUDIT_EXTENSION_MAP.get(
            code_path.suffix.lower(), ""
        )
        file_result, timing = audit_file_with_timeout(
            code_path, language, args.per_file_timeout
        )
        file_results.append(file_result)
        timings.append(timing)

    files_with_issues = sum(1 for result in file_results if not result.success)
    result = AuditDirectoryResult(
        success=not errors and files_with_issues == 0,
        source_dir=str(path),
        language=normalized_language or "mixed",
        file_results=file_results,
        total_files=len(file_results),
        files_with_issues=files_with_issues,
        errors=errors,
        skipped_rate_limited_files=[
            result.source_file
            for result in file_results
            if result.skipped_rate_limited
        ],
    )
    _aggregate_directory_fixed_keys(result)
    result.next_steps = _generate_directory_next_steps(result)
    result.summary = _build_directory_report(result)
    return result, timings


def _audit(pipeline: AuditPipeline, path: Path, args: argparse.Namespace) -> AuditDirectoryResult:
    if path.is_dir():
        return pipeline.audit_directory(
            path,
            args.language,
            include_tests=args.include_tests,
        )
    file_result = pipeline.audit_file(path, args.language)
    return AuditDirectoryResult(
        success=file_result.success,
        source_dir=str(path),
        language=file_result.language,
        file_results=[file_result],
        total_files=1,
        files_with_issues=0 if file_result.success else 1,
        verification_status=file_result.verification_status,
        spec_health_issues=list(file_result.spec_health_issues),
        verification_violations=list(file_result.verification_violations),
        cross_validation_gaps=list(file_result.cross_validation_gaps),
        migration_hints=list(file_result.migration_hints),
        healed_files=list(file_result.healed_files),
        heal_errors=list(file_result.heal_errors),
        next_steps=list(file_result.next_steps),
        errors=list(file_result.errors),
    )


def _combined_totals(reports: list[DogfoodTriageReport]) -> dict[str, object]:
    unverifiable_counts: dict[str, int] = {}
    for report in reports:
        for category, count in report.unverifiable_counts.items():
            unverifiable_counts[category] = unverifiable_counts.get(category, 0) + count
    return {
        "total_files": sum(report.total_files for report in reports),
        "human_review_count": sum(report.human_review_count for report in reports),
        "verified_count": sum(report.verified_count for report in reports),
        "unverifiable_count": sum(report.unverifiable_count for report in reports),
        "unverifiable_counts": unverifiable_counts,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    pipeline = AuditPipeline(config=AgentConfig())

    directories: list[dict[str, object]] = []
    reports: list[DogfoodTriageReport] = []
    markdown_sections: list[str] = []
    all_timings: list[FileAuditTiming] = []

    for raw_path in args.paths:
        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
            print(f"skipping missing path: {path}", file=sys.stderr)
            continue
        if path.is_dir() and args.per_file_timeout > 0:
            result, timings = _audit_directory_supervised(path, args)
        else:
            result, timings = _audit(pipeline, path, args), []
        report = triage_directory_result(result)
        reports.append(report)
        all_timings.extend(timings)
        directories.append(
            {
                "source_dir": result.source_dir,
                "language": result.language,
                "triage": report.to_dict(),
                "audit_contract": _fixed_keys(result),
                "file_timings": [timing.to_dict() for timing in timings],
            }
        )
        markdown_sections.append(format_triage_markdown(result, report))
        timing_markdown = format_timing_markdown(timings, args.slow_file_threshold)
        if timing_markdown:
            markdown_sections.append(timing_markdown)

    totals = _combined_totals(reports)
    payload: dict[str, object] = {"directories": directories, "totals": totals}
    markdown = "\n".join(["## Dogfood triage", "", *markdown_sections])

    alerts: list[str] = []
    if args.history_file:
        history_path = Path(args.history_file).expanduser()
        history = load_history(history_path)
        history.append(snapshot_from_totals(totals, args.run_id))
        save_history(history_path, history, args.history_limit)
        history = history[-args.history_limit :]
        alerts = [
            *detect_refuted_spike(
                history, min_delta=args.refuted_spike_min_delta
            ),
            *detect_unverifiable_skew(
                history, share_threshold=args.unverifiable_skew_share
            ),
        ]
        payload["trend"] = {
            "history": [snapshot.to_dict() for snapshot in history],
            "alerts": alerts,
        }
        markdown = "\n".join([markdown, "", format_trend_markdown(history, alerts)])

    if args.json_output:
        Path(args.json_output).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.markdown_output:
        Path(args.markdown_output).write_text(markdown + "\n", encoding="utf-8")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    print(markdown)

    for alert in alerts:
        print(f"::warning::{alert}")
    timed_out = [timing for timing in all_timings if timing.timed_out]
    for timing in timed_out:
        markers = ", ".join(timing.risk_markers) or "none detected"
        print(
            f"::warning::{timing.source_file} exceeded the per-file timeout "
            f"({args.per_file_timeout:g}s); risk markers: {markers}"
        )

    refuted = int(totals["human_review_count"])
    if refuted:
        print(
            f"::warning::{refuted} file(s) refuted; review them through next_steps",
        )
    if args.fail_on_refuted and refuted:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
