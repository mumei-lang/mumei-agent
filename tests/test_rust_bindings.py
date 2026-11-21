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
        (
            "enum E { V(i32) } fn f(value:E){ match value { E::V(x) => x } }",
            "E::V",
            None,
            "qualified_path",
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
