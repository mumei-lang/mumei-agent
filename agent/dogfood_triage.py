"""Triage aggregated audit results for dogfood review."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from agent.audit_findings import build_directory_triage
from agent.audit_models import AuditDirectoryResult, AuditResult


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


def triage_directory_result(result: AuditDirectoryResult) -> DogfoodTriageReport:
    """Bucket files through the same stable triage projection exposed by audit."""
    triage = result.triage or build_directory_triage(result)
    unverifiable = {
        category: list(files)
        for category, files in triage["unverifiable"].items()
    }
    return DogfoodTriageReport(
        human_review=list(triage["refuted"]),
        verified=list(triage["verified"]),
        unverifiable=unverifiable,
        total_files=len(result.file_results),
        human_review_count=len(triage["refuted"]),
        verified_count=len(triage["verified"]),
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
