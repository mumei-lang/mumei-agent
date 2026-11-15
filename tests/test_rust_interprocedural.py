"""C06 Rust interprocedural summaries — slice tests."""

import json

import pytest

import agent.rust_interprocedural as rust
from agent.rust_interprocedural import (
    PROFILE,
    RustSummarySet,
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
    assert len(r.context_key) == 64


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
    assert s.available and s.return_dependencies == frozenset({0})


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


def test_slice6_loop_break_value():
    s = _fn(
        """fn f(x: u64) -> u64 {
    let y = loop {
        if x > 0 { break x; }
        break 0;
    };
    y
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice7_mod_scoped_call():
    s = _fn(
        """mod inner { pub fn h(a: u64) -> u64 { a + 1 } }
fn f(x: u64) -> u64 { inner::h(x) }""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_review1_wildcard_param_consumes_slot():
    s = _fn(
        """fn h(_: u64, y: u64) -> u64 { y }
fn f(x: u64) -> u64 { h(0, x) }""",
        "f",
    )
    assert s.available
    assert s.return_dependencies == frozenset({0})


def test_review1_static_mut_compound_assign():
    s = _fn(
        """static mut S: u64 = 0;
fn f(x: u64) { unsafe { S += x; } }""",
        "f",
    )
    assert s.available
    assert s.effects == "unknown"


def test_review1_element_write_reaches_read():
    s = _fn(
        "fn f(x: u64) -> u64 { let mut a = [0]; a[0] = x; a[0] }",
        "f",
    )
    assert s.available
    assert s.return_dependencies == frozenset({0})


def test_review1_wrapper_propagates_ref_write():
    s = _fn(
        """fn inner(p: &mut u64, x: u64) { *p = x; }
fn w(p: &mut u64, x: u64) { inner(p, x); }
fn f(s: u64, y: u64) -> u64 { let mut s2 = s; w(&mut s2, y); s2 }""",
        "f",
    )
    assert s.available
    assert s.return_dependencies == frozenset({0, 1})


def test_review1_conditional_write_carries_condition_deps():
    s = _fn(
        """fn st(p: &mut u64, c: u64, x: u64) { if c > 0 { *p = x; } }
fn f(s: u64, c: u64, x: u64) -> u64 { let mut s2 = s; st(&mut s2, c, x); s2 }""",
        "f",
    )
    assert s.available
    assert s.return_dependencies == frozenset({0, 1, 2})


def test_manifest_round_trip_restores_the_summary_set():
    s = summarize_rust(
        "fn f(x: u64, y: u64) -> u64 { g(x) + y }"
        "fn g(v: u64) -> u64 { v + 1 }"
    )
    restored = RustSummarySet.from_dict(
        json.loads(json.dumps(s.to_dict()))
    )
    assert restored == s


def test_manifest_restoration_rejects_a_wrong_schema():
    s = summarize_rust("fn f(x: u64) -> u64 { x }")
    bad = s.to_dict()
    bad["schema_version"] = "mumei.other/v1"
    with pytest.raises(ValueError, match="malformed"):
        RustSummarySet.from_dict(bad)


def test_manifest_restoration_rejects_unknown_and_missing_keys():
    s = summarize_rust("fn f(x: u64) -> u64 { x }")
    good = s.to_dict()
    bad = dict(good, extra_key=1)
    with pytest.raises(ValueError, match="malformed"):
        RustSummarySet.from_dict(bad)
    bad = dict(good)
    del bad["context_key"]
    with pytest.raises(ValueError, match="malformed"):
        RustSummarySet.from_dict(bad)


def test_manifest_restoration_rejects_a_contradictory_available_flag():
    s = summarize_rust("fn f(x: u64) -> u64 { x }")
    good = s.to_dict()
    forged = dict(good)
    forged["functions"] = [
        dict(good["functions"][0], available=False)
    ]
    # `available: false` alongside a derived result claims the
    # record has a gap it does not declare — malformed.
    with pytest.raises(ValueError, match="malformed"):
        RustSummarySet.from_dict(forged)


def test_manifest_restoration_rejects_wrong_types():
    s = summarize_rust("fn f(x: u64) -> u64 { x }")
    good = s.to_dict()
    bad = dict(good, context_key=123)
    with pytest.raises(ValueError, match="malformed"):
        RustSummarySet.from_dict(bad)
    fn = dict(good["functions"][0])
    fn["calls"] = [
        {
            "byte": 0,
            "name": "g",
            "arguments": [["x"]],
            "result": [0],
        }
    ]
    bad = dict(good, functions=[fn])
    with pytest.raises(ValueError, match="malformed"):
        RustSummarySet.from_dict(bad)


# --- slice 9: rust-summaries / rust-summaries-accept routes -------------------

def _rust_args(source, manifest=None, function=None):
    return type(
        "A",
        (),
        {
            "source": str(source),
            "manifest": str(manifest) if manifest else None,
            "function": function,
        },
    )()


_RS_SRC = (
    "fn f(x: u64) -> u64 { g(x) }"
    "fn g(v: u64) -> u64 { v + 1 }"
)


def test_summaries_route_emits_json(tmp_path, capsys):
    src = tmp_path / "a.rs"
    src.write_text(_RS_SRC)
    rust.main(_rust_args(src))
    out = json.loads(capsys.readouterr().out)
    assert out["schema_version"] == "mumei.rust-interprocedural/v0"
    assert out["functions"][0]["name"] == "f"


def test_accept_route_accepts_a_surviving_function(tmp_path, capsys):
    src = tmp_path / "a.rs"
    src.write_text(_RS_SRC)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(summarize_rust(_RS_SRC).to_dict())
    )
    with pytest.raises(SystemExit) as exc:
        rust.main_accept(_rust_args(src, manifest, "f"))
    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema_version"] == "mumei.rust-summary-accept/v1"
    assert out["accepted"] is True
    assert out["summary"]["name"] == "f"


def test_accept_route_refuses_a_changed_context(tmp_path, capsys):
    src = tmp_path / "a.rs"
    src.write_text(_RS_SRC)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(summarize_rust(_RS_SRC + "//x").to_dict())
    )
    with pytest.raises(SystemExit):
        rust.main_accept(_rust_args(src, manifest, "f"))
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is False
    assert out["reason"] == "context_mismatch"


