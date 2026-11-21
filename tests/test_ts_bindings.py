import hashlib
import subprocess
import sys

import pytest

from agent.lexical_bindings import LexicalReportError, load_lexical_report
from agent.ts_bindings import (
    MAX_SOURCE_BYTES,
    PROFILE,
    build_ts_bindings as _build_ts_bindings,
)


def build_ts_bindings(source, *, tsx=False):
    report = _build_ts_bindings(source, tsx=tsx)
    references = [
        (reference.span, reference.binding_id, reference.kind)
        for reference in report.references
    ]
    assert len(references) == len(set(references)), source
    call_spans = [call.span for call in report.calls]
    assert len(call_spans) == len(set(call_spans)), source
    restored = load_lexical_report(
        report.to_json(), source, profile=PROFILE, target={}
    )
    assert restored.to_json() == report.to_json()
    return report


def _text(source, span):
    return source.encode("utf-8")[span.start : span.end].decode("utf-8")


def _bindings(report, name, kind=None):
    return sorted(
        (
            binding for binding in report.bindings
            if binding.name == name and (kind is None or binding.kind == kind)
        ),
        key=lambda binding: binding.span.start,
    )


def _refs(report, source, name=None, kind=None):
    return [
        reference for reference in report.references
        if (name is None or _text(source, reference.span) == name)
        and (kind is None or reference.kind == kind)
    ]


def _unresolved(report, name=None, reason=None):
    return [
        item for item in report.unresolved
        if (name is None or item.name == name)
        and (reason is None or item.reason == reason)
    ]


def _calls(report, kind=None):
    return [call for call in report.calls if kind is None or call.kind == kind]


def test_var_hoisting_function_hoisting_and_lexical_shadowing():
    source = """
function caller() {
    before;
    { var before = 1; }
    helper();
    function helper() {}
    let local = before;
}
"""
    report = build_ts_bindings(source)
    before = _bindings(report, "before", "local")[0]
    refs = _refs(report, source, "before")
    assert len(refs) == 2
    assert all(reference.binding_id == before.id for reference in refs)
    assert before.scope is not None
    assert before.scope.start <= source.index("before;") < before.scope.end
    helper = _bindings(report, "helper", "function")[0]
    call = _calls(report, "direct_local")[0]
    assert call.target == helper.id
    assert call.owner == _bindings(report, "caller", "function")[0].id
    assert not any(gap.reason == "temporal_dead_zone" for gap in report.gaps)


def test_unparenthesized_arrow_parameter_shadows_outer_binding():
    source = """
let x = 0;
const f = x => x;
const g = y => missing;
"""
    report = build_ts_bindings(source)
    outer = _bindings(report, "x", "local")[0]
    parameter = _bindings(report, "x", "parameter")[0]
    body_reference = next(
        reference for reference in _refs(report, source, "x")
        if reference.span.start > source.index("=>")
    )
    assert body_reference.binding_id == parameter.id
    assert body_reference.binding_id != outer.id
    assert any(
        item.name == "missing" and item.reason == "unknown_name"
        for item in _unresolved(report)
    )


def test_temporal_dead_zone_is_reported_but_not_for_nested_closures():
    source = """
function f() {
    value;
    const readLater = () => value;
    let value = 1;
    return readLater();
}
"""
    report = build_ts_bindings(source)
    binding = _bindings(report, "value", "local")[0]
    references = _refs(report, source, "value")
    assert len(references) == 2
    assert all(reference.binding_id == binding.id for reference in references)
    tdz_gaps = [gap for gap in report.gaps if gap.reason == "temporal_dead_zone"]
    assert len(tdz_gaps) == 1
    assert tdz_gaps[0].span == next(
        reference.span
        for reference in references
        if reference.span.start < binding.span.start
    )


def test_nested_function_expression_and_method_call_owners():
    source = """
function target() {}
function outer() {
    const arrow = () => target();
    function nested() { target(); }
}
class C { method() { target(); } }
"""
    report = build_ts_bindings(source)
    target = _bindings(report, "target", "function")[0]
    calls = [call for call in report.calls if call.target == target.id]
    assert len(calls) == 3
    arrow_call = next(call for call in calls if call.owner == "")
    nested = _bindings(report, "nested", "function")[0]
    method = _bindings(report, "method", "associated_function")[0]
    assert next(call for call in calls if call.owner == nested.id)
    assert next(call for call in calls if call.owner == method.id)
    assert arrow_call.kind == "direct_local"


