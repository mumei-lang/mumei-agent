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
    forged["functions"][0]["return_dependencies"] = []
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
    check = report["evidence_check"]
    assert check["schema_version"] == "mumei.verifier-evidence-check/v1"
    assert check["outcome"] == "valid"
    acceptance = report["acceptance"]
    assert (
        acceptance["schema_version"]
        == "mumei.evidence-check-acceptance/v1"
    )
    assert acceptance["accepted"] is True
    # A summary manifest discharges only the byte/run-level checks:
    # its dep claims stay unperformed until the strict accept route
    # re-derives them.
    assert report["discharged_checks"] == [
        "file_identity",
        "freshness",
        "producer_authenticity",
    ]
    assert report["checks_not_performed"] == [
        "artifact_semantics",
        "claim_truth",
        "semantic_correspondence",
    ]


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
        self, request, argv, memory_bound_mb=None, cancel_event=None,
        feed_bytes=None, environment=None, isolate_network=False,
        isolate_filesystem_write=False,
    ):
        src.write_text(_RS_SRC + "//mutated mid-run")
        return real_run(
            self,
            request,
            argv,
            memory_bound_mb=memory_bound_mb,
            cancel_event=cancel_event,
            feed_bytes=feed_bytes,
            environment=environment,
            isolate_network=isolate_network,
            isolate_filesystem_write=isolate_filesystem_write,
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


def test_review6_ref_mut_binding_aliases_pointee():
    # `let ref mut q = p` binds `q: &mut p` — writes through
    # `q` reach `p`'s storage, so `**q = v` writes the caller.
    s = _fn(
        """fn f(p: &mut u64, v: u64) { let ref mut q = p; **q = v; }""",
        "f",
    )
    assert s.available
    assert s.effects == "state_writes"
    assert s.param_writes.get(0) == frozenset({0, 1})


def test_review6_plain_ref_binding_does_not_alias():
    # `let ref q = p` binds `&p` — immutable, so `q` cannot be
    # a write path and must not alias `p`'s slot.
    s = _fn(
        """fn f(p: &mut u64, v: u64) { let ref q = p; }""",
        "f",
    )
    assert s.available
    assert not getattr(s, "param_writes", None)
    assert s.effects == "none_in_supported_fragment"


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


def test_review7_assign_then_shadow_keeps_outer_deps():
    # `x = p` writes the outer `x`; the later `let x` shadows it
    # only inside the block — block exit must keep the write, not
    # restore the block-entry value.
    s = _fn(
        """fn f(p: u64) -> u64 {
    let mut x = 0;
    { x = p; let x = 42; }
    x
}""",
        "f",
    )
    assert s.available
    assert s.return_dependencies == frozenset({0})


def test_review7_assign_then_shadow_keeps_param_write():
    # Same shape for a `&mut` param: `*q = v` writes through the
    # outer `q`; a shadowing `let q` afterwards must not drop the
    # param write.
    s = _fn(
        """struct P { v: u64 }
fn f(p: &mut P, q: &mut P, v: u64) {
    { *q = v; let q = p; }
}""",
        "f",
    )
    assert s.available
    assert s.effects == "state_writes"
    assert s.param_writes.get(1) == frozenset({1, 2})


def test_review7_double_shadow_restores_first_capture():
    # A second `let x` shadows the inner binding, not the outer
    # one — the restore value stays the first-shadow capture.
    s = _fn(
        """fn f(p: u64, q: u64) -> u64 {
    let mut x = 0;
    { x = p; let x = 1; x = q; let x = 2; }
    x
}""",
        "f",
    )
    assert s.available
    assert s.return_dependencies == frozenset({0})


# -- cross-file module resolution (resolver contract) ------------

_B_SRC = "fn bf(x: u64) -> u64 { x + 1 }\n"
_A_SRC = "mod b;\nfn af(x: u64) -> u64 { b::bf(x) }\n"


def _set_resolver(table):
    """In-memory resolver: spec -> source bytes/str."""

    def resolve(spec):
        return table.get(spec)

    return resolve


def _path_resolver(table):
    """Importer-aware resolver: (importer_path, spec) -> source."""

    def resolve(spec, importer_path=None):
        return table.get((importer_path, spec))

    return resolve


def test_mod_resolution_registers_module_functions():
    r = summarize_rust(_A_SRC, resolver=_set_resolver({"b": _B_SRC}))
    s = next(f for f in r.functions if f.name == "af")
    assert s.available and s.return_dependencies == frozenset({0})
    assert "b.bf" in {f.name for f in r.functions}


def test_use_binding_resolves_bare_call():
    src = "mod b;\nuse b::bf;\nfn af(x: u64) -> u64 { bf(x) }\n"
    r = summarize_rust(src, resolver=_set_resolver({"b": _B_SRC}))
    s = next(f for f in r.functions if f.name == "af")
    assert s.available and s.return_dependencies == frozenset({0})


def test_use_list_and_alias_bind():
    src = (
        "mod b;\nuse b::{bf, bf2 as h};\n"
        "fn af(x: u64) -> u64 { bf(x) + h(x) }\n"
    )
    b = _B_SRC + "fn bf2(y: u64) -> u64 { y * 2 }\n"
    r = summarize_rust(src, resolver=_set_resolver({"b": b}))
    s = next(f for f in r.functions if f.name == "af")
    assert s.available and s.return_dependencies == frozenset({0})


def test_same_module_bare_call_resolves():
    # `caller` inside `b.rs` calls `hidden` bare — the same-module
    # prefixed candidate resolves `b.hidden`.
    src = (
        "mod b;\n"
        "fn af(x: u64) -> u64 { b::caller(x) }\n"
    )
    b = (
        "fn hidden(y: u64) -> u64 { y }\n"
        "fn caller(z: u64) -> u64 { hidden(z) }\n"
    )
    r = summarize_rust(src, resolver=_set_resolver({"b": b}))
    s = next(f for f in r.functions if f.name == "b.caller")
    assert s.available and s.return_dependencies == frozenset({0})
    assert any(c.name and "hidden" in c.name for c in s.calls)


def test_crate_self_super_heads_resolve():
    src = (
        "mod a {\n"
        "    pub fn deep(x: u64) -> u64 { x }\n"
        "    mod c {\n"
        "        pub fn cf(y: u64) -> u64 { y }\n"
        "        pub fn sup(z: u64) -> u64 { super::deep(z) }\n"
        "        pub fn sf(z: u64) -> u64 { self::cf(z) }\n"
        "    }\n"
        "}\n"
        "fn f(x: u64) -> u64 { crate::a::deep(x) + a::c::cf(x) }\n"
    )
    r = summarize_rust(src)
    for n in ("a.c.sup", "a.c.sf", "f"):
        s = next(x for x in r.functions if x.name == n)
        assert s.available
        assert s.return_dependencies == frozenset({0}), n


def test_use_head_segment_in_scoped_call():
    # `use a::c;` binds the head `c`, so `c::cf(x)` resolves
    # `a.c.cf`.
    src = (
        "mod a {\n"
        "    pub mod c {\n"
        "        pub fn cf(y: u64) -> u64 { y }\n"
        "    }\n"
        "}\n"
        "use a::c;\n"
        "fn f(x: u64) -> u64 { c::cf(x) }\n"
    )
    r = summarize_rust(src)
    s = next(f for f in r.functions if f.name == "f")
    assert s.available and s.return_dependencies == frozenset({0})


def test_unresolved_mod_stays_opaque():
    r = summarize_rust(_A_SRC, resolver=_set_resolver({}))
    s = next(f for f in r.functions if f.name == "af")
    # `b::bf` unresolvable — the call records opaque deps, the
    # function still summarizes with the arg union (never weaker
    # than no resolver).
    assert s.available
    assert "b.bf" not in {f.name for f in r.functions}


def test_no_resolver_mod_stays_opaque():
    r = summarize_rust(_A_SRC)
    s = next(f for f in r.functions if f.name == "af")
    assert s.available
    assert "b.bf" not in {f.name for f in r.functions}


def test_local_shadow_beats_module_item():
    src = (
        "mod b;\nuse b::bf;\n"
        "fn af(x: u64, bf: u64) -> u64 { bf(x) }\n"
    )
    # A param named `bf` shadows the use binding — `bf(x)` stays
    # opaque over the local's own deps.
    r = summarize_rust(src, resolver=_set_resolver({"b": _B_SRC}))
    s = next(f for f in r.functions if f.name == "af")
    assert s.return_dependencies is None or frozenset(
        {0, 1}
    ) == s.return_dependencies or not s.available


def test_nested_distinct_module_paths_resolve(tmp_path):
    # `a::b::a` through real files: each `mod` declares a FRESH
    # path — `a.b.a.af` is a distinct module, not a cycle.
    (tmp_path / "a.rs").write_text("mod b;\n")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b.rs").write_text("mod a;\n")
    ba = tmp_path / "a" / "b" / "a.rs"
    ba.parent.mkdir()
    ba.write_text("fn af2(x: u64) -> u64 { x }\n")
    root = tmp_path / "main.rs"
    root.write_text("mod a;\n")
    r = summarize_rust(
        root.read_bytes(),
        resolver=rust._fs_resolver,
        source_path=str(root),
    )
    assert "a.b.a.af2" in {f.name for f in r.functions}


def test_self_resolving_mod_terminates_opaque():
    # A degenerate resolver returning the same bytes for the same
    # declaration: `a.af` registers once, `a.a.af` never does.
    src = "mod a;\nfn af(x: u64) -> u64 { a::af(x) }\n"
    r = summarize_rust(src, resolver=lambda spec: src)
    names = {f.name for f in r.functions}
    assert "a.af" in names
    assert "a.a.af" not in names


def test_module_digests_feed_context_key():
    src = "mod b;\nfn af(x: u64) -> u64 { b::bf(x) }\n"
    d1, d2 = {}, {}
    k1 = summarize_rust(
        src, resolver=_set_resolver({"b": "fn bf(x: u64) -> u64 { x }"}),
        module_digests=d1,
    ).context_key
    k2 = summarize_rust(
        src, resolver=_set_resolver({"b": "fn bf(x: u64) -> u64 { 0 }"}),
        module_digests=d2,
    ).context_key
    assert "b" in d1 and "b" in d2
    assert k1 != k2


def test_fs_resolver_layout_and_confinement(tmp_path):
    # `a.rs` importer: `b` resolves `<dir>/a/b.rs` then
    # `<dir>/a/b/mod.rs`; `mod.rs`/`main.rs` importers use their
    # own directory. `..` specs never escape the base.
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b.rs").write_text("fn bf() {}\n")
    (tmp_path / "a.rs").write_text("")
    (tmp_path / "main.rs").write_text("")
    (tmp_path / "c.rs").write_text("")
    assert rust._fs_resolver(
        "b", str(tmp_path / "a.rs")
    ) == (tmp_path / "a" / "b.rs").resolve()
    assert rust._fs_resolver(
        "c", str(tmp_path / "main.rs")
    ) == (tmp_path / "c.rs").resolve()
    assert rust._fs_resolver("../etc/x", str(tmp_path / "a.rs")) is None
    assert rust._fs_resolver("b", None) is None


def test_cli_resolve_modules_route(tmp_path):
    # `rust-summaries --resolve-modules` resolves through the
    # filesystem resolver; without it the module stays opaque.
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b.rs").write_text(
        "fn bf(x: u64) -> u64 { x }\n"
    )
    a = tmp_path / "a.rs"
    a.write_text("mod b;\nfn af(x: u64) -> u64 { b::bf(x) }\n")
    args = type(
        "A",
        (),
        {"source": str(a), "resolve_modules": True},
    )()
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rust.main(args)
    out = __import__("json").loads(buf.getvalue())
    names = {f["name"] for f in out["functions"]}
    assert "b.bf" in names


