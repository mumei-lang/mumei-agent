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
            "mod m { const K:i32=0; } fn f(v:i32){ match v { m::K..=m::K => (), _ => () } }",
            "m::K",
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


def test_prelude_variant_payload_stays_opaque_through_alias():
    # Prelude gating needs the spelled container name — `type O =
    # Option<P>` hides it, so `Some(p)` on `O` stays unpinned.
    source = """
struct P;
type O = Option<P>;
impl P { fn m(&self) {} }
fn f(o: O) {
    match o { Some(p) => p.m(), None => {} }
}
"""
    report = build_rust_bindings(source, pointer_width=64)
    assert _call(report, source, "p.m()").target == ""


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
    # Map iteration yields (K, V) pairs — a shape the element model
    # cannot spell, so neither `for e in map` nor a destructured
    # `(k, v)` picks up `P`'s methods.
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
    for text in ("e.m()", "v.m()"):
        call = next(
            c for c in report.calls
            if source[c.span.start:c.span.end] == text
        )
        assert call.target == ""


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
