"""Tests for .mm migration suggestions."""
from __future__ import annotations

from pathlib import Path

from agent.mm_migration_advisor import (
    suggest_migration,
    suggest_migration_for_file,
)


def test_suggest_migration_python_generates_skeleton() -> None:
    source = "def add(a: int, b: int) -> int:\n    return a + b\n"

    hint = suggest_migration(
        "add",
        source,
        "python",
        [{"kind": "drift", "location": "add", "message": "Spec drift detected."}],
    )

    assert hint.function_name == "add"
    assert "atom add(a: i64, b: i64) -> i64" in hint.skeleton
    assert "trusted atom" not in hint.skeleton
    assert "uv run python -m agent generate --spec-file <extracted_spec.json>" in hint.next_step


def test_migration_priority_high_for_postcondition_violated() -> None:
    source = "def add(a: int, b: int) -> int:\n    return a + b\n"

    hint = suggest_migration(
        "add",
        source,
        "python",
        [{"kind": "postcondition_violated", "location": "add"}],
    )

    assert hint.priority == "high"


def test_suggest_migration_for_file_returns_hints(tmp_path: Path) -> None:
    source = tmp_path / "code.py"
    source.write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n\n"
        "def sub(a: int, b: int) -> int:\n    return a - b\n",
        encoding="utf-8",
    )

    hints = suggest_migration_for_file(
        str(source),
        "python",
        {
            "issues": [
                {
                    "kind": "postcondition_violated",
                    "location": "add",
                    "message": "Postcondition does not hold.",
                }
            ]
        },
    )

    assert [hint.function_name for hint in hints] == ["add"]
    assert hints[0].priority == "high"


def test_suggest_migration_for_file_returns_no_hints_without_issues(tmp_path: Path) -> None:
    source = tmp_path / "code.py"
    source.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

    hints = suggest_migration_for_file(str(source), "python", {"issues": []})

    assert hints == []