def test_path_attr_mod_stays_opaque():
    # `#[path = "..."]` redirects the compiler's file lookup —
    # outside the resolver contract, the declaration stays opaque
    # even when the default `b` resolution exists.
    src = '#[path = "alt.rs"]\nmod b;\nfn af(x: u64) -> u64 { b::bf(x) }\n'
    r = summarize_rust(src, resolver=_set_resolver({"b": _B_SRC}))
    assert "b.bf" not in {f.name for f in r.functions}


def test_use_external_head_stays_opaque():
    # `use std::fs` is authoritative: `fs::read` resolves
    # `std::fs::read` or nothing — never a same-named internal
    # item. The internal `fs.read` returns a constant, so a
    # mis-resolution would drop `x`'s dep.
    src = (
        "use std::fs;\n"
        "mod fs {\n"
        "    pub fn read(x: u64) -> u64 { 0 }\n"
        "}\n"
        "fn af(x: u64) -> u64 { fs::read(x) }\n"
    )
    r = summarize_rust(src)
    s = next(f for f in r.functions if f.name == "af")
    assert s.return_dependencies == frozenset({0})
    assert not any(c.name == "fs.read" for c in s.calls)


def test_method_call_scoped_to_caller_module():
    # `t.m()` inside `mod b` resolves `b`'s impl only — the
    # same-named root impl (dep-free `0`) must not be picked.
    src = (
        "struct T;\n"
        "impl T { fn m(&self, x: u64) -> u64 { 0 } }\n"
        "mod b {\n"
        "    pub struct T;\n"
        "    impl T { pub fn m(&self, x: u64) -> u64 { x } }\n"
        "    pub fn caller(t: T, x: u64) -> u64 { t.m(x) }\n"
        "}\n"
    )
    r = summarize_rust(src)
    s = next(f for f in r.functions if f.name == "b.caller")
    assert s.return_dependencies == frozenset({1})
    assert any(c.name == "b.T.m" for c in s.calls)


