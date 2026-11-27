#!/usr/bin/env python3
"""Render the mumei audit action step summary and timing outputs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def _int_file(path: str) -> int | None:
    try:
        return int(Path(path).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _seconds(start: int | None, end: int | None) -> int | None:
    if start is None or end is None or end < start:
        return None
    return end - start


def _load_audit(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _bullet_lines(items: list[object], *, limit: int) -> list[str]:
    rows = []
    for item in items[:limit]:
        text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False, sort_keys=True)
        rows.append("- " + text.replace("\n", " ")[:500])
    if len(items) > limit:
        rows.append(f"- … {len(items) - limit} more")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-json", required=True)
    parser.add_argument("--exit-code", required=True, type=int)
    parser.add_argument("--timing-dir", required=True)
    parser.add_argument("--github-output", default="")
    parser.add_argument("--migration-status-json", default="")
    args = parser.parse_args()

    audit_path = Path(args.audit_json)
    audit = _load_audit(audit_path)
    counts = audit.get("finding_counts") if isinstance(audit.get("finding_counts"), dict) else {}
    timing = Path(args.timing_dir)
    setup_seconds = _seconds(_int_file(str(timing / "start")), _int_file(str(timing / "setup_end")))
    audit_seconds = _seconds(_int_file(str(timing / "audit_start")), _int_file(str(timing / "audit_end")))
    total_seconds = _seconds(_int_file(str(timing / "start")), _int_file(str(timing / "audit_end")))

    status = audit.get("verification_status") or ("operational_error" if args.exit_code == 2 else "unavailable")
    lines = [
        "## Mumei audit",
        "",
        f"- Exit code: `{args.exit_code}` (`0` no failing code findings, `1` code evidence, `2` operational/extraction error)",
        f"- verification_status: `{status}`",
        f"- Findings: code `{counts.get('code', 0)}`, confirmed `{counts.get('confirmed', 0)}`, spec `{counts.get('spec', 0)}`, model limitations `{counts.get('model_limitations', 0)}`, errors `{counts.get('errors', 0)}`",
        f"- Runtime: setup `{setup_seconds if setup_seconds is not None else 'unknown'}s`, audit `{audit_seconds if audit_seconds is not None else 'unknown'}s`, total `{total_seconds if total_seconds is not None else 'unknown'}s`",
    ]
    migration = _load_audit(Path(args.migration_status_json)) if args.migration_status_json else {}
    migration_status = migration.get("status")
    if migration_status and migration_status != "not_requested":
        counts = migration.get("counts") if isinstance(migration.get("counts"), dict) else {}
        lines.extend(
            [
                "",
                "### migration execution",
                f"- Status: `{migration_status}`; ready `{counts.get('ready_for_human_review', 0)}`, blocked `{counts.get('blocked', 0)}`, operational_error `{counts.get('operational_error', 0)}`; review_required `{str(migration.get('review_required', False)).lower()}`",
                f"- Evidence boundary: {migration.get('boundary', 'generated .mm evidence only; not host-code semantic equivalence proof')}",
            ]
        )
        auto_migrate_note = timing.parent / "migration-auto-migrate"
        if auto_migrate_note.is_file():
            note = auto_migrate_note.read_text(encoding="utf-8").strip()
            if note == "added":
                lines.append("- `--auto-migrate` was added automatically because migration execution was requested.")
            elif note == "requested":
                lines.append("- `--auto-migrate` was supplied explicitly by the caller.")
        if migration_status == "emitted_by_audit_cli":
            if counts.get("operational_error", 0):
                lines.append("- Consumer policy: failing the action because at least one candidate is `operational_error`; `blocked` and `ready_for_human_review` do not fail the action.")
            else:
                lines.append("- Consumer policy: candidate `operational_error` fails the action; `blocked` and `ready_for_human_review` do not.")
        if migration.get("error"):
            lines.append(f"- Operational error: {migration['error']}")
    violations = audit.get("verification_violations") if isinstance(audit.get("verification_violations"), list) else []
    gaps = audit.get("cross_validation_gaps") if isinstance(audit.get("cross_validation_gaps"), list) else []
    next_steps = audit.get("next_steps") if isinstance(audit.get("next_steps"), list) else []
    if violations:
        lines.extend(["", "### verification_violations", *_bullet_lines(violations, limit=5)])
    if gaps:
        lines.extend(["", "### cross_validation_gaps", *_bullet_lines(gaps, limit=5)])
    if next_steps:
        lines.extend(["", "### next_steps", *_bullet_lines(next_steps, limit=5)])
    if not audit:
        lines.extend(["", "Audit JSON was not produced or was malformed; inspect the audit log artifact."])

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))

    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            for key, value in {
                "setup_seconds": setup_seconds,
                "audit_seconds": audit_seconds,
                "total_seconds": total_seconds,
            }.items():
                if value is not None:
                    handle.write(f"{key}={value}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