def test_named_function_expression_and_class_expression_names_are_self_scoped():
    source = """
const fn = function selfName() { return selfName(); };
const klass = class Inner { method() { return Inner; } };
function outside() { selfName(); Inner; }
"""
    report = build_ts_bindings(source)
    self_name = _bindings(report, "selfName", "function")[0]
    inner = _bindings(report, "Inner", "class")[0]
    self_reference = next(
        reference for reference in _refs(report, source, "selfName")
        if reference.span.start > source.index("return selfName")
    )
    inner_reference = next(
        reference for reference in _refs(report, source, "Inner")
        if source.index("return Inner") < reference.span.start < source.index("function outside")
    )
    assert self_reference.binding_id == self_name.id
    assert inner_reference.binding_id == inner.id
    assert {item.name for item in _unresolved(report, reason="unknown_name")} >= {
        "selfName", "Inner"
    }


def test_catch_and_for_bindings_have_narrow_scopes():
    source = """
try { throw 1; } catch (error) { error = 1; }
error;
for (let index = 0; index < 2; index++) { index; }
index;
"""
    report = build_ts_bindings(source)
    error = _bindings(report, "error", "parameter")[0]
    index = _bindings(report, "index", "local")[0]
    inside_error = next(
        reference for reference in _refs(report, source, "error")
        if reference.span.start > error.span.end
    )
    inside_index = [
        reference for reference in _refs(report, source, "index")
        if index.scope is not None
        and index.scope.start <= reference.span.start < index.scope.end
    ]
    assert inside_error.binding_id == error.id
    assert error.mutable
    assert inside_error.kind == "write"
    assert not any(gap.reason == "const_reassignment" for gap in report.gaps)
    assert len(inside_index) == 4
    assert all(reference.binding_id == index.id for reference in inside_index)
    assert any(item.name == "error" for item in _unresolved(report, "error"))
    assert any(item.name == "index" for item in _unresolved(report, "index"))


def test_for_in_and_for_of_declarations_use_loop_or_var_scope():
    source = """
function loops(values, record) {
    for (let key in record) { key; }
    key;
    for (const [a, b] of values) { a; b; }
    a; b;
    for (var item of values) { item; }
    item;
}
"""
    report = build_ts_bindings(source)
    key = _bindings(report, "key", "local")[0]
    a = _bindings(report, "a", "local")[0]
    b = _bindings(report, "b", "local")[0]
    item = _bindings(report, "item", "local")[0]
    assert any(
        reference.binding_id == key.id and reference.kind == "read"
        for reference in _refs(report, source, "key")
    )
    assert any(reference.binding_id == a.id for reference in _refs(report, source, "a"))
    assert any(reference.binding_id == b.id for reference in _refs(report, source, "b"))
    assert item.scope is not None
    assert item.scope.start <= source.index("item;", source.index("for (var")) < item.scope.end
    assert {name for name in ("key", "a", "b")} <= {
        item.name for item in _unresolved(report, reason="unknown_name")
    }
    iterable_refs = _refs(report, source, "values")
    assert len(iterable_refs) == 2
    assert all(reference.kind == "read" for reference in iterable_refs)


def test_for_in_and_for_of_bare_targets_write_existing_bindings():
    source = """
function assign(iterable) {
    let x = 0, a = 0, b = 0;
    const fixed = 0;
    for (x of iterable) {}
    for ([a, b] of iterable) {}
    for (fixed of iterable) {}
    for (missing of iterable) {}
}
"""
    report = build_ts_bindings(source)
    for name in ("x", "a", "b", "fixed"):
        binding = _bindings(report, name, "local")[0]
        reference = _refs(report, source, name, "write")[0]
        assert reference.binding_id == binding.id
    assert any(
        item.name == "missing" and item.reason == "implicit_global"
        for item in _unresolved(report)
    )
    assert any(gap.reason == "const_reassignment" for gap in report.gaps)
    iterable_refs = _refs(report, source, "iterable")
    assert len(iterable_refs) == 4
    assert all(reference.kind == "read" for reference in iterable_refs)


