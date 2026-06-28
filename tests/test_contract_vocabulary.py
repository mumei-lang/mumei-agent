"""Regression tests for cross-repo harness contract vocabulary."""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_UNDER_CONTRACT = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "VERIFICATION_WORKFLOW_GUIDE.md",
    REPO_ROOT / "docs" / "ROADMAP.md",
]
NO_MM_KEYS = [
    "spec_health_issues",
    "verification_violations",
    "cross_validation_gaps",
    "next_steps",
    "migration_hints",
    "healed_files",
    "heal_errors",
]
FORBIDDEN_ALIASES = [
    "recommendations",
    "actions",
    "audit_issues",
    "verification_gaps",
    "repair_hints",
    "review_actions",
    "human_review",
]


def _alias_key_patterns(alias: str) -> list[re.Pattern[str]]:
    escaped = re.escape(alias)
    return [
        re.compile(rf"`{escaped}(?:\[\])?`"),
        re.compile(rf'"{escaped}(?:\[\])?"\s*:'),
        re.compile(rf"'{escaped}(?:\[\])?'\s*:"),
        re.compile(rf"(?m)^\s*[-*]?\s*{escaped}(?:\[\])?\s*:"),
        re.compile(rf"\b{escaped}\[\]"),
    ]


def test_no_mm_docs_use_fixed_audit_keys_without_alias_keys() -> None:
    failures: list[str] = []
    for path in DOCS_UNDER_CONTRACT:
        text = path.read_text(encoding="utf-8")
        for key in NO_MM_KEYS:
            if key not in text:
                failures.append(f"{path.relative_to(REPO_ROOT)} does not mention `{key}`")
        for alias in FORBIDDEN_ALIASES:
            for pattern in _alias_key_patterns(alias):
                match = pattern.search(text)
                if match:
                    line = text[: match.start()].count("\n") + 1
                    failures.append(
                        f"{path.relative_to(REPO_ROOT)}:{line} documents forbidden alias key `{alias}`"
                    )
                    break
    assert failures == []
