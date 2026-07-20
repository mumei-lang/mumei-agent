"""Offline corpus regression tests for deterministic foreign-code extraction."""
from __future__ import annotations

import pytest

from agent.audit_reporting import (
    _is_boolean_like_clause,
    _malformed_extraction_issue_strings,
)
from agent.cross_validation import validate_foreign_code
from agent.cross_validation_foreign import _is_multi_value_return_expression


GO_CORPUS = [
    "package demo\nfunc add(a int, b int) int { return a + b }\n",
    "package demo\nfunc flag(ok bool) bool { if !ok { return false }; return true }\n",
    "package demo\ntype Pair struct { A int; B int }\nfunc pair(a, b int) Pair { return Pair{A: a, B: b} }\n",
    "package demo\nfunc guarded(x int) int {\n\tif x < 0 { return 0 }\n\treturn x + 1\n}\n",
    "package demo\nfunc noResult(x int) { _ = x; return }\n",
    "package demo\nfunc safeAdd(x, y uint64) (uint64, bool) {\n\tsum, carry := x+y, false\n\treturn sum, carry\n}\n",
    "package demo\nfunc unpack(values []int) int {\n\tfirst, _ := values[0], values[1]\n\treturn first\n}\n",
]

RUST_CORPUS = [
    "pub fn add(a: i64, b: i64) -> i64 { a + b }\n",
    "pub fn flag(ok: bool) -> bool { if !ok { return false; } true }\n",
    "struct Pair { a: i64, b: i64 }\npub fn pair(a: i64, b: i64) -> Pair { Pair { a, b } }\n",
    "pub fn guarded(x: i64) -> i64 {\n    if x < 0 { return 0; }\n    x + 1\n}\n",
    "pub fn no_result(x: i64) { let _ = x; }\n",
    "pub fn tuple(a: i64, b: i64) -> (i64, bool) { (a + b, a < b) }\n",
    "pub fn destructure(values: (i64, i64)) -> i64 {\n    let (first, _) = values;\n    first\n}\n",
]

TYPESCRIPT_CORPUS = [
    "function add(a: number, b: number): number { return a + b; }\n",
    "function flag(ok: boolean): boolean { if (!ok) return false; return true; }\n",
    "type Pair = { a: number; b: number };\nfunction pair(a: number, b: number): Pair { return { a, b }; }\n",
    "function guarded(x: number): number {\n  if (x < 0) return 0;\n  return x + 1;\n}\n",
    "function noResult(x: number): void { console.log(x); return; }\n",
    "function tuple(a: number, b: number): [number, boolean] { return [a + b, a < b]; }\n",
    "function destructure(values: [number, number]): number {\n  const [first] = values;\n  return first;\n}\n",
]

PYTHON_CORPUS = [
    "def add(a: int, b: int) -> int:\n    return a + b\n",
    "def flag(ok: bool) -> bool:\n    if not ok:\n        return False\n    return True\n",
    "def pair(a: int, b: int) -> dict:\n    return {'a': a, 'b': b}\n",
    "def guarded(x: int) -> int:\n    if x < 0:\n        return 0\n    return x + 1\n",
    "def no_result(x: int) -> None:\n    print(x)\n    return None\n",
    "def tuple_result(a: int, b: int) -> tuple:\n    return (a + b, a < b)\n",
    "def destructure(values: tuple[int, int]) -> int:\n    first, _ = values\n    return first\n",
]


def _assert_corpus_clauses_are_valid(language: str, source: str) -> None:
    result = validate_foreign_code(
        source,
        language,
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
            f"{language} source produced malformed clause: {source!r}; "
            f"ensures={atom.ensures!r}, requires={atom.requires!r}"
        )
        assert _is_boolean_like_clause(atom.ensures), (
            f"{language} source produced non-boolean ensures: {source!r}; "
            f"ensures={atom.ensures!r}"
        )
        assert not _is_multi_value_return_expression(atom.ensures), (
            f"{language} source retained a multi-value return: {source!r}; "
            f"ensures={atom.ensures!r}"
        )


@pytest.mark.parametrize("source", GO_CORPUS)
def test_go_deterministic_corpus_clauses_are_valid(source: str) -> None:
    _assert_corpus_clauses_are_valid("go", source)


@pytest.mark.parametrize("source", RUST_CORPUS)
def test_rust_deterministic_corpus_clauses_are_valid(source: str) -> None:
    _assert_corpus_clauses_are_valid("rust", source)


@pytest.mark.parametrize("source", TYPESCRIPT_CORPUS)
def test_typescript_deterministic_corpus_clauses_are_valid(source: str) -> None:
    _assert_corpus_clauses_are_valid("typescript", source)


@pytest.mark.parametrize("source", PYTHON_CORPUS)
def test_python_deterministic_corpus_clauses_are_valid(source: str) -> None:
    _assert_corpus_clauses_are_valid("python", source)