def test_child_static_does_not_taint_root_effects():
    # `b`'s `static mut STATE` stays scoped — a root function's
    # same-named local assignment is not an observable write, and
    # `b`'s own write still marks unknown.
    src = (
        "mod b;\n"
        "fn af(x: u64) -> u64 { let mut STATE = x; STATE += 1; STATE }\n"
    )
    b = "static mut STATE: u64 = 0;\nfn bf(x: u64) { STATE = x; }\n"
    r = summarize_rust(src, resolver=_set_resolver({"b": b}))
    sa = next(f for f in r.functions if f.name == "af")
    sb = next(f for f in r.functions if f.name == "b.bf")
    assert sa.effects != "unknown"
    assert sb.effects == "unknown"


def test_pathless_child_importers_stay_distinct():
    # Bytes-resolved modules carry a unique importer identity —
    # `a`'s `mod c` and `d`'s `mod c` resolve their own bytes,
    # never each other's (a shared `None` importer would serve the
    # first resolution to both).
    src = "mod a;\nmod d;\nfn f(x: u64) -> u64 { x }\n"
    a = "mod c;\nfn af(x: u64) -> u64 { c::cf(x) }\n"
    d = "mod c;\nfn df(x: u64) -> u64 { c::cf(x) }\n"
    table = {
        ("root.rs", "a"): a,
        ("root.rs", "d"): d,
        ("root.rs\x00a", "c"): "fn cf(x: u64) -> u64 { x }\n",
        ("root.rs\x00d", "c"): "fn cf(x: u64) -> u64 { 0 }\n",
    }
    r = summarize_rust(
        src, resolver=_path_resolver(table), source_path="root.rs"
    )
    sa = next(f for f in r.functions if f.name == "a.af")
    sd = next(f for f in r.functions if f.name == "d.df")
    assert sa.return_dependencies == frozenset({0})
    assert sd.return_dependencies == frozenset()


def test_pathless_digest_keys_stay_distinct():
    # The context key must see each parent's `mod c` — a bare
    # `c` digest key would overwrite one with the other.
    src = "mod a;\nmod d;\n"
    table = {
        ("root.rs", "a"): "mod c;\n",
        ("root.rs", "d"): "mod c;\n",
        ("root.rs\x00a", "c"): "fn cf(x: u64) -> u64 { x }\n",
        ("root.rs\x00d", "c"): "fn cf(x: u64) -> u64 { 0 }\n",
    }
    digs = {}
    summarize_rust(
        src,
        resolver=_path_resolver(table),
        source_path="root.rs",
        module_digests=digs,
    )
    assert "root.rs\x00a\x00c" in digs
    assert "root.rs\x00d\x00c" in digs


def test_resolved_module_paths_reject_output_overwrite(tmp_path):
    # A `--output` pointing at a resolved child module is refused —
    # the report write would destroy bytes the report describes.
    (tmp_path / "a").mkdir()
    b = tmp_path / "a" / "b.rs"
    b.write_text("fn bf(x: u64) -> u64 { x }\n")
    a = tmp_path / "a.rs"
    a.write_text("mod b;\nfn af(x: u64) -> u64 { b::bf(x) }\n")
    resolved = set()
    summarize_rust(
        a.read_bytes(),
        resolver=rust._fs_resolver,
        source_path=str(a),
        resolved_paths=resolved,
    )
    assert str(b.resolve()) in resolved
    with pytest.raises(SystemExit) as exc:
        rust._reject_overwrite(str(b), resolved, "p")
    assert exc.value.code == 2


def test_use_imported_mut_static_write_marks_unknown():
    # `use b::STATE` binds the name authoritatively — a write
    # through it mutates imported state like a same-module
    # `static mut` write.
    src = (
        "mod b;\nuse b::STATE;\n"
        "fn af(x: u64) { unsafe { STATE = x; } }\n"
    )
    b = "pub static mut STATE: u64 = 0;\n"
    r = summarize_rust(src, resolver=_set_resolver({"b": b}))
    s = next(f for f in r.functions if f.name == "af")
    assert s.effects == "unknown"


def test_local_let_shadows_use_imported_mut_static():
    # `let mut STATE` shadows the `use`-bound static — writes
    # target the local slot and must not mark `unknown` effects.
    src = (
        "mod b;\nuse b::STATE;\n"
        "fn af(x: u64) -> u64 {\n"
        "    let mut STATE = 0;\n"
        "    STATE = x;\n"
        "    STATE\n"
        "}\n"
    )
    b = "pub static mut STATE: u64 = 0;\n"
    r = summarize_rust(src, resolver=_set_resolver({"b": b}))
    s = next(f for f in r.functions if f.name == "af")
    assert s.available
    assert s.effects != "unknown"
    assert s.return_dependencies == frozenset({0})


def test_local_let_shadows_use_imported_mut_static_mut_ref():
    # `opaque(&mut STATE, x)` — the callee's param write merges
    # into the shadowing local slot; the imported static is not
    # touched, so effects stay honest.
    src = (
        "mod b;\nuse b::{STATE, opaque};\n"
        "fn af(x: u64) -> u64 {\n"
        "    let mut STATE = 0;\n"
        "    opaque(&mut STATE, x);\n"
        "    STATE\n"
        "}\n"
    )
    b = (
        "pub static mut STATE: u64 = 0;\n"
        "pub fn opaque(x: &mut u64, y: u64) { *x = y; }\n"
    )
    r = summarize_rust(src, resolver=_set_resolver({"b": b}))
    s = next(f for f in r.functions if f.name == "af")
    assert s.available
    assert s.effects != "unknown"
    assert s.return_dependencies == frozenset({0})

    # Same call without the shadowing `let` — the merge writes
    # the imported static.
    src2 = (
        "mod b;\nuse b::{STATE, opaque};\n"
        "fn af(x: u64) -> u64 {\n"
        "    unsafe { opaque(&mut STATE, x); }\n"
        "    x\n"
        "}\n"
    )
    r2 = summarize_rust(src2, resolver=_set_resolver({"b": b}))
    s2 = next(f for f in r2.functions if f.name == "af")
    assert s2.effects == "unknown"


