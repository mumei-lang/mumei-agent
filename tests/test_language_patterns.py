"""Unit tests for ``agent/language_patterns.py`` (V1-B-2 language-specific
"common problem" heuristics) and its wiring into verify() warnings and
validate-code advisory issues."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent.config import AgentConfig
from agent.cross_validation import validate_foreign_code
from agent.language_patterns import (
    LANGUAGE_PATTERNS,
    language_pattern_issues,
)
from agent.strategies.foreign_code_strategy import ForeignCodeVerifier


def _verify(source: str, language: str):
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "{}",
        "stderr": "",
    }
    return ForeignCodeVerifier(mumei_client=mumei).verify(source, language)


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------


def test_python_mutable_default_detected() -> None:
    issues = language_pattern_issues(
        "def bad(items=[]):\n    return items\n", "python"
    )
    assert any("mutable default" in i.message and "`bad`" in i.message for i in issues)


def test_python_immutable_defaults_not_flagged() -> None:
    issues = language_pattern_issues(
        "def ok(a=None, b=0, c='x', d=(1, 2)):\n    return a\n", "python"
    )
    assert not any("mutable default" in i.message for i in issues)


def test_python_mutable_default_call_detected() -> None:
    issues = language_pattern_issues(
        "def bad(cache=dict()):\n    return cache\n", "python"
    )
    assert any("mutable default" in i.message for i in issues)


def test_python_bare_except_detected() -> None:
    source = (
        "def risky():\n"
        "    try:\n"
        "        work()\n"
        "    except:\n"
        "        pass\n"
    )
    issues = language_pattern_issues(source, "python")
    assert any("bare `except:`" in i.message for i in issues)


def test_python_swallowed_exception_detected() -> None:
    source = (
        "def risky():\n"
        "    try:\n"
        "        work()\n"
        "    except Exception:\n"
        "        pass\n"
    )
    issues = language_pattern_issues(source, "python")
    assert any("swallow" in i.message.lower() or "does nothing" in i.message for i in issues)


def test_python_handled_exception_not_flagged() -> None:
    source = (
        "def risky():\n"
        "    try:\n"
        "        work()\n"
        "    except ValueError:\n"
        "        handle()\n"
        "    except Exception as e:\n"
        "        log(e)\n"
    )
    issues = language_pattern_issues(source, "python")
    assert not any("except" in i.message for i in issues)


def test_python_nested_function_defaults_attributed_correctly() -> None:
    source = (
        "def outer():\n"
        "    def inner(cache={}):\n"
        "        return cache\n"
        "    return inner\n"
    )
    issues = language_pattern_issues(source, "python")
    assert any("`inner`" in i.message for i in issues)
    assert not any("`outer`" in i.message for i in issues)


# ---------------------------------------------------------------------------
# Rust
# ---------------------------------------------------------------------------


def test_rust_unguarded_unwrap_detected() -> None:
    issues = language_pattern_issues(
        "fn fetch(res: Option<i32>) -> i32 {\n    res.unwrap()\n}\n", "rust"
    )
    assert any("unwrap()" in i.message and "`fetch`" in i.message for i in issues)


def test_rust_unguarded_expect_detected() -> None:
    issues = language_pattern_issues(
        'fn fetch(r: Result<i32, E>) -> i32 {\n    r.expect("boom")\n}\n', "rust"
    )
    assert any("expect(" in i.message for i in issues)


@pytest.mark.parametrize(
    "guard",
    [
        # `res.unwrap()` actually appears in the body — the guard, not the
        # absence of unwrap, is what must suppress the finding.
        "if res.is_some() { res.unwrap() } else { 0 }",
        "if res.is_ok() { res.unwrap() } else { 0 }",
        "if let Some(v) = res { res.unwrap() } else { 0 }",
        "while let Some(v) = res { res.unwrap(); }",
        "let Some(v) = res else { return 0; };\n    res.unwrap()",
        "match res { Some(v) => v, None => 0 }\n    // body uses res? later\n    let x = res?;\n    x",
        "res.unwrap_or(0)",
    ],
)
def test_rust_guarded_unwrap_not_flagged(guard: str) -> None:
    source = f"fn safe(res: Option<i32>) -> i32 {{\n    {guard}\n}}\n"
    issues = language_pattern_issues(source, "rust")
    assert not issues, issues


def test_python_kwonly_mutable_default_attributed_correctly() -> None:
    source = (
        "def f(a, *, k=[]):\n    return k\n"
        "def g(a=[], *, k):\n    return a\n"
    )
    issues = language_pattern_issues(source, "python")
    assert any("`k=[]`" in i.message and "`f`" in i.message for i in issues)
    assert any("`a=[]`" in i.message and "`g`" in i.message for i in issues)
    # `g`'s required kwonly `k` must not inherit `a`'s positional default.
    assert not any("`k=`" in i.message and "`g`" in i.message for i in issues)


def test_go_defer_in_string_literal_not_flagged() -> None:
    source = (
        "package p\n"
        'func hint() {\n'
        '    for _, s := range items {\n'
        '        log("defer f.Close()")\n'
        "    }\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "go")
    assert not issues


def test_solidity_payable_call_receiver_detected() -> None:
    source = (
        "contract C {\n"
        "    function pay() external {\n"
        "        payable(addr).call{value: 1}(\"\");\n"
        "    }\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "solidity")
    assert any("unchecked" in i.message for i in issues)


def test_rust_unwrap_in_string_literal_not_flagged() -> None:
    source = 'fn s() -> &\'static str {\n    "x.unwrap()"\n}\n'
    issues = language_pattern_issues(source, "rust")
    assert not issues


# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------


def test_go_defer_in_loop_detected() -> None:
    source = (
        "package p\n"
        "func flush(files []string) {\n"
        "    for _, f := range files {\n"
        "        h, _ := os.Open(f)\n"
        "        defer h.Close()\n"
        "    }\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "go")
    assert any("inside a loop" in i.message and "`flush`" in i.message for i in issues)


def test_go_defer_outside_loop_not_flagged() -> None:
    source = (
        "package p\n"
        "func open(f string) {\n"
        "    h, _ := os.Open(f)\n"
        "    defer h.Close()\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "go")
    assert not issues


def test_go_range_func_variants_detected() -> None:
    source = (
        "package p\n"
        "func both(a []string) {\n"
        "    for i := 0; i < len(a); i++ {\n"
        "        defer cleanup(i)\n"
        "    }\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "go")
    assert any("inside a loop" in i.message for i in issues)


# ---------------------------------------------------------------------------
# TypeScript
# ---------------------------------------------------------------------------


def test_typescript_floating_promise_detected() -> None:
    source = (
        "async function send(x: number): Promise<number> { return x; }\n"
        "async function run(): Promise<void> {\n"
        "    send(1);\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "typescript")
    assert any(
        "floating promise" in i.message and "`run`" in i.message for i in issues
    )


@pytest.mark.parametrize(
    "call",
    [
        "await send(1);",
        "return send(1);",
        "void send(1);",
        "send(1).catch(() => {});",
        "send(1).then(() => {});",
        "const p = send(1);",
        "await Promise.all([send(1), send(2)]);",
    ],
)
def test_typescript_handled_promise_not_flagged(call: str) -> None:
    source = (
        "async function send(x: number): Promise<number> { return x; }\n"
        "async function run(): Promise<void> {\n"
        f"    {call}\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "typescript")
    assert not issues, issues


def test_typescript_sync_call_not_flagged() -> None:
    source = (
        "function send(x: number): number { return x; }\n"
        "function run(): void {\n"
        "    send(1);\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "typescript")
    assert not issues


# ---------------------------------------------------------------------------
# Solidity
# ---------------------------------------------------------------------------


def test_solidity_tx_origin_detected() -> None:
    source = (
        "contract C {\n"
        "    function auth() public {\n"
        "        require(tx.origin == owner);\n"
        "    }\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "solidity")
    assert any("tx.origin" in i.message for i in issues)


def test_solidity_selfdestruct_detected() -> None:
    source = (
        "contract C {\n"
        "    function kill() external onlyOwner {\n"
        "        selfdestruct(payable(msg.sender));\n"
        "    }\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "solidity")
    assert any("selfdestruct" in i.message for i in issues)


def test_solidity_unchecked_low_level_call_detected() -> None:
    source = (
        "contract C {\n"
        "    function pay() external {\n"
        "        target.call{value: 1}(\"\");\n"
        "    }\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "solidity")
    assert any("unchecked" in i.message and "call" in i.message for i in issues)


def test_solidity_checked_low_level_call_not_flagged() -> None:
    source = (
        "contract C {\n"
        "    function pay() external {\n"
        "        (bool ok, ) = target.call{value: 1}(\"\");\n"
        "        require(ok);\n"
        "    }\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "solidity")
    assert not any("unchecked" in i.message for i in issues)


def test_solidity_msg_sender_not_flagged_as_tx_origin() -> None:
    source = (
        "contract C {\n"
        "    function auth() public {\n"
        "        require(msg.sender == owner);\n"
        "    }\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "solidity")
    assert not any("tx.origin" in i.message for i in issues)


# ---------------------------------------------------------------------------
# Registry / dispatch
# ---------------------------------------------------------------------------


def test_registry_covers_the_five_languages() -> None:
    covered = set().union(*(p.languages for p in LANGUAGE_PATTERNS))
    for language in ("python", "rust", "go", "typescript", "solidity"):
        assert language in covered
    assert all(p.name and callable(p.detect) for p in LANGUAGE_PATTERNS)
    # Registry entries must be uniquely named and hold normalized languages —
    # dispatch normalizes before matching, so a raw alias ("javascript") would
    # be a dead entry.
    assert len({p.name for p in LANGUAGE_PATTERNS}) == len(LANGUAGE_PATTERNS)
    for pattern in LANGUAGE_PATTERNS:
        for language in pattern.languages:
            assert language == language.strip().lower()


def test_unsupported_language_returns_no_issues() -> None:
    assert language_pattern_issues("int main() {}", "cpp") == []
    assert language_pattern_issues("", "python") == []


def test_generated_source_skipped() -> None:
    source = (
        "// Code generated by tool. DO NOT EDIT.\n"
        "def bad(items=[]):\n"
        "    return items\n"
    )
    assert language_pattern_issues(source, "python") == []


def test_language_alias_dispatch() -> None:
    source = (
        "async function send(x: number): Promise<number> { return x; }\n"
        "async function run(): Promise<void> {\n"
        "    send(1);\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "javascript")
    assert any("floating promise" in i.message for i in issues)


# ---------------------------------------------------------------------------
# Wiring: verify() warnings and validate-code advisory issues
# ---------------------------------------------------------------------------


def test_verify_surfaces_pattern_warnings_not_errors() -> None:
    result = _verify("def bad(items=[]):\n    return items\n", "python")
    assert any("mutable default" in w for w in result["warnings"])
    assert not any("mutable default" in e for e in result["errors"])


def test_verify_clean_source_has_no_pattern_warnings() -> None:
    result = _verify("def ok(items=None):\n    return items\n", "python")
    assert result["warnings"] == []


def test_validate_foreign_code_emits_pattern_advisory_on_refuted() -> None:
    """When the verdict is not ``verified`` the advisory stays in ``issues``
    (severity ``warning``) with a routed fix_suggestion."""
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": False,
        "report": {"status": "failed", "failed": 1},
        "stdout": "{}",
        "stderr": "",
    }
    source = "def bad(items=[]):\n    return items\n"
    with patch("agent.cross_validation.create_mumei_client", return_value=mumei):
        result = validate_foreign_code(
            source,
            "python",
            config=AgentConfig(api_key=""),
            use_llm=False,
            run_mumei=True,
        )

    assert result.verdict != "verified"
    advisory = next(
        issue for issue in result.issues if "mutable default" in issue.message
    )
    assert advisory.severity == "warning"
    assert advisory.kind == "verification"
    assert advisory.source_line > 0
    assert "mutable default" in advisory.fix_suggestion


def test_validate_foreign_code_verified_demotes_advisory_to_warnings() -> None:
    """On a ``verified`` result, warning-severity advisories are demoted into
    ``warnings`` (the existing unsubstantiated-advisory contract) and do not
    appear in ``issues``."""
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "{}",
        "stderr": "",
    }
    source = "def bad(items=[]):\n    return items\n"
    with patch("agent.cross_validation.create_mumei_client", return_value=mumei):
        result = validate_foreign_code(
            source,
            "python",
            config=AgentConfig(api_key=""),
            use_llm=False,
            run_mumei=True,
        )

    assert result.verdict == "verified"
    assert not any("mutable default" in issue.message for issue in result.issues)
    assert any("mutable default" in warning for warning in result.warnings)


def test_validate_foreign_code_pattern_fix_templates_routed() -> None:
    """Each pattern message routes to its own fix template, not `generic`."""
    from agent.cross_validation_report import _suggest_verification_fix

    cases = {
        "uses a mutable default argument `items=[]` that is shared across calls": "not None",
        "has a bare `except:` that swallows all exceptions": "narrower exception",
        "can panic via `res.unwrap()` without a contract": "unwrap_or",
        "runs `defer f.Close()` inside a loop": "out of the loop",
        "calls async `send()` without awaiting it — a floating promise": "await",
        "uses `tx.origin` — it authenticates the originating account": "msg.sender",
        "invokes `selfdestruct`": "authorization guard",
        "makes an unchecked `call` low-level call": "success flag",
    }
    for message, expected in cases.items():
        assert expected in _suggest_verification_fix(message, ""), message


def test_solidity_comment_mentions_not_flagged() -> None:
    source = (
        "contract C {\n"
        "    function ok() public {\n"
        "        // never use tx.origin for auth\n"
        "        require(msg.sender == owner);\n"
        "    }\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "solidity")
    assert not any("tx.origin" in i.message for i in issues)


def test_solidity_staticcall_unchecked_detected() -> None:
    source = (
        "contract C {\n"
        "    function probe() external {\n"
        "        target.staticcall(data);\n"
        "    }\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "solidity")
    assert any("staticcall" in i.message for i in issues)


def test_typescript_later_promise_chain_does_not_suppress() -> None:
    """`send(1)` followed by an unrelated `foo().then(...)` must still flag —
    only a `.then/.catch/.finally` on this call's own `)` suppresses."""
    source = (
        "async function send(x: number): Promise<number> { return x; }\n"
        "function foo(): Promise<void> { return Promise.resolve(); }\n"
        "async function run(): Promise<void> {\n"
        "    send(1),\n"
        "    foo().then(() => {});\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "typescript")
    assert any("`send()`" in i.message or "async `send`" in i.message for i in issues)


def test_typescript_nested_args_then_chain_suppressed() -> None:
    source = (
        "async function send(x: number): Promise<number> { return x; }\n"
        "function wrap(f: () => number, n: number): number { return n; }\n"
        "async function run(): Promise<void> {\n"
        "    send(wrap(() => 2, 1)).catch(() => {});\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "typescript")
    assert not any("floating promise" in i.message for i in issues)


def test_go_defer_in_loop_with_composite_literal_header() -> None:
    """`for _, x := range []int{1,2} {` — the literal's `{...}` must not be
    mistaken for the loop body."""
    source = (
        "package p\n"
        "func f() {\n"
        "    for _, x := range []int{1, 2, 3} {\n"
        "        defer c(x)\n"
        "    }\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "go")
    assert any("inside a loop" in i.message for i in issues)


def test_go_defer_after_loop_not_flagged() -> None:
    """A `defer` inside an `if` AFTER a composite-literal loop header is not
    inside the loop."""
    source = (
        "package p\n"
        "func f() {\n"
        "    for _, x := range []int{1, 2, 3} {\n"
        "        work(x)\n"
        "    }\n"
        "    if done {\n"
        "        defer report()\n"
        "    }\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "go")
    assert not issues


def test_go_defer_in_loop_after_literal_and_second_loop() -> None:
    """defer in a later real loop is still found when an earlier loop header
    carried a composite literal."""
    source = (
        "package p\n"
        "func f() {\n"
        "    for _, x := range []int{1, 2, 3} {\n"
        "        work(x)\n"
        "    }\n"
        "    for j := 0; j < 3; j++ {\n"
        "        defer c(j)\n"
        "    }\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "go")
    assert any("inside a loop" in i.message for i in issues)


def test_typescript_async_name_in_comment_does_not_mark() -> None:
    """`// async function send()` in a comment must not mark `send` async."""
    source = (
        "// async function send(x: number) { return x; }\n"
        "function send(x: number): number { return x; }\n"
        "function run(): void {\n"
        "    send(1);\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "typescript")
    assert not issues


def test_typescript_call_inside_comment_not_flagged() -> None:
    source = (
        "async function send(x: number): Promise<number> { return x; }\n"
        "function run(): void {\n"
        "    // send(1);\n"
        "    /* send(2); */\n"
        "    work();\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "typescript")
    assert not issues


def test_rust_nested_fn_unwrap_attributed_to_inner_only() -> None:
    """An unwrap inside a nested `fn` item must report `inner`, not `outer`."""
    source = (
        "fn outer(res: Option<i32>) -> i32 {\n"
        "    fn inner(v: Option<i32>) -> i32 {\n"
        "        v.unwrap()\n"
        "    }\n"
        "    inner(res)\n"
        "}\n"
    )
    issues = language_pattern_issues(source, "rust")
    assert any("`inner`" in i.message for i in issues)
    assert not any("`outer`" in i.message for i in issues)
