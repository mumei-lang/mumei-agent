"""Tests for .mm migration suggestions."""
from __future__ import annotations

import sys
from pathlib import Path

from agent.__main__ import main as agent_cli_main
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
    assert hint.skeleton == (
        "atom add(a: i64, b: i64) -> i64 {\n"
        "    requires: true;\n"
        "    ensures: true;\n"
        "    body: {\n"
        "        0\n"
        "    }\n"
        "}"
    )
    assert "uv run python -m agent generate --spec-file <extracted_spec.json>" in hint.next_step


def test_clause_labels_only_label_existing_preconditions_and_escape_messages() -> None:
    source = (Path(__file__).parent / "fixtures" / "sample_python.py").read_text(
        encoding="utf-8"
    )
    issues = [
        {
            "kind": "postcondition_violated",
            "location": "safe_divide",
            "message": 'Divisor "must be nonzero"\nfor this call',
            "required_contracts": [" b != 0; ", "a > 0"],
        },
        {
            "kind": "drift",
            "location": "safe_divide",
            "message": "Second issue label",
            "required_contracts": ["b != 0"],
        },
    ]

    hint = suggest_migration(
        "safe_divide",
        source,
        "python",
        issues,
        clause_labels=True,
    )

    assert 'requires "Divisor \\"must be nonzero\\" for this call": b != 0;' in hint.skeleton
    assert "requires: b != 0;" not in hint.skeleton
    assert "a > 0" not in hint.skeleton


def test_clause_labels_do_not_add_requirements_to_skeletons() -> None:
    source = "def add(a: int, b: int) -> int:\n    return a + b\n"

    hint = suggest_migration(
        "add",
        source,
        "python",
        [
            {
                "kind": "drift",
                "location": "add",
                "message": "External requirement",
                "required_contracts": ["a > 0"],
            }
        ],
        clause_labels=True,
    )

    assert "requires: true;" in hint.skeleton
    assert "a > 0" not in hint.skeleton


def test_migrate_suggest_cli_passes_clause_labels(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "code.py"
    source.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    received: dict[str, object] = {}

    def fake_suggest_migration_for_file(
        code_file: str,
        language: str,
        validation_result: dict,
        *,
        clause_labels: bool = False,
    ) -> list:
        received["code_file"] = code_file
        received["language"] = language
        received["clause_labels"] = clause_labels
        return []

    monkeypatch.setattr(
        "agent.mm_migration_advisor.suggest_migration_for_file",
        fake_suggest_migration_for_file,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent",
            "migrate-suggest",
            "--code-file",
            str(source),
            "--language",
            "python",
            "--issues-json",
            '[{"kind":"drift","location":"add"}]',
            "--clause-labels",
        ],
    )

    agent_cli_main()
    capsys.readouterr()

    assert received["code_file"] == str(source.resolve())
    assert received["language"] == "python"
    assert received["clause_labels"] is True


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