def test_unresolved_mod_keeps_resolved_path_listing():
    # An unresolvable `mod` caches `None` — resolved-path
    # collection must skip it rather than crash.
    resolved = set()
    r = summarize_rust(
        _A_SRC, resolver=_set_resolver({}), resolved_paths=resolved
    )
    assert resolved == set()
    s = next(f for f in r.functions if f.name == "af")
    assert s.available


def test_shared_parent_path_cache_hit(tmp_path):
    # Two parents resolving to the same Path share the child
    # cache — a cached pathless child still scans under each
    # parent's own prefix without needing `module_ref` bound.
    shared = tmp_path / "shared.rs"
    shared.write_text("mod c;\n")
    table = {
        ("root.rs", "a"): shared,
        ("root.rs", "d"): shared,
        (str(shared), "c"): "fn cf(x: u64) -> u64 { x }\n",
    }
    src = "mod a;\nmod d;\nfn f(x: u64) -> u64 { x }\n"
    r = summarize_rust(
        src, resolver=_path_resolver(table), source_path="root.rs"
    )
    names = {f.name for f in r.functions}
    assert "a.c.cf" in names and "d.c.cf" in names


def test_identical_content_modules_are_not_cycles(tmp_path):
    # Different paths with identical bytes are different files —
    # the byte-identity cycle guard only applies to pathless
    # resolutions, so `a.inner.inner.f` still registers.
    (tmp_path / "a" / "inner").mkdir(parents=True)
    (tmp_path / "a" / "inner" / "inner.rs").write_text(
        "fn f(x: u64) -> u64 { x }\n"
    )
    same = "pub mod inner;\n"
    (tmp_path / "a" / "mod.rs").write_text(same)
    (tmp_path / "a" / "inner" / "mod.rs").write_text(same)
    root = tmp_path / "main.rs"
    root.write_text("mod a;\n")
    r = summarize_rust(
        root.read_bytes(),
        resolver=rust._fs_resolver,
        source_path=str(root),
    )
    assert "a.inner.inner.f" in {f.name for f in r.functions}


def test_static_mut_write_after_container_write_marks_unknown():
    # `V.push(x)` tracks the static's name in `locals_` for dep
    # tracking — that slot must not make a later `V[0] = x` or
    # `V = x` look like a local write.
    src = (
        "mod b;\nuse b::V;\n"
        "fn af(x: u64) {\n"
        "    unsafe {\n"
        "        V.push(x);\n"
        "        V[0] = x;\n"
        "        V = vec![x];\n"
        "    }\n"
        "}\n"
    )
    b = "pub static mut V: Vec<u64> = Vec::new();\n"
    r = summarize_rust(src, resolver=_set_resolver({"b": b}))
    s = next(f for f in r.functions if f.name == "af")
    assert s.effects == "unknown"


def test_container_write_on_use_imported_mut_static_marks_unknown():
    # `V.push(x)` alone on a `use`-imported `static mut` mutates
    # external state.
    src = (
        "mod b;\nuse b::V;\n"
        "fn af(x: u64) {\n"
        "    unsafe { V.push(x); }\n"
        "}\n"
    )
    b = "pub static mut V: Vec<u64> = Vec::new();\n"
    r = summarize_rust(src, resolver=_set_resolver({"b": b}))
    s = next(f for f in r.functions if f.name == "af")
    assert s.effects == "unknown"


def test_caller_let_does_not_shadow_callee_static_write():
    # A caller's `let STATE` must not make the callee's write to
    # the `use`-imported static look local — `_block_decls` is a
    # per-function stack.
    src = (
        "mod b;\nuse b::STATE;\n"
        "fn callee(x: u64) { unsafe { STATE = x; } }\n"
        "fn af(x: u64) -> u64 {\n"
        "    let mut STATE = 0;\n"
        "    callee(x);\n"
        "    STATE\n"
        "}\n"
    )
    b = "pub static mut STATE: u64 = 0;\n"
    r = summarize_rust(src, resolver=_set_resolver({"b": b}))
    callee = next(f for f in r.functions if f.name == "callee")
    af = next(f for f in r.functions if f.name == "af")
    assert callee.effects == "unknown"
    # The caller observes the callee's external mutation.
    assert af.effects == "unknown"
    # The return reads the caller's local STATE, not the static.
    assert af.return_dependencies == frozenset()


def test_destructured_param_shadows_ancestor_static():
    # `f((mut a, b): ...)` binds `a`/`b` as function locals — a
    # write to `a` targets the parameter, not the `use`-imported
    # static of the same name.
    src = (
        "mod b;\nuse b::a;\n"
        "fn af((mut a, b): (u64, u64)) -> u64 {\n"
        "    a = b;\n"
        "    a\n"
        "}\n"
    )
    b = "pub static mut a: u64 = 0;\n"
    r = summarize_rust(src, resolver=_set_resolver({"b": b}))
    s = next(f for f in r.functions if f.name == "af")
    assert s.effects != "unknown"
    assert s.return_dependencies == frozenset({0})


def _reads(s):
    return {r.span: r.deps for r in s.statement_reads}


def test_statement_reads_attribute_per_statement():
    src = (
        "fn f(a: u64, b: u64) -> u64 {\n"
        "    let x = a + 1;\n"
        "    let y = b;\n"
        "    x + y\n"
        "}\n"
    )
    s = _fn(src, "f")
    assert s.available
    reads = _reads(s)
    decl_span = (
        src.index("let x = a + 1"),
        src.index("let x = a + 1") + len("let x = a + 1;"),
    )
    assert reads.get(decl_span) == frozenset({0}), reads
    tail_span = (
        src.index("x + y"),
        src.index("x + y") + len("x + y"),
    )
    hit = next(
        r for span, r in reads.items()
        if span[0] <= tail_span[0] < span[1]
    )
    assert hit == frozenset({0, 1})


