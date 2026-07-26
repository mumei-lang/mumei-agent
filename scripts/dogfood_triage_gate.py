#!/usr/bin/env python3
"""Aggregate directory/corpus dogfood audits into existing verdict buckets.

Runs a directory audit per input path, buckets each file with
``agent.dogfood_triage.triage_directory_result`` (``refuted`` / ``unverifiable`` /
``verified`` — no new verdicts or aliases), and emits:

- a JSON report per directory plus a combined roll-up (``--json-output``),
- a Markdown job summary (``--markdown-output``, appended to
  ``$GITHUB_STEP_SUMMARY`` when that variable is set),
- exit code 1 when ``--fail-on-refuted`` is passed and any file is ``refuted``.

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

from agent.audit import AUDIT_SCHEMA_KEYS, AuditPipeline
from agent.audit_models import AuditDirectoryResult
from agent.config import AgentConfig
from agent.dogfood_triage import (
    DogfoodTriageReport,
    format_triage_markdown,
    triage_directory_result,
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
    return parser


def _fixed_keys(result: AuditDirectoryResult) -> dict[str, object]:
    """Echo the eight fixed audit-contract keys without renaming any of them."""
    payload: dict[str, object] = {}
    for key in AUDIT_SCHEMA_KEYS:
        value = getattr(result, key, None)
        payload[key] = value.value if hasattr(value, "value") else value
    return payload


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

    for raw_path in args.paths:
        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
            print(f"skipping missing path: {path}", file=sys.stderr)
            continue
        result = _audit(pipeline, path, args)
        report = triage_directory_result(result)
        reports.append(report)
        directories.append(
            {
                "source_dir": result.source_dir,
                "language": result.language,
                "triage": report.to_dict(),
                "audit_contract": _fixed_keys(result),
            }
        )
        markdown_sections.append(format_triage_markdown(result, report))

    totals = _combined_totals(reports)
    payload = {"directories": directories, "totals": totals}
    markdown = "\n".join(["## Dogfood triage", "", *markdown_sections])

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
