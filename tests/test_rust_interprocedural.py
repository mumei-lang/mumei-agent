"""C06 Rust interprocedural summaries — slice tests."""

from agent.rust_interprocedural import (
    PROFILE,
    summarize_rust,
)


def _fn(src, name):
    r = summarize_rust(src)
    for f in r.functions:
        if f.name == name:
            return f
    raise AssertionError(f"{name} not found")


def test_profile_and_context():
    r = summarize_rust("fn f(x: u64) -> u64 { x }")
    assert r.profile == PROFILE
    assert len(r.context_key) == 16


def test_scalar_param_return():
    s = _fn("fn f(x: u64) -> u64 { x }", "f")
    assert s.available
    assert s.return_dependencies == frozenset({0})


def test_tail_and_explicit_return():
    s = _fn("fn f(x: u64) -> u64 { return x * 2; }", "f")
    assert s.available and s.return_dependencies == frozenset({0})


def test_intrafile_call():
    s = _fn(
        """fn helper(a: u64, b: u64) -> u64 { a + b }
fn f(x: u64) -> u64 { helper(x, 1) }""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_if_else_joins_condition():
    s = _fn(
        """fn f(x: u64, c: bool) -> u64 {
    let mut s: u64 = x;
    if c { s = 1; }
    s
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_if_else_overwrite_keeps_cond():
    s = _fn(
        """fn f(x: u64, c: bool) -> u64 {
    let mut s: u64 = x;
    if c { s = 1; } else { s = 2; }
    s
}""",
        "f",
    )
    # both branches overwrite s — x's dep is gone, cond's remains
    assert s.available and s.return_dependencies == frozenset({1})


def test_while_loop_may_write():
    s = _fn(
        """fn f(x: u64) -> u64 {
    let mut s: u64 = x;
    while s > 0 { s -= 1; }
    s
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_match_arms_join():
    s = _fn(
        """fn f(x: u64, c: bool) -> u64 {
    match c { true => x, _ => 0 }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_non_scalar_param_closes():
    s = _fn(
        "fn f(xs: Vec<u64>) -> u64 { 0 }",
        "f",
    )
    assert not s.available
    assert s.effects == "unknown"
    assert s.gaps[0].reason == "unsupported_parameter"


def test_unknown_call_is_opaque():
    s = _fn(
        """fn f(x: u64) -> u64 {
    let y = ext_call(x);
    y
}""",
        "f",
    )
    assert s.available
    assert s.return_dependencies == frozenset({0})
    assert s.effects == "unknown"


def test_slice1_for_binds_pattern_to_iterator():
    s = _fn(
        """fn f(x: u64) -> u64 {
    let mut s: u64 = 0;
    for i in 0..x { s += i; }
    s
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice1_loop_return_gains_cond_deps():
    s = _fn(
        """fn f(x: u64) -> u64 {
    while x > 0 { return 1; }
    0
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice1_mut_param():
    s = _fn("fn f(mut y: u64) -> u64 { y += 1; y }", "f")
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice1_method_call_receiver_deps():
    s = _fn(
        """fn f(x: u64) -> u64 {
    let v = x.max(2);
    v
}""",
        "f",
    )
    assert s.available
    assert s.return_dependencies == frozenset({0})
    assert s.effects == "unknown"


def test_slice1_index_read_union():
    s = _fn(
        """fn f(x: u64, i: u64) -> u64 {
    let a = [x, 1];
    a[i as usize]
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_slice1_tuple_field_read():
    s = _fn(
        """fn f(x: u64) -> u64 {
    let p = (x, 1u64);
    p.0
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})