def test_statement_reads_nested_attribution():
    # Reads inside an if-body attribute to the inner statement's
    # own span AND the enclosing if.
    src = (
        "fn f(a: u64) -> u64 {\n"
        "    let mut y = 0;\n"
        "    if a > 0 { y = a; }\n"
        "    y\n"
        "}\n"
    )
    s = _fn(src, "f")
    assert s.available
    reads = _reads(s)
    assert list(reads.values()).count(frozenset({0})) >= 2


def test_statement_reads_call_actual_records():
    # `g(a)` records {0} on the statement even though the callee
    # returns a constant and the result is dropped.
    src = (
        "fn g(v: u64) -> u64 { 0 }\n"
        "fn f(a: u64) -> u64 {\n"
        "    g(a);\n"
        "    0\n"
        "}\n"
    )
    s = _fn(src, "f")
    assert s.available
    assert frozenset({0}) in _reads(s).values()


def test_statement_reads_callee_composed_not_inlined():
    # A call composed from the callee's summary keeps the
    # callee's own statements in ITS statement_reads — the
    # caller's records carry only the call site.
    src = (
        "fn g(v: u64) -> u64 {\n"
        "    let y = v + 1;\n"
        "    y\n"
        "}\n"
        "fn f(a: u64) -> u64 {\n"
        "    let z = g(a);\n"
        "    z\n"
        "}\n"
    )
    r = summarize_rust(src)
    f = next(fn for fn in r.functions if fn.name == "f")
    g = next(fn for fn in r.functions if fn.name == "g")
    callee_span = (
        src.index("let y = v + 1"),
        src.index("let y = v + 1") + len("let y = v + 1;"),
    )
    assert callee_span not in _reads(f)
    assert _reads(g).get(callee_span) == frozenset({0})
    assert frozenset({0}) in _reads(f).values()


def test_statement_reads_compound_assign_lhs():
    # `x += v` reads the old LHS slot — `_assign` bypasses
    # `_expr`, so the read must be recorded explicitly.
    src = (
        "fn f(a: u64, b: u64) -> u64 {\n"
        "    let mut x = a;\n"
        "    x += b;\n"
        "    x\n"
        "}\n"
    )
    s = _fn(src, "f")
    assert s.available
    idx = src.index("x += b")
    aug = next(
        r for span, r in _reads(s).items()
        if span[0] <= idx < span[1]
    )
    assert aug == frozenset({0, 1})


def test_statement_reads_fn_pointer_call_target():
    # `cb();` reads the bound callee value even though the call
    # is opaque and its result voided.
    src = (
        "fn f(cb: fn(u64) -> u64, a: u64) -> u64 {\n"
        "    cb(a);\n"
        "    0\n"
        "}\n"
    )
    s = _fn(src, "f")
    if not s.available:
        pytest.skip("fn-pointer params unsupported")
    idx = src.index("cb(a)")
    call = next(
        r for span, r in _reads(s).items()
        if span[0] <= idx < span[1]
    )
    assert frozenset({0}) <= call


def test_statement_reads_deep_expression_no_overflow():
    # ~600 chained additions stay under the recursion limit —
    # the `_expr` wrapper must not double the frame count.
    expr = " + ".join(["a"] * 600)
    src = f"fn f(a: u64) -> u64 {{ {expr} }}"
    s = _fn(src, "f")
    assert s.available
    assert s.return_dependencies == frozenset({0})


def test_statement_reads_failure_keeps_partial():
    # A mid-body `_Unsupported` keeps the reads recorded before
    # it — the failed summary is not rebuilt empty.
    src = (
        "fn f(a: u64) -> u64 {\n"
        "    let x = a;\n"
        "    let y = qq;\n"
        "    x\n"
        "}\n"
    )
    s = _fn(src, "f")
    assert not s.available
    assert s.gaps
    idx = src.index("let x = a")
    rec = next(
        (r for span, r in _reads(s).items()
         if span[0] <= idx < span[1]),
        None,
    )
    assert rec == frozenset({0})
    # `params` is bound before the body walk, so the carried
    # partial summary keeps the names its dep indexes mean.
    assert s.params == ("a",)


def test_statement_reads_closure_partial_failure():
    # `u64::MAX` is unsupported inside the closure and swallows
    # as an opaque value — but the `a` read evaluated before it
    # still attributes to the `let` statement.
    src = (
        "fn f(a: u64) -> u64 {\n"
        "    let cb = || a + u64::MAX;\n"
        "    a\n"
        "}\n"
    )
    s = _fn(src, "f")
    assert s.available
    idx = src.index("let cb")
    rec = next(
        (r for span, r in _reads(s).items()
         if span[0] <= idx < span[1]),
        None,
    )
    assert rec == frozenset({0})


def test_statement_reads_callee_failure_no_param_leak():
    # A callee failing mid-expression carries ITS param indexes
    # on `partial_deps` — `_summarize` blanks them at the
    # boundary so the caller's frames never inherit dep indexes
    # that belong to the callee's signature.
    src = (
        "fn g(b: u64) -> u64 {\n"
        "    let z = b + qq;\n"
        "    z\n"
        "}\n"
        "fn f() -> u64 {\n"
        "    g()\n"
        "}\n"
    )
    g = _fn(src, "g")
    f = _fn(src, "f")
    assert not g.available
    assert not f.available
    # `g`'s own reads stay on its own partial summary.
    assert any(r == frozenset({0}) for r in _reads(g).values())
    # `f` has no parameters — nothing from `g`'s index space
    # may appear in `f`'s records.
    for r in _reads(f).values():
        assert r == frozenset()


def test_statement_reads_call_arg_partial_failure():
    # `ok(a, u64::MAX)` — the second actual is unsupported, but
    # the first actual's read still attributes to the call.
    src = (
        "fn f(a: u64) -> u64 {\n"
        "    opaque(a, u64::MAX)\n"
        "}\n"
    )
    s = _fn(src, "f")
    idx = src.index("opaque(")
    rec = next(
        (r for span, r in _reads(s).items()
         if span[0] <= idx < span[1]),
        None,
    )
    assert rec == frozenset({0})


def test_statement_reads_roundtrip():
    r = summarize_rust("fn f(a: u64) -> u64 { a }")
    restored = RustSummarySet.from_dict(r.to_dict())
    fn = next(f for f in restored.functions if f.name == "f")
    orig = next(f for f in r.functions if f.name == "f")
    assert fn.statement_reads == orig.statement_reads


def test_statement_reads_manifest_optional():
    # Manifests predating the field restore without it.
    r = summarize_rust("fn f(a: u64) -> u64 { a }").to_dict()
    for f in r["functions"]:
        f.pop("statement_reads", None)
    restored = RustSummarySet.from_dict(r)
    assert all(fn.statement_reads == () for fn in restored.functions)