def test_var_scope_stops_at_namespaces_and_class_static_blocks():
    source = """
var outer = 1;
namespace N { var namespaceLocal = 2; namespaceLocal; }
namespaceLocal;
class C { static { var staticLocal = 3; staticLocal; } }
staticLocal;
outer;
"""
    report = build_ts_bindings(source)
    namespace_local = _bindings(report, "namespaceLocal", "local")[0]
    static_local = _bindings(report, "staticLocal", "local")[0]
    outer = _bindings(report, "outer", "local")[0]
    assert _refs(report, source, "namespaceLocal")[0].binding_id == namespace_local.id
    assert _refs(report, source, "staticLocal")[0].binding_id == static_local.id
    assert _refs(report, source, "outer")[0].binding_id == outer.id
    assert any(item.name == "namespaceLocal" for item in _unresolved(report))
    assert any(item.name == "staticLocal" for item in _unresolved(report))


def test_destructured_parameters_defaults_and_rest_are_bound():
    source = """
function f(first = 1, second = first, {item: renamed = second, plain, ...rest}: Shape, ...tail: number[]) {
    return renamed + plain + rest.value + tail.length;
}
"""
    report = build_ts_bindings(source)
    for name in ("first", "second", "renamed", "plain", "rest", "tail"):
        assert _bindings(report, name, "parameter")
    first_ref = next(
        reference for reference in _refs(report, source, "first")
        if reference.span.start > source.index("second =")
    )
    assert first_ref.binding_id == _bindings(report, "first", "parameter")[0].id
    function = _bindings(report, "f", "function")[0]
    entry = next(item for item in report.functions if item.binding_id == function.id)
    assert len(entry.parameters) == 6
    assert entry.variadic
    assert any(item.name == "Shape" for item in _unresolved(report, "Shape"))


def test_assignment_pattern_defaults_bind_names_and_scan_expressions():
    source = """
function known() {}
const {x = known()} = {};
let [y = missing()] = [];
const f = ({a = known()}) => a;
let assigned = 0;
({ assigned = known() } = {});
"""
    report = build_ts_bindings(source)
    x = _bindings(report, "x", "local")[0]
    y = _bindings(report, "y", "local")[0]
    a = _bindings(report, "a", "parameter")[0]
    assigned = _bindings(report, "assigned", "local")[0]
    assert len(_refs(report, source, "x")) == 0
    assert any(reference.binding_id == a.id for reference in _refs(report, source, "a"))
    assert _refs(report, source, "assigned", "write")[0].binding_id == assigned.id
    known = _bindings(report, "known", "function")[0]
    assert [
        call.target for call in report.calls if call.target == known.id
    ] == [known.id, known.id, known.id]
    assert any(
        item.name == "missing" and item.reason == "unknown_name"
        for item in _unresolved(report)
    )
    assert y.name == "y" and x.name == "x"


@pytest.mark.parametrize(
    ("declaration", "name", "mutable"),
    [
        ("const fixed = 1;", "fixed", False),
        ("let changeable = 1;", "changeable", True),
        ("var hoisted = 1;", "hoisted", True),
    ],
)
def test_variable_mutability_is_binding_specific(declaration, name, mutable):
    report = build_ts_bindings(declaration)
    assert _bindings(report, name, "local")[0].mutable is mutable


def test_const_reassignment_and_implicit_global_writes_are_explicit():
    source = "const fixed = 1; let changed = 0; fixed = 2; changed += 1; missing = 3;"
    report = build_ts_bindings(source)
    fixed = _bindings(report, "fixed", "local")[0]
    changed = _bindings(report, "changed", "local")[0]
    fixed_write = next(
        reference
        for reference in _refs(report, source, kind="write")
        if reference.binding_id == fixed.id
    )
    assert _text(source, fixed_write.span) == "fixed"
    changed_refs = [reference for reference in report.references if reference.binding_id == changed.id]
    assert {reference.kind for reference in changed_refs} == {"read", "write"}
    assert any(gap.reason == "const_reassignment" for gap in report.gaps)
    assert any(item.name == "missing" and item.reason == "implicit_global" for item in report.unresolved)


