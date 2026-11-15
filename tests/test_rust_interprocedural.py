"""C06 Rust interprocedural summaries — slice tests."""

import json
import os

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
    assert out["schema_version"] == "mumei.rust-scalar-parameter-deps/v1"
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
    assert out["schema_version"] == "mumei.rust-scalar-parameter-deps/v1"
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


def _attempt_args(source, attempt_timeout=60000, output=None,
                  memory_bound_mb=None):
    return type(
        "A",
        (),
        {
            "source": str(source),
            "attempt_timeout": attempt_timeout,
            "memory_bound_mb": memory_bound_mb,
            "output": str(output) if output else None,
        },
    )()


def test_attempt_route_emits_lineage_and_candidate(tmp_path, capsys):
    src = tmp_path / "a.rs"
    src.write_text(_RS_SRC)
    rust.main_attempt(_attempt_args(src))
    report = json.loads(capsys.readouterr().out)
    assert (
        report["schema_version"]
        == "mumei.rust-summaries-attempt-report/v1"
    )
    sequence = report["sequence"]
    assert (
        sequence["schema_version"] == "mumei.verifier-attempt-sequence/v1"
    )
    assert sequence["attempts"][0]["state"] == "exited"
    assert sequence["attempts"][0]["events"][-1]["kind"] == "exited"
    assert sequence["attempts"][0]["events"][-1]["exit_code"] == 0
    assert sequence["selected_result"]["attempt_number"] == 1
    normalized = report["normalized"]
    assert normalized["outcome"] == "exited"
    assert normalized["exit_code"] == 0
    candidate = report["candidate"]
    assert (
        candidate["schema_version"]
        == "mumei.verifier-evidence-candidate/v1"
    )
    assert (
        candidate["request_fingerprint"]
        == sequence["request_fingerprint"]
    )


def test_attempt_route_binds_source_bytes(tmp_path, capsys):
    src = tmp_path / "a.rs"
    src.write_text(_RS_SRC)
    rust.main_attempt(_attempt_args(src))
    first = json.loads(capsys.readouterr().out)["sequence"][
        "request_fingerprint"
    ]
    src.write_text(_RS_SRC + "//changed")
    rust.main_attempt(_attempt_args(src))
    second = json.loads(capsys.readouterr().out)["sequence"][
        "request_fingerprint"
    ]
    assert first != second


def test_attempt_route_rejects_output_overwriting_source(
    tmp_path, capsys
):
    src = tmp_path / "a.rs"
    src.write_text(_RS_SRC)
    with pytest.raises(SystemExit) as exc:
        rust.main_attempt(_attempt_args(src, output=src))
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["reason"] == "output_overwrites_source"
    assert src.read_text() == _RS_SRC


def test_attempt_route_output_file(tmp_path, capsys):
    src = tmp_path / "a.rs"
    src.write_text(_RS_SRC)
    out_path = tmp_path / "report.json"
    rust.main_attempt(_attempt_args(src, output=out_path))
    capsys.readouterr()
    report = json.loads(out_path.read_text())
    assert (
        report["schema_version"]
        == "mumei.rust-summaries-attempt-report/v1"
    )


def test_attempt_route_rejects_output_hardlink_to_source(
    tmp_path, capsys
):
    src = tmp_path / "a.rs"
    src.write_text(_RS_SRC)
    link = tmp_path / "linked.rs"
    os.link(src, link)
    with pytest.raises(SystemExit) as exc:
        rust.main_attempt(_attempt_args(src, output=link))
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["reason"] == "output_overwrites_source"
    assert src.read_text() == _RS_SRC


def test_attempt_route_skips_candidate_when_inputs_change(
    tmp_path, capsys, monkeypatch
):
    src = tmp_path / "a.rs"
    src.write_text(_RS_SRC)
    from agent import attempt_runner

    real_run = attempt_runner.AttemptRunner.run

    def run_then_modify(
        self, request, argv, memory_bound_mb=None, cancel_event=None
    ):
        src.write_text(_RS_SRC + "//mutated mid-run")
        return real_run(
            self,
            request,
            argv,
            memory_bound_mb=memory_bound_mb,
            cancel_event=cancel_event,
        )

    monkeypatch.setattr(
        attempt_runner.AttemptRunner, "run", run_then_modify
    )
    rust.main_attempt(_attempt_args(src))
    report = json.loads(capsys.readouterr().out)
    assert report["sequence"].get("selected_result") is None
    assert "candidate" not in report


def test_review2_param_write_marks_state_writes():
    s = _fn("fn f(p: &mut u64, v: u64) { *p = v; }", "f")
    assert s.effects == "state_writes"