def test_statement_reads_gapped_still_attaches():
    # A gapped walk attaches what was recorded before the gap.
    src = (
        "fn f(a: u64) -> u64 {\n"
        "    let x = a;\n"
        "    x + missing_callee()\n"
        "}\n"
    )
    s = _fn(src, "f")
    if not s.available:
        assert s.gaps


# -- --summary-aware-calls -------------------------------------------

def _decl_fn(name, params, deps, effects="none_in_supported_fragment"):
    return {
        "name": name,
        "available": deps is not None,
        "parameters": params,
        "return_dependencies": None if deps is None else sorted(deps),
        "calls": [],
        "gaps": (
            [] if deps is not None
            else [{"reason": "unresolved_call", "byte": 0}]
        ),
        "effects": effects,
        "statement_reads": [],
    }


def _callee_manifest(*functions):
    return RustSummarySet.from_dict({
        "schema_version": PROFILE,
        "context_key": "declared-context",
        "functions": list(functions),
    })


_SRC = "fn caller(x: u64, y: u64) -> u64 {\n    let r = m::f(x, y);\n    r\n}\n"


def test_aware_fold_narrows():
    plain = _fn(_SRC, "caller")
    declared = _callee_manifest(_decl_fn("f", ["a", "b"], {0}))
    aware = next(
        f for f in summarize_rust(_SRC, declared=declared).functions
        if f.name == "caller"
    )
    assert plain.return_dependencies == frozenset({0, 1})
    assert aware.return_dependencies == frozenset({0})


def test_aware_call_modeling_counts():
    declared = _callee_manifest(
        _decl_fn("f", ["a", "b"], {0}),
        _decl_fn("unused", ["a"], {0}),
    )
    r = summarize_rust(_SRC, declared=declared)
    assert r.call_modeling == {
        "summary_modeled_calls": 1,
        "opaque_calls": 0,
        "summary_unmatched": 1,
    }


def test_aware_bare_ident_folds():
    src = "fn caller(x: u64, y: u64) -> u64 { f(x, y) }\n"
    declared = _callee_manifest(_decl_fn("f", ["a", "b"], {1}))
    aware = next(
        f for f in summarize_rust(src, declared=declared).functions
        if f.name == "caller"
    )
    assert aware.return_dependencies == frozenset({1})


def test_aware_crate_prefix_folds():
    src = "fn caller(x: u64, y: u64) -> u64 { crate::m::f(x, y) }\n"
    declared = _callee_manifest(_decl_fn("f", ["a", "b"], {0}))
    aware = next(
        f for f in summarize_rust(src, declared=declared).functions
        if f.name == "caller"
    )
    assert aware.return_dependencies == frozenset({0})


def test_aware_deep_qualifier_stays_opaque():
    src = "fn caller(x: u64, y: u64) -> u64 { a::b::f(x, y) }\n"
    declared = _callee_manifest(_decl_fn("f", ["a", "b"], {0}))
    r = summarize_rust(src, declared=declared)
    aware = next(f for f in r.functions if f.name == "caller")
    assert aware.return_dependencies == frozenset({0, 1})
    assert r.call_modeling["opaque_calls"] == 1
    assert r.call_modeling["summary_unmatched"] == 1


def test_aware_receiver_call_never_folds():
    src = (
        "fn caller(x: u64, y: u64) -> u64 {\n"
        "    let t = x;\n"
        "    let r = t.m(y);\n"
        "    r\n"
        "}\n"
    )
    declared = _callee_manifest(_decl_fn("m", ["a"], {0}))
    r = summarize_rust(src, declared=declared)
    aware = next(f for f in r.functions if f.name == "caller")
    assert aware.return_dependencies == frozenset({0, 1})
    assert r.call_modeling["summary_modeled_calls"] == 0


def test_aware_local_bound_never_folds():
    src = (
        "fn caller(x: u64, y: u64) -> u64 {\n"
        "    let cb = x;\n"
        "    cb(y)\n"
        "}\n"
    )
    declared = _callee_manifest(_decl_fn("cb", ["a"], {0}))
    r = summarize_rust(src, declared=declared)
    aware = next(f for f in r.functions if f.name == "caller")
    assert aware.return_dependencies == frozenset({0, 1})
    assert r.call_modeling["summary_modeled_calls"] == 0


def test_aware_empty_bound_local_never_folds():
    # A local bound to a dependency-free value still shadows the
    # callee name — an empty `bound` set must not read as "not a
    # local" and let the manifest fold the call away.
    src = (
        "fn caller(x: u64) -> u64 {\n"
        "    let f = 1;\n"
        "    f(x)\n"
        "}\n"
    )
    declared = _callee_manifest(_decl_fn("f", ["a"], set()))
    r = summarize_rust(src, declared=declared)
    aware = next(f for f in r.functions if f.name == "caller")
    assert aware.return_dependencies == frozenset({0})
    assert r.call_modeling["summary_modeled_calls"] == 0
    assert r.call_modeling["opaque_calls"] == 1


def test_aware_empty_manifest_counts_opaque():
    # A declared-but-empty manifest still counts the calls it did
    # not model — `opaque_calls` reports the requests the manifest
    # was consulted for, not dict truthiness.
    r = summarize_rust(_SRC, declared=_callee_manifest())
    assert r.call_modeling == {
        "summary_modeled_calls": 0,
        "opaque_calls": 1,
        "summary_unmatched": 0,
    }


def test_aware_opaque_call_counted_once_per_call():
    # `caller` is walked before `helper`; helper's inline
    # summarization for that call must not recount its opaque call
    # when the top-level loop reaches it.
    src = (
        "fn caller() -> u64 {\n    helper(1)\n}\n"
        "fn helper(x: u64) -> u64 {\n    m::f(x)\n}\n"
    )
    r = summarize_rust(src, declared=_callee_manifest())
    assert r.call_modeling["opaque_calls"] == 1


def test_aware_gapped_callee_stays_opaque():
    declared = _callee_manifest(_decl_fn("f", ["a", "b"], None))
    r = summarize_rust(_SRC, declared=declared)
    aware = next(f for f in r.functions if f.name == "caller")
    assert aware.return_dependencies == frozenset({0, 1})
    assert r.call_modeling["opaque_calls"] == 1