def test_nested_place_writes_traverse_indexes_and_skip_this_binding():
    source = """
function update(array: any, index: number, other: number) {
    array[index].field = 1;
    array[index][other] += compute();
    this.field = 2;
}
"""
    report = build_ts_bindings(source)
    array = _bindings(report, "array", "parameter")[0]
    index_reads = _refs(report, source, "index", "read")
    array_refs = [reference for reference in report.references if reference.binding_id == array.id]
    assert len(index_reads) == 2
    assert [reference.kind for reference in array_refs] == [
        "write", "read", "write",
    ]
    assert len(_calls(report, "unresolved")) == 1
    assert any(item.name == "compute" for item in _unresolved(report, "compute"))
    this_start = source.index("this.field")
    assert not any(reference.span.start >= this_start for reference in report.references)


def test_destructuring_assignment_targets_write_each_binding():
    source = """
function assign(source: any) {
    let first = 0;
    let second = 0;
    ({ first, value: second } = source);
}
"""
    report = build_ts_bindings(source)
    for name in ("first", "second"):
        binding = _bindings(report, name, "local")[0]
        assert len(_refs(report, source, name, "write")) == 1
        assert _refs(report, source, name, "write")[0].binding_id == binding.id


def test_dynamic_constructs_and_with_scope_fail_closed():
    source = """
function run(known: any) {
    eval(known);
    new Function("return 1");
    with (known) { known; hidden; }
    arguments;
}
"""
    report = build_ts_bindings(source)
    reasons = {gap.reason for gap in report.gaps}
    assert {"dynamic_eval", "dynamic_function", "with_statement"} <= reasons
    assert any(item.name == "arguments" and item.reason == "arguments_object" for item in report.unresolved)
    with_names = [
        item.name for item in report.unresolved if item.reason == "with_scope"
    ]
    assert with_names == ["known", "hidden"]
    with_body_start = source.index("{", source.index("with (")) + 1
    with_body_end = source.index("}", with_body_start)
    assert not any(
        with_body_start <= reference.span.start < with_body_end
        for reference in report.references
    )


def test_decorators_ambient_declarations_and_namespaces():
    source = """
@sealed
class Decorated {}
declare function external(value: number): string;
declare const ambientValue: number;
namespace N {
    export const localValue: number = 1;
    export function localFunction() { return localValue; }
}
function use() { external(ambientValue); N.localFunction(); }
"""
    report = build_ts_bindings(source)
    assert any(gap.reason == "decorator" for gap in report.gaps)
    external = _bindings(report, "external", "ambient")[0]
    assert any(call.kind == "opaque_ambient" and call.target == external.id for call in report.calls)
    assert _bindings(report, "N", "namespace")
    local_value = _bindings(report, "localValue", "local")[0]
    assert any(reference.binding_id == local_value.id for reference in _refs(report, source, "localValue"))
    assert any(call.kind == "opaque_method" for call in report.calls)


def test_import_forms_and_type_only_import_namespaces():
    source = """
import Default, { named as localName, type TypeOnly } from "module-a";
import * as NS from "module-b";
import type TypeDefault from "module-c";
import Equals = require("module-d");
function use(value: TypeOnly, second: TypeDefault) {
    localName();
    Default();
    Equals();
    NS.member;
    TypeOnly;
}
"""
    report = build_ts_bindings(source)
    for name in ("Default", "localName", "TypeOnly", "NS", "TypeDefault", "Equals"):
        assert _bindings(report, name, "import")
    calls = [call for call in report.calls if call.kind == "opaque_import"]
    assert len(calls) == 3
    assert _refs(report, source, "NS")
    assert not _refs(report, source, "member")
    value_only = [
        item for item in _unresolved(report, "TypeOnly")
        if item.span.start >= source.index("TypeOnly;", source.index("function use"))
    ]
    assert value_only