def test_review3_inferred_receiver_type_resolves_method():
    # `let mut q = p` has no annotation — q must inherit p's
    # declared type so `q.update(x)` resolves the impl method and
    # its param_writes project onto q's slot.
    s = _fn(
        """struct P { v: u64 }
impl P { fn update(&mut self, x: u64) { self.v = x; } }
fn f(p: P, x: u64) -> u64 { let mut q = p; q.update(x); q.v }""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_review3_global_write_then_param_write_stays_unknown():
    # `unknown` is absorbing: a mut-global write followed by a
    # param-root write must not downgrade to `state_writes` —
    # the caller would lose the global side effect.
    s = _fn(
        """static mut G: u64 = 0;
fn f(p: &mut u64, x: u64) { unsafe { G = x; } *p = x; }""",
        "f",
    )
    assert s.effects == "unknown"


def test_review3_param_write_then_opaque_call_stays_unknown():
    # Same absorption in the other order: an opaque call after a
    # tracked param write keeps `unknown`.
    s = _fn(
        """extern "C" { fn ext(); }
fn g(p: &mut u64, x: u64) { *p = x; unsafe { ext(); } }""",
        "g",
    )
    assert s.effects == "unknown"


def test_review2_opaque_mut_ref_arg_gains_deps():
    s = _fn(
        """extern "C" { fn ext(p: &mut u64, x: u64); }
fn f(s: u64, y: u64) -> u64 { let mut l = s; unsafe { ext(&mut l, y); } l }""",
        "f",
    )
    # `l` is written through by an opaque callee — a later read
    # must see the write's argument deps.
    assert s.return_dependencies == frozenset({0, 1})


def test_review2_local_shadows_file_function():
    s = _fn(
        """fn g(x: u64) -> u64 { x }
fn f(y: u64) -> u64 { let g = |a: u64| a + y; g(0) }""",
        "f",
    )
    # `g` is a local closure — the call may not borrow the
    # file-level `g`'s summary.
    assert s.return_dependencies == frozenset({0})


def test_review2_method_requires_receiver_type():
    s = _fn(
        """struct P { v: u64 }
impl P { fn get(&self) -> u64 { self.v } }
struct Q { w: u64 }
fn f(q: Q, y: u64) -> u64 { q.get() + y }""",
        "f",
    )
    # `q: Q` may not resolve `P::get` — the call stays opaque
    # and the receiver's dep survives.
    assert s.return_dependencies == frozenset({0, 1})


def test_review2_typed_method_still_resolves():
    s = _fn(
        """struct P { v: u64 }
impl P { fn get(&self) -> u64 { self.v } }
fn f(p: P) -> u64 { p.get() }""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_review2_failed_parse_not_recursive():
    s = summarize_rust(
        """fn g(x: u64) -> u64 { loop { for i in 0.. {} } }
fn f(y: u64) -> u64 { g(y) }"""
    )
    fs = {x.name: x for x in s.functions}
    assert not fs["g"].available
    assert fs["f"].return_dependencies is None
    assert fs["f"].effects == "unknown"


def test_review2_accept_rejects_undeclared_function(tmp_path):
    import json
    import subprocess
    import sys
    from agent.rust_interprocedural import summarize_rust

    src = tmp_path / "s.rs"
    src.write_text("fn f(x: u64) -> u64 { x }\nfn g(y: u64) -> u64 { y }")
    manifest = tmp_path / "m.json"
    live = summarize_rust(src.read_text())
    declared = type(live)(
        context_key=live.context_key,
        profile=live.profile,
        functions=[f for f in live.functions if f.name == "f"],
    )
    manifest.write_text(json.dumps(declared.to_dict()))
    out = subprocess.run(
        [
            sys.executable, "-m", "agent", "rust-summaries-accept",
            str(src), "--manifest", str(manifest), "--function", "g",
        ],
        capture_output=True, text=True,
    )
    report = json.loads(out.stdout)
    assert report["context_match"] is True
    assert report["accepted"] is False
    assert report["reason"] == "undeclared_function"


def test_review2_check_output_cannot_overwrite_inputs(tmp_path):
    import subprocess
    import sys

    src = tmp_path / "s.rs"
    src.write_text("fn f(x: u64) -> u64 { x }")
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(summarize_rust(src.read_text()).to_dict())
    )
    for target in (src, manifest):
        out = subprocess.run(
            [
                sys.executable, "-m", "agent", "rust-summaries-check",
                str(src), "--manifest", str(manifest),
                "--output", str(target),
            ],
            capture_output=True, text=True,
        )
        assert out.returncode == 2
        assert "output_overwrites_source" in out.stdout
    assert src.read_text() == "fn f(x: u64) -> u64 { x }"