def test_accept_route_refuses_an_unknown_function(tmp_path, capsys):
    src = tmp_path / "a.rs"
    src.write_text(_RS_SRC)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(summarize_rust(_RS_SRC).to_dict())
    )
    with pytest.raises(SystemExit):
        rust.main_accept(_rust_args(src, manifest, "absent"))
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is False
    assert out["reason"] == "unknown_function"


def test_accept_route_emits_the_live_record_not_the_forged_one(
    tmp_path, capsys
):
    src = tmp_path / "a.rs"
    src.write_text(_RS_SRC)
    manifest = tmp_path / "m.json"
    forged = summarize_rust(_RS_SRC).to_dict()
    forged["functions"][0]["return_dependencies"] = [1, 2, 3]
    manifest.write_text(json.dumps(forged))
    with pytest.raises(SystemExit):
        rust.main_accept(_rust_args(src, manifest, "f"))
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is True
    assert out["summary"]["return_dependencies"] == [0]


def test_accept_route_rejects_a_malformed_manifest(tmp_path, capsys):
    src = tmp_path / "a.rs"
    src.write_text(_RS_SRC)
    manifest = tmp_path / "m.json"
    manifest.write_text('{"schema_version": "mumei.other/v1"}')
    with pytest.raises(SystemExit) as exc:
        rust.main_accept(_rust_args(src, manifest, "f"))
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["reason"] == "manifest_malformed"


# --- slice 10: rust-summaries-check / rust-summaries-reuse routes -------------