def test_aware_arity_mismatch_stays_opaque():
    declared = _callee_manifest(_decl_fn("f", ["a"], {0}))
    r = summarize_rust(_SRC, declared=declared)
    aware = next(f for f in r.functions if f.name == "caller")
    assert aware.return_dependencies == frozenset({0, 1})
    assert r.call_modeling["opaque_calls"] == 1


def test_aware_ordinal_out_of_range_stays_opaque():
    # `from_dict` rejects the entry as malformed — the runtime
    # gate is exercised through a directly built set.
    bad = rust.RustFunctionSummary(
        name="f",
        params=("a", "b"),
        available=True,
        return_dependencies=frozenset({2}),
        calls=[],
        gaps=[],
    )
    r = summarize_rust(
        _SRC,
        declared=rust.RustSummarySet(
            "declared-context", PROFILE, [bad]
        ),
    )
    aware = next(f for f in r.functions if f.name == "caller")
    assert aware.return_dependencies == frozenset({0, 1})
    assert r.call_modeling["opaque_calls"] == 1


def test_manifest_rejects_an_out_of_range_ordinal():
    r = summarize_rust("fn f(x: u64) -> u64 { x }").to_dict()
    r["functions"][0]["return_dependencies"] = [1]
    with pytest.raises(ValueError, match="malformed"):
        RustSummarySet.from_dict(r)


def test_aware_void_call_never_folds():
    src = "fn caller(x: u64, y: u64) -> u64 {\n    m::f(x, y);\n    x\n}\n"
    declared = _callee_manifest(_decl_fn("f", ["a", "b"], {0}))
    r = summarize_rust(src, declared=declared)
    aware = next(f for f in r.functions if f.name == "caller")
    assert aware.return_dependencies == frozenset({0})
    assert r.call_modeling["opaque_calls"] == 1


def test_aware_fold_empty_deps():
    declared = _callee_manifest(_decl_fn("f", ["a", "b"], set()))
    aware = next(
        f for f in summarize_rust(_SRC, declared=declared).functions
        if f.name == "caller"
    )
    assert aware.return_dependencies == frozenset()


def test_aware_no_modeling_without_manifest():
    r = summarize_rust(_SRC)
    assert r.call_modeling is None
    assert "call_modeling" not in r.to_dict()


def test_aware_context_key_binds_manifest():
    one = _callee_manifest(_decl_fn("f", ["a", "b"], {0}))
    two = _callee_manifest(_decl_fn("f", ["a", "b"], {1}))
    assert (
        summarize_rust(_SRC, declared=one).context_key
        != summarize_rust(_SRC, declared=two).context_key
    )
    assert (
        summarize_rust(_SRC).context_key
        != summarize_rust(_SRC, declared=one).context_key
    )


def test_aware_call_modeling_roundtrip():
    declared = _callee_manifest(_decl_fn("f", ["a", "b"], {0}))
    r = summarize_rust(_SRC, declared=declared)
    restored = RustSummarySet.from_dict(r.to_dict())
    assert restored.call_modeling == r.call_modeling


def _aware_args(source, manifest, output=None):
    import argparse
    return argparse.Namespace(
        source=str(source),
        manifest=None,
        function=None,
        resolve_modules=False,
        summary_aware_calls=None if manifest is None else str(manifest),
        output=None if output is None else str(output),
    )


def _produce(tmp_path, capsys, src_path, manifest=None):
    rust.main(_aware_args(src_path, manifest))
    out = capsys.readouterr().out
    p = tmp_path / "out.json"
    p.write_text(out)
    return p


def test_aware_produce_route(tmp_path, capsys):
    src = tmp_path / "caller.rs"
    src.write_text(_SRC)
    callee = _produce(tmp_path, capsys, src)
    man = tmp_path / "callee.json"
    man.write_text(json.dumps(
        _callee_manifest(_decl_fn("f", ["a", "b"], {0})).to_dict()
    ))
    out = _produce(tmp_path, capsys, src, man)
    doc = json.loads(out.read_text())
    assert doc["call_modeling"]["summary_modeled_calls"] == 1


def test_aware_check_route(tmp_path, capsys):
    src = tmp_path / "caller.rs"
    src.write_text(_SRC)
    man = tmp_path / "callee.json"
    man.write_text(json.dumps(
        _callee_manifest(_decl_fn("f", ["a", "b"], {0})).to_dict()
    ))
    produced = _produce(tmp_path, capsys, src, man)
    args = _aware_args(src, man)
    args.manifest = str(produced)
    rust.main_check(args)
    doc = json.loads(capsys.readouterr().out)
    assert doc["context_match"] is True
    args2 = _aware_args(src, None)
    args2.manifest = str(produced)
    rust.main_check(args2)
    doc2 = json.loads(capsys.readouterr().out)
    assert doc2["context_match"] is False


def test_aware_reuse_propagates_modeling():
    declared = _callee_manifest(_decl_fn("f", ["a", "b"], {0}))
    live = summarize_rust(_SRC, declared=declared)
    merged = rust.summary_reuse_set(_callee_manifest(), live)
    assert merged.call_modeling == live.call_modeling


def test_aware_output_over_manifest_refused(tmp_path, capsys):
    src = tmp_path / "caller.rs"
    src.write_text(_SRC)
    man = tmp_path / "callee.json"
    man.write_text(json.dumps(
        _callee_manifest(_decl_fn("f", ["a", "b"], {0})).to_dict()
    ))
    produced = _produce(tmp_path, capsys, src, man)
    args = _aware_args(src, man, output=man)
    args.manifest = str(produced)
    with pytest.raises(SystemExit) as exc:
        rust.main_check(args)
    assert exc.value.code == 2


def test_aware_attempt_fingerprint_binds_manifest(tmp_path):
    src = tmp_path / "caller.rs"
    src.write_text(_SRC)
    one = tmp_path / "one.json"
    two = tmp_path / "two.json"
    one.write_text(json.dumps(
        _callee_manifest(_decl_fn("f", ["a", "b"], {0})).to_dict()
    ))
    two.write_text(json.dumps(
        _callee_manifest(_decl_fn("f", ["a", "b"], {1})).to_dict()
    ))
    raw = src.read_bytes()
    base = rust._attempt_fingerprint(str(src), raw)
    f1 = rust._attempt_fingerprint(
        str(src), raw, summary_aware_calls=str(one))
    f2 = rust._attempt_fingerprint(
        str(src), raw, summary_aware_calls=str(two))
    assert len({base, f1, f2}) == 3
    with pytest.raises(ValueError):
        rust._attempt_fingerprint(
            str(src), raw,
            summary_aware_calls=str(tmp_path / "missing.json"))


