"""Report large-scale composability measurements through the fixed audit keys.

`mumei` measures the large-scale (Priority 16) scenarios with
``scripts/measure_composability.py`` and ``scripts/scale_trust_surface.py``.
This module turns those two measurement artifacts into the same fixed-key
payload every other audit path emits, so composition breaks reach operators
through ``verification_status`` / ``verification_violations`` / ``next_steps``
only — no new verdict vocabulary and no new report channel.

Mapping:

* a composition break (a neighbouring atom cannot close its proof unless the
  owning atom's contract is stronger than it needs locally) becomes one
  ``verification_violations`` entry;
* the break patterns become ``next_steps`` entries pointing at the
  `mumei-core` modular verification surfaces (`effect_pre` / `effect_post`);
* a failed ``mumei verify-cert --strict`` or a non-zero trusted-atom count in
  ``std/`` becomes a ``refuted`` ``verification_status``.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent.cross_validation_models import ForeignCodeVerdict

FIXED_KEYS = (
    "spec_health_issues",
    "verification_violations",
    "verification_status",
    "cross_validation_gaps",
    "next_steps",
    "migration_hints",
    "healed_files",
    "heal_errors",
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _break_violation(case: str, record: dict[str, Any]) -> str:
    affected = ", ".join(record.get("affected_atoms", [])) or "unknown"
    return (
        f"{case}:{record.get('atom')}: composition break at "
        f"{record.get('clause_kind')} line {record.get('clause_line')} "
        f"({record.get('clause_text', '').strip()}) — {affected} cannot close "
        f"without this neighbouring contract [{record.get('pattern')}]"
    )


def _trust_violation(case: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    name = case.get("case", "unknown")
    if not case.get("verify_cert_strict", False):
        violations.append(
            f"{name}: mumei verify-cert --strict failed "
            f"(exit {case.get('verify_cert_strict_exit_code')})"
        )
    if not case.get("all_atoms_certified", False):
        violations.append(
            f"{name}: proof certificate covers {case.get('certified_atoms')} of "
            f"{case.get('atom_count')} atoms"
        )
    trust = case.get("trust_surface", {})
    trusted = int(trust.get("application_trusted_atoms", 0) or 0)
    if trusted:
        violations.append(f"{name}: {trusted} application trusted atom(s) at scale")
    return violations


def _next_steps(patterns: dict[str, Any], violations: list[str]) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = []
    for pattern, payload in sorted(patterns.items()):
        count = payload.get("count", 0)
        steps.append(
            {
                "priority": "high" if pattern == "effect_state_obligation" else "medium",
                "action": (
                    f"Strengthen {payload.get('compiler_surface', pattern)} for "
                    f"{count} composition break(s) classified as {pattern}."
                ),
                "command": (
                    "python3 scripts/measure_composability.py <scale-case>.mm "
                    "--clause-kinds all --output composability.json"
                ),
            }
        )
    if violations:
        steps.append(
            {
                "priority": "high",
                "action": (
                    "Re-run the scale case and re-check the proof certificate before "
                    "trusting the measurement."
                ),
                "command": "mumei verify-cert --strict <cert> <source>",
            }
        )
    return steps


def build_report(
    composability: dict[str, Any],
    trust_surface: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the fixed-key payload for a scale composability measurement."""
    cases = composability.get("cases", [])
    patterns = composability.get("modular_verification_inputs", {})

    violations: list[str] = []
    gaps: list[str] = []
    for case in cases:
        name = case.get("case", "unknown")
        for record in case.get("breaks", []):
            violations.append(_break_violation(name, record))
        ratio = case.get("atom_local_closure_ratio")
        closed = case.get("whole_system_invariants_closed", 0)
        total = len(case.get("top_level_atoms", []))
        gaps.append(
            f"{name}: atom_local_closure_ratio={ratio}, "
            f"whole-system invariants closed {closed}/{total}, "
            f"{case.get('composition_breaks', 0)} composition break(s) over "
            f"{case.get('atom_count', 0)} atoms at depth "
            f"{case.get('max_dependency_depth', 0)}"
        )

    trust_violations: list[str] = []
    fingerprint = composability.get("budget_policy_fingerprint")
    if trust_surface is not None:
        for case in trust_surface.get("cases", []):
            trust_violations.extend(_trust_violation(case))
        std_trusted = int(
            trust_surface.get("std_trust_surface", {}).get("std_trusted_atoms", 0) or 0
        )
        if std_trusted:
            trust_violations.append(f"std/: trusted atom count regressed to {std_trusted}")
        fingerprint = trust_surface.get("budget_policy_fingerprint") or fingerprint

    status: ForeignCodeVerdict = "refuted" if trust_violations else "verified"
    if not cases:
        status = "unverifiable"

    return {
        "success": not trust_violations,
        "source_file": ", ".join(case.get("source", "") for case in cases),
        "language": "mumei",
        "spec_extracted": True,
        "spec_health_issues": [],
        "verification_status": status,
        "verification_violations": trust_violations + violations,
        "cross_validation_gaps": gaps,
        "next_steps": _next_steps(patterns, trust_violations),
        "migration_hints": [],
        "healed_files": [],
        "heal_errors": [],
        "budget_policy_fingerprint": fingerprint,
        "report": (
            f"verification_status: {status}; "
            f"{len(violations)} composition break(s) recorded as verification_violations; "
            "next_steps is the only human-review entrypoint"
        ),
        "errors": [],
    }


def render(report: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, indent=2, ensure_ascii=False)
    if output_format == "text":
        return report["report"]
    if output_format == "markdown":
        lines = [
            "## Scale composability report",
            "",
            f"- `verification_status`: {report['verification_status']}",
            "",
            f"### verification_violations ({len(report['verification_violations'])})",
        ]
        lines.extend(f"- {item}" for item in report["verification_violations"])
        lines.append("")
        lines.append(f"### cross_validation_gaps ({len(report['cross_validation_gaps'])})")
        lines.extend(f"- {item}" for item in report["cross_validation_gaps"])
        lines.append("")
        lines.append(f"### next_steps ({len(report['next_steps'])})")
        lines.extend(f"- **[{step['priority']}]** {step['action']}" for step in report["next_steps"])
        return "\n".join(lines)
    lines = [
        f"verification_status: {report['verification_status']}",
        f"verification_violations ({len(report['verification_violations'])}):",
    ]
    lines.extend(f"  - {item}" for item in report["verification_violations"])
    lines.append(f"cross_validation_gaps ({len(report['cross_validation_gaps'])}):")
    lines.extend(f"  - {item}" for item in report["cross_validation_gaps"])
    lines.append(f"next_steps ({len(report['next_steps'])}):")
    lines.extend(f"  - [{step['priority']}] {step['action']}" for step in report["next_steps"])
    return "\n".join(lines)


def build_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--composability",
        type=Path,
        required=True,
        help="Composability report emitted by mumei scripts/measure_composability.py.",
    )
    parser.add_argument(
        "--trust-surface",
        type=Path,
        default=None,
        help="Trust surface report emitted by mumei scripts/scale_trust_surface.py.",
    )
    parser.add_argument("--json", action="store_true", help="Output the full result as JSON.")
    parser.add_argument(
        "--format",
        choices=["human", "markdown", "json", "text"],
        default="human",
        help="Output format (default: human).",
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional output path.")
    return parser


def main(args: argparse.Namespace) -> int:
    composability = _load(args.composability)
    trust_surface = _load(args.trust_surface) if args.trust_surface else None
    report = build_report(composability, trust_surface)

    output_format = "json" if args.json else args.format
    text = render(report, output_format)
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return 0
