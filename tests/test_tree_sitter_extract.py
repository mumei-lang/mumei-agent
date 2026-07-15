"""Layer B stage 1: tree-sitter function/block extraction and regex fallback.

These tests pin the structural cases the regex extraction got wrong (nested
braces, ``{}``/keywords inside string/comment literals, class methods and nested
functions) and confirm the extraction falls back to the regex path when
tree-sitter is unavailable, keeping the deterministic no-LLM fixture behavior.
"""
from __future__ import annotations

import pytest

from agent import tree_sitter_extract
from agent.cross_validation import _is_function_name_in_source
from agent.cross_validation_foreign import _infer_foreign_source_line_map
from agent.strategies.foreign_code_strategy_helpers import (
    _go_function_blocks,
    _rust_function_blocks,
    _solidity_function_blocks,
    _typescript_function_blocks,
)


@pytest.fixture
def _no_tree_sitter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the regex fallback by making every parser unavailable."""
    monkeypatch.setattr(tree_sitter_extract, "_get_parser", lambda language: None)


# --- tree-sitter is actually available in this environment ------------------

def test_tree_sitter_available_for_supported_languages() -> None:
    for language in ("rust", "go", "typescript", "solidity"):
        assert tree_sitter_extract.is_available(language) is True
    # Python is handled by ``ast`` and is intentionally not a tree-sitter target.
    assert tree_sitter_extract.is_available("python") is False


def test_rust_blocks_capture_nested_braces_and_ignore_string_fn() -> None:
    source = (
        'fn outer(a: i64) -> i64 {\n'
        '    let msg = "fn fake() { not a real function }";\n'
        '    if a > 0 {\n'
        '        let x = a + 1;\n'
        '        return x;\n'
        '    }\n'
        '    a\n'
        '}\n'
        'fn second() -> i64 { 2 }\n'
    )
    blocks = dict(_rust_function_blocks(source))
    # The literal ``fn fake`` must not be extracted as a function.
    assert set(blocks) == {"outer", "second"}
    # The full nested body is captured (regex non-greedy stopped at the first
    # ``}`` and dropped ``return x`` / the closing brace).
    assert "let x = a + 1" in blocks["outer"]
    assert "return x" in blocks["outer"]


def test_go_blocks_capture_nested_braces_and_methods() -> None:
    source = (
        "package p\n"
        "func nth(v []int, i int) int {\n"
        "    if i >= 0 {\n"
        '        _ = "}"\n'
        "        return v[i]\n"
        "    }\n"
        "    return 0\n"
        "}\n"
        "func (r Recv) Meth(x int) int { return x }\n"
    )
    blocks = dict(_go_function_blocks(source))
    assert set(blocks) == {"nth", "Meth"}
    assert "return v[i]" in blocks["nth"]


def test_typescript_blocks_include_class_methods_and_nested_functions() -> None:
    source = (
        "export class S {\n"
        "  compute(v: number[], i: number): number {\n"
        "    function helper(x: number) { return x * 2; }\n"
        "    return v[i];\n"
        "  }\n"
        "}\n"
        "export const shout = (m: string) => { return m; };\n"
    )
    names = {name for name, _ in _typescript_function_blocks(source)}
    # Class methods and nested functions were invisible to the old regex.
    assert {"compute", "helper", "shout"}.issubset(names)


def test_solidity_blocks_ignore_commented_out_functions() -> None:
    source = (
        "contract C {\n"
        "  uint256 owner;\n"
        "  // function fake() public { owner = 1; }\n"
        "  function withdraw(uint256 amt) public {\n"
        "    if (amt > 0) { owner = amt; }\n"
        "  }\n"
        "}\n"
    )
    names = {name for name, _ in _solidity_function_blocks(source)}
    assert names == {"withdraw"}


def test_source_line_map_uses_tree_sitter_for_class_methods() -> None:
    source = (
        "export class StreamingApi {\n"
        "  async write(input: string): Promise<StreamingApi> {\n"
        "    return this;\n"
        "  }\n"
        "  abort() {\n"
        "    this.aborted = true;\n"
        "  }\n"
        "}\n"
    )
    line_map = _infer_foreign_source_line_map(source, "typescript")
    assert line_map["write"] == 2
    assert line_map["abort"] == 5


def test_is_function_name_in_source_rejects_hallucinated_atom() -> None:
    source = (
        "contract C {\n"
        "  function withdraw() public {}\n"
        "}\n"
    )
    assert _is_function_name_in_source("withdraw", source, "solidity") is True
    assert _is_function_name_in_source("ghostFn", source, "solidity") is False


# --- regex fallback when tree-sitter is unavailable -------------------------

def test_rust_blocks_fall_back_to_regex(_no_tree_sitter: None) -> None:
    assert tree_sitter_extract.is_available("rust") is False
    source = (
        "fn add(a: i64, b: i64) -> i64 { a + b }\n"
        "fn branch() -> i64 { if true { 1 } else { 2 } }\n"
    )
    blocks = dict(_rust_function_blocks(source))
    assert set(blocks) == {"add", "branch"}
    # The fallback still balances braces for the nested body.
    assert "else { 2 }" in blocks["branch"]


def test_source_line_map_falls_back_to_regex(_no_tree_sitter: None) -> None:
    source = "package p\nfunc alpha() {}\nfunc beta() {}\n"
    line_map = _infer_foreign_source_line_map(source, "go")
    assert line_map == {"alpha": 2, "beta": 3}


def test_is_function_name_in_source_falls_back_to_regex(_no_tree_sitter: None) -> None:
    source = "fn real() {}\n"
    assert _is_function_name_in_source("real", source, "rust") is True
    assert _is_function_name_in_source("missing", source, "rust") is False


def test_extraction_is_deterministic() -> None:
    source = "fn a() -> i64 { 1 }\nfn b() -> i64 { 2 }\n"
    first = _rust_function_blocks(source)
    second = _rust_function_blocks(source)
    assert first == second
