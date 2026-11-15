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


def test_non_scalar_param_binds_dep_index():
    # Slice 2: any identifier param gets a dep index
    # (over-approx — reads carry the param's dep).
    s = _fn(
        "fn f(xs: Vec<u64>) -> u64 { 0 }",
        "f",
    )
    assert s.available
    assert s.return_dependencies == frozenset()
    assert not s.gaps


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


def test_slice2_impl_method_self_param():
    s = _fn(
        """struct P { x: u64 }
impl P { fn get(&self) -> u64 { self.x } }""",
        "P.get",
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert s.params == ("self",)


def test_slice2_scoped_call_inlines():
    s = _fn(
        """struct P { x: u64 }
impl P { fn add(a: u64, b: u64) -> u64 { a + b } }
fn f(x: u64) -> u64 { P::add(x, 1) }""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice2_method_call_binds_self():
    s = _fn(
        """struct P { x: u64 }
impl P { fn dbl(&self, v: u64) -> u64 { self.x + v } }
fn f(p: &P, y: u64) -> u64 { p.dbl(y) }""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_slice2_reference_param():
    s = _fn("fn f(p: &u64, y: u64) -> u64 { *p + y }", "f")
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_slice2_unsafe_block():
    s = _fn("fn f(x: u64) -> u64 { unsafe { x } }", "f")
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice2_macro_opaque_call():
    s = _fn(
        """fn f(x: u64) -> u64 {
    println!("{}", x);
    x
}""",
        "f",
    )
    assert s.available
    assert s.return_dependencies == frozenset({0})
    assert s.effects == "unknown"
    assert any(c.name == "println!" for c in s.calls)


def test_slice2_generic_call_inlines():
    s = _fn(
        """fn id<T>(v: T) -> T { v }
fn f(x: u64) -> u64 { id::<u64>(x) }""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice2_tuple_pattern_binds():
    s = _fn("fn f((a, b): (u64, u64)) -> u64 { a + b }", "f")
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice3_if_let_binds_pattern():
    s = _fn(
        """fn f(x: u64) -> u64 {
    if let Some(v) = Some(x) { v } else { 0 }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice3_while_let_binds_pattern():
    s = _fn(
        """fn f(x: u64) -> u64 {
    let mut s = 0u64;
    while let Some(v) = Some(x) { s += v; break; }
    s
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice3_match_arm_binds_pattern():
    s = _fn(
        """fn f(a: u64, b: u64) -> u64 {
    match (a, b) { (x, y) => x + y }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_slice3_closure_value_and_call():
    s = _fn(
        """fn f(o: u64, x: u64) -> u64 {
    let g = |a| a + x;
    g(o)
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_slice3_enum_ctor_opaque():
    s = _fn(
        """fn f(x: u64) -> u64 {
    let o = Some(x);
    match o { Some(v) => v, None => 0 }
}""",
        "f",
    )
    assert s.available
    assert s.return_dependencies == frozenset({0})
    assert s.effects == "unknown"


def test_slice3_extern_path_call_opaque():
    s = _fn(
        """fn f(x: u64) -> u64 {
    let y = std::cmp::max(x, 1);
    y
}""",
        "f",
    )
    assert s.available
    assert s.return_dependencies == frozenset({0})
    assert s.effects == "unknown"


def test_slice4_let_destructure():
    s = _fn(
        "fn f(x: u64, y: u64) -> u64 { let (a, b) = (x, y); a + b }",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_slice4_self_field_write_propagates():
    s = _fn(
        """struct P { x: u64 }
impl P { fn set(&mut self, v: u64) { self.x = v; } }
fn f(p: &mut P, v: u64) -> u64 { p.set(v); unsafe { *p } }""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_slice4_mut_arg_write_propagates():
    s = _fn(
        """fn st(p: &mut u64, v: u64) { *p = v; }
fn f(x: u64) -> u64 { let mut s = 0u64; st(&mut s, x); s }""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({1})


def test_slice4_mut_arg_root_resolution():
    s = _fn(
        """fn st(p: &mut u64, v: u64) { *p = v; }
fn f(x: u64, y: u64) -> u64 {
    let mut s = x;
    st(&mut s, y);
    s
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_slice5_container_write_method():
    s = _fn(
        """fn f(x: u64) -> u64 {
    let mut v = Vec::new();
    v.push(x);
    v[0]
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice5_const_global_dep_free():
    s = _fn(
        """const K: u64 = 7;
fn f(x: u64) -> u64 { x + K }""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert s.effects == "none_in_supported_fragment"


def test_slice5_static_mut_write_marks_unknown():
    s = _fn(
        """static mut S: u64 = 0;
fn f(x: u64) -> u64 { unsafe { S = x; } x }""",
        "f",
    )
    assert s.available and s.effects == "unknown"


def test_slice5_recursion_opaque():
    s = _fn(
        "fn g(n: u64) -> u64 { if n == 0 { 0 } else { g(n - 1) } }",
        "g",
    )
    assert s.available
    assert s.return_dependencies == frozenset({0})
    assert s.effects == "unknown"