@pytest.mark.parametrize(
    ("source", "name", "type_only"),
    [
        ('import {type as renamed} from "m";', "renamed", False),
        ('import type from "m";', "type", False),
        ('import {type} from "m";', "type", False),
        ('import type X from "m";', "X", True),
        ('import {type X} from "m";', "X", True),
        ('import type {X} from "m";', "X", True),
    ],
)
def test_import_type_only_classification_uses_syntax_nodes(
    source, name, type_only
):
    report = build_ts_bindings(source)
    binding = _bindings(report, name, "import")[0]
    assert binding.type_only is type_only
    assert ("value" in binding.namespaces) is not type_only


@pytest.mark.parametrize("prefix", ["export default", "export ="])
def test_expression_exports_scan_resolved_names(prefix):
    source = f"const known = 1; {prefix} known;"
    report = build_ts_bindings(source)
    known = _bindings(report, "known", "local")[0]
    reference = next(
        reference for reference in _refs(report, source, "known")
        if reference.span.start > source.index(prefix)
    )
    assert reference.binding_id == known.id


@pytest.mark.parametrize("prefix", ["export default", "export ="])
def test_expression_exports_scan_unresolved_calls(prefix):
    source = f"{prefix} missing();"
    report = build_ts_bindings(source)
    assert any(item.name == "missing" and item.reason == "unknown_name" for item in _unresolved(report))
    assert len(report.calls) == 1
    assert report.calls[0].kind == "unresolved"
    assert not report.complete


def test_tsx_uses_tsx_grammar_and_resolves_component_expression():
    source = 'import { Widget } from "ui"; const view = <Widget value={amount}/>;'
    report = build_ts_bindings(source, tsx=True)
    widget = _bindings(report, "Widget", "import")[0]
    assert any(reference.binding_id == widget.id for reference in _refs(report, source, "Widget"))
    assert any(item.name == "amount" and item.reason == "unknown_name" for item in report.unresolved)


def test_source_annotation_type_facts_and_alias_chains():
    source = """
type NumberAlias = number;
type NumberAgain = NumberAlias;
type Big = bigint;
const value: NumberAgain = 1;
const big: Big = 1n;
const flag: boolean = true;
"""
    report = build_ts_bindings(source)
    aliases = {
        name: _bindings(report, name, "type_alias")[0]
        for name in ("NumberAlias", "NumberAgain", "Big")
    }
    value = _bindings(report, "value", "local")[0]
    big = _bindings(report, "big", "local")[0]
    flag = _bindings(report, "flag", "local")[0]
    assert (value.type.kind, value.type.bit_width, value.type.type_id) == (
        "float", 64, aliases["NumberAgain"].id
    )
    assert (big.type.kind, big.type.bit_width, big.type.signed, big.type.type_id) == (
        "bigint", 0, True, aliases["Big"].id
    )
    assert (flag.type.kind, flag.type.bit_width) == ("bool", 1)


def test_type_facts_follow_lexical_scopes_and_enum_bindings():
    source = """
type Shadowed = number;
interface Named {}
enum Status { Outer }
class Box {}
namespace Inner {
    type Shadowed = boolean;
    interface Named {}
    enum Status { Ready }
    class Box {}
    const namespaceAlias: Shadowed = true;
    const namespaceInterface: Named = {} as Named;
    const namespaceEnum: Status = Status.Ready;
    const namespaceClass: Box = new Box();
}
function local() {
    type Shadowed = bigint;
    interface Named {}
    enum Status { Local }
    class Box {}
    const functionAlias: Shadowed = 1n;
    const functionInterface: Named = {} as Named;
    const functionEnum: Status = Status.Local;
    const functionClass: Box = new Box();
}
const outerAlias: Shadowed = 1;
const outerInterface: Named = {} as Named;
const outerEnum: Status = Status.Outer;
const outerClass: Box = new Box();
function localOnly() {
    type LocalOnly = number;
    const inside: LocalOnly = 1;
}
const outside: LocalOnly = 1;
"""
    report = build_ts_bindings(source)
    aliases = _bindings(report, "Shadowed", "type_alias")
    interfaces = _bindings(report, "Named", "interface")
    enums = _bindings(report, "Status", "enum")
    classes = _bindings(report, "Box", "class")
    assert len(aliases) == len(interfaces) == len(enums) == len(classes) == 3
    expected = {
        "namespaceAlias": (aliases[1].id, "bool"),
        "functionAlias": (aliases[2].id, "bigint"),
        "outerAlias": (aliases[0].id, "float"),
        "namespaceInterface": (interfaces[1].id, "named"),
        "functionInterface": (interfaces[2].id, "named"),
        "outerInterface": (interfaces[0].id, "named"),
        "namespaceEnum": (enums[1].id, "named"),
        "functionEnum": (enums[2].id, "named"),
        "outerEnum": (enums[0].id, "named"),
        "namespaceClass": (classes[1].id, "named"),
        "functionClass": (classes[2].id, "named"),
        "outerClass": (classes[0].id, "named"),
    }
    for name, (type_id, kind) in expected.items():
        fact = _bindings(report, name, "local")[0].type
        assert (fact.type_id, fact.kind) == (type_id, kind)
    assert any(
        item.name == "LocalOnly" and item.reason == "unknown_name"
        for item in report.unresolved
    )