def _rust_route_args(source, manifest, output=None):
    return type(
        "A",
        (),
        {
            "source": str(source),
            "manifest": str(manifest),
            "output": str(output) if output else None,
        },
    )()


_RS_CHANGED = "fn f(x: u64) -> u64 { g(x) } fn g(v: u64) -> u64 { 7 }"


def test_check_route_partitions_names(tmp_path, capsys):
    src = tmp_path / "a.rs"
    src.write_text(_RS_SRC)
    manifest = tmp_path / "m.json"
    old = summarize_rust(_RS_SRC).to_dict()
    old["functions"].append(
        {
            "name": "gone",
            "available": True,
            "parameters": [],
            "return_dependencies": [],
            "calls": [],
            "gaps": [],
            "effects": "unknown",
        }
    )
    manifest.write_text(json.dumps(old))
    src.write_text(_RS_CHANGED)
    rust.main_check(_rust_route_args(src, manifest))
    out = json.loads(capsys.readouterr().out)
    assert out["schema_version"] == "mumei.rust-summary-check/v1"
    assert out["context_match"] is False
    assert out["missing"] == ["gone"]
    assert "g" in out["stale"]


def test_check_route_reports_reusable_records(tmp_path, capsys):
    src = tmp_path / "a.rs"
    src.write_text(_RS_SRC)
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps(summarize_rust(_RS_SRC).to_dict()))
    rust.main_check(_rust_route_args(src, manifest))
    out = json.loads(capsys.readouterr().out)
    assert out["context_match"] is True
    assert out["reusable"] == ["f", "g"]
    assert out["stale"] == []
    assert out["missing"] == []


def test_reuse_route_merges_and_rekeys(tmp_path, capsys):
    src = tmp_path / "a.rs"
    src.write_text(_RS_CHANGED)
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps(summarize_rust(_RS_SRC).to_dict()))
    rust.main_reuse(_rust_route_args(src, manifest))
    out = json.loads(capsys.readouterr().out)
    assert out["schema_version"] == "mumei.rust-interprocedural/v0"
    fresh = summarize_rust(_RS_CHANGED)
    assert out["context_key"] == fresh.context_key
    by_name = {f["name"]: f for f in out["functions"]}
    assert by_name["g"]["return_dependencies"] == []


def test_manifest_restoration_rejects_duplicate_function_names():
    s = summarize_rust(_RS_SRC).to_dict()
    s["functions"].append(dict(s["functions"][0]))
    with pytest.raises(ValueError, match="malformed"):
        RustSummarySet.from_dict(s)


def test_accept_route_prefers_an_exact_name_over_suffix_matches(
    tmp_path, capsys
):
    both = (
        "fn f(x: u64) -> u64 { x }"
        "struct P;"
        "impl P { fn f(&self, x: u64) -> u64 { x + 1 } }"
    )
    src = tmp_path / "a.rs"
    src.write_text(both)
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps(summarize_rust(both).to_dict()))
    # `f` is the emitted name of the top-level function — it wins
    # over the `P.f` suffix match.
    args = type(
        "A",
        (),
        {
            "source": str(src),
            "manifest": str(manifest),
            "function": "f",
            "output": None,
        },
    )()
    with pytest.raises(SystemExit):
        rust.main_accept(args)
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is True
    assert out["summary"]["name"] == "f"


def test_accept_route_bare_name_covers_qualified_records(
    tmp_path, capsys
):
    impl_only = (
        "struct P;"
        "impl P { fn f(&self, x: u64) -> u64 { x + 1 } }"
    )
    src = tmp_path / "a.rs"
    src.write_text(impl_only)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(summarize_rust(impl_only).to_dict())
    )
    args = type(
        "A",
        (),
        {
            "source": str(src),
            "manifest": str(manifest),
            "function": "f",
            "output": None,
        },
    )()
    with pytest.raises(SystemExit):
        rust.main_accept(args)
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is True
    assert out["summary"]["name"] == "P.f"