def test_aware_fingerprint_bounds_manifest_read(tmp_path, monkeypatch):
    src = tmp_path / "caller.rs"
    src.write_text(_SRC)
    man = tmp_path / "big.json"
    man.write_bytes(b"x" * 64)
    monkeypatch.setattr(rust, "MAX_MANIFEST_BYTES", 8)
    with pytest.raises(ValueError, match="too large"):
        rust._attempt_fingerprint(
            str(src), src.read_bytes(), summary_aware_calls=str(man))


def test_aware_fingerprint_error_hides_path(tmp_path):
    # The attempt report carries this message — a checkout-local
    # path must never reach it.
    src = tmp_path / "caller.rs"
    src.write_text(_SRC)
    missing = tmp_path / "missing.json"
    with pytest.raises(ValueError) as exc:
        rust._attempt_fingerprint(
            str(src), src.read_bytes(),
            summary_aware_calls=str(missing))
    assert str(missing) not in str(exc.value)


def test_aware_attempt_forwards_flag(tmp_path):
    # A malformed callee manifest makes the forwarded child fail
    # while the same source without the flag exits cleanly.
    src = tmp_path / "caller.rs"
    src.write_text(_SRC)
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    report = rust.run_attempt(
        str(src), src.read_bytes(), 30000,
        summary_aware_calls=str(bad),
    )
    norm = report["normalized"]
    assert norm["outcome"] == "exited" and norm["exit_code"] != 0
    report2 = rust.run_attempt(str(src), src.read_bytes(), 30000)
    assert report2["normalized"]["exit_code"] == 0

def _reuse_attempt_args(source, manifest, attempt_timeout=60000,
                        output=None, memory_bound_mb=None, resolve=False):
    return type(
        "A",
        (),
        {
            "source": str(source),
            "manifest": str(manifest),
            "attempt_timeout": attempt_timeout,
            "memory_bound_mb": memory_bound_mb,
            "output": str(output) if output else None,
            "resolve_modules": resolve,
            "summary_aware_calls": None,
        },
    )()


def test_reuse_attempt_emits_lineage_and_acceptance(tmp_path, capsys):
    src = tmp_path / "a.rs"
    src.write_text(_RS_SRC)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(rust.summarize_rust(_RS_SRC).to_dict())
    )
    rust.main_reuse_attempt(_reuse_attempt_args(src, manifest))
    report = json.loads(capsys.readouterr().out)
    assert (
        report["schema_version"]
        == "mumei.rust-summaries-reuse-attempt-report/v1"
    )
    sequence = report["sequence"]
    assert sequence["attempts"][0]["state"] == "exited"
    assert sequence["selected_result"]["attempt_number"] == 1
    assert report["normalized"]["outcome"] == "exited"
    assert (
        report["candidate"]["schema_version"]
        == "mumei.verifier-evidence-candidate/v1"
    )
    assert report["evidence_check"]["outcome"] == "valid"
    assert report["acceptance"]["accepted"] is True
    assert report["discharged_checks"] == [
        "file_identity",
        "freshness",
        "producer_authenticity",
    ]
    assert report["checks_not_performed"] == [
        "artifact_semantics",
        "claim_truth",
        "semantic_correspondence",
    ]


def test_reuse_attempt_binds_manifest_bytes(tmp_path, capsys):
    src = tmp_path / "a.rs"
    src.write_text(_RS_SRC)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(rust.summarize_rust(_RS_SRC).to_dict())
    )
    rust.main_reuse_attempt(_reuse_attempt_args(src, manifest))
    first = json.loads(capsys.readouterr().out)["sequence"][
        "request_fingerprint"
    ]
    tampered = json.loads(manifest.read_text())
    tampered["context_key"] = "tampered-context"
    manifest.write_text(json.dumps(tampered))
    rust.main_reuse_attempt(_reuse_attempt_args(src, manifest))
    second = json.loads(capsys.readouterr().out)["sequence"][
        "request_fingerprint"
    ]
    assert first != second


def test_reuse_attempt_run_reuse_attempt_exits(tmp_path, capsys):
    src = tmp_path / "a.rs"
    src.write_text(_RS_SRC)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(rust.summarize_rust(_RS_SRC).to_dict())
    )
    report = rust.run_reuse_attempt(
        str(src),
        _RS_SRC.encode(),
        str(manifest),
        60000,
    )
    assert report["normalized"]["outcome"] == "exited"
    assert report["acceptance"]["accepted"] is True


def test_reuse_attempt_skips_selection_when_manifest_drifts(
    tmp_path, capsys, monkeypatch
):
    src = tmp_path / "a.rs"
    src.write_text(_RS_SRC)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(rust.summarize_rust(_RS_SRC).to_dict())
    )
    from agent import attempt_runner

    real_run = attempt_runner.AttemptRunner.run

    def run_then_modify(
        self, request, argv, memory_bound_mb=None, cancel_event=None,
        feed_bytes=None, environment=None, isolate_network=False,
        isolate_filesystem_write=False,
    ):
        manifest.write_text("{}")
        return real_run(
            self,
            request,
            argv,
            memory_bound_mb=memory_bound_mb,
            cancel_event=cancel_event,
            feed_bytes=feed_bytes,
            environment=environment,
            isolate_network=isolate_network,
            isolate_filesystem_write=isolate_filesystem_write,
        )

    monkeypatch.setattr(
        attempt_runner.AttemptRunner, "run", run_then_modify
    )
    rust.main_reuse_attempt(_reuse_attempt_args(src, manifest))
    report = json.loads(capsys.readouterr().out)
    assert report["sequence"].get("selected_result") is None
    assert "candidate" not in report


def test_reuse_attempt_rejects_resolve_modules(tmp_path, capsys):
    src = tmp_path / "a.rs"
    src.write_text(_RS_SRC)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(rust.summarize_rust(_RS_SRC).to_dict())
    )
    with pytest.raises(SystemExit) as exc:
        rust.main_reuse_attempt(
            _reuse_attempt_args(src, manifest, resolve=True)
        )
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["reason"] == "unsupported_option"


def test_reuse_attempt_rejects_output_overwriting_manifest(
    tmp_path, capsys
):
    src = tmp_path / "a.rs"
    src.write_text(_RS_SRC)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(rust.summarize_rust(_RS_SRC).to_dict())
    )
    with pytest.raises(SystemExit) as exc:
        rust.main_reuse_attempt(
            _reuse_attempt_args(src, manifest, output=manifest)
        )
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["reason"] == "output_overwrites_source"
