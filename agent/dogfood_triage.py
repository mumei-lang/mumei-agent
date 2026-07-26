"""Triage aggregated audit results for dogfood review."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from agent.audit import _errors_indicate_rate_limit
from agent.audit_models import AuditDirectoryResult, AuditResult
from agent.audit_reporting import _is_spec_lowering_or_unsupported_error

_TIMEOUT_MARKERS = ("timeout", "timed out", "deadline exceeded")


@dataclass
class DogfoodTriageReport:
    """Human-review candidates and noise buckets from a directory audit."""

    human_review: list[str]
    verified: list[str]
    unverifiable: dict[str, list[str]]
    total_files: int
    human_review_count: int
    verified_count: int
    unverifiable_count: int
    unverifiable_counts: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation of the triage report."""
        return asdict(self)


def _issue_strings(file_result: AuditResult) -> list[str]:
    return [
        *file_result.errors,
        *file_result.spec_health_issues,
        *file_result.verification_violations,
        *file_result.cross_validation_gaps,
    ]


def _unverifiable_category(
    file_result: AuditResult, result: AuditDirectoryResult
) -> str:
    issues = _issue_strings(file_result)
    if (
        file_result.skipped_rate_limited
        or file_result.source_file in result.skipped_rate_limited_files
        or _errors_indicate_rate_limit(file_result.errors)
    ):
        return "skipped_rate_limited"
    lowered_issues = [issue.lower() for issue in issues]
    if any(
        marker in issue
        for issue in lowered_issues
        for marker in _TIMEOUT_MARKERS
    ):
        return "timeout"
    if any(
        issue.startswith("encoding-gap")
        or _is_spec_lowering_or_unsupported_error(issue)
        or "Skipped unsupported Z3 clause" in issue
        for issue in file_result.spec_health_issues
    ):
        return "encoding_gap"
    if (
        not file_result.spec_extracted
        or any(
            marker in issue.lower()
            for issue in file_result.errors
            for marker in ("no mumei atoms", "no supported source", "no functions")
        )
    ):
        return "no_function_declarations"
    return "other"


def triage_directory_result(result: AuditDirectoryResult) -> DogfoodTriageReport:
    """Bucket files using the verdict already assigned by the audit pipeline."""
    human_review: list[str] = []
    verified: list[str] = []
    unverifiable: dict[str, list[str]] = {
        "skipped_rate_limited": [],
        "timeout": [],
        "encoding_gap": [],
        "no_function_declarations": [],
        "other": [],
    }

    for file_result in result.file_results:
        if file_result.verification_status == "refuted":
            human_review.append(file_result.source_file)
        elif file_result.verification_status == "verified":
            verified.append(file_result.source_file)
        else:
            unverifiable[_unverifiable_category(file_result, result)].append(
                file_result.source_file
            )

    return DogfoodTriageReport(
        human_review=human_review,
        verified=verified,
        unverifiable=unverifiable,
        total_files=len(result.file_results),
        human_review_count=len(human_review),
        verified_count=len(verified),
        unverifiable_count=sum(len(files) for files in unverifiable.values()),
        unverifiable_counts={
            category: len(files) for category, files in unverifiable.items()
        },
    )


def format_triage_markdown(
    result: AuditDirectoryResult, report: DogfoodTriageReport
) -> str:
    """Render a job-summary table for a triaged directory audit.

    Only ``refuted`` files are expanded, and they are expanded through the
    existing human-review entrypoint (``next_steps``) plus their
    ``verification_violations``.  ``unverifiable`` files are folded into their
    cause subcategory counts so they stay out of human attention, and
    ``verified`` files are kept as an aggregate count only.
    """
    lines = [
        "### Dogfood verdict buckets",
        "",
        f"`{result.source_dir}` — {report.total_files} file(s), language `{result.language or 'mixed'}`",
        "",
        "| verdict | files |",
        "| --- | ---: |",
        f"| refuted (human review) | {report.human_review_count} |",
        f"| verified | {report.verified_count} |",
        f"| unverifiable | {report.unverifiable_count} |",
        "",
    ]

    if report.unverifiable_count:
        lines += [
            "#### unverifiable causes",
            "",
            "| cause | files |",
            "| --- | ---: |",
        ]
        lines += [
            f"| {category} | {count} |"
            for category, count in report.unverifiable_counts.items()
            if count
        ]
        lines.append("")

    if not report.human_review:
        lines += ["_No `refuted` files; nothing to review._", ""]
        return "\n".join(lines)

    lines += ["#### refuted files (next_steps)", ""]
    by_file = {
        file_result.source_file: file_result for file_result in result.file_results
    }
    for source_file in report.human_review:
        lines.append(f"- `{source_file}`")
        file_result = by_file.get(source_file)
        if file_result is None:
            continue
        for violation in file_result.verification_violations:
            lines.append(f"  - violation: {violation}")
        for step in file_result.next_steps:
            priority = step.get("priority") or "info"
            action = step.get("action") or ""
            command = step.get("command") or ""
            suffix = f" — `{command}`" if command else ""
            lines.append(f"  - next_step [{priority}]: {action}{suffix}")
    lines.append("")
    return "\n".join(lines)
