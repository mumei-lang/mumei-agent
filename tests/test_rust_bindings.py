import subprocess
import sys

import pytest

from agent.lexical_bindings import LexicalReportError, load_lexical_report
from agent.rust_bindings import PROFILE, build_rust_bindings as _build_rust_bindings

def build_rust_bindings(source, *, pointer_width):
    report = _build_rust_bindings(source, pointer_width=pointer_width)
    reference_keys = [
        (reference.span, reference.binding_id, reference.kind)
        for reference in report.references
    ]
    assert len(reference_keys) == len(set(reference_keys)), source
    call_spans = [call.span for call in report.calls]
    assert len(call_spans) == len(set(call_spans)), source
    restored = load_lexical_report(
        report.to_json(),
        source,
        profile=PROFILE,
        target={"pointer_width": pointer_width},
    )
    assert restored.to_json() == report.to_json(), source
    return report

def _bindings(report, name, kind=None):
    return sorted(
        (
            binding
            for binding in report.bindings
            if binding.name == name and (kind is None or binding.kind == kind)
        ),
        key=lambda binding: binding.span.start,
    )

def _refs(report, source, name):
    raw = source.encode()
    return sorted(
        (
            ref
            for ref in report.references
            if raw[ref.span.start : ref.span.end].decode() == name
        ),
        key=lambda ref: (ref.span.start, ref.kind),
    )

def _unresolved(report, name=None, reason=None):
    return [
        item
        for item in report.unresolved
        if (name is None or item.name == name) and (reason is None or item.reason == reason)
    ]

def _call(report, source, call_text):
    raw = source.encode()
    return next(
        call
        for call in report.calls
        if raw[call.span.start : call.span.end].decode() == call_text
    )

def test_shadowing_initializer_resolves_outer_binding_and_spans_are_utf8_bytes():
    source = "fn f(){ let x = 1; let x = x + 1; x; }"
    report = build_rust_bindings(source, pointer_width=64)
    first, second = _bindings(report, "x", "local")
    refs = _refs(report, source, "x")
    assert len((first, second)) == 2
    assert [ref.binding_id for ref in refs] == [first.id, second.id]

    unicode_source = "fn f(){ let λ = 1; λ; }"
    unicode_report = build_rust_bindings(unicode_source, pointer_width=64)
    for binding in _bindings(unicode_report, "λ", "local"):
        assert unicode_source.encode()[binding.span.start : binding.span.end] == "λ".encode()
    for reference in _refs(unicode_report, unicode_source, "λ"):
        assert unicode_source.encode()[reference.span.start : reference.span.end] == "λ".encode()

def test_reassignment_is_write_and_compound_assignment_is_read_write():
    source = "fn f(){ let mut x = 1; x = 2; x += 3; x; }"
    report = build_rust_bindings(source, pointer_width=64)
    binding = _bindings(report, "x", "local")[0]
    refs = _refs(report, source, "x")
    assert binding.mutable
    assert [ref.kind for ref in refs] == ["write", "read", "write", "read"]
    assert all(ref.binding_id == binding.id for ref in refs)
    name_source = "fn f(){ let mutation = 1; }"
    assert not _bindings(
        build_rust_bindings(name_source, pointer_width=64), "mutation", "local"
    )[0].mutable

def test_dereference_compound_assignment_only_reads_the_pointer_binding():
    source = "fn f(mut pointer: &mut i32){ *pointer += 1; }"
    report = build_rust_bindings(source, pointer_width=64)
    binding = _bindings(report, "pointer", "parameter")[0]
    refs = _refs(report, source, "pointer")
    assert [ref.kind for ref in refs] == ["read"]
    assert all(ref.binding_id == binding.id for ref in refs)

@pytest.mark.parametrize(
    ("place", "root", "expected", "index_read", "compound"),
    [
        ("*p", "p", ["read"], False, False),
        ("*p", "p", ["read"], False, True),
        ("s.0", "s", ["write"], False, False),
        ("s.f", "s", ["write"], False, False),
        ("a[i]", "a", ["write"], True, False),
        ("s.f.g", "s", ["write"], False, False),
        ("s.f", "s", ["read", "write"], False, True),
        ("a[i]", "a", ["read", "write"], True, True),
        ("a[i].f", "a", ["write"], True, False),
        ("a[i][j]", "a", ["read", "write"], True, True),
        ("(*p).f", "p", ["read"], False, False),
        ("p.as_mut().f", "p", ["read"], False, False),
    ],
)
def test_place_assignments_reference_the_binding_root(
    place, root, expected, index_read, compound
):
    operator = "+=" if compound else "="
    value = "1" if compound else "2"
    source = (
        "struct S { f: i32 } "
        "fn f(mut s:S, mut a:[i32;4], mut p:&mut S, i:usize, j:usize) { "
        f"{place} {operator} {value}; }}"
    )
    report = build_rust_bindings(source, pointer_width=64)
    assert [ref.kind for ref in _refs(report, source, root)] == expected
    assert bool(_refs(report, source, "i")) is index_read
    if index_read:
        assert [ref.kind for ref in _refs(report, source, "i")] == ["read"]

def test_nested_place_indexes_are_traversed_for_reads_and_calls():
    source = (
        "struct S { f: [i32;4] } fn index()->usize {0} "
        "fn f(mut s:S) { s.f[index()] += 1; }"
    )
    report = build_rust_bindings(source, pointer_width=64)
    assert [ref.kind for ref in _refs(report, source, "s")] == ["read", "write"]
    assert _call(report, source, "index()").kind == "direct_local"

def test_nested_place_index_names_remain_explicitly_unresolved():
    source = "fn f(mut a:[i32;4]) { a[missing].field = 1; }"
    report = build_rust_bindings(source, pointer_width=64)
    assert _unresolved(report, "missing", "unknown_name")

def test_assignment_to_const_is_a_read_with_an_unsupported_gap():
    source = "const K:u8=0; fn f(){ K = 1; }"
    report = build_rust_bindings(source, pointer_width=64)
    assert [ref.kind for ref in _refs(report, source, "K")] == ["read"]
    assert any(g.reason == "unsupported_syntax" for g in report.gaps)
    assert not report.complete

def test_block_scope_and_nested_item_boundary_are_explicit():
    source = "fn f(x:i32){ { let y = 1; } y; fn nested(){ x; } }"
    report = build_rust_bindings(source, pointer_width=64)
    assert _unresolved(report, "y", "unknown_name")
    assert _unresolved(report, "x", "item_boundary")

def test_items_are_visible_before_declaration_and_calls_are_conservative():
    source = "fn first(){ later(); } fn later(){}"
    report = build_rust_bindings(source, pointer_width=64)
    call = _call(report, source, "later()")
    later = _bindings(report, "later", "function")[0]
    assert call.kind == "direct_local"
    assert call.target == later.id
    assert later.id.endswith(":0:0")
    assert _refs(report, source, "later")[0].kind == "call"

def test_inline_module_does_not_resolve_outer_module_items():
    source = "fn outer(){} mod inner { fn f(){ outer(); } }"
    report = build_rust_bindings(source, pointer_width=64)
    assert _unresolved(report, "outer", "module_boundary")

def test_closure_captures_lexically_and_does_not_claim_call_owner():
    source = "fn target(x:i32){} fn f(x:i32){ let c = |q| target(q + x); c(1); }"
    report = build_rust_bindings(source, pointer_width=64)
    target_call = _call(report, source, "target(q + x)")
    closure_call = _call(report, source, "c(1)")
    assert target_call.owner == ""
    assert target_call.kind == "direct_local"
    assert closure_call.kind == "opaque_value"
    assert closure_call.owner == _bindings(report, "f", "function")[0].id
    captured_parameter = _bindings(report, "x", "parameter")[-1]
    assert any(
        ref.binding_id == captured_parameter.id
        for ref in _refs(report, source, "x")
    )

def test_match_const_patterns_imported_names_and_or_patterns():
    source = "const K:u8=1; fn f(v:u8){ match v { K => (), Some(x) | Other(x) => { x; }, _ => () } }"
    report = build_rust_bindings(source, pointer_width=64)
    const = _bindings(report, "K", "const")[0]
    assert any(ref.binding_id == const.id for ref in _refs(report, source, "K"))
    assert len(_bindings(report, "x", "local")) == 1
    assert not any(g.reason == "or_pattern_mismatch" for g in report.gaps)

    mismatch = build_rust_bindings(
        "fn f(v:u8){ match v { A(x) | B(y) => (), _ => () } }",
        pointer_width=64,
    )
    assert any(g.reason == "or_pattern_mismatch" for g in mismatch.gaps)

    imported_source = "use foo::K; fn f(v:u8){ match v { K => (), _ => () } }"
    imported = build_rust_bindings(imported_source, pointer_width=64)
    assert any(g.reason == "pattern_name_ambiguous" for g in imported.gaps)
    later_use_source = (
        "use external::K; fn f(value: Option<i32>) { match value { K => K, _ => 0 }; }"
    )
    later_use = build_rust_bindings(later_use_source, pointer_width=64)
    assert _unresolved(later_use, "K", "unknown_name")

@pytest.mark.parametrize(
    ("source", "local_names"),
    [
        ("fn f(value:i32){ let _ = value; }", []),
        ("fn f(pair:(i32,i32)){ let (head, _) = pair; head; }", ["head"]),
        ("fn f(array:[i32;2]){ let [_, item] = array; item; }", ["item"]),
        ("fn f(pair:(i32,i32)){ let (head, ..) = pair; head; }", ["head"]),
        ("fn f(array:[i32;3]){ let [head, ..] = array; head; }", ["head"]),
        (
            "struct S { a:i32 } fn f(value:S){ let S { a: _, .. } = value; }",
            [],
        ),
        ("fn f(value:i32){ let Some(_) = value; }", []),
    ],
)
def test_wildcard_and_rest_patterns_bind_only_named_identifiers(source, local_names):
    report = build_rust_bindings(source, pointer_width=64)
    assert {binding.name for binding in report.bindings if binding.kind == "local"} == set(
        local_names
    )
    assert not any(g.reason == "unsupported_syntax" for g in report.gaps)
    if "Some(_)" in source:
        assert _unresolved(report, "Some", "prelude_name")

def test_literal_range_and_captured_range_patterns_are_supported():
    source = (
        "fn f(value:i32){ match value { -1 => (), 1.5 => (), "
        "1..=5 => (), ..=5 => (), 1.. => (), "
        "'a'..='z' => (), 'x' => (), \"text\" => (), true => (), "
        "w @ 2..=3 => w, _ => () } }"
    )
    report = build_rust_bindings(source, pointer_width=64)
    assert not report.gaps
    assert len(_bindings(report, "w", "local")) == 1
    assert {
        binding.name for binding in report.bindings if binding.kind == "local"
    } == {"w"}
    assert any(ref.binding_id == _bindings(report, "w", "local")[0].id for ref in _refs(report, source, "w"))
    assert report.complete

def test_range_pattern_path_bounds_resolve_or_remain_unresolved():
    source = "const K:i32=0; const L:i32=5; fn f(v:i32){ match v { K..=L => (), _ => () } }"
    report = build_rust_bindings(source, pointer_width=64)
    assert [ref.binding_id for ref in _refs(report, source, "K")] == [
        _bindings(report, "K", "const")[0].id
    ]
    assert [ref.binding_id for ref in _refs(report, source, "L")] == [
        _bindings(report, "L", "const")[0].id
    ]
    assert not report.gaps

@pytest.mark.parametrize(
    ("source", "name", "reason"),
    [
        (
            "mod m { const K:i32=0; } fn f(v:i32){ match v { m::J..=m::J => (), _ => () } }",
            "m::J",
            "qualified_path",
        ),
        (
            "fn f(v:i32){ match v { Some..=None => (), _ => () } }",
            "Some",
            "prelude_name",
        ),
    ],
)
def test_unresolved_range_path_bounds_are_not_bound(source, name, reason):
    report = build_rust_bindings(source, pointer_width=64)
    assert _unresolved(report, name, reason)
    assert not report.gaps

@pytest.mark.parametrize(
    ("source", "constructor", "binding_kind", "reason"),
    [
        (
            "struct S { a:i32 } fn f(value:S){ let S { a } = value; a; }",
            "S",
            "struct",
            None,
        ),
        (
            "struct S(i32); fn f(value:S){ match value { S(x) => x } }",
            "S",
            "struct",
            None,
        ),
        (
            "fn f(value:i32){ match value { Some(_) => (), Ok(_) => (), Err(_) => (), None => () } }",
            "Some",
            None,
            "prelude_name",
        ),
        (
            "fn f(value:i32){ match value { Some { field: _, .. } => (), _ => () } }",
            "Some",
            None,
            "prelude_name",
        ),
    ],
)

def test_pattern_constructor_paths_are_referenced_or_explicitly_unresolved(
    source, constructor, binding_kind, reason
):
    report = build_rust_bindings(source, pointer_width=64)
    if binding_kind is not None:
        binding = _bindings(report, constructor, binding_kind)[0]
        assert any(ref.binding_id == binding.id for ref in _refs(report, source, constructor))
    else:
        assert _unresolved(report, constructor, reason)
        if constructor == "Some" and "Ok(_)" in source:
            for name in ("Some", "Ok", "Err", "None"):
                assert _unresolved(report, name, "prelude_name")

def test_pattern_enum_variant_path_resolves_to_the_member():
    source = "enum E { V(i32) } fn f(value:E){ match value { E::V(x) => x } }"
    report = build_rust_bindings(source, pointer_width=64)
    variant = _bindings(report, "V", "enum_member")[0]
    assert any(
        ref.binding_id == variant.id
        and source[ref.span.start:ref.span.end] == "V"
        and ref.span.start > source.index("match")
        for ref in report.references
    )
    assert not _unresolved(report, "E::V", "qualified_path")

def test_match_guards_resolve_inside_the_arm_after_pattern_bindings():
    source = (
        "const K:i32=1; "
        "fn f(n:i32, flag:bool){ "
        "match n { n if n > K => n, x if flag => x, _ => 0 } }"
    )
    report = build_rust_bindings(source, pointer_width=64)
    parameter_n = _bindings(report, "n", "parameter")[0]
    arm_n = _bindings(report, "n", "local")[0]
    flag = _bindings(report, "flag", "parameter")[0]
    assert [ref.binding_id for ref in _refs(report, source, "n")] == [
        parameter_n.id,
        arm_n.id,
        arm_n.id,
    ]
    assert [ref.binding_id for ref in _refs(report, source, "flag")] == [flag.id]
    assert len(_bindings(report, "x", "local")) == 1
    assert len(_refs(report, source, "x")) == 1

def test_unresolved_match_guard_does_not_create_a_pattern_binding():
    source = "fn f(n:i32){ match n { x if missing => x, _ => 0 } }"
    report = build_rust_bindings(source, pointer_width=64)
    assert len(_bindings(report, "x", "local")) == 1
    assert _unresolved(report, "missing", "unknown_name")

@pytest.mark.parametrize(
    "attribute",
    [
        "allow(dead_code)",
        "warn(dead_code)",
        "deny(dead_code)",
        "forbid(dead_code)",
        "expect(dead_code)",
        "deprecated",
        "must_use",
        "inline",
        "cold",
        "doc = \"text\"",
        "repr(C)",
        "non_exhaustive",
        "track_caller",
        "no_mangle",
        "export_name = \"f\"",
        "link_name = \"f\"",
        "link_section = \".text\"",
        "used",
        "test",
        "ignore",
        "should_panic",
        "automatically_derived",
        "rustfmt::skip",
        "clippy::some_lint",
    ],
)
def test_allowlisted_attributes_do_not_create_gaps(attribute):
    report = build_rust_bindings(f"#[{attribute}] fn f(){{}}", pointer_width=64)
    assert not report.gaps

def test_derive_attribute_policy_and_conditional_compilation_gaps():
    standard = build_rust_bindings(
        "#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Default, "
        "std::fmt::Debug, core::cmp::Eq)] struct S;",
        pointer_width=64,
    )
    assert not standard.gaps
    nonstandard = build_rust_bindings(
        "#[derive(Serialize)] struct S;", pointer_width=64
    )
    assert [gap.reason for gap in nonstandard.gaps] == ["macro_invocation"]
    for attribute in ("cfg(feature=\"x\")", "cfg_attr(feature=\"x\", allow(dead_code))"):
        source = f"#[{attribute}] fn f(){{}}"
        report = build_rust_bindings(source, pointer_width=64)
        assert [gap.reason for gap in report.gaps] == ["conditional_compilation"]
        assert not report.complete
        assert load_lexical_report(
            report.to_json(), source, profile=PROFILE, target={"pointer_width": 64}
        ).to_json() == report.to_json()
    inner_conditional = build_rust_bindings(
        "#![cfg(feature=\"x\")] fn f(){}", pointer_width=64
    )
    assert [gap.reason for gap in inner_conditional.gaps] == [
        "conditional_compilation"
    ]
    unknown = build_rust_bindings("#[my_proc_macro] fn f(){}", pointer_width=64)
    assert [gap.reason for gap in unknown.gaps] == ["macro_invocation"]
    inner_unknown = build_rust_bindings("#![my_proc_macro] fn f(){}", pointer_width=64)
    assert [gap.reason for gap in inner_unknown.gaps] == ["macro_invocation"]

def test_inner_and_nested_attributes_are_classified():
    source = (
        "#![allow(dead_code)] struct S { #[unknown_field] value:i32 } "
        "fn f(#[unknown_parameter] value:i32) { "
        "#[unknown_statement] let local = value; "
        "#[unknown_expression] { local; } "
        "match value { #[unknown_arm] _ => () } }"
    )
    report = build_rust_bindings(source, pointer_width=64)
    assert [gap.reason for gap in report.gaps] == [
        "macro_invocation",
        "macro_invocation",
        "macro_invocation",
        "macro_invocation",
        "macro_invocation",
    ]

def test_if_while_for_and_let_else_scopes():
    source = """
fn f(xs: Vec<u8>) {
    if let Some(a) = get() { a; } else { a; }
    while let Some(b) = get() { b; }
    for item in item { item; }
    let Some(c) = get() else { c; };
    c;
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    assert _unresolved(report, "a", "unknown_name")
    assert _unresolved(report, "c", "unknown_name")
    assert _unresolved(report, "item", "unknown_name")
    assert any(g.reason == "pattern_name_ambiguous" for g in report.gaps) is False
    assert len(_bindings(report, "b", "local")) == 1

@pytest.mark.parametrize(
    ("width", "typ", "kind", "bits", "signed"),
    [
        (64, "i8", "int", 8, True), (64, "i16", "int", 16, True),
        (64, "i32", "int", 32, True), (64, "i64", "int", 64, True),
        (64, "i128", "int", 128, True), (64, "u8", "int", 8, False),
        (64, "u16", "int", 16, False), (64, "u32", "int", 32, False),
        (64, "u64", "int", 64, False), (64, "u128", "int", 128, False),
        (16, "isize", "int", 16, True), (32, "isize", "int", 32, True),
        (64, "isize", "int", 64, True), (16, "usize", "int", 16, False),
        (32, "usize", "int", 32, False), (64, "usize", "int", 64, False),
        (64, "f32", "float", 32, None), (64, "f64", "float", 64, None),
        (64, "bool", "bool", 1, None), (64, "char", "char", 32, None),
    ],
)
def test_explicit_primitive_type_facts(width, typ, kind, bits, signed):
    report = build_rust_bindings(f"fn f(x: {typ}) {{ let y: {typ} = x; }}", pointer_width=width)
    assert _bindings(report, "x", "parameter")[0].type.kind == kind
    fact = _bindings(report, "x", "parameter")[0].type
    assert (fact.bit_width, fact.signed) == (bits, signed)
    assert _bindings(report, "y", "local")[0].type == fact

def test_alias_chains_named_local_types_and_unsupported_types_stay_unknown():
    source = """
type A = u8;
type B = A;
struct S;
enum E { Value }
fn f(a:B, s:S, e:E) { let x: B = 1; let r: &u8 = &x; let t: (u8,u8)=(1,2); let z=[1u8;4]; let n = 1; }
"""
    report = build_rust_bindings(source, pointer_width=64)
    alias = _bindings(report, "B", "type_alias")[0]
    assert _bindings(report, "a", "parameter")[0].type.type_id == alias.id
    assert _bindings(report, "s", "parameter")[0].type.kind == "named"
    assert _bindings(report, "e", "parameter")[0].type.kind == "named"
    assert _bindings(report, "x", "local")[0].type.type_id == alias.id
    for name in ("r", "t", "z", "n"):
        assert _bindings(report, name, "local")[0].type.kind == "unknown"

    cycle = build_rust_bindings("type A=B; type B=A; fn f(x:A){}", pointer_width=64)
    assert _bindings(cycle, "x", "parameter")[0].type.kind == "unknown"

def test_type_lifetime_and_const_generics_resolve_in_item_scopes():
    source = """
type T = u8;
struct S<'a, T, const N: usize> where T: Copy { r: &'a T, values: [T; N] }
enum E<T> { Value(T) }
trait Tr<'a, T> { fn borrow(x: &'a T); }
impl<U> S<'static, U, 4> {
    fn method<V, const M: usize>(x: V, values: [u8; M]) -> U
    where V: Copy { let result: U = x; result }
}
fn generic<T, const N: usize>(x: T, values: [u8; N]) -> T
where T: Copy { x }
fn outside(x: T) {}
"""
    report = build_rust_bindings(source, pointer_width=64)
    generic_types = _bindings(report, "T", "generic_parameter")
    assert len(generic_types) == 4
    assert all(binding.type.kind == "unknown" for binding in generic_types)
    generic_ids = {binding.id for binding in generic_types}
    assert _refs(report, source, "T")
    assert {ref.binding_id for ref in _refs(report, source, "T")} <= generic_ids

    lifetimes = _bindings(report, "'a", "generic_parameter")
    assert len(lifetimes) == 2
    assert all(
        ref.binding_id in {binding.id for binding in lifetimes}
        for ref in _refs(report, source, "'a")
    )
    consts = [
        binding
        for binding in report.bindings
        if binding.kind == "generic_parameter" and binding.name in {"N", "M"}
    ]
    assert len(consts) == 3
    assert all(
        (binding.type.kind, binding.type.bit_width, binding.type.signed)
        == ("int", 64, False)
        for binding in consts
    )
    method = next(
        binding for binding in _bindings(report, "method", "associated_function")
    )
    generic_function = next(
        fn for fn in report.functions if fn.binding_id == method.id
    )
    assert generic_function.generic

    generic_start = source.index("fn generic")
    generic_end = source.index("fn outside")
    generic_parameter = next(
        binding
        for binding in report.bindings
        if binding.kind == "parameter"
        and binding.name == "x"
        and generic_start < binding.span.start < generic_end
    )
    assert generic_parameter.type.kind == "unknown"
    outside = next(
        binding
        for binding in _bindings(report, "x", "parameter")
        if binding.span.start > generic_end
    )
    alias = _bindings(report, "T", "type_alias")[0]
    assert outside.type.type_id == alias.id

def test_const_generic_type_facts_follow_forward_aliases():
    sources = (
        "fn f<const N: Count>() {} type Count = u32;",
        "type Count = u32; fn f<const N: Count>() {}",
    )
    for source in sources:
        report = build_rust_bindings(source, pointer_width=64)
        alias = _bindings(report, "Count", "type_alias")[0]
        parameter = _bindings(report, "N", "generic_parameter")[0]
        assert (
            parameter.type.kind,
            parameter.type.name,
            parameter.type.bit_width,
            parameter.type.signed,
            parameter.type.type_id,
        ) == ("int", "u32", 32, False, alias.id)

    unresolved = build_rust_bindings(
        "fn f<const N: Missing>() {}",
        pointer_width=64,
    )
    assert _bindings(unresolved, "N", "generic_parameter")[0].type.kind == "unknown"

    cyclic = build_rust_bindings(
        "type A = B; type B = A; fn f<const N: A>() {}",
        pointer_width=64,
    )
    assert _bindings(cyclic, "N", "generic_parameter")[0].type.kind == "unknown"

def test_extern_functions_declare_generic_parameters_and_signature_references():
    source = """
extern "C" {
    fn foreign<'a, T, const N: usize>(value: &'a T, values: [u8; N]) -> &'a T;
    fn plain(value: Missing);
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    foreign = _bindings(report, "foreign", "function")[0]
    foreign_function = next(
        function for function in report.functions if function.binding_id == foreign.id
    )
    assert foreign_function.generic
    assert foreign_function.body is None
    for name in ("'a", "T", "N"):
        generic = _bindings(report, name, "generic_parameter")
        assert len(generic) == 1
        references = [
            reference
            for reference in _refs(report, source, name)
            if reference.binding_id == generic[0].id
        ]
        assert references
    assert (
        _bindings(report, "N", "generic_parameter")[0].type.bit_width,
        _bindings(report, "N", "generic_parameter")[0].type.signed,
    ) == (64, False)

    plain = _bindings(report, "plain", "function")[0]
    plain_function = next(
        function for function in report.functions if function.binding_id == plain.id
    )
    assert not plain_function.generic
    assert not _bindings(report, "Missing", "generic_parameter")
    assert not _refs(report, source, "Missing")

@pytest.mark.parametrize(
    "source",
    [
        "fn g<const N: usize>(a: usize) -> usize { a + N }",
        (
            "fn f<T, const N: usize>(x: T) { "
            "match 1 { n if n > N => {}, _ => {} } }"
        ),
    ],
)
def test_generic_const_references_are_emitted_once(source):
    report = build_rust_bindings(source, pointer_width=64)
    const_parameter = next(
        binding
        for binding in report.bindings
        if binding.kind == "generic_parameter" and binding.name == "N"
    )
    n_references = [
        reference
        for reference in report.references
        if reference.binding_id == const_parameter.id
    ]
    assert len(n_references) == 1
    assert n_references[0].kind == "read"

def test_higher_ranked_lifetimes_are_scoped_to_their_binders():
    source = """
trait Bound {}
fn outer<'a, T>(parameter: &'a u8)
where
    T: for<'b> Bound<&'b T>,
    for<'e> &'e u8: Bound,
{
    let _: for<'c> fn(&'c u8) -> &'c u8;
    let _: &'a u8;
    let _: dyn for<'d> Bound<&'d u8>;
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    raw = source.encode()
    a_bindings = _bindings(report, "'a", "generic_parameter")
    outer_a = next(
        binding
        for binding in a_bindings
        if binding.scope is not None
        and binding.scope.start < source.index("where")
    )
    bound_e = _bindings(report, "'e", "generic_parameter")[0]

    def lifetime_reference(token: str, after: int = 0):
        start = source.index(token, after) + token.index("'")
        return next(
            reference
            for reference in report.references
            if reference.span.start == start
        )

    assert lifetime_reference("&'a u8").binding_id == outer_a.id
    bound_reference = lifetime_reference("&'e u8", source.index("for<'e>"))
    assert bound_reference.binding_id == bound_e.id
    assert (
        lifetime_reference("&'a u8", source.index("let _: &'a")).binding_id
        == outer_a.id
    )

    for lifetime in ("b", "c", "d", "e"):
        name = f"'{lifetime}"
        binding = _bindings(report, name, "generic_parameter")[0]
        reference = lifetime_reference(f"&{name} ")
        assert reference.binding_id == binding.id
        assert binding.scope is not None
        assert binding.scope.start <= reference.span.start < binding.scope.end
    assert not any(
        item.reason == "item_boundary"
        and raw[item.span.start : item.span.end].startswith(b"'")
        for item in report.unresolved
    )

def test_higher_ranked_lifetimes_cover_their_complete_predicate_or_type():
    source = """