def test_composite_types_stay_unknown_and_keep_inner_type_references():
    source = """
type Atom = number;
const array: Atom[] = [];
const tuple: [Atom, number] = [1, 2];
const union: Atom | string = 1;
const generic: Array<Atom> = [];
const object: { value: Atom } = { value: 1 };
const callable: (input: Atom) => Atom = (input) => input;
"""
    report = build_ts_bindings(source)
    atom = _bindings(report, "Atom", "type_alias")[0]
    values = [
        _bindings(report, name, "local")[0]
        for name in ("array", "tuple", "union", "generic", "object", "callable")
    ]
    assert all(
        (value.type.kind, value.type.bit_width, value.type.type_id)
        == ("unknown", 0, "")
        for value in values
    )
    atom_references = _refs(report, source, "Atom")
    assert len(atom_references) == 7
    assert all(reference.binding_id == atom.id for reference in atom_references)
    assert all(reference.kind == "read" for reference in atom_references)


def test_generic_parameters_shadow_outer_types_and_do_not_leak():
    source = """
type T = number;
function generic<T extends number>(value: T): T {
    const local: T = value;
    return local;
}
function outside(value: T) { return value; }
"""
    report = build_ts_bindings(source)
    alias = _bindings(report, "T", "type_alias")[0]
    generic = _bindings(report, "T", "generic_parameter")[0]
    inside = _bindings(report, "value", "parameter")[0]
    outside = _bindings(report, "value", "parameter")[1]
    assert inside.type.kind == "unknown"
    assert outside.type.kind == "float"
    assert outside.type.type_id == alias.id
    assert any(reference.binding_id == generic.id for reference in _refs(report, source, "T"))
    assert generic.scope is not None


def test_qualified_and_type_query_names_do_not_resolve_final_segments():
    source = """
namespace NS { export type T = number; }
type Qualified = NS.T;
type Imported = import("module-x").T;
type Queried = typeof value;
const value = 1;
"""
    report = build_ts_bindings(source)
    assert sum(item.reason == "qualified_path" for item in report.unresolved) == 3
    assert not _refs(report, source, "T")
    assert not _refs(report, source, "value")


def test_reserved_primitive_alias_syntax_is_handled_without_shadowing_number():
    source = "type number = string; const value: number = 1;"
    report = build_ts_bindings(source)
    assert _bindings(report, "number", "type_alias")
    assert _bindings(report, "value", "local")[0].type.kind == "float"


@pytest.mark.parametrize(
    ("source", "expected_kind"),
    [
        ("function f() {} function g() { f(); }", "direct_local"),
        ("async function f() {} function g() { f(); }", "opaque_async"),
        ("function* f() {} function g() { f(); }", "opaque_generator"),
        ("function f<T>() {} function g() { f<number>(); }", "opaque_value"),
        ("function g() { (f)(); } function f() {}", "direct_local"),
    ],
)
def test_call_classification_for_local_function_forms(source, expected_kind):
    report = build_ts_bindings(source)
    assert expected_kind in {call.kind for call in report.calls}


