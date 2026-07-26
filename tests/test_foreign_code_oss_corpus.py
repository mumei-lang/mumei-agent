"""Pinned real-OSS corpus regression tests for deterministic foreign-code extraction.

`tests/test_foreign_code_corpus.py` exercises synthetic signatures that target known
structural fragility of the deterministic extractor. This module complements it with
unmodified files from real OSS projects, pinned by commit in
`tests/corpora/oss/MANIFEST.json`, and asserts on the *surface* that every inferred
`requires` / `ensures` clause stays valid under the existing oracles:

- `agent.audit_reporting._malformed_extraction_issue_strings` reports nothing,
- `agent.audit_reporting._is_boolean_like_clause` holds for each `ensures`,
- `agent.cross_validation_foreign._is_multi_value_return_expression` is false.

No new verdicts, keys, or aliases are introduced; extraction runs with `use_llm=False`
and `run_mumei=False` so the corpus is offline and deterministic.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.audit_reporting import (
    _is_boolean_like_clause,
    _malformed_extraction_issue_strings,
)
from agent.cross_validation import validate_foreign_code
from agent.cross_validation_foreign import _is_multi_value_return_expression

CORPUS_DIR = Path(__file__).parent / "corpora" / "oss"
MANIFEST_PATH = CORPUS_DIR / "MANIFEST.json"
SUPPORTED_LANGUAGES = ("python", "rust", "typescript", "go", "solidity")

# CI budget guard: deterministic extraction is fast, but large upstream files with
# heavy generics / inline assembly are what push per-file parse time up. Sample
# small files instead of raising these limits.
MAX_LINES_PER_FILE = 200
MAX_TOTAL_LINES = 2000


def _manifest_entries() -> list[dict[str, str]]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return manifest["entries"]


ENTRIES = _manifest_entries()


def _entry_id(entry: dict[str, str]) -> str:
    return entry["path"]


def test_manifest_covers_every_supported_language() -> None:
    languages = {entry["language"] for entry in ENTRIES}
    assert languages == set(SUPPORTED_LANGUAGES)


def test_manifest_and_corpus_files_agree() -> None:
    listed = {CORPUS_DIR / entry["path"] for entry in ENTRIES}
    on_disk = {
        path
        for path in CORPUS_DIR.rglob("*")
        if path.is_file() and path.name not in {"MANIFEST.json", "README.md"}
    }
    assert on_disk == listed


@pytest.mark.parametrize("entry", ENTRIES, ids=_entry_id)
def test_corpus_entry_is_pinned_with_provenance(entry: dict[str, str]) -> None:
    assert entry["language"] in SUPPORTED_LANGUAGES
    assert entry["upstream"].startswith("https://")
    assert entry["source_path"]
    assert entry["license"]
    commit = entry["commit"]
    assert len(commit) == 40 and all(c in "0123456789abcdef" for c in commit), (
        f"{entry['path']} must pin a full upstream commit sha, got {commit!r}"
    )
    assert (CORPUS_DIR / entry["path"]).is_file()


def test_corpus_files_stay_within_ci_budget() -> None:
    total = 0
    for entry in ENTRIES:
        lines = len(
            (CORPUS_DIR / entry["path"]).read_text(encoding="utf-8").splitlines()
        )
        assert lines <= MAX_LINES_PER_FILE, f"{entry['path']} is too large for CI: {lines} lines"
        total += lines
    assert total <= MAX_TOTAL_LINES


@pytest.mark.parametrize("entry", ENTRIES, ids=_entry_id)
def test_oss_corpus_clauses_are_valid(entry: dict[str, str]) -> None:
    source = (CORPUS_DIR / entry["path"]).read_text(encoding="utf-8")
    result = validate_foreign_code(
        source,
        entry["language"],
        use_llm=False,
        run_mumei=False,
    )

    for atom in result.inferred_atoms:
        spec = {
            "atoms": [
                {
                    "name": atom.name,
                    "requires": atom.requires,
                    "ensures": atom.ensures,
                }
            ]
        }
        assert _malformed_extraction_issue_strings(spec) == [], (
            f"{entry['path']}::{atom.name} produced a malformed clause: "
            f"ensures={atom.ensures!r}, requires={atom.requires!r}"
        )
        assert _is_boolean_like_clause(atom.ensures), (
            f"{entry['path']}::{atom.name} produced a non-boolean ensures: "
            f"{atom.ensures!r}"
        )
        assert not _is_multi_value_return_expression(atom.ensures), (
            f"{entry['path']}::{atom.name} retained a multi-value return: "
            f"{atom.ensures!r}"
        )


def test_oss_corpus_extracts_atoms_for_every_language() -> None:
    """Guard against a silently empty surface (e.g. a parser regression)."""
    per_language: dict[str, int] = {language: 0 for language in SUPPORTED_LANGUAGES}
    for entry in ENTRIES:
        source = (CORPUS_DIR / entry["path"]).read_text(encoding="utf-8")
        result = validate_foreign_code(
            source,
            entry["language"],
            use_llm=False,
            run_mumei=False,
        )
        per_language[entry["language"]] += len(result.inferred_atoms)
    for language, count in per_language.items():
        assert count > 0, f"deterministic extraction produced no atoms for {language}"