trait Tr<'a> {}
fn f<'a, T, U, V, W>(
    pointer: for<'d> fn(&'d T),
    outside_pointer: &'d T,
)
where
    for<'b> T: Tr<'b>,
    U: Tr<'b>,
    V: for<'c> Tr<'c>,
    W: Tr<'c>,
{
    let _: &'a T;
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    for lifetime in ("'a", "'b", "'c", "'d"):
        assert _bindings(report, lifetime, "generic_parameter")
    assert len(_refs(report, source, "'b")) == 1
    assert len(_refs(report, source, "'c")) == 1
    assert len(_refs(report, source, "'d")) == 1
    assert len(_refs(report, source, "'a")) == 1
    for name, outside_marker in (
        ("'b", "U: Tr<'b>"),
        ("'c", "W: Tr<'c>"),
        ("'d", "outside_pointer"),
    ):
        outside_position = source.index(outside_marker)
        assert not any(
            reference.span.start > outside_position
            for reference in _refs(report, source, name)
        )

def test_generic_type_parameters_do_not_leak_outside_their_item_scope():
    source = "type T=u8; fn generic<T>(x:T){} fn outside(x:T){}"
    report = build_rust_bindings(source, pointer_width=64)
    generic = _bindings(report, "T", "generic_parameter")[0]
    outside = [
        binding
        for binding in _bindings(report, "x", "parameter")
        if binding.span.start > source.index("outside")
    ][0]
    alias = _bindings(report, "T", "type_alias")[0]
    assert generic.scope is not None
    assert outside.type.type_id == alias.id

def test_nested_function_items_do_not_inherit_outer_function_generics():
    source = """
fn outer<T, const N: usize>() {
    fn shadows<T>(value: T) {}
    fn inner(value: T) { let _ = N; }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    inner_generic = next(
        binding
        for binding in _bindings(report, "T", "generic_parameter")
        if binding.span.start > source.index("fn shadows")
        and binding.span.start < source.index("fn inner")
    )
    shadow_reference = next(
        reference
        for reference in _refs(report, source, "T")
        if source.index("fn shadows") < reference.span.start < source.index("fn inner")
    )
    assert shadow_reference.binding_id == inner_generic.id
    boundary_references = [
        unresolved
        for unresolved in report.unresolved
        if unresolved.reason == "item_boundary"
        and unresolved.span.start > source.index("fn inner")
    ]
    assert {unresolved.name for unresolved in boundary_references} == {"T", "N"}

def test_nested_impl_and_trait_methods_use_their_own_generics():
    source = """
fn outer<T>() {
    struct Local;
    impl<U> Bound<U> for Local {
        fn method(&self, value: U) -> U {
            fn nested() { let _: U; }
            let _: T;
            value
        }
    }
    trait Tr<V> {
        fn bodyless(&self, value: V);
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    impl_generic = _bindings(report, "U", "generic_parameter")[0]
    trait_generic = _bindings(report, "V", "generic_parameter")[0]
    raw = source.encode()
    impl_references = [
        reference
        for reference in report.references
        if raw[reference.span.start : reference.span.end] == b"U"
    ]
    trait_references = [
        reference
        for reference in report.references
        if raw[reference.span.start : reference.span.end] == b"V"
    ]
    assert impl_references
    assert all(reference.binding_id == impl_generic.id for reference in impl_references)
    assert trait_references
    assert all(reference.binding_id == trait_generic.id for reference in trait_references)
    assert {
        (item.name, item.reason)
        for item in report.unresolved
        if item.reason == "item_boundary"
    } == {("T", "item_boundary"), ("U", "item_boundary")}

def test_where_clauses_record_generic_parameters_without_binding_other_names():
    source = """
type Outside = u8;
struct S;
trait Bound<T> where T: Copy {}
impl<U> Bound<U> for S where U: Copy {}
fn bounded<T>() where T: Copy {}
fn unrelated<T>() where Outside: Copy {}
"""
    report = build_rust_bindings(source, pointer_width=64)
    expected_positions = [
        source.index("T: Copy"),
        source.index("U: Copy"),
        source.rindex("T: Copy"),
    ]
    for position in expected_positions:
        reference = next(
            reference
            for reference in report.references
            if reference.span.start == position
        )
        assert report.binding(reference.binding_id).kind == "generic_parameter"
    assert not _refs(report, source, "Outside")

def test_body_type_positions_record_generic_parameter_references():
    source = """
struct S<T>(T);
fn make<T>(value: T) {}
fn caller<T>(value: T) {
    let local: T = value;
    let cast = value as T;
    let closure = |parameter: T| parameter;
    make::<T>(value);
    value.method::<T>();
    let _ = S::<T>(value);
    let _ = S::<T>{0: value};
    let _: S<T>;
}
fn outside(value: Missing) {
    let _: Missing = value;
    let _ = value as Missing;
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    caller_start = source.index("fn caller")
    outside_start = source.index("fn outside")
    caller_generic = next(
        binding
        for binding in _bindings(report, "T", "generic_parameter")
        if binding.scope is not None
        and binding.scope.start <= caller_start < binding.scope.end
    )
    caller_type_references = [
        reference
        for reference in _refs(report, source, "T")
        if caller_start < reference.span.start < outside_start
    ]
    assert len(caller_type_references) == 9
    assert all(
        reference.binding_id == caller_generic.id
        for reference in caller_type_references
    )
    tuple_struct = _bindings(report, "S", "struct")[0]
    tuple_constructor = next(
        call for call in report.calls if call.target == tuple_struct.id
    )
    assert tuple_constructor.kind == "constructor"
    assert not _refs(report, source, "Missing")

def test_bare_generic_arguments_search_type_then_const_value_namespaces():
    source = """
type N = u8;
const N: usize = 1;
const K: usize = 2;
struct TypeArg<T>(T);
struct ConstArg<const M: usize>;
fn take<const M: usize>() {}
fn uses_type() { let _: TypeArg<N>; }
fn uses_const<const M: usize>() {
    let _: ConstArg<M>;
    take::<M>();
}
fn uses_const_item() { let _: ConstArg<K>; }
fn missing() { let _: TypeArg<Unknown>; }
fn local_is_not_a_const_argument() {
    let M = 1;
    let _: ConstArg<M>;
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    raw = source.encode()
    alias = _bindings(report, "N", "type_alias")[0]
    type_argument_position = source.index("TypeArg<N>") + len("TypeArg<")
    type_argument_reference = next(
        reference
        for reference in report.references
        if reference.span.start == type_argument_position
    )
    assert type_argument_reference.binding_id == alias.id
    const_generic = next(
        binding
        for binding in _bindings(report, "M", "generic_parameter")
        if binding.scope is not None
        and binding.scope.start <= source.index("fn uses_const") < binding.scope.end
    )
    for token in ("ConstArg<M>", "take::<M>"):
        position = source.index(token) + token.index("M")
        reference = next(
            reference
            for reference in report.references
            if reference.span.start == position
        )
        assert reference.binding_id == const_generic.id
    const_item = _bindings(report, "K", "const")[0]
    const_item_position = source.index("ConstArg<K>") + len("ConstArg<")
    const_item_reference = next(
        reference
        for reference in report.references
        if reference.span.start == const_item_position
    )
    assert const_item_reference.binding_id == const_item.id
    unknown_position = source.index("TypeArg<Unknown>") + len("TypeArg<")
    unknown = next(
        unresolved
        for unresolved in report.unresolved
        if unresolved.span.start == unknown_position
    )
    assert (unknown.name, unknown.reason) == ("Unknown", "unknown_name")
    local_position = source.rindex("ConstArg<M>") + len("ConstArg<")
    assert not any(
        reference.span.start == local_position for reference in report.references
    )
    assert raw[unknown.span.start : unknown.span.end] == b"Unknown"

def test_generic_argument_fallback_respects_glob_barriers_and_prelude_types():
    source = """
const Vec: usize = 1;
const Hidden: usize = 2;
struct Generic<T>;
fn prelude_type() { let _: Generic<Vec>; }
fn glob_barrier() { use external::*; let _: Generic<Hidden>; }
"""
    report = build_rust_bindings(source, pointer_width=64)
    raw = source.encode()
    vec_start = source.index("Generic<Vec>") + len("Generic<")
    hidden_start = source.index("Generic<Hidden>") + len("Generic<")
    assert not any(
        reference.span.start == vec_start for reference in report.references
    )
    assert any(
        item.span.start == vec_start
        and item.name == "Vec"
        and item.reason == "prelude_name"
        for item in report.unresolved
    )
    assert not any(
        reference.span.start == hidden_start for reference in report.references
    )
    assert any(
        item.span.start == hidden_start
        and item.name == "Hidden"
        and item.reason == "glob_import"
        for item in report.unresolved
    )
    assert raw[vec_start : vec_start + len("Vec")] == b"Vec"

def test_generic_argument_value_fallback_ignores_outer_module_value_names():
    source = """
const N: usize = 1;
mod m {
    const N: usize = 2;
    struct S<const K: usize>;
    fn f() { let _: S<N>; }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    local_n = next(
        binding
        for binding in _bindings(report, "N", "const")
        if binding.span.start > source.index("mod m")
    )
    argument_start = source.index("S<N>") + len("S<")
    reference = next(
        reference
        for reference in report.references
        if reference.span.start == argument_start
    )
    assert reference.binding_id == local_n.id
    assert not any(item.span.start == argument_start for item in report.unresolved)

def test_bodyless_trait_const_generic_facts_finalize_after_item_predeclaration():
    source = """
trait Tr {
    fn good<const N: Width>();
    fn unknown<const M: Missing>();
}
type Width = u8;
"""
    report = build_rust_bindings(source, pointer_width=64)
    width = _bindings(report, "Width", "type_alias")[0]
    good = _bindings(report, "N", "generic_parameter")[0]
    unknown = _bindings(report, "M", "generic_parameter")[0]
    assert (good.type.kind, good.type.bit_width, good.type.type_id) == (
        "int",
        8,
        width.id,
    )
    assert unknown.type.kind == "unknown"

def test_mutability_does_not_spread_into_nested_rust_patterns():
    source = """
struct S { f: Option<u8>, field: u8 }
fn patterns(value: S) {
    match value {
        mut capture @ Some(inner) => {},
        S { f: Some(mut x) } => {},
        S { mut field } => {},
        S { ref mut field } => {},
        S { f: Some(plain) } => {},
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    assert _bindings(report, "capture", "local")[0].mutable
    assert not _bindings(report, "inner", "local")[0].mutable
    assert _bindings(report, "x", "local")[0].mutable
    assert [binding.mutable for binding in _bindings(report, "field", "local")] == [
        True,
        True,
    ]
    assert not _bindings(report, "plain", "local")[0].mutable

def test_qualified_rust_paths_stay_unresolved_as_whole_paths():
    source = """
type T = u8;
const N: u8 = 1;
fn plain(value: T) { let _ = N; }
fn qualified() {
    let _: crate::T;
    let _: self::N;
    let _: super::X;
    let _: Self::T;
    let _: <T as Tr>::X;
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    alias = _bindings(report, "T", "type_alias")[0]
    plain_parameter = _bindings(report, "value", "parameter")[0]
    assert plain_parameter.type.type_id == alias.id
    assert any(
        reference.binding_id == _bindings(report, "N", "const")[0].id
        for reference in report.references
    )
    qualified_paths = {
        source.encode()[unresolved.span.start : unresolved.span.end].decode()
        for unresolved in report.unresolved
        if unresolved.reason == "qualified_path"
    }
    assert qualified_paths == {
        "crate::T",
        "self::N",
        "super::X",
        "Self::T",
        "<T as Tr>::X",
    }
    assert not any(
        reference.span
        == unresolved.span
        for reference in report.references
        for unresolved in report.unresolved
        if unresolved.reason == "qualified_path"
    )

def test_local_type_alias_precedes_primitive_type_facts():
    source = """
type u8 = u16;
fn shadowed(x: u8) -> u8 { let y: u8 = x; y }
fn builtin(x: i8) -> i8 { x }
"""
    report = build_rust_bindings(source, pointer_width=64)
    alias = _bindings(report, "u8", "type_alias")[0]
    for name in ("x", "y"):
        shadowed = next(
            binding
            for binding in _bindings(report, name, "parameter" if name == "x" else "local")
            if binding.span.start < source.index("fn builtin")
        )
        assert (
            shadowed.type.kind,
            shadowed.type.name,
            shadowed.type.bit_width,
            shadowed.type.type_id,
        ) == ("int", "u16", 16, alias.id)
    builtin = next(
        binding
        for binding in _bindings(report, "x", "parameter")
        if binding.span.start > source.index("fn builtin")
    )
    assert (builtin.type.kind, builtin.type.name, builtin.type.bit_width) == (
        "int",
        "i8",
        8,
    )

def test_raw_identifiers_are_normalized_in_declarations_and_references():
    source = """
fn r#helper() {}
fn caller() { helper(); r#helper(); }
fn raw_parameter(r#type: u8) {
    let r#match = r#type;
    r#match;
}
fn missing_call() { r#missing(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    helper = _bindings(report, "helper", "function")[0]
    assert all(call.target == helper.id for call in report.calls[:2])
    assert all(call.kind == "direct_local" for call in report.calls[:2])
    assert len(_bindings(report, "type", "parameter")) == 1
    assert len(_bindings(report, "match", "local")) == 1
    missing = next(
        unresolved for unresolved in report.unresolved if unresolved.name == "missing"
    )
    assert report.resolve(missing.span) is None
    assert report.calls[-1].kind == "unresolved"

def test_raw_identifier_function_item_lookup_round_trips():
    source = "fn r#helper() {} fn f() { helper(); r#helper(); }"
    report = build_rust_bindings(source, pointer_width=64)
    helper = _bindings(report, "helper", "function")[0]
    assert [call.target for call in report.calls] == [helper.id, helper.id]
    assert [call.kind for call in report.calls] == ["direct_local", "direct_local"]

def test_impl_trait_arguments_are_generic_and_turbofish_stays_on_the_callee():
    source = """
fn impl_trait(argument: impl Copy) {}
fn plain(argument: u8) {}
fn target(argument: u8) {}
fn caller() { plain(target::<u8>()); impl_trait(1); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    impl_trait = _bindings(report, "impl_trait", "function")[0]
    plain = _bindings(report, "plain", "function")[0]
    target = _bindings(report, "target", "function")[0]
    functions = {function.binding_id: function for function in report.functions}
    assert functions[impl_trait.id].generic
    assert not functions[plain.id].generic
    assert not functions[target.id].generic
    calls = {call.target: call for call in report.calls}
    assert calls[impl_trait.id].kind == "opaque_generic"
    assert calls[target.id].kind == "opaque_generic"
    assert calls[plain.id].kind == "direct_local"

@pytest.mark.parametrize(
    "source",
    [
        "struct S { field: make_type!() }",
        "fn f() { let value: make_type!() = 0; }",
        "fn f() -> make_type!() { loop {} }",
        "type Alias = make_type!();",
    ],
)
def test_type_position_macros_create_macro_gaps(source):
    report = build_rust_bindings(source, pointer_width=64)
    macro_start = source.encode().index(b"make_type!")
    assert any(
        gap.reason == "macro_invocation" and gap.span.start == macro_start
        for gap in report.gaps
    )
    assert not report.complete

def test_explicit_non_macro_types_do_not_create_macro_gaps():
    report = build_rust_bindings(
        "struct S { field: u8 } type Alias = u16; fn f(x: u8) -> u16 { x as u16 }",
        pointer_width=64,
    )
    assert not any(gap.reason == "macro_invocation" for gap in report.gaps)

def test_turbofish_method_calls_traverse_the_receiver():
    source = "fn caller(x: Thing) { x.method::<u8>(); }"
    report = build_rust_bindings(source, pointer_width=64)
    assert len(report.calls) == 1
    assert report.calls[0].kind == "opaque_method"
    assert report.calls[0].target == ""
    receiver = next(
        binding for binding in _bindings(report, "x", "parameter")
    )
    assert any(
        reference.span.start == source.index("x.method")
        and reference.binding_id == receiver.id
        and reference.kind == "read"
        for reference in report.references
    )
    assert not any(
        unresolved.name.startswith("x.method") for unresolved in report.unresolved
    )

def test_pattern_mutability_is_preserved_per_binding():
    source = """
fn parameters((mut c, d): (i32, i32)) {}
fn locals(pair: (i32, i32), value: S) {
    let (mut a, b) = pair;
    let S { mut field, ref mut other } = value;
    let mut capture @ Some(inner) = None;
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    expected = {
        ("c", "parameter"): True,
        ("d", "parameter"): False,
        ("a", "local"): True,
        ("b", "local"): False,
        ("field", "local"): True,
        ("other", "local"): True,
        ("capture", "local"): True,
        ("inner", "local"): False,
    }
    for (name, kind), mutable in expected.items():
        assert _bindings(report, name, kind)[0].mutable is mutable

def test_comments_are_skipped_in_call_arguments_and_other_visitor_children():
    source = """
fn identity(/* parameter */ value: u8) {
    /* block */
    let (left, /* pattern */ right) = (value, value);
}
fn caller(value: u8) {
    identity(/* argument */ value);
    match value {
        /* arm */ 0 => {},
        // next arm
        _ => {}
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    identity = _bindings(report, "identity", "function")[0]
    call = next(call for call in report.calls if call.target == identity.id)
    assert len(call.arguments) == 1
    assert not any(gap.reason == "unsupported_syntax" for gap in report.gaps)
    assert not report.unresolved

def test_macros_and_glob_imports_keep_hidden_names_unresolved_and_incomplete():
    macro_source = 'fn f(x:i32){ println!("{}", x); }'
    macro = build_rust_bindings(macro_source, pointer_width=64)
    assert not _refs(macro, macro_source, "x")
    assert any(g.reason == "macro_invocation" for g in macro.gaps)
    assert not macro.complete

    source = "use foo::*; fn f(){ bar(); }"
    report = build_rust_bindings(source, pointer_width=64)
    assert _unresolved(report, "bar", "glob_import")
    assert any(g.reason == "glob_import" for g in report.gaps)

def test_inner_glob_import_blocks_outer_items_but_not_other_scopes():
    source = (
        "fn helper(){} "
        "fn f(){ { use m::*; helper(); } } "
        "fn g(){ helper(); }"
    )
    report = build_rust_bindings(source, pointer_width=64)
    helper = _bindings(report, "helper", "function")[0]
    raw = source.encode()
    calls = sorted(
        (
            call
            for call in report.calls
            if raw[call.span.start : call.span.end] == b"helper()"
        ),
        key=lambda call: call.span.start,
    )
    assert [call.kind for call in calls] == ["unresolved", "direct_local"]
    assert calls[0].target == ""
    assert calls[1].target == helper.id
    assert _unresolved(report, "helper", "glob_import")

def test_glob_import_in_inline_module_blocks_outer_name_lookup():
    source = "fn helper(){} mod m { use other::*; fn f(){ helper(); } }"
    report = build_rust_bindings(source, pointer_width=64)
    call = _call(report, source, "helper()")
    assert call.kind == "unresolved"
    assert call.target == ""
    assert _unresolved(report, "helper", "glob_import")

def test_use_imports_prelude_qualified_method_and_generic_calls():
    source = """
use std::cmp::max;
fn generic<T>(x:T){}
async fn asynchronous(){}
fn f(x:i32){
  max(x,x); Some(x); Vec::new(); Self::f(); crate::f(); self_call();
  generic(x); generic::<i32>(x); asynchronous(); x.abs();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    assert _bindings(report, "max", "import")
    assert _call(report, source, "max(x,x)").kind == "opaque_import"
    assert _unresolved(report, "Some", "prelude_name")
    assert any(item.reason == "qualified_path" for item in report.unresolved)
    assert _call(report, source, "Some(x)").kind == "unresolved"
    assert _call(report, source, "Vec::new()").kind == "opaque_path"
    assert _call(report, source, "Self::f()").kind == "opaque_path"
    assert _call(report, source, "crate::f()").kind == "opaque_path"
    assert _call(report, source, "x.abs()").kind == "opaque_method"
    assert _call(report, source, "generic(x)").kind == "opaque_generic"
    assert _call(report, source, "generic::<i32>(x)").kind == "opaque_generic"
    assert _call(report, source, "asynchronous()").kind == "opaque_async"

def test_tuple_struct_constructor_parenthesized_fn_and_struct_shorthand():
    source = """
struct Pair(u8);
fn f(x:u8){ fn helper(y:u8){} (helper)(x); Pair(x); let p = Point { x }; }
struct Point { x:u8 }
"""
    report = build_rust_bindings(source, pointer_width=64)
    assert _call(report, source, "(helper)(x)").kind == "direct_local"
    assert _call(report, source, "Pair(x)").kind == "constructor"
    assert _refs(report, source, "x")[-1].binding_id == _bindings(report, "x", "parameter")[0].id

def test_struct_pattern_shorthand_creates_a_local_binding():
    source = "struct Point { value:u8 } fn f(point:Point){ let Point { value }=point; value; }"
    report = build_rust_bindings(source, pointer_width=64)
    local = _bindings(report, "value", "local")[0]
    assert _refs(report, source, "value")[0].binding_id == local.id

def test_associated_functions_are_not_bare_names_and_self_is_a_parameter():
    source = "struct S; impl S { fn method(&mut self){ self_call(); } } fn f(){ method(); }"
    report = build_rust_bindings(source, pointer_width=64)
    method = _bindings(report, "method", "associated_function")[0]
    fn_record = next(fn for fn in report.functions if fn.binding_id == method.id)
    assert fn_record.method
    assert _bindings(report, "self", "self_parameter")[0].mutable
    assert _unresolved(report, "method", "unknown_name")

def test_static_mut_write_parse_limits_source_hash_and_determinism():
    source = "static mut COUNT:u8=0; fn f(){ COUNT = 1; }"
    report = build_rust_bindings(source, pointer_width=64)
    assert _bindings(report, "COUNT", "static")[0].mutable
    assert _refs(report, source, "COUNT")[0].kind == "write"
    assert report.to_json() == build_rust_bindings(source, pointer_width=64).to_json()
    changed = build_rust_bindings(source + " ", pointer_width=64)
    assert report.source_sha256 != changed.source_sha256
    assert report.bindings[0].id != changed.bindings[0].id
    with pytest.raises(LexicalReportError):
        build_rust_bindings("fn broken( {", pointer_width=64)
    with pytest.raises(LexicalReportError):
        build_rust_bindings(" " * (64 * 1024 + 1), pointer_width=64)
    for invalid in (8, True, 128):
        with pytest.raises(LexicalReportError):
            build_rust_bindings("fn f(){}", pointer_width=invalid)

def test_deep_expression_recursion_is_reported_as_a_source_limit_error():
    expression = " + ".join("1" for _ in range(2000))
    source = f"fn f() {{ let value = {expression}; }}"
    previous_limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(1000)
        with pytest.raises(
            LexicalReportError,
            match="Rust source nesting exceeds the lexical report limit",
        ):
            build_rust_bindings(source, pointer_width=64)
    finally:
        sys.setrecursionlimit(previous_limit)

def test_explicit_function_const_static_and_unit_types_and_extern_calls():
    source = """
const fn counted() -> u16 { 2 }
const COUNT: u16 = counted();
const fn enabled() -> bool { true }
static STATE: bool = enabled();
fn unit() -> () {}
extern "C" { fn external(value: u8); }
fn caller() { external(1); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    assert _bindings(report, "COUNT", "const")[0].type.bit_width == 16
    assert _bindings(report, "STATE", "static")[0].type.kind == "bool"
    unit = next(fn for fn in report.functions if fn.binding_id == _bindings(report, "unit", "function")[0].id)
    assert unit.result.kind == "unit"
    assert _call(report, source, "counted()").owner == ""
    assert _call(report, source, "enabled()").owner == ""
    assert _call(report, source, "external(1)").kind == "opaque_bodyless"

def test_use_group_self_alias_names_and_report_completeness():
    source = "use foo::{self, a, b as d}; fn f(){ a(); d(); foo(); }"
    report = build_rust_bindings(source, pointer_width=64)
    assert {binding.name for binding in report.bindings if binding.kind == "import"} == {
        "foo", "a", "d"
    }
    assert all(
        _call(report, source, call_text).kind == "opaque_import"
        for call_text in ("a()", "d()", "foo()")
    )
    assert build_rust_bindings("fn clean(){}", pointer_width=64).complete
    assert not build_rust_bindings("fn unresolved(){ missing(); }", pointer_width=64).complete

def test_every_emitted_target_and_reference_points_to_an_existing_binding():
    fixtures = [
        "fn a(){} fn b(){a();}",
        "fn f(x:i32){ x = 2; }",
        "struct S(u8); fn f(){ S(1); }",
        "impl S { fn m(&self){} } struct S;",
    ]
    for source in fixtures:
        report = build_rust_bindings(source, pointer_width=64)
        identifiers = {binding.id for binding in report.bindings}
        assert all(ref.binding_id in identifiers for ref in report.references)
        assert all(call.target == "" or call.target in identifiers for call in report.calls)
        assert all(call.owner == "" or call.owner in identifiers for call in report.calls)
        assert all(fn.binding_id in identifiers for fn in report.functions)
        assert all(parameter in identifiers for fn in report.functions for parameter in fn.parameters)
        restored = load_lexical_report(
            report.to_json(), source, profile=PROFILE, target={"pointer_width": 64}
        )
        assert restored.to_json() == report.to_json()

def test_cli_emits_loadable_json_requires_width_and_fails_closed(tmp_path):
    source_file = tmp_path / "sample.rs"
    source_file.write_text("fn f(){}", encoding="utf-8")
    command = [sys.executable, "-m", "agent", "rust-bindings", str(source_file)]
    missing = subprocess.run(command, capture_output=True, text=True, check=False)
    assert missing.returncode == 2
    success = subprocess.run(
        [*command, "--pointer-width", "32"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert success.returncode == 0 and success.stderr == ""
    loaded = load_lexical_report(
        success.stdout,
        source_file.read_text(),
        profile=PROFILE,
        target={"pointer_width": 32},
    )
    assert loaded.profile == PROFILE

    source_file.write_text("fn broken( {", encoding="utf-8")
    failed = subprocess.run(
        [*command, "--pointer-width", "32"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert failed.returncode == 2
    assert failed.stdout == ""
    assert failed.stderr

def test_cli_preserves_crlf_bytes_for_report_hash_and_spans(tmp_path):
    source = "fn first() {}\r\nfn second() { first(); }\r\n"
    source_file = tmp_path / "crlf.rs"
    source_file.write_bytes(source.encode("utf-8"))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent",
            "rust-bindings",
            str(source_file),
            "--pointer-width",
            "64",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    restored = load_lexical_report(
        result.stdout,
        source,
        profile=PROFILE,
        target={"pointer_width": 64},
    )
    assert restored.source_sha256 == build_rust_bindings(
        source, pointer_width=64
    ).source_sha256

def test_member_access_resolves_declared_type_fields_and_methods():
    source = """
struct Point { x: i32, y: i32 }
impl Point {
    fn get(&self) -> i32 { self.x }
    fn dist(&self, other: &Point) -> f64 {
        let dx = self.x - other.x;
        self.y as f64 + other.y as f64
    }
}
fn use_it(p: Point, q: Point) {
    p.get();
    q.dist(p);
    p.x;
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    get_rec = _bindings(report, "get", "associated_function")[0]
    dist_rec = _bindings(report, "dist", "associated_function")[0]
    x_rec = _bindings(report, "x", "struct_field")[0]
    y_rec = _bindings(report, "y", "struct_field")[0]
    assert _call(report, source, "p.get()").kind == "direct_local"
    assert _call(report, source, "p.get()").target == get_rec.id
    assert _call(report, source, "q.dist(p)").target == dist_rec.id
    member_refs = [
        ref
        for ref in _refs(report, source, "x")
        if ref.binding_id == x_rec.id
    ]
    # self.x (twice) + other.x + p.x member reads
    assert len(member_refs) == 4
    y_refs = [ref for ref in _refs(report, source, "y") if ref.binding_id == y_rec.id]
    assert len(y_refs) == 2

def test_member_write_emits_write_reference_on_field():
    source = """
struct P { v: i32 }
fn f(p: &mut P, w: i32) { p.v = w; }
"""
    report = build_rust_bindings(source, pointer_width=64)
    v_rec = _bindings(report, "v", "struct_field")[0]
    writes = [
        ref
        for ref in _refs(report, source, "v")
        if ref.kind == "write" and ref.binding_id == v_rec.id
    ]
    assert len(writes) == 1

def test_member_call_on_trait_impl_resolves_when_trait_in_scope():
    source = """
struct P {}
trait T { fn t(&self) -> i32; }
impl T for P { fn t(&self) -> i32 { 1 } }
fn f(p: P) { p.t(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    impl_member = next(
        b
        for b in _bindings(report, "t", "associated_function")
        if b.span.start > source.index("impl T")
    )
    call = _call(report, source, "p.t()")
    assert call.kind == "direct_local"
    assert call.target == impl_member.id

def test_member_tuple_positional_field_stays_unresolved():
    source = """
struct T(i32, i32);
fn f(t: T) { t.0; }
"""
    report = build_rust_bindings(source, pointer_width=64)
    assert not _bindings(report, "0")

def test_member_call_through_method_return_type_chains():
    source = """
struct A {}
struct B {}
impl A { fn mk(&self) -> B { B {} } }
impl B { fn hit(&self) -> i32 { 1 } }
fn f(a: A) { a.mk().hit(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    hit = _bindings(report, "hit", "associated_function")[0]
    call = _call(report, source, "a.mk().hit()")
    assert call.target == hit.id

def test_member_generic_impl_method_resolves_through_generic_impl():
    source = """
struct Wrap<T> { inner: T }
impl<T> Wrap<T> { fn get(&self) -> i32 { 0 } }
fn f(w: Wrap<i32>) { w.get(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = _call(report, source, "w.get()")
    get = _bindings(report, "get", "associated_function")[0]
    assert call.target == get.id
    assert call.kind == "direct_local"

def test_member_write_prefers_field_over_same_named_method():
    source = """
struct P { m: i32 }
impl P { fn m(&self) {} }
fn f(p: &P) { p.m = 1; p.m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    field = _bindings(report, "m", "struct_field")[0]
    method = _bindings(report, "m", "associated_function")[0]
    write = next(
        r for r in report.references
        if r.kind == "write" and source[r.span.start : r.span.end] == "m"
    )
    call = _call(report, source, "p.m()")
    assert write.binding_id == field.id
    assert call.target == method.id

def test_member_call_respects_concrete_impl_specialization():
    source = """
struct Wrap<T>(T);
impl Wrap<i32> { fn get(&self) -> i32 { 0 } }
impl Wrap<bool> { fn get(&self) -> bool { true } }
fn f(w: Wrap<bool>) { w.get(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    bool_get = _bindings(report, "get", "associated_function")[1]
    call = _call(report, source, "w.get()")
    assert call.target == bool_get.id

def test_member_resolves_annotation_at_its_own_position():
    source = """
struct P { x: i32 }
fn g(p: &P) { p.x; }
struct Q { x: i32 }
"""
    report = build_rust_bindings(source, pointer_width=64)
    field = _bindings(report, "x", "struct_field")[0]
    read = next(
        r for r in report.references
        if r.kind == "read" and source[r.span.start : r.span.end] == "x"
        and r.span.start > source.index("p.x")
    )
    assert read.binding_id == field.id

def test_member_destructured_parameter_does_not_resolve_as_whole_type():
    source = """
struct P { inner: i32 }
impl P { fn n(&self) {} }
fn f(P { inner }: P) { inner.n(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    method_call = _call(report, source, "inner.n()")
    assert method_call.kind == "opaque_method"

def test_member_async_method_return_does_not_chain_members():
    source = """
struct A {}
struct B {}
impl A { async fn mk(&self) -> B { B {} } }
impl B { fn hit(&self) {} }
fn h(a: A) { a.mk().hit(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    hit_call = _call(report, source, "a.mk().hit()")
    assert hit_call.kind == "opaque_method"
    assert not hit_call.target

def test_member_forward_reference_inside_impl_resolves():
    source = """
struct S {}
impl S {
    fn outer(&self) { self.inner(); }
    fn inner(&self) {}
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    inner = _bindings(report, "inner", "associated_function")[0]
    call = _call(report, source, "self.inner()")
    assert call.target == inner.id
    assert call.kind == "direct_local"

def test_member_call_chains_through_reference_return_type():
    source = """
struct A {}
struct B {}
impl A { fn mk(&self) -> &B { &B {} } }
impl B { fn hit(&self) {} }
fn h(a: A) { a.mk().hit(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    hit = _bindings(report, "hit", "associated_function")[0]
    call = _call(report, source, "a.mk().hit()")
    assert call.target == hit.id

def test_member_reference_annotated_local_resolves():
    source = """
struct P { x: i32 }
fn f() { let q: &P = &P { x: 0 }; q.x; }
"""
    report = build_rust_bindings(source, pointer_width=64)
    field = _bindings(report, "x", "struct_field")[0]
    read = next(
        r for r in report.references
        if r.kind == "read" and source[r.span.start : r.span.end] == "x"
    )
    assert read.binding_id == field.id

def test_member_receiver_prefers_field_over_same_named_method():
    # `a.b.hit()` reads field `b` (type B), not method `b() -> C`.
    source = """
struct A { b: B }
impl A { fn b(&self) -> C { C } }
struct B;
impl B { fn hit(&self) {} }
struct C;
fn f(a: &A) { a.b.hit(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    hit = _bindings(report, "hit", "associated_function")[0]
    call = _call(report, source, "a.b.hit()")
    assert call.target == hit.id
    assert call.kind == "direct_local"

def test_member_self_call_in_specialized_impl():
    source = """
struct W<T>(T);
impl W<i32> { fn inner(&self) {} fn outer(&self) { self.inner(); } }
"""
    report = build_rust_bindings(source, pointer_width=64)
    inner = _bindings(report, "inner", "associated_function")[0]
    call = _call(report, source, "self.inner()")
    assert call.target == inner.id
    assert call.kind == "direct_local"

def test_member_captured_pattern_keeps_annotation():
    source = """
struct P { x: i32 }
fn f(q @ P{x}: P) { q.x; }
"""
    report = build_rust_bindings(source, pointer_width=64)
    field = _bindings(report, "x", "struct_field")[0]
    reads = [
        r
        for r in report.references
        if r.kind == "read" and source[r.span.start - 1 : r.span.end] == ".x"
    ]
    assert [r.binding_id == field.id for r in reads] == [True]

def test_ref_pattern_binding_is_not_the_annotated_type():
    # `ref p: P` binds `p: &P` — the annotation must not be
    # reported as `p`'s type.
    source = "struct P {} fn f(ref p: P) {}"
    report = build_rust_bindings(source, pointer_width=64)
    p = _bindings(report, "p", "parameter")[0]
    assert p.type.kind == "unknown"

def test_member_captured_pattern_inner_name_stays_opaque():
    source = """
struct P { inner: i32 }
impl P { fn n(&self) {} }
fn f(q @ P{inner}: P) { inner.n(); q.n(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    n = _bindings(report, "n", "associated_function")[0]
    inner_call = _call(report, source, "inner.n()")
    q_call = _call(report, source, "q.n()")
    assert inner_call.kind == "opaque_method"
    assert q_call.target == n.id

def test_member_tuple_element_receiver_resolves_by_index():
    source = """
struct P { x: i32 }
impl P { fn get(&self) -> i32 { self.x } }
fn f(t: (i32, P)) { t.1.get(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    get = _bindings(report, "get", "associated_function")[0]
    call = _call(report, source, "t.1.get()")
    assert call.target == get.id
    assert call.kind == "direct_local"

def test_member_tuple_element_receiver_through_reference():
    source = """
struct P { x: i32 }
impl P { fn get(&self) -> i32 { self.x } }
fn f(u: &(i32, P)) { u.1.get(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    get = _bindings(report, "get", "associated_function")[0]
    call = _call(report, source, "u.1.get()")
    assert call.target == get.id

def test_member_tuple_element_out_of_range_stays_opaque():
    source = """
struct P { x: i32 }
impl P { fn get(&self) -> i32 { self.x } }
fn f(t: (i32,)) { t.1.get(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = _call(report, source, "t.1.get()")
    assert call.kind == "opaque_method"

def test_member_tuple_element_let_annotation_receiver():
    source = """
struct P { x: i32 }
impl P { fn get(&self) -> i32 { self.x } }
fn f() { let t: (i32, P) = (0, P{x: 1}); t.1.get(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    get = _bindings(report, "get", "associated_function")[0]
    call = _call(report, source, "t.1.get()")
    assert call.target == get.id

def test_member_tuple_element_non_tuple_receiver_stays_opaque():
    source = """
struct T(i32, i32);
fn f(t: T) { t.0.get(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = _call(report, source, "t.0.get()")
    assert call.kind == "opaque_method"

def test_member_tuple_element_receiver_through_lifetime_reference():
    source = """
struct P { x: i32 }
impl P { fn get(&self) -> i32 { self.x } }
fn f<'a>(t: &'a mut (i32, P), u: &'static (i32, P)) { t.1.get(); u.1.get(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    get = _bindings(report, "get", "associated_function")[0]
    calls = {source[c.span.start : c.span.end]: c for c in report.calls}
    assert calls["t.1.get()"].target == get.id
    assert calls["u.1.get()"].target == get.id

def test_member_trait_impl_resolves_when_trait_in_scope():
    source = """
trait Greet { fn hi(&self); }
struct P;
impl Greet for P { fn hi(&self) {} }
fn f(p: &P) { p.hi(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    hi = next(
        b
        for b in _bindings(report, "hi", "associated_function")
        if b.span.start > source.index("impl Greet")
    )
    call = _call(report, source, "p.hi()")
    assert call.target == hi.id
    assert call.kind == "direct_local"

def test_member_trait_impl_via_imported_trait_resolves():
    source = """
mod inner { pub trait Greet { fn hi(&self); } }
use inner::Greet;
struct P;
impl Greet for P { fn hi(&self) {} }
fn f(p: &P) { p.hi(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = _call(report, source, "p.hi()")
    assert call.kind == "direct_local"
    assert call.target

def test_member_scoped_trait_impl_stays_opaque():
    # `impl inner::Greet` — the scoped trait is not resolvable here,
    # so its members must not resolve as methods.
    source = """
mod inner { pub trait Greet { fn hi(&self); } }
struct P;
impl inner::Greet for P { fn hi(&self) {} }
fn f(p: &P) { p.hi(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = _call(report, source, "p.hi()")
    assert call.kind == "opaque_method"

def test_member_inherent_impl_shadows_trait_impl():
    source = """
trait Greet { fn hi(&self); }
struct P;
impl P { fn hi(&self) {} }
impl Greet for P { fn hi(&self) {} }
fn f(p: &P) { p.hi(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    inherent = next(
        b
        for b in _bindings(report, "hi", "associated_function")
        if source.index("impl P") < b.span.start < source.index("impl Greet")
    )
    call = _call(report, source, "p.hi()")
    assert call.target == inherent.id

def test_member_ambiguous_trait_impls_stay_opaque():
    # `p.get()` could call T::get or U::get — Rust reports ambiguity,
    # so no single implementation is bound.
    source = """
struct P { x: i32 }
trait T { fn get(&self) -> i32; }
trait U { fn get(&self) -> i32; }
impl T for P { fn get(&self) -> i32 { self.x } }
impl U for P { fn get(&self) -> i32 { 2 } }
fn f(p: P) { p.get(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = _call(report, source, "p.get()")
    assert call.kind == "opaque_method"
    assert not call.target

def test_member_single_trait_impl_still_resolves():
    source = """
struct Q { y: i32 }
trait V { fn only(&self) -> i32; }
impl V for Q { fn only(&self) -> i32 { self.y } }
fn f(q: Q) { q.only(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    only = next(
        b
        for b in _bindings(report, "only", "associated_function")
        if b.span.start > source.index("impl V")
    )
    call = _call(report, source, "q.only()")
    assert call.target == only.id

def test_trait_default_method_resolves_through_empty_impl():
    source = """
trait T { fn m(&self) {} }
struct P {}
impl T for P {}
fn f() { let p: P; p.m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    default_m = next(
        b
        for b in report.bindings
        if b.name == "m" and b.span.start == source.index("fn m") + 3
    )
    call = _call(report, source, "p.m()")
    assert call.kind == "direct_local"
    assert call.target == default_m.id

def test_impl_member_shadows_trait_default():
    source = """
trait T { fn m(&self) {} }
struct P {}
impl T for P { fn m(&self) {} }
fn f() { let p: P; p.m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    impl_m = next(
        b
        for b in report.bindings
        if b.name == "m" and b.span.start == source.rindex("fn m") + 3
    )
    call = _call(report, source, "p.m()")
    assert call.target == impl_m.id

def test_two_trait_defaults_stay_ambiguous():
    source = """
trait T { fn m(&self) {} }
trait U { fn m(&self) {} }
struct P {}
impl T for P {}
impl U for P {}
fn f() { let p: P; p.m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = _call(report, source, "p.m()")
    assert call.kind == "opaque_method"
    assert call.target == ""

def test_trait_default_does_not_apply_to_other_specialization():
    source = """
trait T { fn m(&self) {} }
struct W<T>(T);
impl T for W<i32> {}
fn f(w: W<u32>) { w.m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = _call(report, source, "w.m()")
    assert call.kind == "opaque_method"
    assert call.target == ""

def test_trait_default_applies_to_matching_specialization():
    source = """
trait T { fn m(&self) {} }
struct W<T>(T);
impl T for W<i32> {}
fn f(w: W<i32>) { w.m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    default_m = next(
        b
        for b in report.bindings
        if b.name == "m" and b.span.start == source.index("fn m") + 3
    )
    call = _call(report, source, "w.m()")
    assert call.target == default_m.id

def test_generic_impl_default_matches_concrete_positions():
    # impl<A> T for W<A, i32> covers W<u8, i32> — the parameter
    # position is a wildcard, concrete positions must match.
    source = """
trait T { fn m(&self) {} }
struct W<A, B>(A, B);
impl<A> T for W<A, i32> {}
impl<A> T for W<A, u32> {}
fn f(w: W<u8, i32>) { w.m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    default_m = next(
        b
        for b in report.bindings
        if b.name == "m" and b.span.start == source.index("fn m") + 3
    )
    call = _call(report, source, "w.m()")
    assert call.target == default_m.id

def test_generic_impl_default_misses_other_concrete_position():
    source = """
trait T { fn m(&self) {} }
struct W<A, B>(A, B);
impl<A> T for W<A, i32> {}
impl<A> T for W<A, u32> {}
fn f(w: W<u8, u16>) { w.m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = _call(report, source, "w.m()")
    assert call.kind == "opaque_method"
    assert call.target == ""

def test_member_generic_impl_covers_composite_args():
    # A generic impl covers receivers whose args contain commas or
    # generics of their own — parameter positions stay wildcards at
    # any nesting depth.
    source = """
trait T { fn m(&self) {} }
struct W<X>(X);
impl<A> T for W<A> { }
fn f(w: W<(u8, u16)>) { w.m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    member_m = _bindings(report, "m", "associated_function")[0]
    call = _call(report, source, "w.m()")
    assert call.target == member_m.id

def test_member_generic_impl_nested_generic_arg():
    source = """
trait T { fn m(&self) {} }
struct W<X>(X);
impl<A> T for W<Vec<A>> { }
fn f(w: W<Vec<u8>>) { w.m(); }
fn g(w: W<Box<u8>>) { g_unchecked(w); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    member_m = _bindings(report, "m", "associated_function")[0]
    call = _call(report, source, "w.m()")
    assert call.target == member_m.id
    # `Box<u8>` does not match `Vec<A>` — m() stays opaque there.
    assert _call(report, source, "w.m()").target == member_m.id
    source2 = """
trait T { fn m(&self) {} }
struct W<X>(X);
impl<A> T for W<Vec<A>> { }
fn g(w: W<Box<u8>>) { w.m(); }
"""
    report2 = build_rust_bindings(source2, pointer_width=64)
    assert _call(report2, source2, "w.m()").target == ""

def test_member_generic_impl_const_and_lifetime_params():
    source = """
trait T { fn m(&self) {} fn n(&self) {} }
struct W<const N: usize>([u8; N]);
impl<const N: usize> T for W<N> { }
struct R<'a>(&'a u8);
trait U { fn p(&self) {} }
impl<'a> U for R<'a> { }
fn f(w: W<4>, r: R<'static>) { w.m(); r.p(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    member_m = _bindings(report, "m", "associated_function")[0]
    member_p = _bindings(report, "p", "associated_function")[0]
    assert _call(report, source, "w.m()").target == member_m.id
    assert _call(report, source, "r.p()").target == member_p.id

def test_member_generic_impl_repeated_param_binds_consistently():
    # Every occurrence of a pattern parameter must bind the same
    # receiver arg: `impl<A> T for W<(A,A)>` covers `W<(u8,u8)>` but
    # not `W<(u8,u16)>`, and likewise for const parameters.
    source = """
trait T { fn m(&self) {} }
struct W<X>(X);
impl<A> T for W<(A, A)> { }
fn f(w: W<(u8, u8)>) { w.m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    member_m = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "w.m()").target == member_m.id
    source2 = """
trait T { fn m(&self) {} }
struct W<X>(X);
impl<A> T for W<(A, A)> { }
fn f(w: W<(u8, u16)>) { w.m(); }
"""
    report2 = build_rust_bindings(source2, pointer_width=64)
    assert _call(report2, source2, "w.m()").target == ""

def test_member_generic_impl_reference_mutability_matters():
    # Shared and mutable references are distinct types: each impl
    # covers only its own mutability side.
    for impl_args, hit, miss in (
        ("&A", "W<&u8>", "W<&mut u8>"),
        ("&mut A", "W<&mut u8>", "W<&u8>"),
    ):
        source = f"""
trait T {{ fn m(&self) {{}} }}
struct W<X>(X);
impl<A> T for W<{impl_args}> {{ }}
fn f(w: {hit}) {{ w.m(); }}
fn g(u: {miss}) {{ u.m(); }}
"""
        report = build_rust_bindings(source, pointer_width=64)
        member_m = _bindings(report, "m", "associated_function")[0]
        assert _call(report, source, "w.m()").target == member_m.id
        assert _call(report, source, "u.m()").target == ""

def test_member_generic_impl_whitespace_independent_concrete_args():
    # `W<(u8,u16)>` and `W<(u8, u16)>` spell the same type — concrete
    # impl-arg keys compare structurally, not by raw text.
    source = """
struct W<A, B> { a: A, b: B }
trait T { fn m(&self) {} }
impl T for W<(u8,u16), u8> {}
fn f(w: W<(u8, u16), u8>) { w.m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    member_m = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "w.m()").target == member_m.id

def test_member_generic_impl_repeated_const_param_must_bind_same_value():
    # `impl<const A: usize> T for W<A, A>` covers `W<3, 3>` but not
    # `W<3, 4>` — repeated parameters bind consistently.
    source = """
struct W<A, B> { a: A, b: B }
trait T { fn m(&self) {} }
impl<const A: usize> T for W<A, A> {}
fn f(w: W<3, 4>) { w.m(); }
fn g(w: W<3, 3>) { w.m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    member_m = _bindings(report, "m", "associated_function")[0]
    calls = [
        c
        for c in report.calls
        if source[c.span.start : c.span.end] == "w.m()"
    ]
    assert calls[0].target == ""
    assert calls[1].target == member_m.id

def test_member_generic_impl_spaceless_reference_syntax():
    # `&mut&u8` and `&'b[u8]` are valid Rust — optional whitespace
    # after `mut` and lifetimes must not break the reference match.
    source = """
struct W<A, B> { a: A, b: B }
trait T { fn m(&self) {} }
impl<A> T for W<&mut A, u8> {}
impl<'b> T for W<&'b [u8], i8> {}
fn f(w: W<&mut&u8, u8>, g: W<&'b[u8], i8>) { w.m(); g.m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    member_m = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "w.m()").target == member_m.id
    assert _call(report, source, "g.m()").target == member_m.id

def test_member_generic_impl_mut_prefixed_type_name_not_mut_ref():
    # `&mutable::Value` is a shared reference to a type named
    # `mutable` — the leading `mut` must not be read as `&mut`, so a
    # `&mut A` impl does not apply, while a shared `&A` impl does.
    source = """
struct W<A, B> { a: A, b: B }
trait T { fn m(&self) {} }
impl<A> T for W<&mut A, u8> {}
mod mutable { pub struct Value {} }
fn f(w: W<&mutable::Value, u8>) { w.m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    assert _call(report, source, "w.m()").target == ""

    source = """
struct W<A, B> { a: A, b: B }
trait T { fn m(&self) {} }
impl<A> T for W<&A, u8> {}
mod mutable { pub struct Value {} }
fn f(w: W<&mutable::Value, u8>) { w.m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    member_m = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "w.m()").target == member_m.id

def test_function_pointer_field_call_reads_the_field():
    # `(p.callback)()` reads field `callback` (type `fn()`) — the read
    # reference must be recorded even though no function is called.
    source = """
struct P { callback: fn() }
fn go(p: P) { (p.callback)(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    field = _bindings(report, "callback", "struct_field")[0]
    read = next(
        r for r in report.references
        if r.kind == "read" and source[r.span.start : r.span.end] == "callback"
    )
    assert read.binding_id == field.id

def test_member_scoped_path_call_and_result_chain():
    source = """
struct P;
impl P { fn new() -> P { P } fn hello(&self) {} }
fn f() { let p = P::new(); p.hello(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    new = next(
        b
        for b in _bindings(report, "new", "associated_function")
        if b.span.start > source.index("impl P")
    )
    hello = _bindings(report, "hello", "associated_function")[0]
    new_call = _call(report, source, "P::new()")
    hello_call = _call(report, source, "p.hello()")
    assert new_call.target == new.id
    assert new_call.kind == "direct_local"
    assert hello_call.target == hello.id

def test_member_generic_scoped_path_call():
    source = """
struct W<T>(T);
impl W<i32> { fn mk() -> W<i32> { W(0) } fn n(&self) {} }
fn f() { let w = W::<i32>::mk(); w.n(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    calls = [c for c in report.calls if source[c.span.start] == source.index("W::<i32>::mk")]
    mk_call = next(
        c for c in report.calls if source[c.span.start : c.span.end].startswith("W::<i32>::mk")
    )
    assert mk_call.kind == "direct_local"
    n_call = _call(report, source, "w.n()")
    assert n_call.kind == "direct_local"

def test_member_deep_scoped_path_stays_opaque():
    source = "mod m { pub struct P; } fn f() { m::P::new(); }"
    report = build_rust_bindings(source, pointer_width=64)
    call = report.calls[0]
    assert call.kind == "opaque_path"
    assert [u.name for u in report.unresolved] == ["m::P::new"]

def test_member_let_infers_struct_literal_type():
    source = """
struct P { x: i32 }
fn f() { let p = P{x: 0}; p.x; }
"""
    report = build_rust_bindings(source, pointer_width=64)
    field = _bindings(report, "x", "struct_field")[0]
    read = next(
        r
        for r in report.references
        if source[r.span.start - 1 : r.span.end] == ".x"
    )
    assert read.binding_id == field.id

def test_member_let_infers_function_result_type():
    source = """
fn mk() -> P { P }
struct P;
impl P { fn n(&self) {} }
fn f() { let p = mk(); p.n(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    n = _bindings(report, "n", "associated_function")[0]
    call = _call(report, source, "p.n()")
    assert call.target == n.id

def test_member_scoped_module_type_annotation_resolves():
    source = """
mod m { pub struct P { pub x: i32 } }
fn f(p: m::P) { p.x; }
"""
    report = build_rust_bindings(source, pointer_width=64)
    field = _bindings(report, "x", "struct_field")[0]
    read = next(
        r
        for r in report.references
        if source[r.span.start - 1 : r.span.end] == ".x"
    )
    assert read.binding_id == field.id

def test_member_scoped_module_path_call_resolves():
    source = """
mod m { pub struct P; impl P { pub fn new() -> P { P } } }
fn f() { let p = m::P::new(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    new = _bindings(report, "new", "associated_function")[0]
    call = _call(report, source, "m::P::new()")
    assert call.target == new.id
    assert call.kind == "direct_local"

def test_member_nested_module_type_annotation_resolves():
    source = """
mod a { pub mod b { pub struct P; impl P { pub fn n(&self) {} } } }
fn f(p: a::b::P) { p.n(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    n = _bindings(report, "n", "associated_function")[0]
    call = _call(report, source, "p.n()")
    assert call.target == n.id

def test_member_enum_variant_path_resolves():
    source = """
enum E { A, B(i32), C = 3 }
fn f() { let e = E::A; let g = E::B; }
"""
    report = build_rust_bindings(source, pointer_width=64)
    variants = {
        b.name: b for b in report.bindings if b.kind == "enum_member"
    }
    assert set(variants) == {"A", "B", "C"}
    a_ref = next(
        r
        for r in report.references
        if source[r.span.start - 2 : r.span.end] == "::A"
    )
    b_ref = next(
        r
        for r in report.references
        if source[r.span.start - 2 : r.span.end] == "::B"
    )
    assert a_ref.binding_id == variants["A"].id
    assert b_ref.binding_id == variants["B"].id
    assert not [u for u in report.unresolved if u.name == "E::A"]

def test_member_enum_variant_in_match_pattern_resolves():
    source = """
enum E { A, B }
fn f(e: E) { match e { E::A => {}, E::B => {} } }
"""
    report = build_rust_bindings(source, pointer_width=64)
    variants = {b.name: b for b in report.bindings if b.kind == "enum_member"}
    reads = {
        source[r.span.start : r.span.end]: r.binding_id
        for r in report.references
        if source[r.span.start : r.span.end] in {"A", "B"}
    }
    assert reads == {"A": variants["A"].id, "B": variants["B"].id}
    assert not [u for u in report.unresolved if u.name.startswith("E::")]

def test_member_ufcs_resolves_named_trait_impl():
    source = """
struct P { x: i32 }
trait T { fn get(&self) -> i32; }
trait U { fn get(&self) -> i32; }
impl T for P { fn get(&self) -> i32 { self.x } }
impl U for P { fn get(&self) -> i32 { 2 } }
fn f() { <P as T>::get(); <P as U>::get(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    impls = _bindings(report, "get", "associated_function")
    t_impl = next(b for b in impls if b.span.start > source.index("impl T"))
    u_impl = next(b for b in impls if b.span.start > source.index("impl U"))
    t_call = _call(report, source, "<P as T>::get()")
    u_call = _call(report, source, "<P as U>::get()")
    assert t_call.target == t_impl.id
    assert u_call.target == u_impl.id

def test_member_ufcs_unknown_trait_stays_opaque():
    source = """
struct P { x: i32 }
fn f() { <P as Z>::get(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = _call(report, source, "<P as Z>::get()")
    assert call.kind == "opaque_path"

def test_member_ufcs_bare_bracket_resolves_inherent_member():
    source = """
struct P { x: i32 }
impl P { fn get(&self) -> i32 { 3 } const K: i32 = 1; }
fn f() { <P>::get(); let k = <P>::K; }
"""
    report = build_rust_bindings(source, pointer_width=64)
    get = _bindings(report, "get", "associated_function")[0]
    const = _bindings(report, "K", "associated_const")[0]
    call = _call(report, source, "<P>::get()")
    assert call.target == get.id
    reads = [
        r
        for r in report.references
        if r.kind == "read" and source[r.span.start : r.span.end] == "K"
    ]
    assert [r.binding_id == const.id for r in reads] == [True]

def test_member_ufcs_missing_trait_member_stays_opaque():
    source = """
struct P { x: i32 }
trait T { fn get(&self) -> i32; }
impl T for P { fn get(&self) -> i32 { self.x } }
impl P { fn other(&self) -> i32 { 3 } }
fn f() { <P as T>::other(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = _call(report, source, "<P as T>::other()")
    assert call.kind == "opaque_path"

def test_function_pointer_field_call_records_field_read():
    source = """
struct P { callback: fn() }
fn f() { let p: P; (p.callback)(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    field = _bindings(report, "callback", "struct_field")[0]
    call = _call(report, source, "(p.callback)()")
    assert call.kind == "opaque_value"
    assert call.target == field.id
    field_refs = [
        r
        for r in report.references
        if r.binding_id == field.id and r.kind == "read"
    ]
    assert len(field_refs) == 1
    assert source[field_refs[0].span.start : field_refs[0].span.end] == "callback"

def test_ufcs_falls_back_to_trait_default_method():
    source = """
trait T { fn m(&self) {} }
struct P;
impl T for P {}
fn f(p: P) { <P as T>::m(&p); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    default_m = next(
        b
        for b in report.bindings
        if b.name == "m" and b.span.start == source.index("fn m") + 3
    )
    call = _call(report, source, "<P as T>::m(&p)")
    assert call.target == default_m.id

def test_ufcs_prefers_impl_member_over_trait_default():
    source = """
trait T { fn m(&self) {} }
struct P;
impl T for P { fn m(&self) {} }
fn f(p: P) { <P as T>::m(&p); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    impl_m = next(
        b
        for b in report.bindings
        if b.name == "m" and b.span.start == source.rindex("fn m") + 3
    )
    call = _call(report, source, "<P as T>::m(&p)")
    assert call.target == impl_m.id

def test_bare_type_path_call_sees_trait_default():
    source = """
trait T { fn m(&self) {} }
struct P;
impl T for P {}
fn f(p: P) { P::m(&p); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    default_m = next(
        b
        for b in report.bindings
        if b.name == "m" and b.span.start == source.index("fn m") + 3
    )
    call = _call(report, source, "P::m(&p)")
    assert call.target == default_m.id

def test_vec_index_receiver_types_member_by_element():
    source = """
struct P;
impl P { fn m(&self) {} }
fn f(v: Vec<P>) { v[0].m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    call = _call(report, source, "v[0].m()")
    assert call.target == m.id

def test_nested_vec_index_receiver_resolves_innermost_element():
    source = """
struct P;
impl P { fn m(&self) {} }
fn f(v: Vec<Vec<P>>) { v[0][0].m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    call = _call(report, source, "v[0][0].m()")
    assert call.target == m.id

def test_multi_arg_container_index_stays_opaque():
    source = """
struct P;
struct Q;
fn f(m: HashMap<u32, P>) { m[&0].q(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = _call(report, source, "m[&0].q()")
    assert call.kind == "opaque_method"
    assert call.target == ""

def test_index_receiver_slice_and_array_element_types():
    # `&[P]` and `[P; N]` index to `P`; a nested `[P; 2]` element is
    # an anonymous type that keeps indexing to `P` without gaining
    # `P`'s own members at the first level.
    source = """
struct P { }
impl P { fn m(&self) {} }
fn f(v: &[P]) { v[0].m(); }
fn g(v: &[[P; 2]]) { v[0][1].m(); }
fn h(v: &[[P; 2]]) { v[0].m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    member_m = _bindings(report, "m", "associated_function")[0]
    calls = [c for c in report.calls]
    assert calls[0].target == member_m.id
    assert calls[1].target == member_m.id
    assert calls[2].target == ""

def test_index_receiver_std_map_indexes_to_value_type():
    # `HashMap<K, V>`/`BTreeMap<K, V>` index to `V`; a value that is
    # itself `Vec<P>` keeps chaining; a source-declared `HashMap` is
    # untouched.
    source = """
struct P { }
impl P { fn m(&self) {} }
fn f(v: HashMap<u32, P>) { v[0].m(); }
fn g(v: HashMap<u32, Vec<P>>) { v[0][0].m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    member_m = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "v[0].m()").target == member_m.id
    assert _call(report, source, "v[0][0].m()").target == member_m.id

def test_enum_discriminant_qualified_path_registers_once():
    # The type walk and the value walk both see `P::K` — the
    # reference must not duplicate or the report fails to load.
    source = """
struct P;
impl P { const K: u32 = 1; }
enum E { A = P::K }
"""
    report = build_rust_bindings(source, pointer_width=64)
    refs = [
        reference
        for reference in report.references
        if source[reference.span.start : reference.span.end] == "K"
    ]
    assert len(refs) == 1

def test_range_subscript_indexes_to_slice_not_element():
    source = """
struct P;
impl P { fn m(&self) {} }
fn f(v: Vec<P>) { v[..].m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = _call(report, source, "v[..].m()")
    assert not call.target

def test_custom_container_index_stays_opaque():
    # `Wrapper<P>` may pick any `Index::Output` — P's method must not
    # attach.
    source = """
struct P;
impl P { fn m(&self) {} }
struct Wrapper<P>;
fn f(w: Wrapper<P>) { w[0].m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = _call(report, source, "w[0].m()")
    assert not call.target

def test_imported_map_index_receiver_uses_value_type():
    source = """
use std::collections::HashMap;
struct P;
impl P { fn m(&self) {} }
fn f(m: HashMap<u32, P>) { m[&0].m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    call = _call(report, source, "m[&0].m()")
    assert call.target == m.id

def test_scoped_generic_annotation_keeps_type_args():
    source = """
mod m { pub struct W<T>; }
impl m::W<i32> { fn n(&self) {} }
fn f(p: m::W<i32>) { p.n(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    n = _bindings(report, "n", "associated_function")[0]
    call = _call(report, source, "p.n()")
    assert call.target == n.id

def test_struct_literal_generic_keeps_type_args():
    source = """
struct W<T>;
impl W<i32> { fn n(&self) {} }
fn f() { let w = W::<i32> { }; w.n(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    n = _bindings(report, "n", "associated_function")[0]
    call = _call(report, source, "w.n()")
    assert call.target == n.id

def test_module_declared_after_use_still_resolves():
    source = """
impl m::P2 { fn m(&self) {} }
fn f(p: m::P2) { p.m(); }
mod m {
    pub struct P2;
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    call = _call(report, source, "p.m()")
    assert call.target == m.id

def test_plain_function_generic_return_types_receiver():
    source = """
struct W<T>;
impl W<i32> { fn n(&self) {} }
fn mk() -> W<i32> { unimplemented!() }
fn f() { let w = mk(); w.n(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    n = _bindings(report, "n", "associated_function")[0]
    call = _call(report, source, "w.n()")
    assert call.target == n.id

def test_ufcs_scoped_trait_name_resolves():
    source = """
struct P;
mod m { pub trait T { fn go(&self); } }
impl m::T for P { fn go(&self) {} }
fn f(p: P) { <P as m::T>::go(&p); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    impl_member = next(
        b for b in _bindings(report, "go", "associated_function")
        if "impl m::T for P" in source[: b.span.start]
    )
    call = _call(report, source, "<P as m::T>::go(&p)")
    assert call.target == impl_member.id

def test_ufcs_alias_receiver_uses_concrete_impl():
    source = """
trait T { fn m(&self) { } }
struct P;
type A = P;
impl T for P { fn m(&self) {} }
fn f() { <A as T>::m(&P); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    impls = _bindings(report, "m", "associated_function")
    impl_member = next(
        b for b in impls
        if source[b.span.start : b.span.end] == "m"
        and "impl T for P" in source[: b.span.start]
    )
    call = _call(report, source, "<A as T>::m(&P)")
    assert call.target == impl_member.id

def test_ufcs_generic_trait_picks_matching_impl():
    # `<P as T<u32>>::m` resolves to the `u32` impl, not the first
    # registered `T` impl for `P`.
    source = """
trait T<A> { fn m(&self) -> i32; }
struct P;
impl T<i32> for P { fn m(&self) -> i32 { 1 } }
impl T<u32> for P { fn m(&self) -> i32 { 2 } }
fn f(p: P) { <P as T<u32>>::m(&p); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    u32_impl = next(
        b
        for b in report.bindings
        if b.name == "m" and b.span.start == source.rindex("fn m") + 3
    )
    call = _call(report, source, "<P as T<u32>>::m(&p)")
    assert call.target == u32_impl.id

def test_index_range_then_index_resolves_element():
    # `v[1..][0]` is a `P` — the slice's anonymous element type.
    source = """
struct P;
impl P { fn m(&self) {} }
fn f(v: &[P]) { v[1..][0].m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    member = next(
        b for b in report.bindings
        if b.name == "m" and b.kind == "associated_function"
    )
    call = _call(report, source, "v[1..][0].m()")
    assert call.target == member.id

def test_index_call_arg_with_range_stays_element():
    # `v[find_index(0..10)]` is an integer index — the `..` inside the
    # call's argument does not make the receiver a slice.
    source = """
struct P;
impl P { fn m(&self) {} }
fn find_index(_r: core::ops::Range<i32>) -> usize { 0 }
fn f(v: &[P]) { v[find_index(0..10)].m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    member = next(
        b for b in report.bindings
        if b.name == "m" and b.kind == "associated_function"
    )
    call = _call(report, source, "v[find_index(0..10)].m()")
    assert call.target == member.id

def test_module_const_generic_type_annotation_resolves():
    # `const N: Count` inside `mod m` finds the module-local alias.
    source = """
fn f(s: &m::S<3>) {}
mod m {
    pub type Count = usize;
    pub struct S<const N: Count> { _a: [u8; N] }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    count = next(
        b for b in report.bindings
        if b.name == "Count" and b.kind == "type_alias"
    )
    param = next(
        b for b in report.bindings
        if b.name == "N" and b.kind == "generic_parameter"
    )
    assert param.type is not None
    assert param.type.type_id == count.id

def test_ufcs_generic_trait_picks_matching_associated_const():
    # `<P as T<u32>>::C` binds to the `u32` impl's const, not the
    # `i32` impl's or the trait's.
    source = """
trait T<A> { const C: i32; }
struct P;
impl T<i32> for P { const C: i32 = 1; }
impl T<u32> for P { const C: i32 = 2; }
fn f() { let x = <P as T<u32>>::C; }
"""
    report = build_rust_bindings(source, pointer_width=64)
    u32_const = next(
        b
        for b in report.bindings
        if b.name == "C" and b.span.start == source.rindex("const C") + 6
    )
    ref = _refs(report, source, "C")[-1]
    assert ref.binding_id == u32_const.id

def test_parenthesized_range_index_stays_a_slice():
    # `v[(..)]` is still a range — `.m()` on the slice does not
    # resolve to `P`'s method.
    source = """
struct P;
impl P { fn m(&self) {} }
fn f(v: &[P]) { v[(..)].m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    member = next(
        b for b in report.bindings
        if b.name == "m" and b.kind == "associated_function"
    )
    call = _call(report, source, "v[(..)].m()")
    assert call.target != member.id

def test_ufcs_generic_impl_trait_args_match_concrete_call():
    # `impl<A> T<A> for P` — `A` is an impl parameter, a wildcard:
    # `<P as T<u32>>::m` reaches the impl's `m`, not the trait's.
    source = """
trait T<A> { fn m(&self) {} }
struct P;
impl<A> T<A> for P { fn m(&self) {} }
fn f() { <P as T<u32>>::m(&P); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    impl_m = next(
        b for b in report.bindings
        if b.name == "m" and b.span.start == source.rindex("fn m") + 3
    )
    call = _call(report, source, "<P as T<u32>>::m(&P)")
    assert call.target == impl_m.id

def test_ufcs_generic_impl_concrete_trait_arg_still_filters():
    # `impl<A> T<i32> for W<A>` is generic over the impl type but its
    # trait args are concrete — `T<u32>` must not reach it.
    source = """
trait T<A> { fn m(&self) {} }
struct W<A>(A);
struct P;
impl<A> T<i32> for P { fn m(&self) {} }
fn f() { <P as T<u32>>::m(&P); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    impl_m = next(
        b for b in report.bindings
        if b.name == "m" and b.span.start == source.rindex("fn m") + 3
    )
    call = _call(report, source, "<P as T<u32>>::m(&P)")
    assert call.target != impl_m.id

def test_ufcs_trait_arg_binding_constrains_impl_type_args():
    # `impl<A> T<A> for W<A>` cannot answer `<W<V<u16>> as T<u8>>::m`
    # — `A` would have to be both `u8` (trait side) and `V<u16>`
    # (impl side). The `impl<A> T<u8> for W<V<A>>` impl is the match.
    source = """
trait T<A> { fn m(&self) {} }
struct W<A>(A);
struct V<A>(A);
impl<A> T<A> for W<A> { fn m(&self) {} }
impl<A> T<u8> for W<V<A>> { fn m(&self) {} }
fn f() { <W<V<u16>> as T<u8>>::m(&W(V(0u16))); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    right_m = next(
        b for b in report.bindings
        if b.name == "m" and b.span.start == source.rindex("fn m") + 3
    )
    wrong_m = next(
        b for b in report.bindings
        if b.name == "m" and b.span.start != source.rindex("fn m") + 3
        and b.span.start != source.index("fn m") + 3
    )
    call = _call(report, source, "<W<V<u16>> as T<u8>>::m(&W(V(0u16)))")
    assert call.target == right_m.id
    assert call.target != wrong_m.id

def test_ufcs_alias_receiver_carries_impl_args():
    # `type Alias = W<u8>` — `<Alias as T>::m` reads `W<u8>` for the
    # impl match, so `impl<A> T for W<A>` answers with A = u8.
    source = """
trait T { fn m(&self) {} }
struct W<A>(A);
impl<A> T for W<A> { fn m(&self) {} }
type Alias = W<u8>;
fn f() { <Alias as T>::m(&W(0u8)); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    impl_m = next(
        b for b in report.bindings
        if b.name == "m" and b.span.start == source.rindex("fn m") + 3
    )
    call = _call(report, source, "<Alias as T>::m(&W(0u8))")
    assert call.target == impl_m.id

def test_ufcs_omitted_receiver_args_still_matches_generic_impl():
    # `<W as T>::m` spells no receiver args — `impl<A> T for W<A>`
    # still applies (every impl arg is a parameter).
    source = """
trait T { fn m(&self) {} }
struct W<A = u8>(A);
impl<A> T for W<A> { fn m(&self) {} }
fn f() { <W as T>::m(&W(0u8)); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    impl_m = next(
        b for b in report.bindings
        if b.name == "m" and b.span.start == source.rindex("fn m") + 3
    )
    call = _call(report, source, "<W as T>::m(&W(0u8))")
    assert call.target == impl_m.id

def test_ufcs_nested_generic_impl_arg_matches():
    # `Result<A, B>` — the comma inside `<>` is nested and does not
    # split the impl's arg list.
    source = """
trait T { fn m(&self) {} }
struct W<A>(A);
struct R<A, B>(A, B);
impl<A, B> T for W<R<A, B>> { fn m(&self) {} }
fn f() { <W<R<u8, u16>> as T>::m(&W(R(0u8, 0u16))); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    impl_m = next(
        b for b in report.bindings
        if b.name == "m" and b.span.start == source.rindex("fn m") + 3
    )
    call = _call(report, source, "<W<R<u8, u16>> as T>::m(&W(R(0u8, 0u16)))")
    assert call.target == impl_m.id

def test_ufcs_array_impl_arg_matches_element_and_length():
    # `impl<A, const N: usize> T for W<[A; N]>` — the receiver's
    # `[u8; 4]` binds `A = u8` and `N = 4`.
    source = """
trait T { fn m(&self) {} }
struct W<A>(A);
impl<A, const N: usize> T for W<[A; N]> { fn m(&self) {} }
fn f() { <W<[u8; 4]> as T>::m(&W([0u8; 4])); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    impl_m = next(
        b for b in report.bindings
        if b.name == "m" and b.span.start == source.rindex("fn m") + 3
    )
    call = _call(report, source, "<W<[u8; 4]> as T>::m(&W([0u8; 4]))")
    assert call.target == impl_m.id

def test_ufcs_generic_alias_substitutes_spelled_args():
    # `type Alias<B> = W<B>` — `<Alias<u8> as T<u8>>::m` substitutes
    # B = u8, so `impl<A> T<A> for W<A>` binds A = u8 and matches.
    source = """
trait T<A> { fn m(&self) {} }
struct W<A>(A);
impl<A> T<A> for W<A> { fn m(&self) {} }
type Alias<B> = W<B>;
fn f() { <Alias<u8> as T<u8>>::m(&W(0u8)); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    impl_m = next(
        b for b in report.bindings
        if b.name == "m" and b.span.start == source.rindex("fn m") + 3
    )
    call = _call(report, source, "<Alias<u8> as T<u8>>::m(&W(0u8))")
    assert call.target == impl_m.id

def test_ufcs_omitted_args_reject_repeated_param_impl():
    # `impl<A> T for W<A, A>` cannot cover `<W as T>::m` — an omitted
    # arg list cannot satisfy `A` at both positions; the trait default
    # answers instead.
    source = """
trait T { fn m(&self) {} }
struct W<A = u8, B = u16>(A, B);
impl<A> T for W<A, A> { fn m(&self) {} }
fn f() { <W as T>::m(&W(0u8, 0u16)); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    impl_m = next(
        b for b in report.bindings
        if b.name == "m" and b.span.start == source.rindex("fn m") + 3
    )
    call = _call(report, source, "<W as T>::m(&W(0u8, 0u16))")
    assert call.target != impl_m.id

def test_ufcs_const_expr_shift_arg_splits():
    # `{1 << 2}, N` — the shift's `<`/`>` inside braces are not
    # generic brackets; the trailing comma still splits.
    source = """
trait T { fn m(&self) {} }
struct W<const A: usize, const B: usize>;
impl<const N: usize> T for W<{1 << 2}, N> { fn m(&self) {} }
fn f() { <W<{1 << 2}, 4> as T>::m(&W::<{1 << 2}, 4>); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    impl_m = next(
        b for b in report.bindings
        if b.name == "m" and b.span.start == source.rindex("fn m") + 3
    )
    call = _call(report, source, "<W<{1 << 2}, 4> as T>::m(&W::<{1 << 2}, 4>)")
    assert call.target == impl_m.id

def test_type_alias_receiver_resolves_concrete_members():
    source = """
struct P;
type A = P;
impl P { fn m(&self) {} }
fn f(a: A) { a.m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    call = _call(report, source, "a.m()")
    assert call.target == m.id

def test_type_alias_chain_resolves_through_intermediate_aliases():
    source = """
struct P;
type A = B;
type B = P;
impl P { fn m(&self) {} }
fn f(a: A) { a.m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    call = _call(report, source, "a.m()")
    assert call.target == m.id

def test_cyclic_type_aliases_do_not_recurse():
    source = """
type A = B;
type B = A;
fn f(a: A) { }
"""
    report = build_rust_bindings(source, pointer_width=64)
    assert report is not None

def test_module_scoped_alias_body_resolves_in_its_own_scope():
    # `inner::A` where `inner::A = inner::P` must type the receiver as
    # the module's P, not the outer struct of the same name.
    source = """
struct P { x: i32 }
impl P { fn outer_m(&self) {} }
mod inner {
    struct P { y: i32 }
    impl P { fn inner_m(&self) {} }
    type A = P;
}
fn f(a: inner::A) { a.inner_m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    inner_m = next(b for b in report.bindings if b.name == "inner_m")
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "a.inner_m()"
    )
    assert call.target == inner_m.id

def test_associated_call_through_alias_spelling_resolves():
    # `impl A` writes members against the alias's target, so `A::m()`
    # must look them up through the same unwrap.
    source = """
struct P { x: i32 }
type A = P;
impl A { fn m(&self) {} }
fn f(a: A) { a.m(); }
fn g() { A::m(&a); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = next(b for b in report.bindings if b.name == "m")
    for text in ("a.m()", "A::m(&a)"):
        call = next(
            c for c in report.calls
            if source[c.span.start:c.span.end] == text
        )
        assert call.target == method.id

def test_glob_import_resolves_module_items():
    # `use m::*` exposes `m`'s items — a type annotation and a call
    # resolve to the module's declared bindings.
    source = """
mod m {
    pub struct P;
    pub fn go() {}
}
use m::*;
fn f() { let v: P = P; go(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    struct_p = next(
        b for b in report.bindings if b.name == "P" and b.kind == "struct"
    )
    go = next(
        b for b in report.bindings if b.name == "go" and b.kind == "function"
    )
    refs = _refs(report, source, "P")
    assert any(ref.binding_id == struct_p.id for ref in refs)
    call = _call(report, source, "go()")
    assert call.target == go.id

def test_glob_import_ambiguity_stays_unresolved():
    # Two glob-imported modules exporting the same name is ambiguous —
    # the name does not silently resolve to either.
    source = """
mod a { pub struct P; }
mod b { pub struct P; }
use a::*;
use b::*;
fn f() { let v: P = P; }
"""
    report = build_rust_bindings(source, pointer_width=64)
    refs = _refs(report, source, "P")
    assert not any(
        ref.binding_id
        in {b.id for b in report.bindings if b.name == "P"}
        for ref in refs
    )

def test_local_binding_shadows_glob_import():
    # An explicit local `P` wins over `use m::*`'s `P`.
    source = """
mod m { pub struct P; }
use m::*;
struct P;
fn f() { let v: P = P; }
"""
    report = build_rust_bindings(source, pointer_width=64)
    local_p = next(
        b for b in report.bindings
        if b.name == "P" and b.span.start == source.rindex("struct P") + 7
    )
    refs = _refs(report, source, "P")
    assert any(ref.binding_id == local_p.id for ref in refs)

def test_glob_import_resolves_at_declaration_scope_not_use_site():
    # `use m::*` binds to the `m` visible where the import is
    # declared — a same-named inner `mod m` at the call site does
    # not redirect the call.
    source = """
mod m { pub fn f() {} }
use m::*;
fn main() {
    mod m { pub fn wrong() {} }
    f();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    outer_f = next(
        b for b in report.bindings
        if b.name == "f" and b.kind == "function"
    )
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "f()"
    )
    assert call.target == outer_f.id

def test_glob_import_skips_private_items():
    source = """
mod m { fn priv_() {} pub fn f() {} }
use m::*;
fn main() { priv_(); f(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    calls = {
        source[c.span.start:c.span.end]: c for c in report.calls
    }
    assert calls["priv_()"].target == ""
    public_f = next(
        b for b in report.bindings
        if b.name == "f" and b.kind == "function"
    )
    assert calls["f()"].target == public_f.id

def test_glob_import_follows_pub_use_reexports():
    source = """
mod n { pub fn g() {} }
mod m { pub use n::*; }
use m::*;
fn main() { g(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    g = next(
        b for b in report.bindings
        if b.name == "g" and b.kind == "function"
    )
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "g()"
    )
    assert call.target == g.id

def test_glob_import_does_not_follow_private_reexports():
    source = """
mod n { pub fn g() {} }
mod m { use n::*; pub fn h() {} }
use m::*;
fn main() { g(); h(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    calls = {
        source[c.span.start:c.span.end]: c for c in report.calls
    }
    assert calls["g()"].target == ""
    h = next(
        b for b in report.bindings
        if b.name == "h" and b.kind == "function"
    )
    assert calls["h()"].target == h.id

def test_match_enum_variant_payload_is_typed():
    # `match e { E::C(p) => p.m() }` types `p` by the variant's
    # declared payload.
    source = """
enum E { C(P), D }
struct P;
impl P { fn m(&self) {} }
fn f(e: E) {
    match e { E::C(p) => p.m(), E::D => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = _bindings(report, "m", "associated_function")[0]
    call = _call(report, source, "p.m()")
    assert call.target == method.id

def test_let_condition_variant_payload_is_typed():
    source = """
enum E { C(P), D }
struct P;
impl P { fn m(&self) {} }
fn f(e: E) {
    if let E::C(p) = e { p.m(); }
    while let E::C(q) = e { q.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = _bindings(report, "m", "associated_function")[0]
    for text in ("p.m()", "q.m()"):
        assert _call(report, source, text).target == method.id

def test_match_named_variant_fields_are_typed():
    source = """
enum E { D { x: P } }
struct P;
impl P { fn m(&self) {} }
fn f(e: E) {
    match e { E::D { x } => x.m(), E::D { x: q } => q.m() }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = _bindings(report, "m", "associated_function")[0]
    for text in ("x.m()", "q.m()"):
        assert _call(report, source, text).target == method.id

def test_struct_pattern_fields_are_typed():
    source = """
struct W { p: P }
struct P;
impl P { fn m(&self) {} }
fn f(w: W) {
    let W { p } = w;
    p.m();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "p.m()").target == method.id

def test_pattern_head_must_name_the_scrutinee():
    # A pattern naming another type does not type its names by the
    # scrutinee — `p` stays unpinned.
    source = """
enum E { C(P), D }
enum F { G(P) }
struct P;
impl P { fn m(&self) {} }
fn f(e: E) {
    match e { F::G(p) => p.m(), _ => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    assert _call(report, source, "p.m()").target == ""

def test_generic_scrutinee_substitutes_field_types():
    source = """
struct W<T> { f: T }
struct P;
impl P { fn m(&self) {} }
fn f(w: W<P>) {
    match w { W { f } => f.m() }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "f.m()").target == method.id

def test_prelude_variant_payload_on_unresolvable_option():
    # `Option` has no record, but the spelled arg still types the
    # prelude payload — `Some(p)` binds `p: P`.
    source = """
struct P;
type O = Option<P>;
impl P { fn m(&self) {} }
fn f(o: O) {
    match o { Some(p) => p.m(), None => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = next(b for b in report.bindings if b.name == "m")
    assert _call(report, source, "p.m()").target == m.id

def test_reference_and_cast_receivers_are_typed():
    source = """
struct P;
impl P { fn m(&self) {} }
fn f(v: Vec<P>, x: u32) {
    let p = &v[0];
    p.m();
    let q = x as P;
    q.m();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "p.m()").target == method.id
    assert _call(report, source, "q.m()").target == method.id

def test_variant_constructor_initializer_types_the_binding():
    source = """
enum E { C(P), F }
struct P;
impl P { fn m(&self) {} }
fn f() {
    let e = E::C(P);
    match e { E::C(p) => p.m(), E::F => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "p.m()").target == method.id

def test_pattern_field_args_keep_string_type_id():
    # `items: Vec<P>` resolves args-only — the emitted fact keeps a
    # string (empty) type_id so the shared loader re-reads it.
    source = "struct W { items: Vec<P> } struct P; fn f(w: W) { let W { items } = w; }"
    report = build_rust_bindings(source, pointer_width=64)
    items = next(b for b in report.bindings if b.name == "items")
    assert isinstance(items.type.type_id, str)

def test_rest_pattern_skips_to_trailing_payload():
    source = """
enum E { V(A, B, C) }
struct A; struct B; struct C;
impl C { fn n(&self) {} }
fn f(e: E) {
    match e { E::V(.., x) => x.n() }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = next(b for b in report.bindings if b.name == "n")
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "x.n()"
    )
    assert call.target == method.id

def test_pub_tuple_fields_do_not_shift_positions():
    source = """
struct W(pub A, pub B);
struct A; struct B;
impl A { fn a(&self) {} }
impl B { fn b(&self) {} }
fn f(w: W) {
    match w { W(a, b) => { a.a(); b.b(); } }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    for text, name in (("a.a()", "a"), ("b.b()", "b")):
        method = next(b for b in report.bindings if b.name == name)
        call = next(
            c for c in report.calls
            if source[c.span.start:c.span.end] == text
        )
        assert call.target == method.id

def test_module_field_types_resolve_in_the_module_scope():
    source = """
mod m {
    pub struct P;
    impl P { fn m(&self) {} }
    pub struct W { pub f: P }
}
struct P;
impl P { fn n(&self) {} }
fn f(w: m::W) {
    match w { m::W { f } => f.m() }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = next(
        b for b in report.bindings
        if b.name == "m" and b.kind == "associated_function"
    )
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "f.m()"
    )
    assert call.target == method.id

def test_for_loop_binds_element_type_from_container_args():
    # `for p in v` types `p` as the container's element — `Vec<P>`
    # yields `P`, so `p.m()` binds.
    source = """
struct P { x: i32 }
impl P { fn m(&self) {} }
fn f(v: Vec<P>) {
    for p in v { p.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = next(b for b in report.bindings if b.name == "m")
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "p.m()"
    )
    assert call.target == method.id

def test_for_loop_binds_element_type_through_reference():
    source = """
struct P { x: i32 }
impl P { fn m(&self) {} }
fn f(v: Vec<P>) {
    for p in &v { p.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = next(b for b in report.bindings if b.name == "m")
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "p.m()"
    )
    assert call.target == method.id

def test_for_loop_binds_nested_container_elements():
    # `Vec<Vec<P>>` binds the inner loop variable to `Vec<P>` whose
    # own args still unwrap — `p2` is `P`.
    source = """
struct P { x: i32 }
impl P { fn m(&self) {} }
fn f(w: Vec<Vec<P>>) {
    for inner in w {
        for p2 in inner { p2.m(); }
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = next(b for b in report.bindings if b.name == "m")
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "p2.m()"
    )
    assert call.target == method.id

def test_for_loop_stays_opaque_on_ranges_and_undeclared_iterables():
    source = """
struct P { x: i32 }
impl P { fn m(&self) {} }
fn f() {
    for i in 0..10 { i.m(); }
    for s in ps { s.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    for text in ("i.m()", "s.m()"):
        call = next(
            c for c in report.calls
            if source[c.span.start:c.span.end] == text
        )
        assert call.target == ""

def test_for_loop_destructuring_pattern_stays_opaque():
    # `for P { x } in v` binds `x` to a field, not the element — its
    # type is unpinned so neither impl is picked up.
    source = """
struct P { x: i32 }
impl P { fn m(&self) {} }
impl i32 { fn bogus(&self) {} }
fn f(v: Vec<P>) {
    for P { x } in v { x.m(); x.bogus(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    for text in ("x.m()", "x.bogus()"):
        call = next(
            c for c in report.calls
            if source[c.span.start:c.span.end] == text
        )
        assert call.target == ""

def test_for_loop_over_map_stays_opaque():
    # Map iteration yields (K, V) pairs — a single-name loop stays
    # unpinned, while a destructured `(k, v)` binds the pair's ends.
    source = """
use std::collections::HashMap;
struct P;
impl P { fn m(&self) {} }
fn f(map: HashMap<u32, P>) {
    for e in map { e.m(); }
    for (k, v) in map { v.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "e.m()").target == ""
    assert _call(report, source, "v.m()").target == method.id

def test_for_loop_element_keeps_own_generic_args():
    # `Vec<W<u8>>` binds the element as `W` carrying "u8" — a
    # specialization impl's member resolves.
    source = """
struct W<T>(T);
impl W<u8> { fn m(&self) {} }
fn f(v: Vec<W<u8>>) {
    for w in v { w.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = next(b for b in report.bindings if b.name == "m")
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "w.m()"
    )
    assert call.target == method.id

def test_for_loop_mutable_binding_keeps_element_type():
    # `for mut p in v` still binds one identifier — `mut` only marks
    # it writable, so `p.m()` resolves.
    source = """
struct P { x: i32 }
impl P { fn m(&self) {} }
fn f(v: Vec<P>) {
    for mut p in v { p.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = next(b for b in report.bindings if b.name == "m")
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "p.m()"
    )
    assert call.target == method.id

def test_for_loop_ref_binding_stays_opaque():
    # `for ref p in v` binds `&P`, not `P` — the pattern is left
    # unpinned rather than guessing the reference's target.
    source = """
struct P { x: i32 }
impl P { fn m(&self) {} }
fn f(v: Vec<P>) {
    for ref p in v { p.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "p.m()"
    )
    assert call.target == ""

def test_use_target_resolves_scoped_calls():
    # `use m::P` — `P::new()` resolves the module's `P`, then the
    # associated function.
    source = """
mod m { pub struct P; impl P { pub fn new() -> P { P } pub fn v(&self) {} } }
use m::P;
fn f() { let x = P::new(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    new = next(
        b for b in report.bindings
        if b.name == "new" and b.span.start == source.rindex("fn new") + 3
    )
    call = _call(report, source, "P::new()")
    assert call.target == new.id

def test_use_alias_target_resolves_scoped_calls():
    # `use m::P as Q` — `Q::new()` resolves through the alias's path.
    source = """
mod m { pub struct P; impl P { pub fn new() -> P { P } } }
use m::P as Q;
fn f() { let x = Q::new(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    new = next(
        b for b in report.bindings
        if b.name == "new" and b.span.start == source.rindex("fn new") + 3
    )
    call = _call(report, source, "Q::new()")
    assert call.target == new.id

def test_use_target_types_annotated_receivers():
    # `let x: P` with `use m::P` — `x.v()` resolves the module
    # type's methods.
    source = """
mod m { pub struct P; impl P { pub fn v(&self) {} } }
use m::P;
fn f() { let x: P = P; x.v(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    v = next(
        b for b in report.bindings
        if b.name == "v" and b.span.start == source.rindex("fn v") + 3
    )
    call = _call(report, source, "x.v()")
    assert call.target == v.id

def test_use_target_unresolvable_module_stays_opaque():
    # A use whose module path does not resolve keeps scoped calls
    # opaque rather than guessing.
    source = """
mod m { pub struct P; impl P { pub fn new() -> P { P } } }
use other::P;
fn f() { let x = P::new(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = _call(report, source, "P::new()")
    assert call.kind == "opaque_path"

def test_use_target_resolves_at_declaration_scope():
    # `use m::P` resolves `m` where the import is declared — an
    # inner same-named `mod m` at the call site does not redirect.
    source = """
mod m { pub struct P; impl P { pub fn new() -> P { P } } }
use m::P;
fn main() { mod m { pub struct P; } let x = P::new(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    p = next(
        b for b in report.bindings
        if b.name == "new" and b.kind == "associated_function"
    )
    call = _call(report, source, "P::new()")
    assert call.target == p.id

def test_use_target_trait_alias_resolves_impl_members_and_ufcs():
    source = """
mod m { pub trait Tr { fn m(&self); } }
use m::Tr as Q;
struct P;
impl Q for P { fn m(&self) {} }
fn f(p: P) { p.m(); <P as Q>::m(&p); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    impl_m = next(
        b for b in report.bindings
        if b.name == "m"
        and b.span.start == source.rindex("fn m(&self) {}") + 3
    )
    assert _call(report, source, "p.m()").target == impl_m.id
    assert _call(report, source, "<P as Q>::m(&p)").target == impl_m.id

def test_use_target_trait_default_via_alias():
    source = """
mod m { pub trait Tr { fn m(&self) {} } }
use m::Tr as Q;
struct P;
impl Q for P {}
fn f(p: P) { p.m(); <P as Q>::m(&p); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    default_m = next(
        b for b in report.bindings
        if b.name == "m"
        and b.span.start == source.index("fn m(&self) {}") + 3
    )
    assert _call(report, source, "p.m()").target == default_m.id
    assert (
        _call(report, source, "<P as Q>::m(&p)").target == default_m.id
    )

def test_use_target_unresolvable_external_trait_keeps_impl_members():
    # `use ext::Trait` — `ext` cannot be resolved, but the imported
    # name is still the trait the impl matches against.
    source = """
use ext::Trait;
struct P;
impl Trait for P { fn m(&self) {} }
fn f(p: P) { p.m(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = next(b for b in report.bindings if b.name == "m")
    assert _call(report, source, "p.m()").target == m.id

def test_use_target_prefers_the_type_namespace_for_annotations():
    source = """
mod m {
    pub struct P;
    impl P { pub fn new() -> P { P } }
    pub const P: i32 = 0;
}
use m::P;
fn f() { let x: P = P::new(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    new = next(b for b in report.bindings if b.name == "new")
    assert _call(report, source, "P::new()").target == new.id

def test_parent_module_use_does_not_leak_into_child_module():
    # `use x::Tr` in `mod outer` names `Tr` in outer only — `p.m()`
    # inside `mod inner` cannot reach the trait's impl. The receiver's
    # `P` resolves through inner's own `use x::P`, so trait visibility
    # — not type resolution — is what keeps the call opaque.
    source = """
mod x { pub struct P; pub trait Tr { fn m(&self) {} } impl Tr for P {} }
mod outer {
    use x::Tr;
    mod inner {
        use x::P;
        fn f(p: P) { p.m(); }
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "p.m()"
    )
    assert call.target == ""

def test_child_module_use_makes_the_trait_visible():
    # Control case: the same receiver resolves when `mod inner`
    # imports the trait itself.
    source = """
mod x { pub struct P; pub trait Tr { fn m(&self) {} } impl Tr for P {} }
mod outer {
    mod inner {
        use x::P;
        use x::Tr;
        fn f(p: P) { p.m(); }
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = next(b for b in report.bindings if b.name == "m")
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "p.m()"
    )
    assert call.target == method.id

def test_prelude_some_pattern_binds_option_element():
    # `match opt { Some(p) => p.m() }` types `p` as Option's element —
    # the prelude constructor's payload is pinned by the scrutinee's
    # declared container.
    source = """
struct P;
impl P { fn m(&self) {} }
fn f(opt: Option<P>) {
    match opt { Some(p) => p.m(), None => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = next(b for b in report.bindings if b.name == "m")
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "p.m()"
    )
    assert call.target == method.id

def test_prelude_ok_err_patterns_bind_result_args():
    # `Ok(p)` binds Result's first arg, `Err(e)` its second — each
    # element keeps its declared position.
    source = """
struct P;
struct E;
impl P { fn m(&self) {} }
impl E { fn n(&self) {} }
fn f(r: Result<P, E>) {
    match r { Ok(p) => p.m(), Err(e) => e.n() }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = next(b for b in report.bindings if b.name == "m")
    n = next(b for b in report.bindings if b.name == "n")
    by_text = {
        source[c.span.start:c.span.end]: c for c in report.calls
    }
    assert by_text["p.m()"].target == m.id
    assert by_text["e.n()"].target == n.id

def test_prelude_pattern_in_let_while_and_let_else():
    # `if let Some(p)`, `while let Ok(p)` and `let Some(p) = ... else`
    # all pin the payload through the same scrutinee typing.
    source = """
struct P;
struct E;
impl P { fn m(&self) {} }
fn f(opt: Option<P>, r: Result<P, E>) {
    if let Some(p) = opt { p.m(); }
    while let Ok(q) = r { q.m(); }
    let Some(s) = opt else { return };
    s.m();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = next(b for b in report.bindings if b.name == "m")
    for text in ("p.m()", "q.m()", "s.m()"):
        call = next(
            c for c in report.calls
            if source[c.span.start:c.span.end] == text
        )
        assert call.target == method.id

def test_prelude_pattern_stays_opaque_on_wrong_container():
    # `Some(x)` only pins Option's element — on `Vec<P>` (or an
    # undeclared scrutinee) the payload name stays untyped.
    source = """
struct P;
impl P { fn m(&self) {} }
fn f(v: Vec<P>, mystery: Undeclared) {
    match v { Some(bad) => bad.m(), _ => {} }
    match mystery { Some(unknown) => unknown.m(), _ => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    for text in ("bad.m()", "unknown.m()"):
        call = next(
            c for c in report.calls
            if source[c.span.start:c.span.end] == text
        )
        assert call.target == ""

def test_bare_match_arm_on_prelude_container_keeps_valid_type_fact():
    # `match opt { x => }` on `Option<P>` binds `x` with an `unknown`
    # fact (no record exists for Option) — never a null type_id.
    source = """
struct P;
impl P { fn m(&self) {} }
fn f(o: Option<P>) {
    match o { x => x.m(), _ => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "x.m()"
    )
    assert call.target == ""
    assert all(
        isinstance(b.to_dict()["type"]["type_id"], str)
        for b in report.bindings
        if isinstance(b.to_dict().get("type"), dict)
        and "type_id" in b.to_dict()["type"]
    )

def test_user_defined_option_keeps_payload_unpinned():
    # A user `enum Option` whose `Some` doesn't resolve at the
    # pattern must not be typed by the std prelude payload.
    source = """
struct P;
struct Q;
impl Q { fn m(&self) {} }
enum Option<T> { Some(Q, T), None }
fn f(o: Option<P>) {
    match o { Some(q, _) => q.m(), None => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "q.m()"
    )
    assert call.target == ""

def test_prelude_payload_args_resolve_at_annotation_scope():
    # `o: Option<P>`'s `P` is the outer declaration — a `struct P`
    # shadowing it inside the body must not capture `Some(p)`'s
    # payload type.
    source = """
struct P;
impl P { fn outer(&self) {} }
fn f(o: Option<P>) {
    struct P;
    impl P { fn inner(&self) {} }
    match o { Some(p) => p.outer(), None => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    outer = next(b for b in report.bindings if b.name == "outer")
    inner = next(b for b in report.bindings if b.name == "inner")
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "p.outer()"
    )
    assert call.target == outer.id
    assert call.target != inner.id

def test_imported_enum_variant_binds_match_payload() -> None:
    source = """
    enum E { V(P), W }
    struct P;
    impl P { fn m(&self) {} }
    use E::V;
    fn f(e: E) {
        match e { V(p) => p.m(), _ => {} }
    }
    """
    report = build_rust_bindings(source, pointer_width=64)
    method = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "p.m()").target == method.id

def test_imported_enum_variant_through_module_chain() -> None:
    source = """
    mod m { pub enum E { V(P), W } }
    struct P;
    impl P { fn m(&self) {} }
    use m::E::V;
    fn f(e: m::E) {
        match e { V(p) => p.m(), _ => {} }
    }
    """
    report = build_rust_bindings(source, pointer_width=64)
    method = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "p.m()").target == method.id

def test_imported_variant_stays_opaque_on_other_type() -> None:
    source = """
    enum E { V(P), W }
    struct P;
    struct Other;
    impl P { fn m(&self) {} }
    use E::V;
    fn f(o: Other) {
        match o { V(p) => p.m(), _ => {} }
    }
    """
    report = build_rust_bindings(source, pointer_width=64)
    assert _call(report, source, "p.m()").target == ""

def test_imported_tuple_struct_still_binds_pattern_payload() -> None:
    source = """
    mod m { pub struct S(pub P); }
    struct P;
    impl P { fn m(&self) {} }
    use m::S;
    fn f(s: m::S) {
        match s { S(p) => p.m() }
    }
    """
    report = build_rust_bindings(source, pointer_width=64)
    method = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "p.m()").target == method.id

def test_self_named_use_path_does_not_recurse() -> None:
    # `use log::log` — an import whose path starts with its own name —
    # must not recurse when a container lookup re-resolves it.
    source = """
use log::log;
trait Tr { fn t(&self) {} }
use Tr as Q;
struct P;
impl Q for P {}
fn f(p: P) {
    p.t();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    assert _call(report, source, "p.t()").target == ""

def test_for_loop_iter_methods_bind_container_element():
    # `for p in v.iter()/iter_mut()/into_iter()` types `p` as the
    # container's element, same as iterating `v` directly.
    source = """
struct P;
impl P { fn m(&self) {} }
fn f(v: Vec<P>) {
    for p in v.iter() { p.m(); }
    for p2 in v.iter_mut() { p2.m(); }
    for p3 in v.into_iter() { p3.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = next(b for b in report.bindings if b.name == "m")
    for text in ("p.m()", "p2.m()", "p3.m()"):
        call = next(
            c for c in report.calls
            if source[c.span.start:c.span.end] == text
        )
        assert call.target == method.id

def test_for_loop_iter_on_array_element():
    source = """
struct P;
impl P { fn m(&self) {} }
fn f(arr: [P; 4]) {
    for p in arr.iter() { p.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = next(b for b in report.bindings if b.name == "m")
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "p.m()"
    )
    assert call.target == method.id

def test_for_loop_map_values_bind_value_type():
    # `m.values()` yields `V` of `HashMap<K, V>` — `m.keys()` reads
    # `K`, and `m.iter()`'s (K, V) pair stays unpinned.
    source = """
struct P;
struct K;
impl P { fn m(&self) {} }
impl K { fn k(&self) {} }
fn f(m: HashMap<K, P>) {
    for v in m.values() { v.m(); }
    for k in m.keys() { k.k(); }
    for pair in m.iter() { pair.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = next(b for b in report.bindings if b.name == "m")
    k = next(b for b in report.bindings if b.name == "k")
    by_text = {source[c.span.start:c.span.end]: c for c in report.calls}
    assert by_text["v.m()"].target == m.id
    assert by_text["k.k()"].target == k.id
    assert by_text["pair.m()"].target == ""

def test_for_loop_chained_iterator_stays_opaque():
    # `v.iter().enumerate()`/`v.iter().map(f)` yield a new iterator
    # shape — the element stays unpinned rather than guessed.
    source = """
struct P;
impl P { fn m(&self) {} }
fn f(v: Vec<P>) {
    for p in v.iter().enumerate() { p.m(); }
    for p2 in v.iter().map(|x| x) { p2.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    for text in ("p.m()", "p2.m()"):
        call = next(
            c for c in report.calls
            if source[c.span.start:c.span.end] == text
        )
        assert call.target == ""

def test_for_loop_over_call_return_binds_element() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
fn make() -> Vec<P> { Vec::new() }
fn f() {
    for p in make() { p.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "p.m()").target == method.id

def test_for_loop_declared_iter_method_stays_opaque() -> None:
    # A user-defined `iter()` need not yield the container's element —
    # the std recipe does not apply once the call resolves.
    source = """
struct P;
struct Q;
impl Q { fn m(&self) {} }
struct MyVec<T> { t: T }
impl MyVec<P> {
    fn iter(&self) -> Q { Q }
}
fn f(v: MyVec<P>) {
    for x in v.iter() { x.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    assert _call(report, source, "x.m()").target == ""

def test_for_loop_iter_element_resolves_at_annotation_scope() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
fn f(v: Vec<P>) {
    struct P;
    impl P { fn n(&self) {} }
    for x in v.iter() { x.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    call = _call(report, source, "x.m()")
    # The bound `m` is the outer `P`'s — the inner `P` only has `n`.
    assert call.target == m.id

def test_for_loop_declared_values_return_type_binds_element() -> None:
    source = """
struct V;
impl V { fn m(&self) {} }
struct MyMap;
impl MyMap {
    fn values(&self) -> Vec<V> { Vec::new() }
}
fn f(m: MyMap) {
    for v in m.values() { v.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "v.m()").target == method.id

def test_for_loop_over_extern_call_stays_opaque() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
struct W;
impl W {
    fn iter(&self) -> impl Iterator<Item = P> { std::iter::empty() }
}
fn f() {
    for x in std::iter::once(1) {
        x.m();
    }
    for p in P.make() {
        p.m();
    }
}
fn g(w: W) {
    // `impl Iterator<Item = P>` hides the element inside an
    // associated binding the model does not spell - opaque.
    for p in w.iter() {
        p.m();
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    assert _call(report, source, "x.m()").target == ""
    # An unresolved extern method's element also stays opaque.
    calls = [
        c for c in report.calls
        if source[c.span.start:c.span.end] == "p.m()"
    ]
    assert len(calls) == 2
    assert all(c.target == "" for c in calls)

def test_prelude_pattern_on_field_scrutinee() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
struct W { opt: Option<P> }
fn f(w: W) {
    match w.opt { Some(p) => p.m(), _ => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "p.m()").target == method.id

def test_prelude_pattern_on_self_field_scrutinee() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
struct W { opt: Option<P> }
impl W {
    fn f(&self) {
        if let Some(p) = self.opt { p.m(); }
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "p.m()").target == method.id

def test_prelude_pattern_on_nested_field_chain() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
struct W { opt: Option<P> }
struct G { w: W }
fn f(g: G) {
    match g.w.opt { Some(p) => p.m(), _ => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "p.m()").target == method.id

def test_prelude_pattern_on_wrong_field_container_stays_opaque() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
struct W { v: Vec<P> }
fn f(w: W) {
    match w.v { Some(p) => p.m(), _ => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    assert _call(report, source, "p.m()").target == ""

def test_field_scrutinee_payload_resolves_in_declaring_module() -> None:
    source = """
mod m {
    pub struct P;
    impl P { pub fn same(&self) {} }
    pub struct W { pub opt: Option<P> }
}
struct P;
impl P { fn same(&self) {} }
use m::W;
fn f(w: W) {
    match w.opt { Some(p) => p.same(), _ => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    module_p = next(
        b for b in report.bindings
        if b.name == "P" and b.kind == "struct" and b.scope is not None
        and b.scope.start != 0
    )
    module_same = min(
        (b for b in report.bindings if b.name == "same"),
        key=lambda b: int(b.id.split(":")[-3]),
    )
    bound = _bindings(report, "p", "local")
    assert bound and bound[0].type.type_id == module_p.id
    assert _call(report, source, "p.same()").target == module_same.id

def test_generic_field_scrutinee_payload_uses_use_site_args() -> None:
    source = """
struct T;
struct Q;
impl Q { fn q(&self) {} }
struct W<X> { opt: Option<X> }
fn f(w: W<Q>) {
    match w.opt { Some(p) => p.q(), _ => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    q = _bindings(report, "q", "associated_function")[0]
    bound = _bindings(report, "p", "local")
    assert bound and _call(report, source, "p.q()").target == q.id

def test_impl_param_reorder_maps_receiver_args() -> None:
    source = """
struct P;
impl P { fn pm(&self) {} }
struct Q;
impl Q { fn qm(&self) {} }
struct W<X, Y> { a: X, b: Y }
impl<A, B> W<B, A> {
    fn get(&self) -> A { panic!() }
}
fn f(w: W<P, Q>) {
    let t = w.get();
    t.qm();
    t.pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    qm = _bindings(report, "qm", "associated_function")[0]
    # impl<A,B> W<B,A> at W<P,Q>: return A is the second arg — Q.
    assert _call(report, source, "t.qm()").target == qm.id
    assert _call(report, source, "t.pm()").target == ""

def test_generic_field_substitution_is_simultaneous() -> None:
    source = """
struct B;
impl B { fn bm(&self) {} }
struct P;
impl P { fn pm(&self) {} }
struct W<A, B> { res: Result<A, B> }
fn f(w: W<B, P>) {
    match w.res {
        Ok(x) => x.bm(),
        Err(e) => e.pm(),
        _ => {}
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    bm = _bindings(report, "bm", "associated_function")[0]
    pm = _bindings(report, "pm", "associated_function")[0]
    # W<B, P> reads Result<A, B> as Result<B, P> — a sequential
    # rewrite would chain A→B then B→P into Result<P, P>.
    assert _call(report, source, "x.bm()").target == bm.id
    assert _call(report, source, "e.pm()").target == pm.id

def test_field_scrutinee_substituted_arg_resolves_fn_local_type() -> None:
    source = """
struct W<T> { opt: Option<T> }
fn f() {
    struct Q;
    impl Q { fn qm(&self) {} }
    let w: W<Q> = W { opt: Some(Q) };
    match w.opt {
        Some(p) => p.qm(),
        _ => {}
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    qm = _bindings(report, "qm", "associated_function")[0]
    # Q is fn-local — invisible at the field's declaration site, so
    # substituted args resolve at the receiver's annotation.
    assert _call(report, source, "p.qm()").target == qm.id

def test_field_scrutinee_fixed_type_keeps_declaring_scope() -> None:
    source = """
mod m {
    pub struct Q;
    pub struct W<A> { pub opt: Option<Q>, pub tag: A }
}
use m::W;
struct P;
struct Q;
impl m::Q { fn qm(&self) {} }
impl Q { fn lm(&self) {} }
fn f(w: W<P>) {
    match w.opt {
        Some(q) => { q.qm(); q.lm(); }
        _ => {}
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    qm = _bindings(report, "qm", "associated_function")[0]
    # `opt`'s `Option<Q>` mentions no substituted param — it resolves
    # in the field's declaring scope, so q binds to m::Q, not the
    # shadowing local Q.
    assert _call(report, source, "q.qm()").target == qm.id
    assert _call(report, source, "q.lm()").target == ""

def test_impl_const_generic_braced_param_substitutes() -> None:
    source = """
struct R<const N: usize>;
impl R<4> { fn rn(&self) {} }
struct W<const N: usize>;
impl<const N: usize> W<{N}> {
    fn get(&self) -> R<N> { panic!() }
}
fn f(w: W<4>) {
    w.get().rn();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    rn = _bindings(report, "rn", "associated_function")[0]
    # impl<const N> W<{N}> maps N→4 — the {N} spelling still matches.
    # `rn` lives only on `impl R<4>` so a missed substitution leaves
    # the return as R<N> and the call opaque.
    assert _call(report, source, "w.get().rn()").target == rn.id

def test_prelude_pattern_on_method_call_scrutinee() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
struct MyMap;
impl MyMap {
    fn get(&self) -> Option<P> { None }
}
fn f(m: MyMap) {
    match m.get() { Some(p) => p.m(), _ => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "p.m()").target == method.id

def test_prelude_pattern_on_result_returning_call() -> None:
    source = """
struct P;
struct E;
impl P { fn m(&self) {} }
impl E { fn e(&self) {} }
struct O;
impl O {
    fn try_get(&self) -> Result<P, E> { Err(E) }
}
fn f(o: O) {
    if let Err(e) = o.try_get() { e.e(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    method = _bindings(report, "e", "associated_function")[0]
    assert _call(report, source, "e.e()").target == method.id

def test_prelude_pattern_on_wrong_call_return_stays_opaque() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
struct MyMap;
impl MyMap {
    fn get(&self) -> Vec<P> { Vec::new() }
}
fn f(m: MyMap) {
    match m.get() { Some(p) => p.m(), _ => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    assert _call(report, source, "p.m()").target == ""

def test_method_call_scrutinee_payload_resolves_in_declaring_module() -> None:
    source = """
mod m {
    pub struct P;
    impl P { pub fn same(&self) {} }
    pub struct W;
    impl W { pub fn get(&self) -> Option<P> { Option::None } }
}
struct P;
impl P { fn same(&self) {} }
use m::W;
fn f(w: W) {
    match w.get() { Some(p) => p.same(), _ => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    module_same = min(
        (b for b in report.bindings if b.name == "same"),
        key=lambda b: int(b.id.split(":")[-3]),
    )
    assert _call(report, source, "p.same()").target == module_same.id

def test_method_call_scrutinee_unwraps_turbofish() -> None:
    source = """
struct P;
impl P { fn same(&self) {} }
struct W;
impl W { fn get(&self) -> Option<P> { Option::None } }
fn f(w: W) {
    match w.get::<u8>() { Some(p) => p.same(), _ => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    same = _bindings(report, "same", "associated_function")[0]
    assert _call(report, source, "p.same()").target == same.id

def test_parenthesized_field_call_reads_the_field_fn_return():
    # `(w.get)()` invokes the field's function pointer — a
    # struct_field of that name shadows the same-named method.
    source = """
struct P; struct Q;
impl P { fn same(&self) {} }
impl Q { fn same(&self) {} }
struct W {
    get: fn() -> Option<Q>,
}
impl W {
    fn get(&self) -> Option<P> { None }
}
fn f(w: W) {
    match (w.get)() {
        Some(p) => { p.same(); }
        _ => {}
    }
    match w.get() {
        Some(p) => { p.same(); }
        _ => {}
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    methods = [b for b in report.bindings if b.name == "same"]
    p_same, q_same = methods[0], methods[1]
    calls = [
        c for c in report.calls
        if source[c.span.start:c.span.end] == "p.same()"
    ]
    assert calls[0].target == q_same.id
    assert calls[1].target == p_same.id

def test_for_tuple_pattern_binds_map_pair() -> None:
    source = """
struct K;
struct V;
impl K { fn k(&self) {} }
impl V { fn v(&self) {} }
fn f(m: HashMap<K, V>) {
    for (k, v) in m { k.k(); v.v(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    k = _bindings(report, "k", "associated_function")[0]
    v = _bindings(report, "v", "associated_function")[0]
    assert _call(report, source, "k.k()").target == k.id
    assert _call(report, source, "v.v()").target == v.id

def test_for_tuple_pattern_binds_map_iter_pair() -> None:
    source = """
struct K;
struct V;
impl K { fn k(&self) {} }
impl V { fn v(&self) {} }
fn f(m: std::collections::BTreeMap<K, V>) {
    for (k, v) in m.iter() { k.k(); v.v(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    k = _bindings(report, "k", "associated_function")[0]
    v = _bindings(report, "v", "associated_function")[0]
    assert _call(report, source, "k.k()").target == k.id
    assert _call(report, source, "v.v()").target == v.id

def test_for_tuple_pattern_wrong_arity_stays_opaque() -> None:
    source = """
struct K;
struct V;
impl V { fn v(&self) {} }
fn f(m: HashMap<K, V>) {
    for (k, v, x) in m { x.v(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    assert _call(report, source, "x.v()").target == ""

def test_for_tuple_pattern_declared_iter_stays_opaque() -> None:
    source = """
struct K;
struct V;
struct Q;
impl V { fn v(&self) {} }
struct M;
impl M { fn iter(&self) -> Q { Q } }
fn f(m: M) {
    for (k, v) in m.iter() { v.v(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    assert _call(report, source, "v.v()").target == ""

def test_for_tuple_pattern_substitutes_generic_map_alias() -> None:
    source = """
struct K;
struct V;
impl K { fn k(&self) {} }
impl V { fn v(&self) {} }
type Flip<A, B> = HashMap<B, A>;
fn f(m: Flip<K, V>) {
    for (k, v) in m { v.k(); k.v(); k.k(); v.v(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    k = _bindings(report, "k", "associated_function")[0]
    v = _bindings(report, "v", "associated_function")[0]
    # Flip<K, V> iterates (V, K) pairs — the alias's args swap.
    assert _call(report, source, "v.k()").target == k.id
    assert _call(report, source, "k.v()").target == v.id
    assert _call(report, source, "k.k()").target == ""
    assert _call(report, source, "v.v()").target == ""

def test_for_tuple_pattern_binds_mut_borrowed_map() -> None:
    source = """
struct K;
struct V;
impl K { fn k(&self) {} }
impl V { fn v(&self) {} }
fn f(m: HashMap<K, V>) {
    for (k, v) in &mut m { k.k(); v.v(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    k = _bindings(report, "k", "associated_function")[0]
    v = _bindings(report, "v", "associated_function")[0]
    assert _call(report, source, "k.k()").target == k.id
    assert _call(report, source, "v.v()").target == v.id

def test_tuple_pattern_binds_elements_by_position():
    source = """\
struct P;
impl P { fn m(&self) {} }
struct Q;
impl Q { fn q(&self) {} }
fn f(t: (P, Q)) {
    let (a, b) = t;
    a.m();
    b.q();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = next(b for b in report.bindings if b.name == "m")
    q = next(b for b in report.bindings if b.name == "q")
    calls = [c for c in report.calls if source[c.span.start:c.span.end].endswith(("m()", "q()"))]
    assert [c.target for c in calls] == [m.id, q.id]

def test_tuple_pattern_in_match_and_nested_variant():
    source = """\
struct P;
impl P { fn m(&self) {} }
enum E { V(P), W }
fn f(t: (E, P)) {
    match t {
        (E::V(p), _) => p.m(),
        _ => (),
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = next(b for b in report.bindings if b.name == "m")
    calls = [c for c in report.calls if source[c.span.start:c.span.end].endswith("m()")]
    assert [c.target for c in calls] == [m.id]

def test_tuple_pattern_rest_binds_last_element():
    source = """\
struct P;
impl P { fn m(&self) {} }
struct Q;
impl Q { fn q(&self) {} }
fn f(t: (P, P, Q)) {
    let (h, .., last) = t;
    last.q();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    q = next(b for b in report.bindings if b.name == "q")
    calls = [c for c in report.calls if source[c.span.start:c.span.end].endswith("q()")]
    assert [c.target for c in calls] == [q.id]

def test_tuple_pattern_short_pattern_stays_unpinned():
    source = """\
struct P;
impl P { fn m(&self) {} }
fn f(t: (P, P, P)) {
    let (a, b) = t;
    a.m();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    calls = [c for c in report.calls if source[c.span.start:c.span.end].endswith("m()")]
    assert calls and all(c.target in {"", None} for c in calls)

def test_for_tuple_pattern_binds_vec_of_tuples() -> None:
    source = """\
struct P;
impl P { fn m(&self) {} }
struct Q;
impl Q { fn q(&self) {} }
fn f(v: Vec<(P, Q)>) {
    for (a, b) in &v {
        a.m();
        b.q();
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = next(b for b in report.bindings if b.name == "m")
    q = next(b for b in report.bindings if b.name == "q")
    calls = [
        c
        for c in report.calls
        if source[c.span.start : c.span.end].endswith(("m()", "q()"))
    ]
    assert [c.target for c in calls] == [m.id, q.id]

def test_prelude_pattern_on_call_returned_option_tuple() -> None:
    source = """\
struct P;
impl P { fn m(&self) {} }
struct Q;
impl Q { fn q(&self) {} }
fn make_opt() -> Option<(P, Q)> { None }
fn f() {
    if let Some((a, b)) = make_opt() {
        a.m();
        b.q();
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = next(b for b in report.bindings if b.name == "m")
    q = next(b for b in report.bindings if b.name == "q")
    calls = [
        c
        for c in report.calls
        if source[c.span.start : c.span.end].endswith(("m()", "q()"))
    ]
    assert [c.target for c in calls] == [m.id, q.id]

def test_err_pattern_on_call_returned_result() -> None:
    source = """\
struct P;
impl P { fn m(&self) {} }
struct E2;
impl E2 { fn e(&self) {} }
fn mk() -> Result<P, E2> { Err(E2) }
fn f() {
    match mk() {
        Ok(p) => p.m(),
        Err(e) => e.e(),
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = next(b for b in report.bindings if b.name == "m")
    e = next(b for b in report.bindings if b.name == "e")
    calls = [
        c
        for c in report.calls
        if source[c.span.start : c.span.end].endswith(("m()", "e()"))
    ]
    assert [c.target for c in calls] == [m.id, e.id]

def test_tuple_pattern_prelude_variant_in_tuple() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
fn f(t: (Option<P>, P)) {
    match t {
        (Some(p), _) => p.m(),
        _ => (),
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "p.m()").target == m.id

def test_let_pattern_inferred_annotation_slots() -> None:
    source = """
struct P;
struct Q;
impl P { fn m(&self) {} }
impl Q { fn q(&self) {} }
fn f(t: (P, Q)) {
    let (a, b): (_, _) = t;
    a.m(); b.q();
    let (c, d): (P, _) = t;
    c.m(); d.q();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    q = _bindings(report, "q", "associated_function")[0]
    assert _call(report, source, "a.m()").target == m.id
    assert _call(report, source, "b.q()").target == q.id
    assert _call(report, source, "c.m()").target == m.id
    assert _call(report, source, "d.q()").target == q.id

def test_for_tuple_pattern_binds_map_pair_around_rest() -> None:
    source = """
struct P;
struct Q;
impl P { fn m(&self) {} }
impl Q { fn q(&self) {} }
use std::collections::HashMap;
fn f(m: HashMap<P, Q>) {
    for (k, .., v) in m { k.m(); v.q(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    q = _bindings(report, "q", "associated_function")[0]
    assert _call(report, source, "k.m()").target == m.id
    assert _call(report, source, "v.q()").target == q.id

def test_for_tuple_pattern_binds_partial_map_pair() -> None:
    source = """
struct P;
struct Q;
impl P { fn m(&self) {} }
impl Q { fn q(&self) {} }
use std::collections::HashMap;
use std::collections::BTreeMap;
fn f(m: HashMap<P, Q>, t: BTreeMap<P, Q>) {
    for (k, ..) in m { k.m(); }
    for (.., v) in t { v.q(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    q = _bindings(report, "q", "associated_function")[0]
    assert _call(report, source, "k.m()").target == m.id
    assert _call(report, source, "v.q()").target == q.id

def test_slice_pattern_binds_element_types() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
fn f(arr: [P; 3], v: Vec<P>) {
    let [a, b, c] = arr;
    a.m();
    let [x, y, ..] = arr;
    x.m();
    if let [s, ..] = v { s.m(); }
    let [h @ .., t] = arr;
    t.m();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    for text in ("a.m()", "x.m()", "s.m()", "t.m()"):
        assert _call(report, source, text).target == m.id

def test_slice_pattern_nested_element_types() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
fn f(v: Vec<Vec<P>>) {
    let [inner] = v;
    inner.m();
    let [deep, ..] = inner;
    deep.m();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    # `inner` is Vec<P> — not P itself — so inner.m() stays unpinned.
    assert _call(report, source, "inner.m()").target == ""
    assert _call(report, source, "deep.m()").target == m.id

def test_slice_pattern_rest_binding_stays_opaque() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
fn f(arr: [P; 3]) {
    let [h @ .., t] = arr;
    h.m();
    t.m();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    # `h` binds the rest slice `[P]`, not `P` — stays opaque.
    assert _call(report, source, "h.m()").target == ""
    assert _call(report, source, "t.m()").target == m.id

def test_slice_pattern_element_resolves_at_annotation_scope() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
fn g(arr: [P; 1]) {
    {
        struct P;
        impl P { fn m(&self) {} }
        let [p] = arr;
        p.m();
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    ms = _bindings(report, "m", "associated_function")
    outer = min(ms, key=lambda b: int(b.id.split(":")[-3]))
    # The element resolves the spelled P at arr's annotation, not the
    # inner block's shadow.
    assert _call(report, source, "p.m()").target == outer.id

def test_unwrap_receivers_yield_option_result_payload() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
struct E;
impl E { fn e(&self) {} }
fn f(opt: Option<P>, res: Result<P, E>, v: Vec<P>) {
    opt.unwrap().m();
    res.unwrap_or(P).m();
    res.expect("x").m();
    res.unwrap_err().e();
    v.unwrap().m();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    e = _bindings(report, "e", "associated_function")[0]
    assert _call(report, source, "opt.unwrap().m()").target == m.id
    assert _call(report, source, "res.unwrap_or(P).m()").target == m.id
    assert _call(report, source, 'res.expect("x").m()').target == m.id
    assert _call(report, source, "res.unwrap_err().e()").target == e.id
    # Vec<P> exposes no `unwrap` — stays opaque.
    assert _call(report, source, "v.unwrap().m()").target == ""

def test_try_operator_receiver_yields_payload() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
struct W { opt: Option<P> }
fn g(res: Result<P, E>) -> Result<(), E> {
    res?.m();
    Ok(())
}
fn h(w: W) {
    w.opt?.m();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "res?.m()").target == m.id
    assert _call(report, source, "w.opt?.m()").target == m.id

def test_unwrap_receiver_of_array_payload_indexes_the_element() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
struct W;
impl W {
    fn pick(&self) -> Option<[P; 2]> { None }
    fn res(&self) -> Result<[P; 2], u8> { Err(0) }
}
fn f(w: W, o: Option<[P; 2]>, r: Result<[P; 2], u8>) -> u8 {
    o.unwrap()[0].m();
    r.unwrap()[1].m();
    o?[0].m();
    match w.pick() {
        Some(a) => { a[0].m(); }
        _ => {}
    }
    if let Ok(a) = w.res() {
        a[1].m();
    }
    0
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    raw = source.encode()
    calls = [
        call
        for call in report.calls
        if raw[call.span.start : call.span.end].decode().endswith(".m()")
    ]
    assert len(calls) == 5
    assert all(c.target == m.id for c in calls)

def test_for_element_through_preserving_iter_adaptors() -> None:
    source = """\
struct P;
impl P { fn m(&self) {} }
fn f(v: Vec<P>) {
    for p in v.iter().rev() { p.m(); }
    for p in v.iter().skip(1).take(2) { p.m(); }
    for p in v.iter().filter(|x| true) { p.m(); }
    for p in v.as_slice() { p.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = next(b for b in report.bindings if b.name == "m")
    calls = [
        c
        for c in report.calls
        if source[c.span.start : c.span.end].endswith("m()")
    ]
    assert [c.target for c in calls] == [m.id] * 4

def test_for_element_map_adaptor_stays_unpinned() -> None:
    source = """\
struct P;
impl P { fn m(&self) {} }
fn f(v: Vec<P>) {
    for p in v.iter().map(|x| x) { p.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = next(
        c
        for c in report.calls
        if source[c.span.start : c.span.end].endswith("m()")
    )
    assert call.target == ""

def test_for_enumerate_binds_value_by_element_type() -> None:
    source = """\
struct P;
impl P { fn m(&self) {} }
fn f(v: Vec<P>) {
    for (i, p) in v.iter().enumerate() {
        p.m();
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = next(b for b in report.bindings if b.name == "m")
    call = next(
        c
        for c in report.calls
        if source[c.span.start : c.span.end].endswith("m()")
    )
    assert call.target == m.id

def test_for_declared_adaptor_uses_its_own_return_type() -> None:
    source = """\
struct P;
impl P { fn m(&self) {} }
struct Q;
impl Q { fn q(&self) {} }
struct W<T>;
impl<T> W<T> {
    fn rev(&self) -> Vec<Q> { vec![] }
    fn as_slice(&self) -> &[Q] { &[] }
}
fn f(w: W<P>) {
    for q in w.rev() { q.q(); }
    for q in w.as_slice() { q.q(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    q = next(b for b in report.bindings if b.name == "q")
    calls = [
        c
        for c in report.calls
        if source[c.span.start : c.span.end].endswith("q()")
    ]
    assert [c.target for c in calls] == [q.id, q.id]

def test_for_custom_container_args_do_not_leak_as_tuple_elements() -> None:
    source = """\
struct P;
impl P { fn m(&self) {} }
struct Q;
struct W<T>;
fn f(w: W<(P, Q)>) {
    for (a, b) in w.iter() { a.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = next(
        c
        for c in report.calls
        if source[c.span.start : c.span.end].endswith("m()")
    )
    assert call.target == ""

def test_for_enumerate_declared_inner_iter_stays_opaque() -> None:
    source = """\
struct P;
impl P { fn m(&self) {} }
struct Q;
struct R;
impl R { fn iter(&self) -> std::vec::IntoIter<Q> { todo!() } }
fn f(r: R) {
    for (i, p) in r.iter().enumerate() { p.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    call = next(
        c
        for c in report.calls
        if source[c.span.start : c.span.end].endswith("m()")
    )
    assert call.target == ""

def test_let_pattern_uses_inline_annotation() -> None:
    source = """\
struct P;
impl P { fn m(&self) {} }
struct Q;
impl Q { fn q(&self) {} }
struct W { x: P, y: Q }
fn h() {
    let (a, b): (P, P) = (P, P);
    a.m();
    b.m();
    let Some(v): Option<P> = Some(P);
    v.m();
    let W { x, y }: W = W { x: P, y: Q };
    x.m();
    y.q();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = next(b for b in report.bindings if b.name == "m")
    q = next(b for b in report.bindings if b.name == "q")
    calls = [
        c
        for c in report.calls
        if source[c.span.start : c.span.end].endswith(("m()", "q()"))
    ]
    assert [c.target for c in calls] == [m.id, m.id, m.id, m.id, q.id]

def test_for_tuple_pattern_binds_zipped_elements() -> None:
    source = """
struct P;
struct Q;
impl P { fn p(&self) {} }
impl Q { fn q(&self) {} }
fn f(v: Vec<P>, u: Vec<Q>, w: Vec<Vec<P>>) {
    for (a, b) in v.iter().zip(u.iter()) { a.p(); b.q(); }
    for (x, y) in w.iter().zip(u.iter()) { x[0].p(); }
    for (a, b) in v.iter().rev().zip(u.iter().take(2)) { a.p(); b.q(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    p = _bindings(report, "p", "associated_function")[0]
    q = _bindings(report, "q", "associated_function")[0]
    assert _call(report, source, "a.p()").target == p.id
    assert _call(report, source, "b.q()").target == q.id
    assert _call(report, source, "x[0].p()").target == p.id

def test_for_tuple_pattern_binds_zipped_map_pair() -> None:
    source = """
struct P;
struct Q;
impl P { fn p(&self) {} }
impl Q { fn q(&self) {} }
use std::collections::HashMap;
fn f(m: HashMap<Q, P>, v: Vec<P>) {
    for ((k, val), o) in m.iter().zip(v.iter()) {
        k.q(); val.p(); o.p();
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    p = _bindings(report, "p", "associated_function")[0]
    q = _bindings(report, "q", "associated_function")[0]
    assert _call(report, source, "k.q()").target == q.id
    assert _call(report, source, "val.p()").target == p.id
    assert _call(report, source, "o.p()").target == p.id

def test_tuple_index_on_spelled_zip_pair_binding() -> None:
    source = """
struct P;
struct Q;
impl P { fn m(&self) {} }
impl Q { fn q(&self) {} }
fn f(a: Vec<P>, b: Vec<Q>) {
    for p in a.iter().zip(b.iter()) {
        p.0.m();
        p.1.q();
    }
    for t in a.iter().enumerate() {
        t.1.m();
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    q = _bindings(report, "q", "associated_function")[0]
    assert _call(report, source, "p.0.m()").target == m.id
    assert _call(report, source, "p.1.q()").target == q.id
    assert _call(report, source, "t.1.m()").target == m.id

def test_zip_named_tuple_struct_args_not_fields():
    source = """
struct P;
struct Q;
impl P { fn pm(&self) {} }
impl Q { fn qm(&self) {} }
struct W<T>(Q, T);
fn f(w: W<(P, Q)>) {
    w.0.qm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    qm = _bindings(report, "qm", "associated_function")[0]
    call = _call(report, source, "w.0.qm()")
    # `W<T>(Q, T)` declares field 0 as `Q` — the generic args are not
    # field types, so the receiver never spells `P`.
    assert call.target in {"", qm.id}
    assert call.target != _bindings(
        report, "pm", "associated_function"
    )[0].id

def test_zip_custom_container_stays_opaque():
    source = """
struct P;
struct Q;
impl P { fn pm(&self) {} }
impl Q { fn qm(&self) {} }
struct W<T>(T);
fn f(w: W<P>, v: Vec<Q>) {
    for (a, b) in w.iter().zip(v.iter()) {
        a.pm();
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    # `W<P>` can Deref to `[Q]` — its args are not the element type.
    assert _call(report, source, "a.pm()").target != pm.id

def test_zip_element_resolves_at_annotation_scope():
    source = """
mod outer { pub struct P; impl P { pub fn pm(&self) {} } }
use outer::P;
fn f(arg: Vec<P>, v: Vec<u8>) {
    {
        struct P;
        impl P { fn other(&self) {} }
        for (a, b) in arg.iter().zip(v.iter()) {
            a.pm();
        }
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    # `arg`'s `P` was written in the signature — the inner block's
    # `struct P` must not shadow the spelled element.
    assert _call(report, source, "a.pm()").target == pm.id

def test_index_receiver_element_through_import_and_scope() -> None:
    source = """
mod m {
    pub struct P;
    impl P { pub fn p(&self) {} }
}
use m::P;
fn f(items: Vec<P>, v: Vec<m::P>, nested: Vec<Vec<P>>) {
    items[0].p();
    v[0].p();
    nested[0][1].p();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    p = _bindings(report, "p", "associated_function")[0]
    assert _call(report, source, "items[0].p()").target == p.id
    assert _call(report, source, "v[0].p()").target == p.id
    assert _call(report, source, "nested[0][1].p()").target == p.id

def test_index_field_element_resolves_in_the_fields_module() -> None:
    source = """
mod m {
    pub struct Fixed<T> { pub x: T }
    impl<T> Fixed<T> { pub fn pm(&self) {} }
    pub struct W<T> { pub items: Vec<Fixed<T>> }
}
struct Fixed;
impl Fixed { fn wrong(&self) {} }
use m::W;
fn g(w: W<i32>) {
    w.items[0].pm();
    w.items[0].wrong();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    # `Fixed` was spelled in `mod m`'s scope — the use-site local
    # `struct Fixed` must not shadow it.
    assert _call(report, source, "w.items[0].pm()").target == pm.id
    assert _call(report, source, "w.items[0].wrong()").target == ""

def test_index_field_element_across_newline_args() -> None:
    source = """
mod m {
    pub struct P;
    impl P { pub fn wrong(&self) {} }
    pub struct W<T> { pub items: Vec<
T
> }
}
struct P;
impl P { fn pm(&self) {} }
fn f(w: m::W<P>) {
    w.items[0].pm();
    w.items[0].wrong();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    assert _call(report, source, "w.items[0].pm()").target == pm.id
    assert _call(report, source, "w.items[0].wrong()").target == ""

def test_index_element_resolves_at_annotation_scope():
    source = """
mod m { pub struct P; impl P { pub fn p(&self) {} } }
fn f(items: Vec<m::P>) {
    mod m { pub struct P; impl P { pub fn other(&self) {} } }
    items[0].p();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    p = _bindings(report, "p", "associated_function")[0]
    assert _call(report, source, "items[0].p()").target == p.id

def test_get_on_prelude_containers_heads_option() -> None:
    source = """
struct P;
struct Q;
impl P { fn m(&self) {} }
impl Q { fn q(&self) {} }
use std::collections::HashMap;
fn f(v: Vec<P>, m: HashMap<P, Q>, i: usize) {
    if let Some(p) = v.get(i) { p.m(); }
    match m.get(&i) {
        Some(q) => q.q(),
        None => (),
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    q = _bindings(report, "q", "associated_function")[0]
    assert _call(report, source, "p.m()").target == m.id
    assert _call(report, source, "q.q()").target == q.id

def test_get_on_declared_method_keeps_member_resolution() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
struct C;
impl C { fn get(&self) -> Option<P> { None } }
fn f(c: C) {
    c.get();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    get = _bindings(report, "get", "associated_function")[0]
    assert _call(report, source, "c.get()").target == get.id

def test_option_head_methods_on_prelude_containers() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
fn f(v: Vec<P>) {
    if let Some(p) = v.first() { p.m(); }
    if let Some(p) = v.last() { p.m(); }
    if let Some(p) = v.pop() { p.m(); }
}
use std::collections::HashMap;
fn g(m: HashMap<u32, P>) {
    if let Some(p) = m.pop() { p.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    calls = [
        call
        for call in report.calls
        if source.encode()[call.span.start : call.span.end] == b"p.m()"
    ]
    assert [c.target for c in calls[:3]] == [m.id] * 3
    # HashMap has no `pop` — the Some payload stays untyped.
    assert not calls[3].target

def test_unwrap_receiver_resolves_at_return_annotation():
    source = """
use std::option::Option;
struct Q;
impl Q { fn qm(&self) {} }
struct W;
impl W { fn get(&self) -> Option<Q> { None } }
fn f(w: W) {
    struct Q;
    impl Q { fn bad(&self) {} }
    w.get().unwrap().qm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    qm = _bindings(report, "qm", "associated_function")[0]
    assert _call(report, source, "w.get().unwrap().qm()").target == qm.id

def test_reference_pattern_tuple_bindings() -> None:
    source = """
struct P;
struct Q;
impl P { fn m(&self) {} }
impl Q { fn q(&self) {} }
fn f() {
    let t: (P, Q) = (P, Q);
    let &(x, y) = &t;
    x.m(); y.q();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    q = _bindings(report, "q", "associated_function")[0]
    assert _call(report, source, "x.m()").target == m.id
    assert _call(report, source, "y.q()").target == q.id

def test_reference_pattern_on_option_match() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
fn f(o: Option<P>) {
    match &o {
        Some(p) => p.m(),
        None => (),
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "p.m()").target == m.id

def test_reference_pattern_whole_binding_tuple_index() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
fn f() {
    let t: (P, P) = (P, P);
    let &w = &t;
    w.0.m(); w.1.m();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    assert _call(report, source, "w.0.m()").target == m.id
    assert _call(report, source, "w.1.m()").target == m.id

def test_iterator_chain_and_next_head_option() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
fn f(v: Vec<P>) {
    for p in v.iter().chain(v.iter()) { p.m(); }
    let mut it = v.iter();
    while let Some(p) = it.next() { p.m(); }
    for p in it { p.m(); }
    if let Some(p) = v.iter().next() { p.m(); }
    if let Some(p) = v.next() { p.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    calls = [
        call
        for call in report.calls
        if source.encode()[call.span.start : call.span.end] == b"p.m()"
    ]
    assert len(calls) == 5
    assert [call.target for call in calls] == [m.id] * 5

def test_option_head_methods_on_vecdeque_and_map_remove() -> None:
    source = """
struct P;
impl P { fn m(&self) {} }
use std::collections::{VecDeque, HashMap};
fn f(d: VecDeque<P>, m: HashMap<u32, P>) {
    if let Some(p) = d.front() { p.m(); }
    if let Some(p) = d.back() { p.m(); }
    if let Some(p) = d.pop_front() { p.m(); }
    if let Some(p) = d.get(0) { p.m(); }
    if let Some(p) = m.remove(&0) { p.m(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    m = _bindings(report, "m", "associated_function")[0]
    calls = [
        call
        for call in report.calls
        if source.encode()[call.span.start : call.span.end] == b"p.m()"
    ]
    assert len(calls) == 5
    assert [call.target for call in calls] == [m.id] * 5

def test_for_element_resolves_at_receiver_annotation():
    source = """
struct Q;
impl Q { fn qm(&self) {} }
struct W<T> { xs: Vec<T> }
fn f(w: W<Q>) {
    for q in w.xs { q.qm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    qm = _bindings(report, "qm", "associated_function")[0]
    assert _call(report, source, "q.qm()").target == qm.id

def test_option_transforms_and_cloned():
    source = """
struct P;
struct E;
impl P { fn pm(&self) {} }
impl E { fn em(&self) {} }
fn f(o: Option<P>, mut o2: Option<P>, r: Result<P, E>, v: Vec<P>, d: P) {
    if let Some(p) = r.ok() { p.pm(); }
    if let Some(e) = r.err() { e.em(); }
    if let Some(p) = o2.take() { p.pm(); }
    let p = o.unwrap_or(d);
    p.pm();
    for p in v.iter().cloned() { p.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    em = _bindings(report, "em", "associated_function")[0]
    calls = [
        call
        for call in report.calls
        if source.encode()[call.span.start : call.span.end] == b"p.pm()"
    ]
    assert len(calls) == 4
    assert [call.target for call in calls] == [pm.id] * 4
    assert _call(report, source, "e.em()").target == em.id

def test_option_ok_stays_opaque():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(o: Option<P>) {
    if let Some(p) = o.ok() { p.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    calls = [call for call in report.calls if call.target == pm.id]
    # `Option` has no `ok()` — the unresolved extension call pins
    # no payload.
    assert calls == []

def test_chunk_and_window_slice_elements():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(v: Vec<P>) {
    for c in v.chunks(2) {
        c[0].pm();
        for x in c.iter() { x.pm(); }
    }
    for w in v.windows(3) { w[0].pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    calls = [
        call
        for call in report.calls
        if call.target == pm.id
    ]
    # c[0], x (c.iter), w[0] — all P.
    assert len(calls) == 3
    assert _call(report, source, "c[0].pm()").target == pm.id
    assert _call(report, source, "x.pm()").target == pm.id
    assert _call(report, source, "w[0].pm()").target == pm.id

def test_chunk_spelling_honors_declared_and_bound_methods():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct Q;
impl Q { fn qm(&self) {} }
struct W<T> { _m: T }
impl<T> W<T> { fn chunks(&self, n: usize) -> Vec<Vec<Q>> { vec![] } }
fn f(v: Vec<P>, w: W<P>) {
    let it = v.chunks(2);
    for c in it { c[0].pm(); }
    for c in w.chunks(2) { c[0].qm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    qm = _bindings(report, "qm", "associated_function")[0]
    chunks = _bindings(report, "chunks", "associated_function")[0]
    # `let it = v.chunks(2)` keeps the slice element — `c[0]` is P.
    assert _call(report, source, "c[0].pm()").target == pm.id
    # A declared `W<T>::chunks` wins over the std recipe — its
    # `Vec<Vec<Q>>` return types the element as `Q`.
    assert _call(report, source, "w.chunks(2)").target == chunks.id
    assert _call(report, source, "c[0].qm()").target == qm.id

def test_chunk_iterator_alias_keeps_slice_elements():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(v: Vec<P>) {
    let it = v.chunks(2);
    let it2 = it;
    for c in it2 { c[0].pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    # `let it2 = it` aliases the chunk iterator — the `&[P]` args
    # are the iterated element, not it2's own slice type.
    assert _call(report, source, "c[0].pm()").target == pm.id

def test_pattern_bound_slice_resolves_at_the_producer_annotation():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(vd: std::collections::VecDeque<P>) {
    struct P;
    impl P { fn pm(&self) {} }
    let (a, _) = vd.as_slices();
    for x in a { x.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")
    # The `&[P]` element was spelled at `vd`'s annotation — a
    # body-local `struct P` must not steal the resolution.
    assert _call(report, source, "x.pm()").target == pm[0].id

def test_declared_as_slices_keeps_its_own_return():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct R;
trait Ext { fn as_slices(&self) -> Option<&R>; }
impl Ext for std::collections::VecDeque<P> {
    fn as_slices(&self) -> Option<&R> { None }
}
fn f(vd: std::collections::VecDeque<P>) {
    if let Some(r) = vd.as_slices() { let _ = r; }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    # A declared `as_slices` wins — the std `(&[P], &[P])` pair is
    # not assumed, so `r` stays opaque rather than misbinding to P.
    r = next(b for b in report.bindings if b.name == "r")
    assert r.type.kind == "unknown"

def test_option_iter_as_ref_and_split_at():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(o: Option<P>, v: Vec<P>) {
    for x in o.iter() { x.pm(); }
    if let Some(p) = o.as_ref() { p.pm(); }
    let (a, b) = v.split_at(1);
    a[0].pm();
    b[0].pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    calls = [call for call in report.calls if call.target == pm.id]
    assert len(calls) == 4
    assert _call(report, source, "x.pm()").target == pm.id
    assert _call(report, source, "p.pm()").target == pm.id
    assert _call(report, source, "a[0].pm()").target == pm.id
    assert _call(report, source, "b[0].pm()").target == pm.id

def test_preserving_adaptors_keep_the_element_type():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(v: Vec<P>) {
    for p in v.iter().peekable() { p.pm(); }
    for p in v.iter().inspect(|x| ()) { p.pm(); }
    for p in v.iter().fuse().by_ref() { p.pm(); }
    for p in v.iter().skip_while(|x| true).take_while(|x| true) { p.pm(); }
    for p in v.iter().cycle().take(3) { p.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    calls = [
        call for call in report.calls
        if raw[call.span.start:call.span.end].decode() == "p.pm()"
    ]
    assert len(calls) == 5
    for call in calls:
        assert call.target == pm.id

def test_option_combinators_keep_the_payload():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct Q;
impl Q { fn qm(&self) {} }
fn f(o: Option<P>, u: Option<P>, v: Option<Q>) {
    if let Some(p) = o.and(u) { p.pm(); }
    if let Some(p) = o.and(v) { p.qm(); p.pm(); }
    if let Some(p) = o.or(u) { p.pm(); }
    if let Some(p) = o.xor(u) { p.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    qm = _bindings(report, "qm", "associated_function")[0]
    raw = source.encode()
    calls = [
        (raw[call.span.start:call.span.end].decode(), call.target)
        for call in report.calls
    ]
    # `and` yields the argument's payload — `o.and(v)` is Option<Q>.
    assert next(t for k, t in calls if k == "p.qm()") == qm.id
    targets = [t for k, t in calls if k == "p.pm()"]
    # three `p.pm()` sites resolve to P::pm; the one under `and(v)`
    # stays unbound (it would need P on a Q payload).
    assert len(targets) == 4
    assert targets.count(pm.id) == 3
    assert sum(1 for t in targets if not t) == 1

def test_smart_pointer_receivers_deref_to_the_payload():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct W<T> { _m: T }
impl<T> W<T> { fn wm(&self) {} }
fn f(b: Box<P>, r: std::rc::Rc<P>, w: W<P>, m: std::sync::Mutex<P>) {
    b.pm();
    r.pm();
    w.pm();
    m.pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    resolved = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    assert resolved["b.pm()"] == pm.id
    assert resolved["r.pm()"] == pm.id
    # A custom `W<P>` and a guard `Mutex<P>` stay opaque — they do
    # not Deref straight to `P`.
    assert not resolved["w.pm()"]
    assert not resolved["m.pm()"]


def test_option_and_keeps_the_option_head_when_scopes_differ():
    source = """
mod m {
    pub struct Q;
    impl Q { pub fn qm(&self) {} }
}
struct Q;
impl Q { fn qm(&self) {} }
struct Is;
impl Is { fn is_some(&self) {} }
fn f(o: Option<m::Q>, u: Option<Q>) {
    match o.and(u) { Some(q) => q.qm(), _ => () }
    match u.and(o) { Some(q2) => q2.qm(), _ => () }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    qms = _bindings(report, "qm", "associated_function")
    inner, outer = qms[0], qms[1]
    raw = source.encode()
    resolved = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `o.and(u)` yields u's payload — the local `Q`.
    assert resolved["q.qm()"] == outer.id, resolved
    # `u.and(o)` yields o's payload — `m::Q`, not the local `Q`.
    assert resolved["q2.qm()"] == inner.id, resolved

def test_scoped_module_call_picks_its_own_function():
    source = """
mod a {
    pub struct P;
    impl P { pub fn pm(&self) {} }
    pub fn make() -> Box<P> { Box::new(P) }
}
mod b {
    pub struct Q;
    impl Q { pub fn qm(&self) {} }
    pub fn make() -> Box<Q> { Box::new(Q) }
}
fn g() {
    let x = b::make();
    x.qm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    raw = source.encode()
    qm = _bindings(report, "qm", "associated_function")[0]
    bound = [
        call
        for call in report.calls
        if raw[call.span.start:call.span.end].decode() == "x.qm()"
    ]
    assert len(bound) == 1
    assert bound[0].target == qm.id
    assert not any(
        raw[call.span.start:call.span.end].decode() == "x.pm()"
        for call in report.calls
        if call.target
    )

def test_member_borrowing_a_container_keeps_the_container():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct W { v: Vec<P> }
impl W {
    fn vref(&self) -> &Vec<P> { &self.v }
    fn oref(&self) -> &Option<P> { &None }
    fn sref(&self) -> &mut [P] { &mut [] }
}
fn f(w: &W) {
    w.vref()[0].pm();
    match w.oref() { Some(q) => q.pm(), _ => () }
    match w.sref().first() { Some(r) => r.pm(), _ => () }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    assert sum(1 for c in report.calls if c.target == pm.id) == 3

def test_pattern_field_args_resolve_in_the_declaring_module():
    source = """
struct Q;
impl Q { fn stray(&self) {} }
mod m {
    pub struct Q;
    impl Q { pub fn qm(&self) {} }
    pub struct W { pub opt: Option<Q> }
}
fn f(w: m::W) {
    let m::W { opt } = w;
    match opt { Some(q) => q.qm(), _ => () }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    qm = _bindings(report, "qm", "associated_function")[0]
    stray = _bindings(report, "stray", "associated_function")[0]
    targets = [c.target for c in report.calls]
    assert qm.id in targets
    assert stray.id not in targets

def test_substituted_pattern_args_resolve_at_the_use_site():
    source = """
mod m {
    pub struct Q;
    impl Q { pub fn stray(&self) {} }
    pub struct W<T> { pub opt: Option<T> }
}
struct Q;
impl Q { fn qm(&self) {} }
fn f(w: m::W<Q>) {
    let m::W { opt } = w;
    match opt { Some(q) => q.qm(), _ => () }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    qm = _bindings(report, "qm", "associated_function")[0]
    stray = _bindings(report, "stray", "associated_function")[0]
    targets = [c.target for c in report.calls]
    assert qm.id in targets
    assert stray.id not in targets

def test_borrowed_smart_pointer_return_resolves_in_member_scope():
    source = """
struct P;
impl P { fn stray(&self) {} }
mod n {
    pub struct P;
    impl P { pub fn pm(&self) {} }
    pub fn get() -> &'static Box<P> { &Box::new(P) }
}
fn g() {
    n::get().pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    stray = _bindings(report, "stray", "associated_function")[0]
    targets = [c.target for c in report.calls]
    assert pm.id in targets
    assert stray.id not in targets

def test_module_reexport_and_same_named_alias():
    source = """
struct P;
impl P { fn pm(&self) {} }
mod a {
    pub struct P2;
    impl P2 { pub fn p2m(&self) {} }
    pub fn make() -> Box<P2> { Box::new(P2) }
}
mod m {
    pub use a::make;
    pub fn direct() -> Box<P> { Box::new(P) }
    pub type alias = P;
}
fn g() {
    let x = m::make();
    x.p2m();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    p2m = _bindings(report, "p2m", "associated_function")[0]
    targets = [c.target for c in report.calls]
    assert p2m.id in targets

def test_smart_pointer_receivers_bind_their_payload():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct W<T> { _m: T }
impl<T> W<T> { fn wm(&self) {} }
fn f(b: Box<P>, r: std::rc::Rc<P>, w: W<P>, m: std::sync::Mutex<P>) {
    b.pm();
    r.pm();
    w.pm();
    m.pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    resolved = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    assert resolved["b.pm()"] == pm.id
    assert resolved["r.pm()"] == pm.id
    # A custom `W<P>` and a guard `Mutex<P>` stay opaque — they do
    # not Deref straight to `P`.
    assert not resolved["w.pm()"]
    assert not resolved["m.pm()"]

def test_slice_and_array_option_heads():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(s: &[P], a: [P; 4]) {
    if let Some(p) = s.first() { p.pm(); }
    if let Some(p) = a.last() { p.pm(); }
    if let Some(p) = s.get(0) { p.pm(); }
    match s.first() { Some(p) => p.pm(), None => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    calls = [
        call for call in report.calls
        if raw[call.span.start:call.span.end].decode() == "p.pm()"
    ]
    assert len(calls) == 4
    for call in calls:
        assert call.target == pm.id

def test_get_mut_and_option_filter_heads():
    source = """
use std::collections::HashMap;
struct P;
impl P { fn pm(&self) {} }
fn f(v: Vec<P>, m: HashMap<i32, P>, o: Option<P>) {
    if let Some(p) = v.get_mut(0) { p.pm(); }
    if let Some(p) = m.get_mut(&1) { p.pm(); }
    if let Some(p) = o.filter(|x| true) { p.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    calls = [
        call for call in report.calls
        if raw[call.span.start:call.span.end].decode() == "p.pm()"
    ]
    assert len(calls) == 3
    for call in calls:
        assert call.target == pm.id

def test_split_first_and_last_pair_payloads():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(v: Vec<P>, s: &[P]) {
    if let Some((h, rest)) = v.split_first() { h.pm(); rest[0].pm(); }
    if let Some((l, rest)) = s.split_last() { l.pm(); rest[0].pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    calls = [
        call for call in report.calls
        if raw[call.span.start:call.span.end].decode()
        in {"h.pm()", "l.pm()", "rest[0].pm()"}
    ]
    assert len(calls) == 4
    for call in calls:
        assert call.target == pm.id

def test_scoped_callee_return_spelled_in_decl_scope():
    # `n::make() -> Box<P>` spells `P` in `n`'s scope — a same-named
    # root `P` must not win the payload resolution.
    source = """
mod n {
    pub struct P;
    impl P { fn pm(&self) {} }
    pub fn make() -> Box<P> { Box::new(P) }
}
struct P;
fn g() { let b = n::make(); b.pm(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    calls = [
        call for call in report.calls
        if raw[call.span.start:call.span.end].decode() == "b.pm()"
    ]
    assert len(calls) == 1
    assert calls[0].target == pm.id

def test_struct_pattern_field_keeps_declared_head():
    # `let m::W { opt } = w` binds `opt` to the field's declared
    # `Option<T>` — a later `if let Some(q) = opt` still reads the
    # `Option` head and resolves `m::Q` in the module's scope.
    source = """
mod m {
    pub struct W<T> { pub opt: Option<T> }
    pub struct Q;
    impl Q { fn qm(&self) {} }
}
struct Q;
fn f() {
    let w: m::W<m::Q> = todo!();
    let m::W { opt } = w;
    if let Some(q) = opt { q.qm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    qm = _bindings(report, "qm", "associated_function")[0]
    raw = source.encode()
    calls = [
        call for call in report.calls
        if raw[call.span.start:call.span.end].decode() == "q.qm()"
    ]
    assert len(calls) == 1
    assert calls[0].target == qm.id

def test_flatten_unwraps_the_iterated_element():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct W<T>(T);
impl W<Vec<P>> { fn flatten(&self) -> W<P> { W(self.0) } }
fn f(v: Vec<Vec<P>>, o: Option<Vec<P>>, w: W<Vec<P>>, s: Vec<P>, n: Vec<Vec<Vec<P>>>) {
    for p in v.iter().flatten() { p.pm(); }
    for p in v.into_iter().flatten() { p.pm(); }
    let it = v.iter().flatten();
    for p in it { p.pm(); }
    for p in o.iter().flatten() { p.pm(); }
    for p in n.iter().flatten().flatten() { p.pm(); }
    for p in s.iter().flatten() { p.pm(); }
    for p in w.flatten() { p.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    resolved = sum(
        1
        for call in report.calls
        if raw[call.span.start:call.span.end].decode() == "p.pm()"
        and call.target == pm.id
    )
    assert resolved == 5

def test_flatten_array_elem_const_block_and_alias_scopes() -> None:
    source = """
struct P;
impl P { fn pm(&self) {} }
mod m {
    pub struct Q<T>(pub T);
    impl<T> Q<T> { pub fn wrong(&self) {} }
    pub type Row<T> = Vec<Q<T>>;
}
fn f(v: Vec<&[P<{1; 2}>; 4]>, w: Vec<m::Row<P>>) {
    for p in v.into_iter().flatten() { p.pm(); }
    for q in w.into_iter().flatten() { q.wrong(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    # `P<{1; 2}>` keeps its whole head — the `;` inside the const
    # block must not cut the slice's element spelling.
    assert (
        _call(report, source, "p.pm()").target == pm.id
    )
    # `Row`'s `Q` was spelled in `mod m` — resolving it at the use
    # site would bind a different type, so the element stays opaque.
    assert _call(report, source, "q.wrong()").target == ""

def test_flatten_alias_std_import_and_shadowed_params() -> None:
    source = """
use std::vec::Vec;
struct P;
impl P { fn pm(&self) {} }
mod m {
    pub struct P;
    impl P { pub fn wrong(&self) {} }
    pub type Row<T> = Vec<T>;
}
type Line<T> = Vec<T>;
fn f(v: Vec<Line<P>>, w: Vec<m::Row<P>>) {
    for p in v.into_iter().flatten() { p.pm(); }
    for p in w.into_iter().flatten() { p.pm(); p.wrong(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    resolved = sum(
        1
        for call in report.calls
        if raw[call.span.start:call.span.end].decode() == "p.pm()"
        and call.target == pm.id
    )
    # `use std::vec::Vec` is still the std container, and `Row<P>`'s
    # substituted `P` resolves at the use site despite `m::P`.
    assert resolved == 2
    assert _call(report, source, "p.wrong()").target == ""

def test_flatten_alias_to_custom_container_stays_opaque() -> None:
    source = """
struct P;
impl P { fn pm(&self) {} }
struct Vec<T>(T);
impl<T> Vec<T> { fn into_iter(self) -> Option<T> { None } }
type Row<T> = Vec<T>;
fn f(v: Vec<Row<P>>) {
    for p in v.into_iter().flatten() { p.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    # The alias target `Vec` resolves to the declared custom type —
    # flattening it as a std container would misbind `p.pm()`.
    assert _call(report, source, "p.pm()").target == ""

def test_flatten_unwraps_array_refs_and_container_aliases():
    source = """
struct P;
impl P { fn pm(&self) {} }
type Row<T> = Vec<T>;
fn f(v: Vec<&[P; 2]>, w: Vec<Row<P>>) {
    for p in v.into_iter().flatten() { p.pm(); }
    for p in w.into_iter().flatten() { p.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    resolved = sum(
        1
        for call in report.calls
        if raw[call.span.start:call.span.end].decode() == "p.pm()"
        and call.target == pm.id
    )
    assert resolved == 2

def test_flatten_through_cloned_and_owned_containers():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(v: Vec<Vec<P>>, s: &[Vec<P>], o: Option<Vec<P>>) {
    for p in v.clone().iter().flatten() { p.pm(); }
    for q in s.to_owned().iter().flatten() { q.pm(); }
    for r in s.as_ref().iter().flatten() { r.pm(); }
    for x in o.iter().flatten() { x.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    resolved = sum(
        1
        for call in report.calls
        if raw[call.span.start:call.span.end].decode().endswith("pm()")
        and call.target == pm.id
    )
    assert resolved == 4

def test_let_bound_next_result_heads_some_patterns():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(v: Vec<P>, w: Vec<Vec<P>>) {
    let r = v.iter().next();
    match r { Some(p) => p.pm(), None => () }
    let s = w.iter().flatten().next();
    if let Some(q) = s { q.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    resolved = sum(
        1
        for call in report.calls
        if raw[call.span.start:call.span.end].decode().endswith("pm()")
        and call.target == pm.id
    )
    assert resolved == 2

def test_borrowed_slice_return_keeps_the_substituted_element():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct W<T> { _m: T }
impl<T> W<T> { fn sref(&self) -> &mut [T] { &mut [] } }
fn f(w: W<P>) { w.sref()[0].pm(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    targets = [
        call.target
        for call in report.calls
        if raw[call.span.start:call.span.end].decode() == "w.sref()[0].pm()"
    ]
    assert targets == [pm.id]

def test_first_on_array_elements_keeps_the_array_shape():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(v: Vec<[P; 2]>) {
    match v.first() { Some(a) => a[0].pm(), _ => () }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    targets = [
        call.target
        for call in report.calls
        if raw[call.span.start:call.span.end].decode() == "a[0].pm()"
    ]
    assert targets == [pm.id]

def test_fixed_field_args_stay_in_the_declaring_module():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct E;
mod m {
    pub struct E;
    impl E { pub fn em(&self) {} }
    pub struct W<T> { pub res: Result<T, E> }
}
fn f(w: m::W<P>) {
    let m::W { res } = w;
    match res { Err(e) => e.em(), _ => () }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    em = _bindings(report, "em", "associated_function")[0]
    raw = source.encode()
    targets = [
        call.target
        for call in report.calls
        if raw[call.span.start:call.span.end].decode() == "e.em()"
    ]
    assert targets == [em.id]

def test_deref_clone_as_ref_payload_bindings() -> None:
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(b: Box<P>, v: Vec<P>, o: Option<P>, s: &[P]) {
    let d = b.deref(); d.pm();
    let r = o.as_ref(); if let Some(p) = r { p.pm(); }
    match s.as_ref().first() { Some(p1) => p1.pm(), _ => () }
    match s.as_ref().last() { Some(l) => l.pm(), _ => () }
    let c = o.clone(); match c { Some(y) => y.pm(), _ => () }
    let t = s.to_owned(); t[0].pm();
    let e = v.clone(); e[0].pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    resolved = sum(
        1
        for call in report.calls
        if raw[call.span.start:call.span.end].decode()
        in {"d.pm()", "p.pm()", "p1.pm()", "l.pm()", "y.pm()"}
        and call.target == pm.id
    )
    assert resolved == 5
    resolved_index = sum(
        1
        for call in report.calls
        if raw[call.span.start:call.span.end].decode()
        in {"t[0].pm()", "e[0].pm()"}
        and call.target == pm.id
    )
    assert resolved_index == 2

def test_option_and_drops_an_unspellable_payload():
    source = """
fn g<Q>(x: Option<Q>) -> Option<Q> { x }
fn f<T>(o: Option<T>) {
    struct Q;
    impl Q { fn qm(&self) {} }
    let u = g(o);
    match o.and(u) {
        Some(q) => q.qm(),
        _ => {}
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    # u's payload spells g's generic `Q` — re-resolving that bare
    # name at the call site lands on f's unrelated local `Q`, so
    # the payload stays opaque instead of misbinding q.qm().
    qm = _bindings(report, "qm", "associated_function")[0]
    assert _call(report, source, "q.qm()").target != qm.id

def test_specialized_impl_matches_crate_qualified_args():
    source = """
mod m {
    pub struct P;
}
struct W<T>;
impl W<m::P> {
    fn pm(&self) {}
}
fn f(o: Option<W<m::P>>, u: Option<W<m::P>>) {
    match o.and(u) {
        Some(w) => w.pm(),
        _ => {}
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    assert _call(report, source, "w.pm()").target == pm.id

def test_crate_path_never_binds_a_generic_parameter():
    # A module fn's `g<P>` parameter shadows the module's own
    # `struct P` when `crate::m::P` walks the module's bindings —
    # parameters are never path-addressable, so the struct must win.
    source = """
mod m {
    pub struct P;
    impl P {
        pub fn pm(&self) {}
    }
    pub fn g<P>(x: P) {}
}
fn f(o: Option<m::P>, u: Option<m::P>) {
    match o.and(u) {
        Some(p) => p.pm(),
        _ => {}
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    assert _call(report, source, "p.pm()").target == pm.id

def test_impl_args_keep_relative_paths_distinct_from_bare_names():
    # `W<m::P>` and `W<P>` are different specializations — a
    # receiver spelled `W<P>` must not match the `W<m::P>` impl
    # just because the final segments coincide.
    source = """
mod m {
    pub struct P;
}
struct P;
struct W<T>;
impl W<m::P> {
    fn other(&self) {}
}
impl W<P> {
    fn pm(&self) {}
}
fn f(o: Option<W<P>>, u: Option<W<P>>) {
    match o.and(u) {
        Some(w) => w.pm(),
        _ => {}
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    assert _call(report, source, "w.pm()").target == pm.id

def test_specialized_impl_args_resolve_through_use_alias():
    # `use m::P` makes `P` an alias — `impl W<P>` is the same
    # specialization as `W<m::P>` and must answer for it.
    source = """
mod m {
    pub struct P;
}
use m::P;
struct W<T>;
impl W<P> {
    fn pm(&self) {}
}
fn f(w: W<m::P>) {
    w.pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    assert _call(report, source, "w.pm()").target == pm.id

def test_call_site_alias_does_not_rebind_impl_specialization():
    source = """
mod m {
    pub struct P;
    pub struct Q;
}
use m::P;
struct W<T>;
impl W<P> {
    fn pm(&self) {}
}
impl W<m::Q> {
    fn qm(&self) {}
}
fn f() {
    use m::Q as P;
    let w: W<P>;
    w.qm();
    w.pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    qm = _bindings(report, "qm", "associated_function")[0]
    # The receiver's `P` is `m::Q` — `w.qm()` picks the W<m::Q>
    # impl, and `w.pm()` must not resolve to the W<P> impl.
    assert _call(report, source, "w.qm()").target == qm.id
    assert _call(report, source, "w.pm()").target != pm.id

def test_raw_pointer_args_distinguish_specializations():
    source = """
struct P;
struct W<T>;
impl W<*const P> {
    fn cm(&self) {}
}
impl W<*mut P> {
    fn mm(&self) {}
}
impl W<P> {
    fn pm(&self) {}
}
fn f(w: W<*mut P>) {
    w.mm();
    w.cm();
    w.pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    mm = _bindings(report, "mm", "associated_function")[0]
    cm = _bindings(report, "cm", "associated_function")[0]
    pm = _bindings(report, "pm", "associated_function")[0]
    assert _call(report, source, "w.mm()").target == mm.id
    assert _call(report, source, "w.cm()").target != cm.id
    assert _call(report, source, "w.pm()").target != pm.id

def test_declared_conversion_args_resolve_in_the_member_scope():
    # `m::W::to_owned -> Vec<Vec<Q>>` — the `Q` spelled in the
    # member's declaration scope is `m::Q`, not the call site's
    # same-named `Q`.
    source = """
mod m {
    pub struct Q;
    impl Q { pub fn qm(&self) {} }
    pub struct W<T>;
    impl<T> W<T> {
        pub fn to_owned(&self) -> Vec<Vec<Q>> { vec![] }
    }
}
struct Q;
struct P;
fn f(w: m::W<P>) {
    for p in w.to_owned().iter().flatten() {
        p.qm();
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    qm = _bindings(report, "qm", "associated_function")[0]
    assert _call(report, source, "p.qm()").target == qm.id

def test_flatten_does_not_peel_std_iterator_wrappers():
    source = """
use std::iter::Peekable;
struct P;
impl P { fn pm(&self) {} }
struct I;
impl I { fn im(&self) {} }
fn f(v: Vec<Peekable<I>>, w: Vec<Vec<P>>) {
    for x in v.iter().flatten() { x.im(); }
    for y in w.iter().flatten() { y.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `Peekable<I>` iterates `I::Item`, not `I` — flatten stays opaque.
    assert not bound.get("x.im()")
    # Real containers still flatten to their element.
    assert bound.get("y.pm()") == pm.id

def test_match_scrutinee_chained_combinator_heads_option():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct Q;
impl Q { fn qm(&self) {} }
fn to_q(p: P) -> Q { Q }
fn identity(q: Q) -> Q { q }
fn f(o: Option<P>, r: Result<Q, E>) {
    match o.map(to_q).map(identity) { Some(q2) => q2.qm(), _ => () }
    match r.ok().map(identity) { Some(q3) => q3.qm(), _ => () }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    qm = _bindings(report, "qm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    assert bound.get("q2.qm()") == qm.id
    assert bound.get("q3.qm()") == qm.id

def test_iter_consumers_bind_option_payloads():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct W<T> { items: Vec<T> }
fn find_q(q: &Q) -> Option<P> { None }
struct Q;
fn f(v: Vec<P>, w: W<P>) {
    match v.iter().find(|x| true) { Some(a) => a.pm(), _ => () }
    match v.iter().nth(0) { Some(b) => b.pm(), _ => () }
    match v.iter().min() { Some(c) => c.pm(), _ => () }
    match v.iter().max() { Some(d) => d.pm(), _ => () }
    match w.items.iter().find(|x| true) { Some(e) => e.pm(), _ => () }
    match w.items.iter().find_map(find_q) { Some(g) => g.pm(), _ => () }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    for call in (
        "a.pm()",
        "b.pm()",
        "c.pm()",
        "d.pm()",
        "e.pm()",
        "g.pm()",
    ):
        assert bound.get(call) == pm.id, call

def test_flat_map_named_callback_elements_and_std_reexport():
    source = """
mod m { pub use std::vec::Vec; }
use m::Vec;
struct P;
impl P { fn pm(&self) {} }
struct Q;
impl Q { fn qm(&self) {} }
fn to_qs(p: P) -> Vec<Q> { Vec::new() }
fn to_opt(p: P) -> Option<Q> { None }
fn f(v: Vec<P>) {
    for q in v.iter().flat_map(to_qs) { q.qm(); }
    for q2 in v.iter().flat_map(to_opt) { q2.qm(); }
    for q3 in v.iter().map(to_qs) { q3.qm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    qm = _bindings(report, "qm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    assert bound.get("q.qm()") == qm.id
    assert bound.get("q2.qm()") == qm.id
    # `map` yields the container itself (Vec<Q>/Option<Q>), not Q.
    assert not bound.get("q3.qm()")

def test_zip_fn_pointer_args_match_impl_structurally():
    source = """
mod m { pub struct P; }
use m::P;
struct Q;
impl Q { fn qm(&self) {} }
struct W<T>;
impl W<fn(P)> { fn wm(&self) {} }
fn f(o: Option<W<fn(P)>>, o2: Option<Q>) {
    match o.zip(o2) { Some((w, q)) => { w.wm(); q.qm(); }, _ => () }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    wm = _bindings(report, "wm", "associated_function")[0]
    qm = _bindings(report, "qm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    assert bound.get("w.wm()") == wm.id
    assert bound.get("q.qm()") == qm.id


def test_unwrap_or_default_yields_the_option_payload():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(o: Option<P>) { o.unwrap_or_default().pm(); }
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    assert _call(report, source, "o.unwrap_or_default().pm()").target == pm.id


def test_as_deref_yields_the_borrowed_payload():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(o: Option<Box<P>>) {
    match o.as_deref() {
        Some(p) => p.pm(),
        _ => {}
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    assert _call(report, source, "p.pm()").target == pm.id


def test_map_and_and_then_take_the_function_return_payload():
    source = """
struct P;
struct Q;
impl Q { fn qm(&self) {} }
fn to_q(p: &P) -> Q { Q }
fn maybe_q(p: &P) -> Option<Q> { Some(Q) }
fn f(o: Option<P>) {
    match o.map(to_q) {
        Some(q) => q.qm(),
        _ => {}
    }
}
fn g(o: Option<P>) {
    match o.and_then(maybe_q) {
        Some(q) => q.qm(),
        _ => {}
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    qm = _bindings(report, "qm", "associated_function")[0]
    assert _call(report, source, "q.qm()").target == qm.id


def test_map_err_rewrites_the_result_error_arg():
    source = """
struct P;
struct F;
impl F { fn fm(&self) {} }
fn to_f(e: &E) -> F { F }
struct E;
fn f(r: Result<P, E>) {
    match r.map_err(to_f) {
        Err(e) => e.fm(),
        _ => {}
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    fm = _bindings(report, "fm", "associated_function")[0]
    assert _call(report, source, "e.fm()").target == fm.id


def test_find_and_nth_yield_the_upstream_element():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(v: Vec<P>) {
    match v.iter().find(|x| true) {
        Some(p) => p.pm(),
        _ => {}
    }
    match v.iter().max() {
        Some(p) => p.pm(),
        _ => {}
    }
    v.iter().nth(1).unwrap().pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    assert _call(report, source, "p.pm()").target == pm.id
    assert _call(report, source, "v.iter().nth(1).unwrap().pm()").target == pm.id


def test_find_map_unwraps_the_function_return_option():
    source = """
struct P;
struct Q;
impl Q { fn qm(&self) {} }
fn maybe_q(p: &P) -> Option<Q> { Some(Q) }
fn f(v: Vec<P>) {
    match v.iter().find_map(maybe_q) {
        Some(q) => q.qm(),
        _ => {}
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    qm = _bindings(report, "qm", "associated_function")[0]
    assert _call(report, source, "q.qm()").target == qm.id


def test_map_with_a_closure_stays_opaque():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(o: Option<P>) {
    match o.map(|x| x) {
        Some(p) => p.pm(),
        _ => {}
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    # The closure's return type is unwritten — the payload stays
    # opaque rather than guessing.
    assert _call(report, source, "p.pm()").target == ""


def test_first_mut_yields_a_mut_borrowed_element():
    source = """
struct P;
impl P { fn pm(&mut self) {} }
fn f(v: &mut Vec<P>) {
    match v.first_mut() {
        Some(p) => p.pm(),
        _ => {}
    }
}
fn g(s: &mut [P]) {
    match s.get_mut(0) {
        Some(p) => p.pm(),
        _ => {}
    }
}
fn h(d: &mut VecDeque<P>) {
    match d.front_mut() {
        Some(p) => p.pm(),
        _ => {}
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    calls = [
        c
        for c in report.calls
        if source[c.span.start : c.span.end] == "p.pm()"
    ]
    assert len(calls) == 3
    assert all(c.target == pm.id for c in calls)


def test_iter_map_filter_map_flat_map_named_fn_elements():
    source = """
struct P;
struct Q;
impl Q { fn qm(&self) {} }
fn to_q(p: &P) -> Q { Q }
fn ok(p: &P) -> Option<Q> { None }
fn vs(p: &P) -> Vec<Q> { Vec::new() }
fn os(p: &P) -> Option<Q> { None }
fn ss(p: &P) -> &[Q] { &[] }
fn bad(p: &P) -> i32 { 0 }
fn f(v: Vec<P>) {
    for q in v.iter().map(to_q) { q.qm(); }
    for q in v.iter().filter_map(ok) { q.qm(); }
    for q in v.iter().flat_map(vs) { q.qm(); }
    for q in v.iter().flat_map(os) { q.qm(); }
    for q in v.iter().flat_map(ss) { q.qm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    qm = _bindings(report, "qm", "associated_function")[0]
    raw = source.encode()
    resolved = sum(
        1
        for call in report.calls
        if raw[call.span.start:call.span.end].decode() == "q.qm()"
        and call.target == qm.id
    )
    assert resolved == 5


def test_iter_fn_element_stays_opaque_for_closures_and_scalars():
    source = """
struct P;
struct Q;
impl Q { fn qm(&self) {} }
fn bad(p: &P) -> i32 { 0 }
fn f(v: Vec<P>) {
    for q in v.iter().map(|x| x) { q.qm(); }
    for q in v.iter().filter_map(|x| None) { q.qm(); }
    for q in v.iter().flat_map(bad) { q.qm(); }
    for q in v.iter().map(bad) { q.qm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    raw = source.encode()
    assert not any(
        raw[call.span.start:call.span.end].decode() == "q.qm()"
        and call.target
        for call in report.calls
    )


def test_iter_fn_element_qualified_return_stays_in_fn_scope():
    source = """
mod m {
    pub struct Q;
    impl Q { pub fn qm(&self) {} }
    pub fn to_q(p: &super::P) -> Q { Q }
}
struct P;
struct Q;
fn f(v: Vec<P>) {
    for q in v.iter().map(m::to_q) { q.qm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    qm = _bindings(report, "qm", "associated_function")[0]
    raw = source.encode()
    assert any(
        raw[call.span.start:call.span.end].decode() == "q.qm()"
        and call.target == qm.id
        for call in report.calls
    )


def test_option_cloned_and_copied_peel_the_borrowed_payload():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(o: Option<&P>, m: Option<&mut P>, n: Option<P>) {
    match o.cloned() { Some(p) => p.pm(), _ => () }
    match o.copied() { Some(p2) => p2.pm(), _ => () }
    match m.cloned() { Some(p3) => p3.pm(), _ => () }
    match n.cloned() { Some(p4) => p4.pm(), _ => () }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    calls = [
        call for call in report.calls
        if raw[call.span.start:call.span.end].decode().endswith("pm()")
    ]
    bound = {
        raw[call.span.start:call.span.end].decode()
        for call in calls
        if call.target == pm.id
    }
    assert bound == {"p.pm()", "p2.pm()", "p3.pm()"}
    # `Option<P>` has no borrow to peel — `n.cloned()` stays opaque.
    assert not any(
        raw[call.span.start:call.span.end].decode() == "p4.pm()"
        and call.target
        for call in calls
    )


def test_option_zip_spells_the_paired_payload():
    source = """
struct P;
struct Q;
impl P { fn pm(&self) {} }
impl Q { fn qm(&self) {} }
fn f(a: Option<P>, b: Option<Q>, v: Vec<Q>) {
    match a.zip(b) { Some((p, q)) => { p.pm(); q.qm(); }, _ => () }
    // A non-Option argument keeps the payload opaque.
    match a.zip(v.first().copied().into_iter().next()) {
        Some((p2, q2)) => { p2.pm(); q2.qm(); },
        _ => (),
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    qm = _bindings(report, "qm", "associated_function")[0]
    raw = source.encode()
    resolved = {
        raw[call.span.start:call.span.end].decode(): call.target
        for call in report.calls
        if raw[call.span.start:call.span.end].decode().endswith(
            ("pm()", "qm()")
        )
    }
    assert resolved.get("p.pm()") == pm.id, resolved
    assert resolved.get("q.qm()") == qm.id, resolved
    # `a.zip(<unresolvable>)` stays opaque — no false bindings.
    assert not resolved.get("p2.pm()"), resolved
    assert not resolved.get("q2.qm()"), resolved


def test_option_insert_methods_bind_the_mut_payload():
    source = """
struct P;
struct V;
struct K;
impl P { fn pm(&self) {} }
impl V { fn vm(&self) {} }
fn f(o: Option<P>, m: HashMap<K, V>, d: P, k: K, v: V) {
    let a = o.get_or_insert(d);
    a.pm();
    let b = o.or_insert(d);
    b.pm();
    let c = o.get_or_insert_with(prod);
    c.pm();
    let e = o.insert(d);
    e.pm();
    let g = o.or_insert_with(prod);
    g.pm();
    match m.insert(k, v) { Some(old) => old.vm(), _ => () }
}
fn prod() -> P { P }
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    vm = _bindings(report, "vm", "associated_function")[0]
    raw = source.encode()
    resolved = {
        raw[call.span.start:call.span.end].decode(): call.target
        for call in report.calls
    }
    for text in ("a.pm()", "b.pm()", "c.pm()", "e.pm()", "g.pm()"):
        assert resolved.get(text) == pm.id, (text, resolved)
    assert resolved.get("old.vm()") == vm.id, resolved


def test_vec_insert_does_not_bind_the_inserted_payload():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(v: Vec<P>, p: P) {
    let r = v.insert(0, p);
    r.pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    # Vec::insert returns (), not a payload — `r` stays untyped.
    assert _call(report, source, "r.pm()").target == ""


def test_map_pair_methods_spell_the_key_value_pair():
    source = """
struct K;
impl K { fn km(&self) {} }
struct V;
impl V { fn vm(&self) {} }
fn f(m: BTreeMap<K, V>) {
    match m.pop_first() { Some((k, v)) => { k.km(); v.vm(); }, _ => () }
    match m.pop_last() { Some((k2, v2)) => { k2.km(); v2.vm(); }, _ => () }
}
fn g(m: HashMap<K, V>, k0: K) {
    match m.remove_entry(k0) { Some((k3, v3)) => { k3.km(); v3.vm(); }, _ => () }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    km = _bindings(report, "km", "associated_function")[0]
    vm = _bindings(report, "vm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    assert bound["k.km()"] == km.id
    assert bound["v.vm()"] == vm.id
    assert bound["k2.km()"] == km.id
    assert bound["v2.vm()"] == vm.id
    assert bound["k3.km()"] == km.id
    assert bound["v3.vm()"] == vm.id


def test_option_replace_and_deque_swap_remove():
    source = """
use std::collections::VecDeque;
struct P;
impl P { fn pm(&self) {} }
fn f(o: Option<P>, q: VecDeque<P>) {
    match o.replace(p) { Some(old) => old.pm(), _ => () }
    match q.swap_remove_front(0) { Some(p1) => p1.pm(), _ => () }
    match q.swap_remove_back(0) { Some(p2) => p2.pm(), _ => () }
    let t = q.swap_remove(0);
    t.pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    assert bound["old.pm()"] == pm.id
    assert bound["p1.pm()"] == pm.id
    assert bound["p2.pm()"] == pm.id
    # `swap_remove` is a Vec-only method — `VecDeque` exposes
    # `swap_remove_front`/`swap_remove_back`, so `t` stays untyped.
    assert not bound["t.pm()"]


def test_set_heap_list_option_heads_bind_payloads():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(s: HashSet<P>, t: BTreeSet<P>, h: BinaryHeap<P>, l: LinkedList<P>, k: P) {
    match s.get(&k) { Some(p) => p.pm(), _ => () }
    match s.take(&k) { Some(p) => p.pm(), _ => () }
    match t.first() { Some(p) => p.pm(), _ => () }
    match t.last() { Some(p) => p.pm(), _ => () }
    match t.take(&k) { Some(p) => p.pm(), _ => () }
    match h.pop() { Some(p) => p.pm(), _ => () }
    match h.peek() { Some(p) => p.pm(), _ => () }
    match l.front() { Some(p) => p.pm(), _ => () }
    match l.back() { Some(p) => p.pm(), _ => () }
    match l.pop_front() { Some(p) => p.pm(), _ => () }
    match l.pop_back() { Some(p) => p.pm(), _ => () }
}
fn g(t: BTreeSet<P>) {
    match t.pop_first() { Some(p) => p.pm(), _ => () }
    match t.pop_last() { Some(p) => p.pm(), _ => () }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    hits = [
        c for c in report.calls
        if raw[c.span.start:c.span.end].decode() == "p.pm()"
        and c.target == pm.id
    ]
    assert len(hits) == 13


def test_map_pair_methods_still_spell_pairs_not_set_elements():
    source = """
struct K;
impl K { fn km(&self) {} }
struct V;
impl V { fn vm(&self) {} }
fn f(m: BTreeMap<K, V>, t: BTreeSet<K>) {
    match m.pop_first() { Some((k, v)) => { k.km(); v.vm(); }, _ => () }
    match t.pop_first() { Some(p) => p.km(), _ => () }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    km = _bindings(report, "km", "associated_function")[0]
    vm = _bindings(report, "vm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    assert bound["k.km()"] == km.id
    assert bound["v.vm()"] == vm.id
    assert bound["p.km()"] == km.id

def test_set_get_ignores_the_hasher_type_arg():
    source = """
use std::collections::HashSet;
struct P;
impl P { fn pm(&self) {} }
struct S;
impl S { fn sm(&self) {} }
fn f(s: HashSet<P, S>) {
    match s.get(&0) { Some(p) => p.pm(), _ => {} }
    match s.get(&0) { Some(x) => x.sm(), _ => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = [
        call for call in report.calls
        if raw[call.span.start:call.span.end].decode() == "p.pm()"
    ]
    assert len(bound) == 1 and bound[0].target == pm.id
    unbound = [
        call for call in report.calls
        if raw[call.span.start:call.span.end].decode() == "x.sm()"
        and call.target
    ]
    assert not unbound

def test_swap_remove_only_types_vec_receivers():
    source = """
use std::collections::VecDeque;
struct P;
impl P { fn pm(&self) {} }
struct Q;
impl Q { fn qm(&self) {} }
impl Q { fn swap_remove(&self, n: usize) -> Q { self } }
fn f(v: Vec<P>, q: VecDeque<P>, w: Q) {
    v.swap_remove(0).pm();
    q.swap_remove(0).pm();
    w.swap_remove(0).qm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    qm_swap = [
        b for b in _bindings(report, "swap_remove", "associated_function")
    ]
    raw = source.encode()
    bound = {
        raw[call.span.start:call.span.end].decode(): call.target
        for call in report.calls
        if "swap_remove" in raw[call.span.start:call.span.end].decode()
    }
    assert bound.get("v.swap_remove(0).pm()") == pm.id
    assert not bound.get("q.swap_remove(0).pm()")
    # A declared `Q::swap_remove` still resolves normally.
    calls = [
        call for call in report.calls
        if raw[call.span.start:call.span.end].decode()
        == "w.swap_remove(0).qm()"
    ]
    assert len(calls) == 1 and calls[0].target

def test_mut_slice_accessors_spell_borrowed_elements():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(mut v: Vec<P>, s: &mut [P]) {
    for c in v.chunks_mut(2) { c[0].pm(); }
    for c in s.split_mut(|x| true) { c[0].pm(); }
    let (a, b) = v.split_at_mut(1);
    a[0].pm();
    b[0].pm();
    if let Some((h, rest)) = v.split_first_mut() { h.pm(); rest[0].pm(); }
    if let Some((l, rest)) = s.split_last_mut() { l.pm(); rest[0].pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    calls = [
        call for call in report.calls
        if raw[call.span.start:call.span.end].decode()
        in {
            "c[0].pm()", "a[0].pm()", "b[0].pm()", "h.pm()",
            "l.pm()", "rest[0].pm()",
        }
    ]
    assert len(calls) == 8
    for call in calls:
        assert call.target == pm.id

def test_mut_chunk_spelling_honors_declared_methods():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct Q;
impl Q { fn qm(&self) {} }
struct W<T> { _m: T }
impl<T> W<T> { fn chunks_mut(&mut self, n: usize) -> Vec<Vec<Q>> { vec![] } }
fn f(mut v: Vec<P>, mut w: W<P>) {
    for c in v.chunks_mut(2) { c[0].pm(); }
    for c in w.chunks_mut(2) { c[0].qm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    qm = _bindings(report, "qm", "associated_function")[0]
    chunks_mut = _bindings(report, "chunks_mut", "associated_function")[0]
    assert _call(report, source, "c[0].pm()").target == pm.id
    # A declared `W<T>::chunks_mut` wins over the std recipe.
    assert _call(report, source, "w.chunks_mut(2)").target == chunks_mut.id
    assert _call(report, source, "c[0].qm()").target == qm.id

def test_mut_split_resplit_and_array_elements():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(mut v: Vec<P>, s: &mut [P], w: Vec<[P; 2]>) {
    let (a, b) = v.split_at_mut(1);
    b[0].pm();
    let (c, d) = a.split_at(0);
    c[0].pm();
    let (e, g) = s.split_at_mut(0);
    g[0].pm();
    if let Some((h, rest)) = w.split_first_mut() { h[0].pm(); }
    if let Some((h2, rest2)) = w.split_first() { h2[0].pm(); rest2[0][0].pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    wanted = {
        "b[0].pm()", "c[0].pm()", "g[0].pm()", "h[0].pm()",
        "h2[0].pm()", "rest2[0][0].pm()",
    }
    calls = [
        call for call in report.calls
        if raw[call.span.start:call.span.end].decode() in wanted
    ]
    assert len(calls) == 6
    for call in calls:
        assert call.target == pm.id

def test_mut_split_option_element_binds_nested_some():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(v: Vec<Option<P>>, s: &mut [Option<P>]) {
    if let Some((Some(p), rest)) = v.split_first_mut() { p.pm(); }
    match s.split_last_mut() {
        Some((Some(q), rest)) => { q.pm(); }
        _ => {}
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    calls = [
        call for call in report.calls
        if raw[call.span.start:call.span.end].decode() in {"p.pm()", "q.pm()"}
    ]
    assert len(calls) == 2
    for call in calls:
        assert call.target == pm.id

def test_set_algebra_methods_bind_left_set_elements():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(a: HashSet<P>, b: HashSet<P>, t: BTreeSet<P>, v: Vec<P>) {
    for x in a.union(&b) { x.pm(); }
    for x2 in a.intersection(&b) { x2.pm(); }
    for x3 in a.difference(&b) { x3.pm(); }
    for x4 in a.symmetric_difference(&b) { x4.pm(); }
    for x5 in t.union(&t) { x5.pm(); }
    for x6 in v.union(&v) { x6.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    for call in ("x.pm()", "x2.pm()", "x3.pm()", "x4.pm()", "x5.pm()"):
        assert bound.get(call) == pm.id, call
    # `Vec` has no union — the method does not invent an element type.
    assert not bound.get("x6.pm()")


def test_btreemap_range_binds_key_value_pairs():
    source = """
struct K;
impl K { fn km(&self) {} }
struct V;
impl V { fn vm(&self) {} }
fn f(m: BTreeMap<K, V>, h: HashMap<K, V>) {
    for (k, v) in m.range(..) { k.km(); v.vm(); }
    for (k2, v2) in m.range_mut(..) { k2.km(); v2.vm(); }
    for (k3, v3) in h.range(..) { k3.km(); v3.vm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    km = _bindings(report, "km", "associated_function")[0]
    vm = _bindings(report, "vm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    assert bound.get("k.km()") == km.id
    assert bound.get("v.vm()") == vm.id
    assert bound.get("k2.km()") == km.id
    assert bound.get("v2.vm()") == vm.id
    # `HashMap` has no `range` view — pairs stay unpinned.
    assert not bound.get("k3.km()")
    assert not bound.get("v3.vm()")



def test_set_algebra_peels_hasher_and_enumerate_pairs():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct Q;
impl Q { fn qm(&self) {} }
struct H;
impl H { fn hm(&self) {} }
fn f(a: HashSet<(P, Q), H>, b: HashSet<(P, Q), H>) {
    for (p, q) in a.union(&b) { p.pm(); q.qm(); }
    for (p2, q2) in a.iter() { p2.pm(); q2.qm(); }
    for (_, (p3, q3)) in a.union(&b).enumerate() { p3.pm(); q3.qm(); }
    for (_, x) in a.union(&b).enumerate() { x.0.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    qm = _bindings(report, "qm", "associated_function")[0]
    hm = _bindings(report, "hm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # The hasher arg must not feed the tuple slots or the pair tail.
    assert bound.get("p.pm()") == pm.id
    assert bound.get("q.qm()") == qm.id
    assert bound.get("p2.pm()") == pm.id
    assert bound.get("q2.qm()") == qm.id
    assert bound.get("p3.pm()") == pm.id
    assert bound.get("q3.qm()") == qm.id
    assert bound.get("x.0.pm()") == pm.id
    for call in bound:
        assert bound[call] != hm.id, call


def test_map_range_survives_turbofish_and_adapters():
    source = """
struct K;
impl K { fn km(&self) {} }
struct V;
impl V { fn vm(&self) {} }
fn f(m: BTreeMap<K, V>) {
    for (k, v) in m.range::<K, _>(..) { k.km(); v.vm(); }
    for (k2, v2) in m.range(..).rev() { k2.km(); v2.vm(); }
    for (k3, v3) in m.range(..).take(2) { k3.km(); v3.vm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    km = _bindings(report, "km", "associated_function")[0]
    vm = _bindings(report, "vm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    assert bound.get("k.km()") == km.id
    assert bound.get("v.vm()") == vm.id
    assert bound.get("k2.km()") == km.id
    assert bound.get("v2.vm()") == vm.id
    assert bound.get("k3.km()") == km.id
    assert bound.get("v3.vm()") == vm.id


def test_option_ok_or_heads_result_payloads():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct E;
impl E { fn em(&self) {} }
fn mk() -> E { E }
fn f(o: Option<P>, e: E, v: Vec<P>) {
    match o.ok_or(e) { Ok(p) => p.pm(), Err(x) => x.em() }
    match o.ok_or_else(mk) { Ok(p2) => p2.pm(), Err(y) => y.em() }
    match o.ok_or_else(|| E) { Ok(p3) => p3.pm(), Err(z) => z.em() }
    match v.iter().ok_or(e) { Ok(p4) => p4.pm(), _ => () }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    em = _bindings(report, "em", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    assert bound.get("p.pm()") == pm.id
    assert bound.get("x.em()") == em.id
    assert bound.get("p2.pm()") == pm.id
    assert bound.get("y.em()") == em.id
    # A closure's unwritten return still pins `Ok` but leaves `Err`
    # unpinned.
    assert bound.get("p3.pm()") == pm.id
    assert not bound.get("z.em()")
    # `iter()` has no `ok_or` — a non-Option receiver stays opaque.
    assert not bound.get("p4.pm()")


def test_ok_or_spells_qualified_error_type():
    source = """
mod m { pub struct E; }
struct E;
impl m::E { fn em(&self) {} }
impl E { fn em(&self) {} }
fn f(o: Option<u8>, e: m::E, e2: E) {
    match o.ok_or(e) { Err(x) => x.em(), _ => {} }
    match o.ok_or(e2) { Err(x2) => x2.em(), _ => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    raw = source.encode()
    ems = sorted(
        b.span.start for b in report.bindings if b.name == "em"
    )
    assert len(ems) == 2
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `x` binds the `m::E` impl's `em`; `x2` the root `E`'s — the
    # spelled `E` in `ok_or(e)` keeps its `m::` qualifier.
    assert bound.get("x.em()") is not None
    assert bound.get("x2.em()") is not None
    assert bound["x.em()"] != bound["x2.em()"]

def test_map_entry_or_insert_binds_mut_value_payload():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn def() -> P { P }
fn f(m: HashMap<K, P>, b: BTreeMap<K, P>, v: Vec<P>) {
    let e = m.entry(K).or_insert_with(def);
    e.pm();
    let e2 = m.entry(K).or_insert(def());
    e2.pm();
    let e3 = m.entry(K).and_modify(|x| ()).or_insert(def());
    e3.pm();
    let e4 = b.entry(K).or_default();
    e4.pm();
    let e5 = b.entry(K).or_insert_with_key(|k| def());
    e5.pm();
    let e6 = v.entry(0).or_insert(def());
    e6.pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    for call in ("e.pm()", "e2.pm()", "e3.pm()", "e4.pm()", "e5.pm()"):
        assert bound.get(call) == pm.id, call
    # `Vec` has no `entry` API.
    assert not bound.get("e6.pm()")

def test_ok_or_ok_payload_resolves_at_the_receiver_annotation():
    # A body-local same-named type must not shadow the `Ok` payload —
    # `o: Option<P>` spells `P` at the parameter's annotation, not
    # inside the body where a second `P` is declared.
    source = """
struct P;
impl P { fn pm(&self) {} }
struct E;
fn f(o: Option<P>) {
    struct P;
    impl P { fn pm2(&self) {} }
    match o.ok_or(E) { Ok(x) => x.pm(), _ => {} }
    match o.ok_or(E) { Ok(y) => y.pm2(), _ => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    assert bound.get("x.pm()") == pm.id
    assert not bound.get("y.pm2()")


def test_custom_map_declared_entry_feeds_option_or_insert():
    # A custom `HashMap` whose declared `entry` returns `Option<Q>`
    # feeds `Option::or_insert` — `&mut Q`, not the map's `V`.
    source = """
struct P;
impl P { fn pm(&self) {} }
struct Q;
impl Q { fn qm(&mut self) {} }
struct HashMap<K, V>;
impl<K, V> HashMap<K, V> {
    fn entry(&mut self, k: K) -> Option<Q> { None }
}
fn f(m: &mut HashMap<i32, P>, k: i32) {
    m.entry(k).or_insert(P).qm();
    m.entry(k).or_insert(P).pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    qm = _bindings(report, "qm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    assert bound.get("m.entry(k).or_insert(P).qm()") == qm.id
    assert not bound.get("m.entry(k).or_insert(P).pm()")

def test_ok_or_spells_qualified_literal_error_type():
    # `o.ok_or(errors::E {})` — the literal's own `errors::` path
    # qualifies the `Err` payload; a same-named root `E` must not
    # steal it.
    source = """
mod errors { pub struct E; }
struct E;
impl errors::E { fn em(&self) {} }
impl E { fn em2(&self) {} }
fn f(o: Option<u8>) {
    match o.ok_or(errors::E {}) { Err(e) => e.em(), _ => {} }
    match o.ok_or(errors::E {}) { Err(e2) => e2.em2(), _ => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    em = _bindings(report, "em", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    assert bound.get("e.em()") == em.id
    assert not bound.get("e2.em2()")



def test_map_key_value_views_bind_elements_through_let():
    source = """
struct K;
impl K { fn km(&self) {} }
struct P;
impl P { fn pm(&self) {} }
struct H;
impl H { fn hm(&self) {} }
struct S { map: std::collections::HashMap<K, P, H> }
type M = std::collections::HashMap<K, P>;
struct T { m: M }
fn f(m: HashMap<K, P>, b: BTreeMap<K, P>, w: W<K, P>, s: S, t: T) {
    let a = m.values(); for p in a { p.pm(); }
    let c = m.keys(); for k in c { k.km(); }
    let d = m.values_mut(); for p in d { p.pm(); }
    let g = b.into_values(); for p in g { p.pm(); }
    let h = b.into_keys(); for k in h { k.km(); }
    for p in m.values_mut() { p.pm(); }
    let e = m.get_key_value(&K); if let Some((k, val)) = e { val.pm(); }
    let e2 = b.get_key_value(&K); if let Some((k2, val2)) = e2 { val2.pm(); }
    let e3 = w.get_key_value(&K); if let Some((k3, val3)) = e3 { val3.pm(); }
    // A trailing hasher arg never wins the value slot.
    let hv = s.map.values(); for vp in hv { vp.pm(); }
    // Field receivers spell the same <K, V> list.
    let hk = s.map.keys(); for kk in hk { kk.km(); }
    let ik = s.map.into_keys(); for ki in ik { ki.km(); }
    if let Some((fk, fv)) = s.map.get_key_value(&K) { fk.km(); fv.pm(); }
    // A field declared through a map alias spells it too.
    if let Some((ak, av)) = t.m.get_key_value(&K) { ak.km(); av.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    km = _bindings(report, "km", "associated_function")[0]
    raw = source.encode()
    calls = [
        (raw[c.span.start:c.span.end].decode(), c.target)
        for c in report.calls
    ]
    targets = lambda name: [t for text, t in calls if text == name]
    # `p.pm()` appears in every values-loop and through fields.
    assert targets("p.pm()") == [pm.id] * 4
    assert targets("vp.pm()") == [pm.id]
    assert targets("k.km()") == [km.id] * 2
    assert targets("kk.km()") == [km.id]
    assert targets("ki.km()") == [km.id]
    assert targets("val.pm()") == [pm.id]
    assert targets("val2.pm()") == [pm.id]
    assert targets("fk.km()") == [km.id]
    assert targets("fv.pm()") == [pm.id]
    assert targets("ak.km()") == [km.id]
    assert targets("av.pm()") == [pm.id]
    # A custom `W` map keeps `get_key_value` opaque.
    assert targets("val3.pm()") == [""]
    # `hm` is the hasher's method — never a values element target.
    assert all(t != _bindings(report, "hm", "associated_function")[0].id for _, t in calls)

def test_next_back_and_or_else_keep_the_payload():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn def() -> P { P }
fn opt() -> Option<P> { Some(P) }
fn cvt(o: Option<P>) -> Option<P> { o }
fn f(v: Vec<P>, o: Option<P>, r: Result<P, E>, w: W<P>) {
    let x1 = v.iter().next_back(); if let Some(p1) = x1 { p1.pm(); }
    let x2 = o.or_else(|| Some(def())); if let Some(p2) = x2 { p2.pm(); }
    let x3 = r.or_else(|e| Err(e)); if let Ok(p3) = x3 { p3.pm(); }
    let x4 = o.or_else(def); if let Some(p4) = x4 { p4.pm(); }
    let x5 = w.or_else(|| w); if let Some(p5) = x5 { p5.pm(); }
    // A named `Option<P>` fallback resolves through the
    // function's own return annotation, not the closure path.
    let x6 = o.or_else(opt); if let Some(p6) = x6 { p6.pm(); }
    // `or_else` on a combinator chain keeps the Option head.
    let x7 = o.map(cvt).or_else(opt); if let Some(p7) = x7 { p7.pm(); }
}
// A same-named `P` in the body must not steal `o`'s `Option<P>`
// payload — spelled names resolve at the receiver's annotation.
type M = std::collections::HashMap<i32, P>;
type N = M;
fn g(o: Option<P>, h: N) {
    struct P { q: u8 }
    let y = o.or_else(opt); if let Some(p) = y { p.pm(); }
    for v in h.values() { v.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    for call in (
        "p1.pm()",
        "p2.pm()",
        "p3.pm()",
        "p4.pm()",
        "p6.pm()",
        "p7.pm()",
    ):
        assert bound.get(call) == pm.id, call
    # A custom `W` receiver keeps `or_else` opaque.
    assert not bound.get("p5.pm()")
    # The body's `struct P` shadows the annotation's `P` — `p` is
    # the outer `P`, so `pm` still binds; `h.values()` unrolls the
    # `N -> M -> HashMap` alias chain to the outer `P` too.
    assert bound.get("p.pm()") == pm.id
    assert bound.get("v.pm()") == pm.id

def test_entry_key_into_mut_and_fn_adaptors_bind():
    source = """
struct K;
impl K { fn km(&self) {} }
struct P;
impl P { fn pm(&self) {} }
struct Q;
impl Q { fn qm(&self) {} }
fn mk() -> Option<Q> { None }
fn f(m: HashMap<K, P>, b: BTreeMap<K, P>, v: Vec<P>) {
    let x1 = b.entry(K).into_mut(); x1.pm();
    let x2 = m.entry(K).into_mut(); x2.pm();
    let x3 = m.entry(K).key(); x3.km();
    let x9 = v.iter().map_while(mk); for p in x9 { p.qm(); }
    let x10 = v.iter().scan(0, mk); for p in x10 { p.qm(); }
    let x13 = v.split_off(1); for p in x13 { p.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    km = _bindings(report, "km", "associated_function")[0]
    qm = _bindings(report, "qm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    assert bound.get("x1.pm()") == pm.id
    # `Entry::into_mut` is `BTreeMap`-only.
    assert not bound.get("x2.pm()")
    assert bound.get("x3.km()") == km.id
    assert bound.get("p.qm()") == qm.id

def test_option_flatten_and_deque_as_slices_bind_elements():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct W<T> { x: T }
fn f(vd: VecDeque<P>, o: Option<Option<P>>, w: W<P>) {
    let (a, b) = vd.as_slices();
    for p in a { p.pm(); }
    let s0 = vd.as_slices().0;
    for q in s0 { q.pm(); }
    let m1 = vd.as_mut_slices().1;
    for r in m1 { r.pm(); }
    let f1 = o.flatten();
    if let Some(u) = f1 { u.pm(); }
    let f2 = o.flatten().flatten();
    if let Some(v) = f2 { v.pm(); }
    let z = w.as_slices().0;
    for s in z { s.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    assert bound.get("p.pm()") == pm.id
    assert bound.get("q.pm()") == pm.id
    assert bound.get("r.pm()") == pm.id
    assert bound.get("u.pm()") == pm.id
    # `o.flatten().flatten()` — `Option<P>` has no second layer.
    assert not bound.get("v.pm()")
    # A custom `W` can name any `as_slices` — stays opaque.
    assert not bound.get("s.pm()")
def test_result_iter_and_option_unzip_bind_payloads():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct Q;
impl Q { fn qm(&self) {} }
struct W<T> { x: T }
fn f(r: Result<P, E>, o: Option<(P, Q)>, w: W<P>) {
    for p in r.iter() { p.pm(); }
    for q in r.iter_mut() { q.pm(); }
    let i1 = r.iter();
    for u in i1 { u.pm(); }
    let (x, y) = o.unzip();
    if let Some(a) = x { a.pm(); }
    if let Some(b) = y { b.qm(); }
    let z = o.unzip();
    if let Some(c) = z { c.pm(); }
    for s in w.iter() { s.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    qm = _bindings(report, "qm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `Result::iter`/`iter_mut` iterate the `Ok` payload `&P`.
    assert bound.get("p.pm()") == pm.id
    assert bound.get("q.pm()") == pm.id
    assert bound.get("u.pm()") == pm.id
    # `Option<(P, Q)>::unzip` gives `(Option<P>, Option<Q>)` —
    # the left name binds `P`, the right `Q`, so a swap shows.
    assert bound.get("a.pm()") == pm.id
    assert bound.get("b.qm()") == qm.id
    # `z` is the pair itself — `Some` on a tuple is a type error.
    assert not bound.get("c.pm()")
    # A custom `W` can name any `iter` — stays opaque.
    assert not bound.get("s.pm()")


def test_nested_option_destructure_binds_the_inner_option():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(o: Option<Option<P>>) {
    if let Some(p) = o {
        if let Some(q) = p { q.pm(); }
        p.pm();
    }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `Some(p)` on `Option<Option<P>>` binds `p: Option<P>` —
    # the nested `Some(q)` unwraps it, but `p` itself is not `P`.
    assert bound.get("q.pm()") == pm.id
    assert not bound.get("p.pm()")
def test_iterator_unzip_and_partition_bind_elements():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct W<T> { x: T }
fn f(v: Vec<(P, P)>, w: Vec<P>, t: (P, P), x: W<(P, P)>) {
    let (xs, ys): (Vec<P>, Vec<P>) = v.into_iter().unzip();
    for a in xs { a.pm(); }
    for b in ys { b.pm(); }
    let it = v.into_iter();
    let (xs2, ys2) = it.unzip();
    for c in xs2 { c.pm(); }
    let (pa, pb) = w.iter().partition(|p| true);
    for d in pa { d.pm(); }
    let (e1, e2) = t.unzip();
    e1.pm();
    let (g1, g2) = x.iter().unzip();
    for h in g1 { h.pm(); }
    let (i1, i2) = w.iter().unzip();
    i1.pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `it.unzip()` on a pair iterator gives `(Vec<P>, Vec<P>)`.
    assert bound.get("a.pm()") == pm.id
    assert bound.get("b.pm()") == pm.id
    assert bound.get("c.pm()") == pm.id
    # `it.partition(f)` gives `(Vec<P>, Vec<P>)`.
    assert bound.get("d.pm()") == pm.id
    # `t.unzip()` on a declared pair names no method — opaque.
    assert not bound.get("e1.pm()")
    # A custom `W` can name any `iter` — stays opaque.
    assert not bound.get("h.pm()")
    # `unzip` on a non-pair element names no method — opaque.
    assert not bound.get("i1.pm()")


def test_unzip_accepts_a_trailing_comma_pair():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(o: Option<(P, P,)>, v: Vec<(P, P,)>) {
    if let Some((a, b)) = o {
        a.pm();
        b.pm();
    }
    let (xs, ys) = v.into_iter().unzip();
    xs[0].pm();
    ys[0].pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `(P, P,)` is a two-element pair — both halves and both
    # unzip outputs resolve.
    assert bound.get("a.pm()") == pm.id
    assert bound.get("b.pm()") == pm.id
    assert bound.get("xs[0].pm()") == pm.id
    assert bound.get("ys[0].pm()") == pm.id


def test_saved_result_iter_keeps_the_element_args():
    source = """
struct G<T>;
impl G<u8> { fn um(&self) {} }
fn f(r: Result<G<u8>, u8>) {
    let it = r.iter();
    for x in it { x.um(); }
    for y in r.iter() { y.um(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    um = _bindings(report, "um", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `let it = r.iter()` then `for x in it` keeps `G<u8>`'s
    # args like the direct `r.iter()` loop does.
    assert bound.get("x.um()") == um.id
    assert bound.get("y.um()") == um.id
def test_result_and_or_and_transpose_bind_payloads():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct Q;
impl Q { fn qm(&self) {} }
struct E;
impl E { fn em(&self) {} }
struct F;
impl F { fn fm(&self) {} }
struct W<T> { x: T }
fn f(r1: Result<P, E>, r2: Result<Q, F>, o: Option<Result<P, E>>, ro: Result<Option<P>, E>, w: W<P>, wo: W<Result<P,E>>) {
    let a = r1.and(r2);
    if let Ok(u) = a { u.qm(); }
    let b = r1.or(r2);
    if let Ok(v) = b { v.pm(); }
    if let Err(e1) = b { e1.fm(); }
    let t1 = o.transpose();
    if let Ok(x) = t1 {
        if let Some(inner) = x { inner.pm(); }
    }
    let t2 = ro.transpose();
    if let Some(y) = t2 {
        if let Ok(p) = y { p.pm(); }
    }
    if let Ok(d) = r1.and(r2) { d.qm(); }
    let z = w.and(r2);
    if let Ok(k) = z { k.qm(); }
    let wt = wo.transpose();
    if let Ok(wt2) = wt { wt2.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    qm = _bindings(report, "qm", "associated_function")[0]
    fm = _bindings(report, "fm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `r1.and(r2)` yields `Result<Q, E>` — `Ok` reads r2's payload.
    assert bound.get("u.qm()") == qm.id
    # `r1.or(r2)` yields `Result<P, F>` — `Ok` reads r1's, `Err` r2's.
    assert bound.get("v.pm()") == pm.id
    assert bound.get("e1.fm()") == fm.id
    # `Option<Result<P, E>>::transpose` yields `Result<Option<P>, E>`.
    assert bound.get("inner.pm()") == pm.id
    # `Result<Option<P>, E>::transpose` yields `Option<Result<P, E>>`.
    assert bound.get("p.pm()") == pm.id
    # A direct `and` scrutinee heads `Result` too.
    assert bound.get("d.qm()") == qm.id
    # A custom `W` can name any `and`/`transpose` — stays opaque.
    assert not bound.get("k.qm()")
    assert not bound.get("wt2.pm()")
def test_result_as_ref_as_mut_and_as_deref_bind_payloads():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct E;
impl E { fn em(&self) {} }
struct W<T> { x: T }
fn f(r: Result<P, E>, rb: Result<Box<P>, E>, rm: Result<P, E>, re: Result<P, Box<E>>, w: W<P>) {
    let a = r.as_ref();
    if let Ok(p) = a { p.pm(); }
    if let Err(e) = a { e.em(); }
    let m = rm.as_mut();
    if let Ok(mp) = m { mp.pm(); }
    if let Err(me) = m { me.em(); }
    let d = rb.as_deref();
    if let Ok(dp) = d { dp.pm(); }
    let de = re.as_deref_err();
    if let Err(dee) = de { dee.em(); }
    if let Ok(x) = r.as_ref() { x.pm(); }
    let p2 = r.as_deref();
    if let Ok(np) = p2 { np.pm(); }
    let wa = w.as_ref();
    if let Ok(wp) = wa { wp.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    em = _bindings(report, "em", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `as_ref`/`as_mut` borrow the payload — `Result<&P, &E>`.
    assert bound.get("p.pm()") == pm.id
    assert bound.get("e.em()") == em.id
    assert bound.get("mp.pm()") == pm.id
    assert bound.get("me.em()") == em.id
    # `as_deref` peels one `Deref` layer — `Box<P>`/`Box<E>`.
    assert bound.get("dp.pm()") == pm.id
    assert bound.get("dee.em()") == em.id
    # A direct `as_ref` scrutinee heads `Result` too.
    assert bound.get("x.pm()") == pm.id
    # `P` does not deref, and a custom `W` names its own method —
    # both stay opaque.
    assert not bound.get("np.pm()")
    assert not bound.get("wp.pm()")



def test_result_produced_spelling_peels_for_unwrap_and_nested_patterns():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct Q;
impl Q { fn qm(&self) {} }
struct E;
impl E { fn em(&self) {} }
struct W<T> { x: T }
impl W<(P, Q)> { fn wq(&self) {} }
struct S { r: Result<[P; 2], E> }
fn make() -> Result<P, E> { todo!() }
fn give() -> Option<Option<P>> { todo!() }
fn f(r: Result<P, E>, w2: W<(P, Q,)>, s: S,
     rp: Result<std::pin::Pin<Box<P>>, E>,
     rl: Result<&'a mut P, E>,
     ro: Result<&Option<P>, E>,
     a: Result<P, E>, b: Result<P, E>, c: Result<Q, E>,
     o: Option<Option<P>>) {
    w2.wq();
    let v = make().as_ref();
    if let Ok(p) = v { p.pm(); }
    let u = r.as_ref().unwrap();
    u.pm();
    let wq2 = r.as_ref()?;
    wq2.pm();
    if let Ok(x) = give() { x.pm(); }
    if let Some(so) = o { if let Some(sp) = so { sp.pm(); } }
    if let Ok(p2) = s.r.as_ref() { p2[0].pm(); }
    if let Err(se) = s.r.as_ref() { se.em(); }
    if let Ok(pp) = rp.as_deref() { pp.pm(); }
    if let Ok(lp) = rl.as_deref_mut() { lp.pm(); }
    if let Err(oe) = a.or(b.and(c)) { oe.em(); }
    if let Ok(Some(sq)) = ro { sq.pm(); }
    if let Ok(xo) = ro { xo.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    em = _bindings(report, "em", "associated_function")[0]
    wq = _bindings(report, "wq", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `W<(P, Q,)>`'s trailing comma still finds `impl W<(P, Q)>`.
    assert bound.get("w2.wq()") == wq.id
    # `make().as_ref()`/`r.as_ref().unwrap()`/`r.as_ref()?` peel
    # the produced `Result<...>` spelling to the payload.
    assert bound.get("p.pm()") == pm.id
    assert bound.get("u.pm()") == pm.id
    assert bound.get("wq2.pm()") == pm.id
    # `Option<Option<P>>`'s `Some(x)` binds the inner `Option<P>`
    # — `x.pm()` is not `P`'s call.
    assert not bound.get("x.pm()")
    assert bound.get("sp.pm()") == pm.id
    # A `Result<[P; 2], E>` field's args are not a slice receiver.
    assert bound.get("p2[0].pm()") == pm.id
    assert bound.get("se.em()") == em.id
    # `Pin<Box<P>>`/`&'a mut P` deref to `P`.
    assert bound.get("pp.pm()") == pm.id
    assert bound.get("lp.pm()") == pm.id
    # `a.or(b.and(c))` types the nested produced `Result`.
    assert bound.get("oe.em()") == em.id
    # `&Option<P>` payload — `Some(q)` peels the borrow to `P`;
    # `Ok(x)` binds the whole `&Option<P>` (no `pm` member).
    assert bound.get("sq.pm()") == pm.id
    assert not bound.get("xo.pm()")
def test_option_and_result_inspect_keep_the_payload():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct E;
impl E { fn em(&self) {} }
struct W<T> { x: T }
mod m { pub struct P; impl P { pub fn pm(&self) {} } }
fn make() -> Option<P> { loop {} }
fn f(o: Option<P>, r: Result<P, E>, w: W<P>, oo: Option<Option<P>>) {
    if let Some(x) = o.inspect(|s| {}) { x.pm(); }
    if let Ok(y) = r.inspect(|s| {}) { y.pm(); }
    if let Err(e1) = r.inspect_err(|s| {}) { e1.em(); }
    if let Ok(z) = r.inspect(|s| {}) { z.pm(); }
    let wi = w.inspect(|s| {});
    if let Ok(wp) = wi { wp.pm(); }
    let oi = o.inspect(|s| {});
    if let Some(q) = oi { q.pm(); }
    if let Some(so) = oo.inspect(|s| {}) {
        if let Some(sp) = so { sp.pm(); }
    }
    if let Err(e2) = r.inspect(|s| {}).inspect_err(|s| {}) { e2.em(); }
    if let Some(mk) = make().inspect(|s| {}) { mk.pm(); }
    if let Some(fl) = o.filter(|s| true).inspect(|s| {}) { fl.pm(); }
    if let Some(ci) = o.inspect(|s| {}).inspect(|s| {}) { ci.pm(); }
    let r2: Result<m::P, E> = loop {};
    if let Ok(qr) = r2.inspect(|s| {}) { qr.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    em = _bindings(report, "em", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `inspect`/`inspect_err` yield the receiver unchanged.
    assert bound.get("x.pm()") == pm.id
    assert bound.get("y.pm()") == pm.id
    assert bound.get("e1.em()") == em.id
    # A direct `inspect` scrutinee heads `Result` too.
    assert bound.get("z.pm()") == pm.id
    # A custom `W` names its own `inspect` — stays opaque.
    assert not bound.get("wp.pm()")
    # An intermediate `let` keeps the payload too.
    assert bound.get("q.pm()") == pm.id
    # `Option<Option<P>>` — the inner `Option` stays a layer deep.
    assert bound.get("sp.pm()") == pm.id
    # A chained `inspect_err` does not re-wrap the `Result`.
    assert bound.get("e2.em()") == em.id
    # Produced receivers — return annotations and combinator chains.
    assert bound.get("mk.pm()") == pm.id
    assert bound.get("fl.pm()") == pm.id
    assert bound.get("ci.pm()") == pm.id
    # Spelled args resolve at the receiver's annotation scope —
    # `m::P` reaches `m::P::pm`, not a same-named local `P`.
    mod_pm = _bindings(report, "pm", "associated_function")[1]
    assert bound.get("qr.pm()") == mod_pm.id


    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(v: Vec<P>, h: std::collections::BinaryHeap<P>) {
    let mut it = v.iter().peekable();
    if let Some(a) = it.peek() { a.pm(); }
    if let Some(b) = it.next_if(|x| true) { b.pm(); }
    if let Some(c) = it.next_if_eq(&v[0]) { c.pm(); }
    if let Some(e) = v.iter().next_if(|x| true) { e.pm(); }
    if let Some(d) = h.peek() { d.pm(); }
    let mut pk = v.chunks(2).peekable();
    if let Some(chunk) = pk.peek() { chunk[0].pm(); }
    while let Some(c2) = pk.next_if(|x| true) { c2[0].pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `peek`/`next_if`/`next_if_eq` borrow the element like `next`.
    assert bound.get("a.pm()") == pm.id
    assert bound.get("b.pm()") == pm.id
    assert bound.get("c.pm()") == pm.id
    assert bound.get("e.pm()") == pm.id
    # `BinaryHeap::peek` still spells `Option<&P>`.
    assert bound.get("d.pm()") == pm.id
    # A `Peekable` over `chunks` carries `&[P]` items — `peek`/
    # `next_if` yield `Option<&&[P]>` whose `Some(chunk)` spells
    # `&[P]`, so `chunk[0]` still reads `P`.
    assert bound.get("chunk[0].pm()") == pm.id
    assert bound.get("c2[0].pm()") == pm.id

    assert bound.get("d.pm()") == pm.id

    assert bound.get("d.pm()") == pm.id
def test_extract_if_and_set_replace_bind_elements():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(s: std::collections::HashSet<P>, b: std::collections::BTreeSet<P>, m: std::collections::BTreeMap<i32, P>, h: std::collections::HashMap<i32, P>, v: Vec<P>) {
    for a in s.extract_if(|x| true) { a.pm(); }
    for c in b.extract_if(.., |x| true) { c.pm(); }
    for (k, e1) in m.extract_if(.., |k, e1| true) { e1.pm(); }
    for (k2, e2) in h.extract_if(.., |k2, e2| true) { e2.pm(); }
    let g = s.extract_if(|x| true);
    for ge in g { ge.pm(); }
    for (i, np) in s.extract_if(|x| true).enumerate() { np.pm(); }
    for ve in v.extract_if(0.., |x| true) { ve.pm(); }
    if let Some(rp) = s.replace(P) { rp.pm(); }
    if let Some(rb) = b.replace(P) { rb.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `s.extract_if(f)` drains the set's `P` elements.
    assert bound.get("a.pm()") == pm.id
    assert bound.get("c.pm()") == pm.id
    # The map variant yields `(K, V)` pairs — the value binds.
    assert bound.get("e1.pm()") == pm.id
    assert bound.get("e2.pm()") == pm.id
    # A let-bound `extract_if` iterator keeps the element too.
    assert bound.get("ge.pm()") == pm.id
    # `extract_if(..).enumerate()` yields (usize, P) pairs.
    assert bound.get("np.pm()") == pm.id
    # `Vec` names no `extract_if` — stays opaque.
    assert not bound.get("ve.pm()")
    # `s.replace(v)` returns the old element — `Option<P>`.
    assert bound.get("rp.pm()") == pm.id
    assert bound.get("rb.pm()") == pm.id


def test_extract_if_hasher_arg_and_alias():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct H;
type S = std::collections::HashSet<P>;
type M = std::collections::HashMap<i32, P>;
fn f(s: std::collections::HashSet<P, H>, m: std::collections::HashMap<i32, P, H>, a: S, b: M) {
    for x in s.extract_if(|v| true) { x.pm(); }
    for (k, e) in m.extract_if(.., |k, e| true) { e.pm(); }
    for y in a.extract_if(|v| true) { y.pm(); }
    for (k2, e2) in b.extract_if(.., |k2, e2| true) { e2.pm(); }
    if let Some(r) = a.replace(P) { r.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # A trailing hasher arg is not the element — `HashSet<P, H>`
    # still yields `P`; `HashMap<K, V, H>` still pairs `(K, V)`.
    assert bound.get("x.pm()") == pm.id
    assert bound.get("e.pm()") == pm.id
    # Type aliases expand to the std containers for the recipe.
    assert bound.get("y.pm()") == pm.id
    assert bound.get("e2.pm()") == pm.id
    assert bound.get("r.pm()") == pm.id


def test_extract_if_element_scope_and_custom_type():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct Holder { s: std::collections::HashSet<P> }
struct HashSet<P>(P);
fn f(x: Holder, c: HashSet<P>) {
    struct P;
    impl P { fn local(&self) {} }
    for a in x.s.extract_if(|v| true) { a.pm(); }
    for b in x.s.union(&x.s) { b.pm(); }
    for q in c.extract_if(|v| true) { q.pm(); }
    for w in c.union(&c) { w.pm(); }
    if let Some(r) = c.replace(P) { r.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # The element name resolves where the receiver's `P` was
    # annotated — the fn-local `struct P` cannot steal it.
    assert bound.get("a.pm()") == pm.id
    assert bound.get("b.pm()") == pm.id
    # A declared `struct HashSet` is not the std set — the
    # extract_if/union/replace recipes stay opaque.
    assert not bound.get("q.pm()")
    assert not bound.get("w.pm()")
    assert not bound.get("r.pm()")

def test_set_get_or_insert_binds_the_borrowed_element():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(s: std::collections::HashSet<P>, b: std::collections::BTreeSet<P>, v: Vec<P>) {
    let g = s.get_or_insert(P);
    g.pm();
    let g2 = s.get_or_insert_owned(P);
    g2.pm();
    let g3 = s.get_or_insert_with(P, |p| p);
    g3.pm();
    let gb = b.get_or_insert(P);
    gb.pm();
    let gb2 = b.get_or_insert_owned(P);
    gb2.pm();
    let gb3 = b.get_or_insert_with(P, |p| p);
    gb3.pm();
    let gv = v.get_or_insert(P);
    gv.pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `s.get_or_insert*` borrow the element — `&P`.
    assert bound.get("g.pm()") == pm.id
    assert bound.get("g2.pm()") == pm.id
    assert bound.get("g3.pm()") == pm.id
    assert bound.get("gb.pm()") == pm.id
    assert bound.get("gb2.pm()") == pm.id
    assert bound.get("gb3.pm()") == pm.id
    # `Vec` names no `get_or_insert` — stays opaque.
    assert not bound.get("gv.pm()")


def test_set_get_or_insert_reads_the_element_arg_before_the_hasher():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct S;
fn f(s: std::collections::HashSet<P, S>) {
    let g = s.get_or_insert(P);
    g.pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `HashSet<P, S>` — `P` is the element, `S` the hasher.
    assert bound.get("g.pm()") == pm.id


def test_set_get_or_insert_reads_through_a_type_alias():
    source = """
struct P;
impl P { fn pm(&self) {} }
type S = std::collections::HashSet<P>;
fn f(s: S) {
    let g = s.get_or_insert(P);
    g.pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    assert bound.get("g.pm()") == pm.id


def test_set_get_or_insert_field_resolves_args_in_the_field_scope():
    source = """
mod m {
    pub struct P;
    impl P { pub fn pm(&self) {} }
    pub struct W {
        pub f: std::collections::HashSet<P>,
    }
}
fn f(w: m::W) {
    let g = w.f.get_or_insert(m::P);
    g.pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `P` was spelled inside `mod m` — resolves `m::P`, not a root `P`.
    assert bound.get("g.pm()") == pm.id


def test_set_get_or_insert_stays_opaque_on_a_declared_same_named_set():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct HashSet<P> { q: i32 }
fn f(s: HashSet<P>, d: P) {
    let g = s.get_or_insert(d);
    g.pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # A user-declared `HashSet` is not the std set — its method
    # could return anything.
    assert not bound.get("g.pm()")

def test_btreemap_first_last_key_value_bind_pairs():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct K;
impl K { fn km(&self) {} }
fn f(b: std::collections::BTreeMap<K, P>, h: std::collections::HashMap<K, P>) {
    if let Some((k, x)) = b.first_key_value() { k.km(); x.pm(); }
    if let Some((k2, y)) = b.last_key_value() { k2.km(); y.pm(); }
    if let Some((k3, z)) = h.first_key_value() { z.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    km = _bindings(report, "km", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `first_key_value`/`last_key_value` are `BTreeMap`-only —
    # `Option<(&K, &V)>` — both halves bind.
    assert bound.get("k.km()") == km.id
    assert bound.get("x.pm()") == pm.id
    assert bound.get("k2.km()") == km.id
    assert bound.get("y.pm()") == pm.id
    # `HashMap` names no such method — stays opaque.
    assert not bound.get("z.pm()")


def test_map_pair_args_resolve_in_annotation_scope():
    source = """
mod m {
    pub type A<V> = std::collections::BTreeMap<i32, V>;
    pub type S<V> = std::collections::BTreeSet<V>;
}
struct P;
impl P { fn crate_pm(&self) {} }
fn f() {
    struct P;
    impl P { fn local_pm(&self) {} }
    let m: m::A<P> = mk();
    let mut s: m::S<P> = mk();
    if let Some((k, v)) = m.first_key_value() { v.local_pm(); v.crate_pm(); }
    for (k2, v2) in m.iter() { v2.local_pm(); }
    for v3 in m.values() { v3.local_pm(); }
    for p in s.extract_if(|q| true) { p.local_pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    local = _bindings(report, "local_pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # Substituted args were written at the receiver's annotation —
    # `P` inside `f`/`g` is the fn-local type, not the crate one.
    assert bound.get("v.local_pm()") == local.id
    assert bound.get("v2.local_pm()") == local.id
    assert bound.get("v3.local_pm()") == local.id
    assert bound.get("p.local_pm()") == local.id
    assert not bound.get("v.crate_pm()")


def test_map_field_pair_args_resolve_at_receiver_annotation():
    source = """
mod a { pub struct T; impl T { fn tm(&self) {} } }
mod m {
    pub struct W { pub map: std::collections::BTreeMap<crate::a::T, i32> }
    pub struct W2<V> { pub map: std::collections::BTreeMap<crate::a::T, V> }
}
struct P;
impl P { fn crate_pm(&self) {} }
fn f(w: m::W) {
    if let Some((k, v)) = w.map.first_key_value() { k.tm(); }
}
fn g(w2: m::W2<P>) {
    if let Some((k, v)) = w2.map.first_key_value() { k.tm(); v.crate_pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    tm = _bindings(report, "tm", "associated_function")[0]
    pm = _bindings(report, "crate_pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    assert bound.get("k.tm()") == tm.id
    assert bound.get("v.crate_pm()") == pm.id


def test_declared_btreemap_first_key_value_stays_opaque():
    source = """
struct BTreeMap<K, V> { _p: core::marker::PhantomData<(K, V)> }
struct P;
impl P { fn pm(&self) {} }
fn f(m: BTreeMap<i32, P>) {
    if let Some((k, v)) = m.first_key_value() { v.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # A user-declared `BTreeMap` is not std's — the speculative
    # `Option<(&K, &V)>` produce stays off.
    assert not bound.get("v.pm()")

def test_splice_and_linked_list_extract_if_bind_elements():
    source = """
struct P;
impl P { fn pm(&self) {} }
type L = LinkedList<P>;
fn f(v: Vec<P>, l: std::collections::LinkedList<P>, m: std::collections::BTreeMap<i32, P>, d: VecDeque<P>) {
    for a in v.splice(0..1, std::iter::empty()) { a.pm(); }
    for b in l.extract_if(|x| true) { b.pm(); }
    let g = l.extract_if(|x| true);
    for ge in g { ge.pm(); }
    for ve in m.splice(0..1, std::iter::empty()) { ve.pm(); }
    let s = v.splice(0..1, std::iter::empty());
    for se in s { se.pm(); }
    for (_, en) in l.extract_if(|x| true).enumerate() { en.pm(); }
    for de in d.splice(0..1, std::iter::empty()) { de.pm(); }
}
fn g(a: L) {
    let ag = a.extract_if(|x| true);
    for ae in ag { ae.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `v.splice` drains the removed `P` elements.
    assert bound.get("a.pm()") == pm.id
    # `LinkedList::extract_if` yields `P` like the sets.
    assert bound.get("b.pm()") == pm.id
    assert bound.get("ge.pm()") == pm.id
    # `extract_if(..).enumerate()` yields (usize, P) pairs.
    assert bound.get("en.pm()") == pm.id
    # An aliased `LinkedList<P>` expands to the same recipe.
    assert bound.get("ae.pm()") == pm.id
    # A let-bound `Vec::splice` iterator keeps the element too.
    assert bound.get("se.pm()") == pm.id
    # A map names no `splice` — stays opaque.
    assert not bound.get("ve.pm()")
    # `VecDeque` names no std `splice` either.
    assert not bound.get("de.pm()")

def test_result_inspect_ok_keeps_the_payload():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(r: Result<P, u8>) {
    let a = r.inspect_ok(|x| {});
    if let Ok(p) = a { p.pm(); }
    let b = r.inspect(|x| {});
    if let Ok(q) = b { q.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    assert bound.get("p.pm()") == pm.id
    assert bound.get("q.pm()") == pm.id


def test_declared_inspect_ok_stays_opaque():
    source = """
struct P;
impl P { fn pm(&self) {} }
trait Ext { fn inspect_ok(&self, f: fn(&i32)) -> Result<i32, u8>; }
impl Ext for Result<P, u8> {
    fn inspect_ok(&self, f: fn(&i32)) -> Result<i32, u8> { Ok(0) }
}
fn f(r: Result<P, u8>) {
    let a = r.inspect_ok(|x| {});
    if let Ok(p) = a { p.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # An extension `inspect_ok` need not echo the receiver — opaque.
    assert not bound.get("p.pm()") or bound.get("p.pm()") != pm.id

def test_btree_set_range_binds_borrowed_elements():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct K;
impl K { fn km(&self) {} }
fn f(s: std::collections::BTreeSet<P>, m: std::collections::BTreeMap<K, P>) {
    for a in s.range(..) { a.pm(); }
    for b in s.range_mut(..) { b.pm(); }
    let r = s.range(..);
    for c in r { c.pm(); }
    for d in m.range(..) { d.pm(); }
    for (i, (k, v)) in m.range(..).enumerate() { k.km(); v.pm(); }
    for (k2, v2) in m.range(..).chain(m.range(..)) { k2.km(); v2.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    km = _bindings(report, "km", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `BTreeSet::range`/`range_mut` iterate `&P` like the
    # set-algebra methods.
    assert bound.get("a.pm()") == pm.id
    assert bound.get("b.pm()") == pm.id
    assert bound.get("c.pm()") == pm.id
    # A map's `range` yields `(K, V)` pairs, not `P` — a single
    # loop name stays opaque.
    assert not bound.get("d.pm()")
    # `enumerate`/`chain` adapters keep the pair slots.
    assert bound.get("k.km()") == km.id
    assert bound.get("v.pm()") == pm.id
    assert bound.get("k2.km()") == km.id
    assert bound.get("v2.pm()") == pm.id


def test_declared_set_head_stops_the_range_recipe():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct BTreeSet<P>(P);
trait Ext { fn range_mut(&self) -> i32; }
fn f(s: BTreeSet<P>) {
    let r = s.range(..);
    for x in r { x.pm(); }
    for y in s.range(..) { y.pm(); }
}
fn g(s: std::collections::BTreeSet<P>) {
    for z in s.range_mut(..) { z.pm(); }
    let t = s.range_mut(..);
    for w in t { w.pm(); }
}
impl Ext for std::collections::BTreeSet<P> {
    fn range_mut(&self) -> i32 { 0 }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # A declared `struct BTreeSet` may `Deref` to a different
    # set — its `range` element is not the receiver's arg.
    assert not bound.get("x.pm()")
    assert not bound.get("y.pm()")
    # A declared `range_mut` extension decides its own return
    # type — `BTreeSet` has no std `range_mut`.
    assert not bound.get("z.pm()")
    assert not bound.get("w.pm()")




def test_split_entry_leak_and_intersperse_bind_payloads():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct K;
fn f(v: Vec<P>, m: std::collections::HashMap<K, P>, b: std::collections::BTreeMap<K, P>) {
    let s = v.leak();
    s[0].pm();
    let e = m.entry(K);
    let r = e.or_insert(P);
    r.pm();
    let e2 = e.and_modify(|x| {});
    let r2 = e2.or_insert(P);
    r2.pm();
    let eb = b.entry(K);
    let r3 = eb.into_mut();
    r3.pm();
    let eh = m.entry(K);
    let r4 = eh.into_mut();
    r4.pm();
    for i in v.iter().intersperse(&P) { i.pm(); }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `v.leak()` yields `&mut [P]` — the index reads `P`.
    assert bound.get("s[0].pm()") == pm.id
    # `let e = m.entry(k)` — the name resolves back to its
    # `entry`/`and_modify` initializer.
    assert bound.get("r.pm()") == pm.id
    assert bound.get("r2.pm()") == pm.id
    # `Entry::into_mut` is `BTreeMap`-only — `HashMap` stays
    # opaque.
    assert bound.get("r3.pm()") == pm.id
    assert not bound.get("r4.pm()")
    # `intersperse` keeps the element.
    assert bound.get("i.pm()") == pm.id


def test_foreign_field_leak_and_declared_into_mut_stay_opaque():
    source = """
struct P;
impl P { fn pm(&self) {} }
struct K;
mod m { pub struct P; pub struct S { pub f: Vec<P> } }
trait Ext { fn into_mut(self) -> i32; }
impl<'a, K2, V2> Ext for std::collections::btree_map::Entry<'a, K2, V2> {
    fn into_mut(self) -> i32 { 0 }
}
fn f(s: m::S, b: std::collections::BTreeMap<K, P>, k: K) {
    let x = s.f.leak();
    x[0].pm();
    let eb = b.entry(k);
    let r = eb.into_mut();
    r.pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `s.f` is another module's `Vec<m::P>` — the element resolves in
    # the field's scope, not the caller's `P` that owns `pm`.
    assert not bound.get("x[0].pm()")
    # A declared `into_mut` extension returns its own type, not the
    # std `&mut V` the BTreeMap entry recipe spells.
    assert not bound.get("r.pm()")

def test_result_cloned_and_into_boxed_slice_bind_payloads():
    source = """
struct P;
impl P { fn pm(&self) {} }
fn f(r: Result<&P, u8>, w: Result<P, u8>, v: Vec<P>) {
    let a = r.cloned();
    if let Ok(x) = a { x.pm(); }
    let c = r.copied();
    if let Ok(y) = c { y.pm(); }
    let d = w.cloned();
    if let Ok(z) = d { z.pm(); }
    let b = v.into_boxed_slice();
    b[0].pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `Result<&P, E>::cloned()`/`copied()` yield `Result<P, E>`.
    assert bound.get("x.pm()") == pm.id
    assert bound.get("y.pm()") == pm.id
    # A non-borrowed `Result` names no `cloned` — stays opaque.
    assert not bound.get("z.pm()")
    # `v.into_boxed_slice()` yields `Box<[P]>`.
    assert bound.get("b[0].pm()") == pm.id


def test_cloned_and_boxed_slice_call_receivers():
    source = """
struct P;
impl P { fn pm(&self) {} }
mod m { pub struct P; pub struct S { pub r: Result<&P, i32> } }
fn make_vec() -> Vec<P> { Vec::new() }
fn f(s: m::S, r: Result<&P, i32>, hs: std::collections::HashSet<P>) {
    if let Ok(p) = s.r.cloned() { p.pm(); }
    let c = r.as_ref().cloned();
    if let Ok(q) = c { q.pm(); }
    let b = make_vec().into_boxed_slice();
    b[0].pm();
    let bs = hs.into_boxed_slice();
    bs[0].pm();
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    pm = _bindings(report, "pm", "associated_function")[0]
    raw = source.encode()
    bound = {
        raw[c.span.start:c.span.end].decode(): c.target
        for c in report.calls
    }
    # `s.r` is `Result<&m::P>` — the peeled `P` resolves in the
    # field's module, not the caller's `P` that owns `pm`.
    assert not bound.get("p.pm()")
    # `r.as_ref().cloned()` keeps `Result<P, _>` — the produced
    # spelling's head still gates the recipe.
    assert bound.get("q.pm()") == pm.id
    # `make_vec()` names `Vec` through its declared return.
    assert bound.get("b[0].pm()") == pm.id
    # `HashSet` has no `into_boxed_slice` — the Vec recipe does not
    # apply to other containers.
    assert not bound.get("bs[0].pm()")