def test_review5_mut_ref_rebind_keeps_param_write():
    # `let q = p` moves the `&mut` reference — writes through `q`
    # reach the caller's pointee, so `p`'s param slot must record
    # them. (post-merge review on f60e4c50)
    s = _fn(
        """struct P { v: u64 }
impl P { fn set(&mut self, x: u64) { self.v = x; } }
fn f(p: &mut P, v: u64) { let q = p; q.set(v); }""",
        "f",
    )
    assert s.available
    assert s.effects == "state_writes"
    # `q`'s dep (0 — it binds `p`) plus `v` (1) both reach the slot.
    assert s.param_writes.get(0) == frozenset({0, 1})


def test_review5_field_read_does_not_inherit_receiver_type():
    # `let q = a.inner` binds the field's own type — `q.get(k)`
    # must not resolve `A`'s impl method and drop `k`'s dep.
    # (post-merge review on f60e4c50)
    s = _fn(
        """struct A { inner: B }
struct B;
impl A { fn get(&self, k: u64) -> u64 { 7 } }
fn f(a: A, k: u64) -> u64 { let q = a.inner; q.get(k) }""",
        "f",
    )
    assert s.available
    assert 1 in s.return_dependencies


def test_review6_paren_rebind_keeps_receiver_type():
    # `let mut q = (p)` — parens are transparent: `q` still
    # inherits `p`'s type so `q.update(x)` resolves the impl
    # method and its write projects onto `q`'s slot.
    s = _fn(
        """struct P { v: u64 }
impl P { fn update(&mut self, x: u64) { self.v = x; } }
fn f(p: P, x: u64) -> u64 { let mut q = (p); q.update(x); q.v }""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_review6_paren_mut_rebind_keeps_param_write():
    # `let q = (p)` moves the `&mut` reference exactly like
    # `let q = p` — writes through `q` reach `p`'s pointee.
    s = _fn(
        """struct P { v: u64 }
impl P { fn set(&mut self, x: u64) { self.v = x; } }
fn f(p: &mut P, v: u64) { let q = (p); q.set(v); }""",
        "f",
    )
    assert s.available
    assert s.effects == "state_writes"
    assert s.param_writes.get(0) == frozenset({0, 1})


def test_review6_paren_mut_borrow_stays_local():
    # `let q = &mut (p)` borrows the local binding like
    # `let q = &mut p` — it must NOT alias `p`'s pointee.
    s = _fn(
        """fn f(p: &mut u64, v: u64) { let q = &mut (p); }""",
        "f",
    )
    assert s.available
    assert not getattr(s, "param_writes", None)
    assert s.effects == "none_in_supported_fragment"


def test_review6_inner_shadow_restores_param_alias():
    # An inner-block `let q = p` shadows outer `q` only inside
    # the block — after it ends, `*q = v` writes `q`'s own slot.
    s = _fn(
        """struct P { v: u64 }
fn f(p: &mut P, q: &mut P, v: u64) { { let q = p; } *q = v; }""",
        "f",
    )
    assert s.available
    assert s.effects == "state_writes"
    assert s.param_writes.get(0) is None
    assert s.param_writes.get(1) == frozenset({1, 2})


def test_review6_ref_pattern_does_not_alias():
    # `let &mut mut q = p` copies `*p` into a local — `q`'s
    # writes are local, never writes through `p`.
    s = _fn(
        """struct P { v: u64 }
fn f(p: &mut P, v: u64) { let &mut mut q = p; q.v = v; }""",
        "f",
    )
    assert s.available
    assert not getattr(s, "param_writes", None)
    assert s.effects == "none_in_supported_fragment"


def test_review6_alias_chain_propagates():
    # `let q = p; let r = q` — `r` re-binds the same `&mut`,
    # so writes through `r` still reach `p`'s pointee.
    s = _fn(
        """fn f(p: &mut u64, v: u64) { let q = p; let r = q; *r = v; }""",
        "f",
    )
    assert s.available
    assert s.effects == "state_writes"
    assert s.param_writes.get(0) == frozenset({0, 1})


def test_review6_loop_body_alias_does_not_leak():
    # A `let` inside a loop body is scoped to the body — the
    # alias must not survive past the loop.
    s = _fn(
        """struct P { v: u64 }
fn f(p: &mut P, q: &mut P, v: u64) {
    loop { let q = p; break; }
    *q = v;
}""",
        "f",
    )
    assert s.available
    assert s.effects == "state_writes"
    assert s.param_writes.get(0) is None
    assert s.param_writes.get(1) == frozenset({1, 2})