def test_optional_method_tagged_and_constructor_calls_are_classified():
    source = """
class C { method() {} }
function f(value: any, tag: any) {
    value.method();
    value?.();
    tag`hello ${value}`;
    new C();
}
"""
    report = build_ts_bindings(source)
    kinds = {call.kind for call in report.calls}
    assert {"opaque_method", "opaque_optional", "opaque_tagged", "opaque_new"} <= kinds


def test_computed_class_and_object_names_scan_key_expressions():
    source = """
function key() { return "name"; }
class C { [key()]() {} [key()] = 1; }
const object = { [key()]: 1, plain: 2 };
"""
    report = build_ts_bindings(source)
    key = _bindings(report, "key", "function")[0]
    calls = [call for call in report.calls if call.target == key.id]
    assert len(calls) == 3
    assert not _refs(report, source, "plain")
    assert not _unresolved(report, "plain")


def test_class_extends_scans_values_and_implements_scans_types():
    source = """
class Base {}
interface Contract {}
class Derived extends Base implements Contract {}
function makeBase() { return Base; }
class Created extends makeBase() {}
class Missing extends missingBase {}
"""
    report = build_ts_bindings(source)
    base = _bindings(report, "Base", "class")[0]
    contract = _bindings(report, "Contract", "interface")[0]
    make_base = _bindings(report, "makeBase", "function")[0]
    assert any(
        reference.binding_id == base.id
        and reference.kind == "read"
        and source.index("class Derived") < reference.span.start < source.index("implements")
        for reference in report.references
    )
    assert any(
        reference.binding_id == contract.id
        and reference.kind == "read"
        for reference in _refs(report, source, "Contract")
    )
    assert any(call.target == make_base.id for call in report.calls)
    assert any(
        item.name == "missingBase" and item.reason == "unknown_name"
        for item in _unresolved(report)
    )


def test_multibyte_spans_hash_and_output_are_deterministic():
    source = 'const greeting = "💡"; function f() { return greeting; }'
    report = build_ts_bindings(source)
    reference = _refs(report, source, "greeting")[0]
    assert _text(source, reference.span) == "greeting"
    assert report.source_sha256 == hashlib.sha256(source.encode("utf-8")).hexdigest()
    assert report.to_json() == build_ts_bindings(source).to_json()


def test_parser_errors_source_limit_and_deep_nesting_fail_closed():
    with pytest.raises(LexicalReportError, match="parse errors"):
        build_ts_bindings("function broken( {")
    with pytest.raises(LexicalReportError, match="source exceeds"):
        build_ts_bindings(" " * (MAX_SOURCE_BYTES + 1))
    old_limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(1000)
        source = "const value = " + "+".join(["1"] * 2000) + ";"
        with pytest.raises(LexicalReportError, match="nesting exceeds"):
            build_ts_bindings(source)
    finally:
        sys.setrecursionlimit(old_limit)


def test_cli_preserves_crlf_bytes_and_emits_loadable_report(tmp_path):
    source = "function f() {\r\n  let value = 1;\r\n  return value;\r\n}\r\n"
    path = tmp_path / "source.ts"
    path.write_bytes(source.encode("utf-8"))
    result = subprocess.run(
        [sys.executable, "-m", "agent", "ts-bindings", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = load_lexical_report(
        result.stdout, source, profile=PROFILE, target={}
    )
    assert report.source_sha256 == hashlib.sha256(source.encode()).hexdigest()
    assert _text(source, report.references[0].span) == "value"


@pytest.mark.parametrize(
    ("contents", "expected"),
    [
        (b"\xff", "not valid UTF-8"),
        (b"function broken( {", "parse errors"),
    ],
)
def test_cli_fails_with_fixed_errors_without_json(tmp_path, contents, expected):
    path = tmp_path / "source.ts"
    path.write_bytes(contents)
    result = subprocess.run(
        [sys.executable, "-m", "agent", "ts-bindings", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert expected in result.stderr
    assert result.stderr.startswith("ts-bindings: ")
