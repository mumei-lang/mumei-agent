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


@pytest.mark.parametrize(
    ("loop", "name"),
    [
        ("for (let x of x) {}", "x"),
        ("for (const [a] of [a]) {}", "a"),
        ("for (let k in k) {}", "k"),
    ],
)
def test_lexical_for_loop_variables_in_iterables_report_tdz(loop, name):
    source = f"function f() {{ {loop} }}"
    report = build_ts_bindings(source)
    binding = _bindings(report, name, "local")[0]
    reference = _refs(report, source, name)[0]
    assert reference.binding_id == binding.id
    assert any(gap.reason == "temporal_dead_zone" for gap in report.gaps)


@pytest.mark.parametrize(
    "source",
    [
        "let x = [1]; for (const y of x) {}",
        "function f() { for (var v of v) {} }",
    ],
)
def test_outer_and_var_for_loop_iterables_do_not_report_tdz(source):
    report = build_ts_bindings(source)
    assert not any(gap.reason == "temporal_dead_zone" for gap in report.gaps)


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


def test_nested_place_writes_read_roots_traverse_indexes_and_skip_this_binding():
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
    assert [reference.kind for reference in array_refs] == ["read", "read"]
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
    local_function = _bindings(report, "localFunction", "function")[0]
    assert any(
        call.kind == "direct_local" and call.target == local_function.id
        for call in report.calls
    )


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
    source = f"{source}\ntype TypeUse = {name};\nconst valueUse = {name};"
    report = build_ts_bindings(source)
    binding = _bindings(report, name, "import")[0]
    type_reference = next(
        reference
        for reference in _refs(report, source, name)
        if reference.span.start > source.index("type TypeUse")
    )
    assert type_reference.binding_id == binding.id
    value_references = [
        reference
        for reference in _refs(report, source, name)
        if reference.span.start > source.index("const valueUse")
    ]
    if type_only:
        assert not value_references
        assert any(
            item.name == name
            and item.reason == "unknown_name"
            and item.span.start > source.index("const valueUse")
            for item in _unresolved(report)
        )
    else:
        assert len(value_references) == 1
        assert value_references[0].binding_id == binding.id


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


def test_qualified_names_stay_unresolved_while_type_queries_resolve_values():
    source = """
namespace NS { export type T = number; }
type Qualified = NS.T;
type Imported = import("module-x").T;
type Queried = typeof value;
const value = 1;
"""
    report = build_ts_bindings(source)
    assert sum(item.reason == "qualified_path" for item in report.unresolved) == 2
    assert not _refs(report, source, "T")
    value = _bindings(report, "value", "local")[0]
    assert _refs(report, source, "value")[0].binding_id == value.id


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


def test_jsx_intrinsic_tags_are_ignored_and_components_resolve_roots():
    source = """
function Foo() {}
const child = 1;
const r = <div attr={child}>{missingChild}</div>;
const component = <Foo.Bar attr={child} />;
const custom = <my-widget attr={missingAttr} />;
const namespaced = <a:b />;
"""
    report = build_ts_bindings(source, tsx=True)
    foo = _bindings(report, "Foo", "function")[0]
    child = _bindings(report, "child", "local")[0]
    assert len(_refs(report, source, "Foo")) == 1
    assert _refs(report, source, "Foo")[0].binding_id == foo.id
    child_refs = _refs(report, source, "child")
    assert len(child_refs) == 2
    assert all(reference.binding_id == child.id for reference in child_refs)
    assert not _refs(report, source, "div")
    assert not _refs(report, source, "my-widget")
    assert not _refs(report, source, "a")
    assert not _refs(report, source, "b")
    assert {
        item.name for item in _unresolved(report)
    } >= {"missingChild", "missingAttr"}
    assert not _unresolved(report, "div")
    assert not _unresolved(report, "my-widget")
    assert not _unresolved(report, "a:b")


def test_jsx_intrinsic_element_does_not_make_report_incomplete():
    report = build_ts_bindings("const r = <div />;", tsx=True)
    assert report.complete
    assert not report.unresolved


def test_member_and_index_writes_read_object_roots_without_reassigning():
    source = """
const o = {x: 1};
const arr = [1];
let index = 0;
o.x = 2;
arr[index] = 3;
o.x += 1;
o.x++;
delete o.x;
"""
    report = build_ts_bindings(source)
    assert report.complete
    assert not any(gap.reason == "const_reassignment" for gap in report.gaps)
    for name, expected in (("o", 4), ("arr", 1), ("index", 1)):
        references = _refs(report, source, name)
        assert len(references) == expected
        assert all(reference.kind == "read" for reference in references)


def test_direct_const_reassignment_still_reports_a_gap():
    report = build_ts_bindings("const fixed = 0; fixed = 1;")
    assert any(gap.reason == "const_reassignment" for gap in report.gaps)


def test_typeof_type_queries_read_value_roots_conservatively():
    source = """
declare const value: number;
declare const object: {x: number};
type ValueType = typeof value;
type MemberType = typeof object.x;
type ImportedType = typeof import("module");
type MissingType = typeof notDeclared;
"""
    report = build_ts_bindings(source)
    value = _bindings(report, "value", "ambient")[0]
    object_binding = _bindings(report, "object", "ambient")[0]
    assert _refs(report, source, "value")[0].binding_id == value.id
    assert _refs(report, source, "object")[0].binding_id == object_binding.id
    assert any(
        item.name == "notDeclared" and item.reason == "unknown_name"
        for item in _unresolved(report)
    )
    assert any(
        "import" in item.name and item.reason == "qualified_path"
        for item in _unresolved(report)
    )
    aliases = {
        binding.name: binding
        for binding in report.bindings
        if binding.name in {"ValueType", "MemberType", "ImportedType", "MissingType"}
    }
    assert len(aliases) == 4
    assert all(binding.type.kind == "unknown" for binding in aliases.values())


def test_typeof_value_reference_does_not_report_runtime_tdz():
    source = "type T = typeof value; const value = 1;"
    report = build_ts_bindings(source)
    value = _bindings(report, "value", "local")[0]
    references = _refs(report, source, "value")
    assert len(references) == 1
    assert references[0].binding_id == value.id
    assert references[0].kind == "read"
    assert report.complete

    runtime_read = build_ts_bindings("value; const value = 1;")
    assert any(gap.reason == "temporal_dead_zone" for gap in runtime_read.gaps)


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


def _member_bindings(report, name, kind):
    return [b for b in report.bindings if b.name == name and b.kind == kind]


def test_member_access_binds_class_members():
    source = """
class Base { base(): number { return 1 } }
class C extends Base {
    static count = 0;
    field: number;
    method(): number { return this.base() + this.field }
    run(other: C) { other.method(); }
}
const c = new C();
c.method(); C.count;
"""
    report = build_ts_bindings(source)
    base = _member_bindings(report, "base", "associated_function")[0]
    assert any(r.binding_id == base.id for r in _refs(report, source, "base"))
    method = _member_bindings(report, "method", "associated_function")[0]
    virtual = [
        c for c in report.calls
        if c.kind == "opaque_virtual" and c.target == method.id
    ]
    assert len(virtual) == 2  # `other.method()` and `c.method()`
    field = _member_bindings(report, "field", "struct_field")[0]
    assert any(r.binding_id == field.id for r in _refs(report, source, "field"))
    count = _member_bindings(report, "count", "struct_field")[0]
    assert any(r.binding_id == count.id for r in _refs(report, source, "count"))


def test_member_access_binds_interface_and_enum_members():
    source = """
interface Shape { area(): number; name: string }
function areaOf(s: Shape): number { return s.area() + s.name.length }
enum Color { Red, Blue }
const pick = Color.Blue;
"""
    report = build_ts_bindings(source)
    area = _member_bindings(report, "area", "associated_function")[0]
    assert any(
        c.kind == "opaque_bodyless" and c.target == area.id
        for c in report.calls
    )
    name = _member_bindings(report, "name", "struct_field")[0]
    assert any(r.binding_id == name.id for r in _refs(report, source, "name"))
    blue = _member_bindings(report, "Blue", "enum_member")[0]
    assert any(r.binding_id == blue.id for r in _refs(report, source, "Blue"))


def test_member_access_private_and_unknown_stay_unbound():
    source = """
class C {
    private secret = 0;
    show(): number { return this.secret }
}
const c = new C();
const leak = c.secret;
const nothing = c.ghost;
"""
    report = build_ts_bindings(source)
    secret = _member_bindings(report, "secret", "struct_field")[0]
    reads = [r for r in _refs(report, source, "secret") if r.binding_id == secret.id]
    assert len(reads) == 1  # only `this.secret`, not `c.secret`
    assert not any(r.kind == "read" for r in _refs(report, source, "ghost"))


def test_member_access_chains_through_field_types():
    source = """
class Engine { start(): void {} }
class Car { engine: Engine; drive(): void { this.engine.start(); } }
function getCar(): Car { return new Car() }
getCar().drive();
"""
    report = build_ts_bindings(source)
    engine = _member_bindings(report, "engine", "struct_field")[0]
    assert any(r.binding_id == engine.id for r in _refs(report, source, "engine"))
    start = _member_bindings(report, "start", "associated_function")[0]
    assert any(
        c.kind == "opaque_virtual" and c.target == start.id
        for c in report.calls
    )
    drive = _member_bindings(report, "drive", "associated_function")[0]
    assert any(
        c.kind == "opaque_virtual" and c.target == drive.id
        for c in report.calls
    )


def test_member_access_on_array_elements_binds():
    source = """
class Car { start(): void {} }
function go(cars: Car[], row: Car[][]) {
    cars[0].start();
    row[0][1].start();
}
"""
    report = build_ts_bindings(source)
    start = _member_bindings(report, "start", "associated_function")[0]
    calls = [
        c for c in report.calls
        if c.kind == "opaque_virtual" and c.target == start.id
    ]
    assert len(calls) == 2


def test_member_access_walks_interface_extends_chain():
    source = """
interface Base { base(): void }
interface Shape extends Base { area(): number }
function go(s: Shape) { s.base(); s.area(); }
"""
    report = build_ts_bindings(source)
    base = _member_bindings(report, "base", "associated_function")[0]
    area = _member_bindings(report, "area", "associated_function")[0]
    targets = {c.target for c in report.calls}
    assert base.id in targets and area.id in targets


def test_member_access_walks_dotted_base_chain():
    source = """
namespace Lib { export class Base { base(): void {} } }
class C extends Lib.Base { run(): void { this.base(); } }
"""
    report = build_ts_bindings(source)
    base = _member_bindings(report, "base", "associated_function")[0]
    assert any(
        c.kind == "opaque_virtual" and c.target == base.id
        for c in report.calls
    )


def test_member_call_kinds_follow_method_modifiers():
    source = """
class C {
    static async fetch(): Promise<number> { return 0 }
    *items(): Generator<number> { yield 1 }
    static make(): void {}
}
namespace N { export function *gen(): Generator<number> { yield 2 } }
C.fetch(); C.make(); const c = new C(); c.items(); N.gen();
"""
    report = build_ts_bindings(source)
    fetch = _member_bindings(report, "fetch", "associated_function")[0]
    items = _member_bindings(report, "items", "associated_function")[0]
    make = _member_bindings(report, "make", "associated_function")[0]
    gen = [b for b in report.bindings if b.name == "gen"][0]
    kinds = {(c.kind, c.target) for c in report.calls}
    assert ("opaque_async", fetch.id) in kinds
    assert ("opaque_generator", items.id) in kinds
    assert ("opaque_generator", gen.id) in kinds
    assert ("direct_local", make.id) in kinds


def test_member_base_resolves_at_declaration_scope():
    source = """
class Base { greet(): void {} }
class Derived extends Base { }
function scope() {
    class Base { other(): void {} }
    const d = new Derived();
    d.greet();
}
"""
    report = build_ts_bindings(source)
    greet = _member_bindings(report, "greet", "associated_function")[0]
    other = _member_bindings(report, "other", "associated_function")[0]
    assert any(
        c.kind == "opaque_virtual" and c.target == greet.id
        for c in report.calls
    )
    assert not any(c.target == other.id for c in report.calls)


def test_method_body_multiplication_is_not_a_generator():
    source = """
class C {
    make(): number { const y = 2 * 3; return y }
}
const c = new C(); c.make();
"""
    report = build_ts_bindings(source)
    make = _member_bindings(report, "make", "associated_function")[0]
    assert any(
        c.kind == "opaque_virtual" and c.target == make.id
        for c in report.calls
    )
    assert not any(c.kind == "opaque_generator" for c in report.calls)


def test_member_base_with_spaces_and_multi_segment_chains():
    source = """
namespace Lib { export namespace Inner { export class Base { m(): void {} } } }
class A extends Lib . Inner . Base { run(): void { this.m(); } }
class B extends Lib.Inner.Base { run(): void { this.m(); } }
"""
    report = build_ts_bindings(source)
    m = _member_bindings(report, "m", "associated_function")[0]
    calls = [
        c for c in report.calls
        if c.kind == "opaque_virtual" and c.target == m.id
    ]
    assert len(calls) == 2


def test_member_declaration_merging_namespace_and_class():
    source = """
namespace Lib {
    export class Inner { static run(): void {} inst(): void {} }
    export namespace Inner { export function viaNs(): void {} }
}
namespace Lib {
    export namespace Inner2 { export function viaNs2(): void {} }
}
namespace Lib {
    export class Inner2 { static run2(): void {} }
}
Lib.Inner.run();
Lib.Inner.viaNs();
Lib.Inner2.run2();
Lib.Inner2.viaNs2();
const i = new Lib.Inner();
i.inst();
"""
    report = build_ts_bindings(source)
    run = _member_bindings(report, "run", "associated_function")[0]
    via_ns = _member_bindings(report, "viaNs", "function")[0]
    inst_ids = {
        b.id for b in _member_bindings(report, "inst", "associated_function")
    }
    kinds = {c.kind for c in report.calls}
    assert "direct_local" in kinds
    targets = {c.target for c in report.calls}
    run2 = _member_bindings(report, "run2", "associated_function")[0]
    via_ns2 = _member_bindings(report, "viaNs2", "function")[0]
    assert run.id in targets
    assert via_ns.id in targets
    assert run2.id in targets
    assert via_ns2.id in targets
    assert inst_ids & targets
    news = [c for c in report.calls if c.kind == "opaque_new"]
    inner = _member_bindings(report, "Inner", "class")[0]
    assert any(c.target == inner.id for c in news)


def test_member_split_block_duplicate_classes_do_not_merge():
    source = """
class B { m(): void {} }
namespace Lib { class C extends B { go(): void { this.m(); } } }
namespace Lib { export class C { m(): void {} } }
"""
    report = build_ts_bindings(source)
    base_m = _member_bindings(report, "m", "associated_function")[0]
    calls = [
        c for c in report.calls
        if c.kind == "opaque_virtual" and c.target == base_m.id
    ]
    assert len(calls) == 1


def test_member_ambient_class_namespace_merge():
    source = """
declare namespace C { export function f(): void; }
declare class C { m(): void; }
const c = new C();
c.m();
C.f();
"""
    report = build_ts_bindings(source)
    ambient_c = [
        b for b in report.bindings if b.name == "C" and b.kind == "ambient"
    ][0]
    m = _member_bindings(report, "m", "associated_function")[0]
    new_calls = [c for c in report.calls if c.kind == "opaque_ambient"]
    assert any(c.target == ambient_c.id for c in new_calls)
    assert any(
        c.kind == "opaque_bodyless" and c.target == m.id
        for c in report.calls
    )


def test_member_split_block_enums_merge():
    # Split `enum E` declarations merge (only one may omit the first
    # initializer) — a member from either block must resolve.
    source = """
enum E { A = 0 }
enum E { B }
const x: E = E.B;
const y: E = E.A;
namespace Lib { export enum Inner { P = 0 } }
namespace Lib { export enum Inner { Q } }
const z = Lib.Inner.Q;
"""
    report = build_ts_bindings(source)
    members = {
        b.name: b.id
        for b in report.bindings
        if b.kind == "enum_member"
    }
    read_targets = {
        ref.binding_id for ref in report.references if ref.kind == "read"
    }
    assert members["A"] in read_targets
    assert members["B"] in read_targets
    assert members["Q"] in read_targets


def test_member_enum_does_not_merge_with_class():
    # `enum` can only merge with `namespace` or another `enum` —
    # `class E` + `enum E` is a duplicate-identifier error, so the
    # enum's members must not leak into the class's member lookup.
    source = """
class E { b(): void {} static s(): void {} }
enum E { B }
const x = E.B;
E.s();
"""
    report = build_ts_bindings(source)
    member_b = _member_bindings(report, "B", "enum_member")[0]
    read_targets = {
        ref.binding_id for ref in report.references if ref.kind == "read"
    }
    assert member_b.id in read_targets
    # The class-only static member must not resolve through the enum:
    # `class E` + `enum E` is a duplicate identifier, not a merge.
    s = _member_bindings(report, "s", "associated_function")[0]
    assert s.id not in read_targets
    assert not any(c.target == s.id for c in report.calls)


def test_member_new_on_local_var_keeps_variable_reference():
    # A `local` is not a declaration-merging participant: `new C()`
    # on the exported const in one `Lib` block must not be repointed
    # at the duplicate `class C` in the sibling block.
    source = """
namespace Lib { export const C = { n: 1 }; const v = new C(); }
namespace Lib { export class C { m(): void {} } }
"""
    report = build_ts_bindings(source)
    local_c = [
        b for b in report.bindings
        if b.name == "C" and b.kind == "local"
    ][0]
    call_refs = [r for r in report.references if r.kind == "call"]
    assert any(r.binding_id == local_c.id for r in call_refs)
    cls = [
        b for b in report.bindings
        if b.name == "C" and b.kind == "class"
    ][0]
    assert not any(r.binding_id == cls.id for r in call_refs)


def test_member_ambient_class_function_merge():
    # `declare class C` + `declare function C` and `declare class D` +
    # bodied `function D` are legal merges (functions may only merge
    # with ambient classes). `new C()` must name the class and the
    # instance-side member must resolve through the merge.
    source = """
declare class C { m(): void; }
declare function C(): void;
const c = new C();
c.m();
declare class D { n(): void; }
function D() {}
const d = new D();
d.n();
"""
    report = build_ts_bindings(source)
    classes = [
        b for b in report.bindings
        if b.name in {"C", "D"} and b.kind == "ambient"
    ]
    ambient = {b.name: b.id for b in classes}
    # The ambient class records are the first declared C/D.
    c_cls = _member_bindings(report, "m", "associated_function")[0]
    d_cls = _member_bindings(report, "n", "associated_function")[0]
    ambient_new = [c for c in report.calls if c.kind == "opaque_ambient"]
    assert len(ambient_new) == 2
    bodyless = {
        c.target for c in report.calls if c.kind == "opaque_bodyless"
    }
    assert c_cls.id in bodyless
    assert d_cls.id in bodyless
    # `new C()`/`new D()` name the ambient classes specifically —
    # `opaque_ambient` alone could not tell class from function here.
    call_refs = [r for r in report.references if r.kind == "call"]
    c_ambient = [b for b in classes if b.name == "C"][0]
    d_ambient = [b for b in classes if b.name == "D"][0]
    c_fn = [
        b for b in report.bindings
        if b.name == "C" and b.id != c_ambient.id
    ][0]
    assert any(r.binding_id == c_ambient.id for r in call_refs)
    assert any(r.binding_id == d_ambient.id for r in call_refs)
    assert not any(r.binding_id == c_fn.id for r in call_refs)


def test_member_ambient_var_interface_merge():
    # `interface I` (type side) + `declare const I` (value side, with a
    # construct signature) merge across spaces: `new I()` calls the
    # ambient const and `i.m()` resolves through the interface.
    source = """
interface I { m(): void }
declare const I: { new(): I }
const i = new I();
i.m();
"""
    report = build_ts_bindings(source)
    ambient = _member_bindings(report, "I", "ambient")[0]
    method = _member_bindings(report, "m", "associated_function")[0]
    call_refs = [r for r in report.references if r.kind == "call"]
    assert any(r.binding_id == ambient.id for r in call_refs)
    assert {
        c.target for c in report.calls if c.kind == "opaque_bodyless"
    } == {method.id}


def test_member_new_on_type_only_name_falls_back_to_value():
    # `declare const K` + `namespace K` can't legally merge (a
    # redeclaration per tsc), but for `new K()` the value-side const —
    # the only callable declaration — is the honest referent even when
    # the type-only namespace shadows the name.
    source = """
declare const K: { new(): K }
namespace K { export const q = 1 }
const k = new K();
"""
    report = build_ts_bindings(source)
    ambient = _member_bindings(report, "K", "ambient")[0]
    call_refs = [r for r in report.references if r.kind == "call"]
    assert call_refs and all(
        r.binding_id == ambient.id for r in call_refs
    )


def test_member_new_prefers_exported_over_private_duplicate():
    # Split-namespace blocks can hold a block-private duplicate of an
    # exported name: `new N.C()` must name the exported constructor
    # (`export const C`) and `c.m()` the exported interface, not the
    # private const/interface siblings in the later block.
    source = """
namespace N {
    export interface C { m(): void }
    export const C: { new(): C } = {} as any;
}
namespace N {
    const C = {} as any;
    interface C { n(): void }
}
const c = new N.C();
c.m();
"""
    report = build_ts_bindings(source)
    exported_const = [
        b for b in report.bindings
        if b.name == "C" and b.kind == "local"
    ]
    assert len(exported_const) == 2
    call_refs = [r for r in report.references if r.kind == "call"]
    # The exported const is the first `local C` (declared first).
    assert any(r.binding_id == exported_const[0].id for r in call_refs)
    assert not any(r.binding_id == exported_const[1].id for r in call_refs)
    method = _member_bindings(report, "m", "associated_function")[0]
    assert {
        c.target for c in report.calls if c.kind == "opaque_bodyless"
    } == {method.id}


def test_member_type_only_namespace_merges_with_var():
    # A namespace that exports only types coexists with a same-named
    # const (tsc accepts the pair); `new K()` names the const.
    source = """
const K: { new(): K } = {} as any;
namespace K { export interface I { im(): void } }
interface K { m(): void }
const k = new K();
k.m();
"""
    report = build_ts_bindings(source)
    var = _member_bindings(report, "K", "local")[0]
    call_refs = [r for r in report.references if r.kind == "call"]
    assert any(r.binding_id == var.id for r in call_refs)
    method = _member_bindings(report, "m", "associated_function")[0]
    assert any(
        c.target == method.id
        for c in report.calls if c.kind == "opaque_bodyless"
    )


def test_member_new_on_type_alias_falls_back_to_value():
    # `type T` + `const T` is a legal cross-space pair: `new T()`
    # names the const (a type alias can't be called).
    source = """
type T = { m(): void }
const T: { new(): T } = {} as any;
const t = new T();
"""
    report = build_ts_bindings(source)
    var = _member_bindings(report, "T", "local")[0]
    call_refs = [r for r in report.references if r.kind == "call"]
    assert call_refs and all(
        r.binding_id == var.id for r in call_refs
    )


def test_member_nested_ambient_namespace_implicit_exports():
    # Inside `declare namespace` every member is implicitly exported
    # at any depth, and bare `function f(): void` declarations parse
    # as function_signature nodes — both must be reachable through
    # qualified `N.Inner.x` access.
    source = """
declare namespace N {
    export namespace Inner {
        function f(): void;
        const v: number;
    }
    class C { m(): void }
}
N.Inner.f();
const x = N.Inner.v;
const c = new N.C();
c.m();
"""
    report = build_ts_bindings(source)
    f = _member_bindings(report, "f", "ambient")[0]
    v = _member_bindings(report, "v", "ambient")[0]
    m = _member_bindings(report, "m", "associated_function")[0]
    call_refs = {r.binding_id for r in report.references if r.kind == "call"}
    read_refs = {r.binding_id for r in report.references if r.kind == "read"}
    assert {f.id, m.id} & call_refs
    assert v.id in read_refs
    kinds = {(c.kind, c.target) for c in report.calls}
    assert ("opaque_bodyless", f.id) in kinds
    assert ("opaque_bodyless", m.id) in kinds
    assert any(
        c.kind == "opaque_ambient"
        for c in report.calls if c.target
    )


def test_member_ambient_export_clause_disables_implicit_export():
    # `export {}` inside `declare namespace` turns off the implicit
    # export of the remaining members: `N.C` is a private member
    # (tsc TS2339) and must not resolve through qualified access.
    # A named `export {D}` clause still exports the named member.
    source = """
declare namespace N {
    export {};
    class C { m(): void }
}
declare namespace M {
    export {D};
    class D { m(): void }
    class E { m(): void }
}
new N.C();
new M.D();
new M.E();
"""
    report = build_ts_bindings(source)
    c_rec = _member_bindings(report, "C", "ambient")
    d_rec = _member_bindings(report, "D", "ambient")
    e_rec = _member_bindings(report, "E", "ambient")
    assert c_rec and d_rec and e_rec
    call_targets = {c.target for c in report.calls if c.target}
    assert c_rec[0].id not in call_targets
    assert e_rec[0].id not in call_targets
    assert d_rec[0].id in call_targets


def test_member_alias_export_resolves_under_exported_name():
    # `export {A as B}` makes the member reachable only as `N.B` —
    # `N.A` is private and a same-named sibling must not shadow it.
    source = """
declare namespace M {
    export {Other as Inner};
    class Other { m(): void }
    class Inner { n(): void }
}
new M.Inner();
new M.Other();
"""
    report = build_ts_bindings(source)
    other = _member_bindings(report, "Other", "ambient")[0]
    inner = _member_bindings(report, "Inner", "ambient")[0]
    call_targets = {c.target for c in report.calls if c.target}
    assert other.id in call_targets
    assert inner.id not in call_targets


def test_member_type_only_export_stays_private_for_values():
    # `export type {Inner}` / `export {type Inner}` export no value:
    # `N.Inner.f()` is a TS2339 error and must not resolve.
    source = """
declare namespace M {
    export type {Inner};
    namespace Inner { function f(): void; }
}
declare namespace K {
    export {type Inner};
    namespace Inner { function f(): void; }
}
M.Inner.f();
K.Inner.f();
"""
    report = build_ts_bindings(source)
    assert not [r for r in report.references if r.kind == "call"]


def test_member_private_split_block_does_not_merge():
    # A non-exported `namespace Inner` is a distinct symbol — its
    # members do not merge into the public same-named namespace.
    source = """
namespace N { namespace Inner { export function f(): void {} } }
namespace N { export namespace Inner { export function g(): void {} } }
N.Inner.f();
N.Inner.g();
"""
    report = build_ts_bindings(source)
    g_rec = _member_bindings(report, "g", "function")
    assert g_rec
    call_targets = {c.target for c in report.calls if c.target}
    assert call_targets == {g_rec[0].id}


def test_member_bare_inner_namespace_in_ambient():
    # A bare `namespace Inner` inside `declare namespace` parses as
    # an expression_statement-wrapped internal_module and is still
    # implicitly exported (tsc resolves `N.Inner.f`).
    source = """
declare namespace N {
    namespace Inner {
        function f(): void;
    }
}
N.Inner.f();
"""
    report = build_ts_bindings(source)
    f = _member_bindings(report, "f", "ambient")[0]
    call_refs = {r.binding_id for r in report.references if r.kind == "call"}
    assert f.id in call_refs


def test_member_ambient_declarations_have_no_tdz():
    # `declare class`/`declare namespace` initialize nothing at
    # runtime: `new A()` textually before the declarations is not a
    # temporal-dead-zone access.
    source = """
const c = new A();
declare class A { m(): void; }
declare namespace A { export function f(): void; }
"""
    report = build_ts_bindings(source)
    assert not any(
        gap.reason == "temporal_dead_zone" for gap in report.gaps
    )
    ambient = [
        b for b in report.bindings
        if b.name == "A" and b.kind == "ambient"
    ][0]
    assert any(
        c.kind == "opaque_ambient" and c.target == ambient.id
        for c in report.calls
    )


def test_member_new_reference_lands_on_merged_class():
    # `class C` + `namespace C` merge: the `new C()` call target and the
    # constructor identifier's reference must both name the class.
    source = """
class C { m(): void {} }
namespace C { export const z = 1 }
const c = new C();
"""
    report = build_ts_bindings(source)
    cls = [
        b for b in report.bindings
        if b.name == "C" and b.kind == "class"
    ][0]
    new_calls = [c for c in report.calls if c.kind == "opaque_new"]
    assert any(c.target == cls.id for c in new_calls)
    call_refs = [r for r in report.references if r.kind == "call"]
    assert any(r.binding_id == cls.id for r in call_refs)


def test_member_alias_does_not_merge_into_same_named_namespace():
    # `export {A as B}` exports the class only as `B` — it must not
    # merge into the same-named `namespace A` from a sibling block.
    source = """
declare namespace N { export {A as B}; class A { static s(): void; } }
declare namespace N { export namespace A { export function s(): void; } }
N.B.s();
N.A.s();
"""
    report = build_ts_bindings(source)
    s_bindings = [
        b for b in report.bindings if b.name == "s"
    ]
    assert len(s_bindings) == 2
    call_targets = {c.target for c in report.calls if c.target}
    assert call_targets == {b.id for b in s_bindings}


def test_member_type_only_export_resolves_on_type_side():
    # `export type {A}` keeps A value-private but type-visible:
    # `interface B extends N.A` is legal and `b.a()` must resolve.
    source = """
declare namespace N { export type {A}; interface A { a(): void } }
interface B extends N.A {}
declare const b: B;
b.a();
"""
    report = build_ts_bindings(source)
    a_method = _member_bindings(report, "a", "associated_function")
    assert a_method
    assert any(
        c.target == a_method[0].id for c in report.calls
    )


def test_member_multiple_export_names_all_resolve():
    # `export {A as B, A as C, A}` publishes the member under A, B and C.
    source = """
declare namespace M { export {A as B, A as C, A}; class A {} }
new M.A(); new M.B(); new M.C();
"""
    report = build_ts_bindings(source)
    a_rec = _member_bindings(report, "A", "ambient")[0]
    for spelling in ("new M.A()", "new M.B()", "new M.C()"):
        call = next(
            c
            for c in report.calls
            if source[c.span.start : c.span.end] == spelling
        )
        assert call.target == a_rec.id, spelling


def test_member_quoted_export_alias_resolves():
    # `export {A as "Q"}` exports under the literal name Q.
    source = """
declare namespace M { export {A as "Q"}; class A {} }
new M.Q();
"""
    report = build_ts_bindings(source)
    a_rec = _member_bindings(report, "A", "ambient")[0]
    assert any(c.target == a_rec.id for c in report.calls)


def test_member_type_only_alias_export_resolves_on_type_side():
    # `export type {A as Public}` publishes A's type under Public.
    source = """
declare namespace N {
  interface A { f(): void }
  export type { A as Public }
}
interface D extends N.Public {}
declare const d: D;
d.f();
"""
    report = build_ts_bindings(source)
    f_rec = _member_bindings(report, "f", "associated_function")[0]
    call = next(
        c for c in report.calls
        if source[c.span.start : c.span.end] == "d.f()"
    )
    assert call.target == f_rec.id


def test_member_type_only_alias_hides_declared_name_on_type_side():
    # `export type {A as Public}` removes N.A — only Public is public.
    source = """
declare namespace N {
  interface A { f(): void }
  export type { A as Public }
}
interface D extends N.A {}
declare const d: D;
d.f();
"""
    report = build_ts_bindings(source)
    call = next(
        c for c in report.calls
        if source[c.span.start : c.span.end] == "d.f()"
    )
    assert not call.target


def test_member_split_block_reexport_alias_resolves():
    # A later same-named block's `export {f as g}` re-exports the
    # merged symbol — both spellings resolve.
    source = """
declare namespace N {
  export function f() {}
}
declare namespace N {
  export { f as g, f }
}
N.f();
N.g();
"""
    report = build_ts_bindings(source)
    f_rec = _member_bindings(report, "f", "function")[0]
    for spelling in ("N.f()", "N.g()"):
        call = next(
            c for c in report.calls
            if source[c.span.start : c.span.end] == spelling
        )
        assert call.target == f_rec.id, spelling


def test_member_class_extends_prefers_value_over_type_only_export():
    # `class D extends N.A` is a value position — the type-only
    # `export type {T as A}` export is not a valid base.
    source = """
declare namespace N {
  class A { m() {} }
  interface T { n(): void }
}
declare namespace N {
  export { A }
  export type { T as A }
}
class D extends N.A { }
const d = new D();
d.m();
"""
    report = build_ts_bindings(source)
    m_rec = _member_bindings(report, "m", "associated_function")[0]
    call = next(
        c for c in report.calls
        if source[c.span.start : c.span.end] == "d.m()"
    )
    assert call.target == m_rec.id


def test_member_inline_export_survives_type_clause():
    # `export class A` keeps `N.A` reachable on the value side even
    # when a sibling clause exports the type under another name.
    source = """
declare namespace N {
  export class A { m() {} }
  export type { A as Public }
}
const a = new N.A();
a.m();
"""
    report = build_ts_bindings(source)
    m_rec = _member_bindings(report, "m", "associated_function")[0]
    calls = {
        source[c.span.start : c.span.end]: c for c in report.calls
    }
    assert calls["new N.A()"].target
    assert calls["a.m()"].target == m_rec.id


def test_member_alias_clause_does_not_shadow_declared_class():
    # `export {B as A}` publishes the merged B only under "A" — a
    # class member in the clause's block must not answer `new N.B()`.
    source = """
declare namespace N {
  interface B { i: number }
  class B { n() {} }
  export { B as A }
}
declare namespace N {
  export class B { m() {} }
}
const x = new N.B();
x.m();
const y = new N.A();
y.n();
"""
    report = build_ts_bindings(source)
    b_public = next(
        b for b in report.bindings
        if b.name == "B" and "export class B" in source
        and source[b.span.start - 20 : b.span.start].find("export") >= 0
    )
    n_rec = _member_bindings(report, "n", "associated_function")[0]
    m_rec = _member_bindings(report, "m", "associated_function")[0]
    calls = {
        source[c.span.start : c.span.end]: c for c in report.calls
    }
    # `N.B` names the inline-exported class; `N.A` the clause block's.
    assert calls["new N.B()"].target == b_public.id
    assert calls["x.m()"].target == m_rec.id
    assert calls["new N.A()"].target != calls["new N.B()"].target
    assert calls["y.n()"].target == n_rec.id


def test_member_alias_prefers_clause_block_declaration():
    # `export {f as g}` exports the merged `f` symbol; when the same
    # block also declares an `f`, `N.g` binds that declaration.
    source = """
declare namespace N {
  function f(): string { return "" }
}
declare namespace N {
  function f(x: number): number { return x }
  export { f as g }
}
N.g();
"""
    report = build_ts_bindings(source)
    clause_block_f = next(
        b for b in report.bindings
        if b.name == "f" and b.span.start == source.index("f(x")
    )
    call = next(
        c for c in report.calls
        if source[c.span.start : c.span.end] == "N.g()"
    )
    assert call.target == clause_block_f.id


def test_member_lookup_cyclic_extends_does_not_recurse():
    # `Outer`/`Middle`/`Outer.Base` form a base-clause cycle: the lookup
    # must terminate and still bind `m` through the acyclic edge.
    source = """
namespace Outer { export class Base { m(): void {} } }
class Middle extends Outer.Base {}
class Outer extends Middle {}
const o = new Outer(); o.m();
"""
    report = build_ts_bindings(source)
    base_m = _member_bindings(report, "m", "associated_function")[0]
    call = next(
        c
        for c in _calls(report)
        if source[c.span.start : c.span.end] == "o.m()"
    )
    assert call.target == base_m.id


def test_member_clause_alias_and_declared_name_both_resolve_as_base():
    source = """
namespace N { export class A { m(): void {} } export {A as Public} }
class X extends N.A { }
class Y extends N.Public { }
const x = new X(); const y = new Y(); x.m(); y.m();
"""
    report = build_ts_bindings(source)
    base_m = _member_bindings(report, "m", "associated_function")[0]
    calls = {
        source[c.span.start : c.span.end]: c for c in _calls(report)
    }
    assert calls["x.m()"].target == base_m.id
    assert calls["y.m()"].target == base_m.id


def test_member_clause_aliased_namespace_resolves_on_type_side():
    # `export {Inner as Public}` publishes the namespace on the type
    # side too — qualified base paths reach `N.Public.B`, while the
    # un-exported `N.Inner` spelling stays unreachable.
    source = """
namespace N { namespace Inner { export class B { m(): void {} } } export {Inner as Public} }
class X extends N.Public.B { }
class Y extends N.Inner.B { }
const x = new X(); const y = new Y(); x.m(); y.m();
"""
    report = build_ts_bindings(source)
    base_m = _member_bindings(report, "m", "associated_function")[0]
    calls = {source[c.span.start : c.span.end]: c for c in _calls(report)}
    assert calls["x.m()"].target == base_m.id
    assert calls["y.m()"].target is None or calls["y.m()"].target != base_m.id


def test_member_interface_extends_picks_class_like_over_namespace_alias():
    # `export {I as Public}; export {M as Public}` collides on the
    # exported name; a type-side `extends` must reach the interface
    # member so its methods are inherited.
    source = """
namespace N { interface I { m(): void } namespace M { } export {I as Public}; export {M as Public} }
interface X extends N.Public {}
const x: X = null as any; x.m();
"""
    report = build_ts_bindings(source)
    base_m = _member_bindings(report, "m", "associated_function")[0]
    call = next(
        c
        for c in _calls(report)
        if source[c.span.start : c.span.end] == "x.m()"
    )
    assert call.target == base_m.id


def test_member_export_clause_resolves_type_only_local_names():
    # `export {I as Public}` on an interface resolves `I` on the
    # type side — a plain clause publishes type-only names too.
    source = """
namespace N { interface I { m(): void } export {I as Public} }
"""
    report = build_ts_bindings(source)
    assert not [
        item
        for item in report.unresolved
        if item.reason == "unknown_name"
    ]
    interface_i = next(
        b
        for b in report.bindings
        if b.name == "I" and b.kind == "interface"
    )
    # The clause name itself must reference the interface
    # declaration — a silently skipped clause would pass the
    # unresolved check above.
    clause_i = next(
        r
        for r in report.references
        if source[r.span.start : r.span.end] == "I"
        and r.span.start > source.index("export {")
    )
    assert clause_i.binding_id == interface_i.id


def test_member_alias_collision_extra_does_not_leak_into_declared_name():
    # Duplicate `export {... as Public}` is a tsc error but must not
    # let a declared-name spelling reach the losing member: `N.I`
    # names the interface only, never the namespace's members — while
    # the aliased `N.Public.B` still resolves in the same input.
    source = """
namespace N { interface I { m(): void } namespace M { export class B { n(): void {} } } export {I as Public}; export {M as Public} }
interface X extends N.Public.B {}
const x: X = null as any; x.n();
interface Y extends N.I {}
const y: Y = null as any; y.m();
"""
    report = build_ts_bindings(source)
    member_n = _member_bindings(report, "n", "associated_function")[0]
    aliased_call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "x.n()"
    )
    assert aliased_call.target == member_n.id
    declared_call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "y.m()"
    )
    assert declared_call.target == ""


def test_member_alias_collision_extra_still_descends_path():
    # `N.Public.B` descends into the namespace's B even when the
    # interface wins the `Public` segment.
    source = """
namespace N { interface I { m(): void } namespace M { export class B { n(): void {} } } export {I as Public}; export {M as Public} }
interface X extends N.Public.B {}
const x: X = null as any; x.n();
"""
    report = build_ts_bindings(source)
    member_n = _member_bindings(report, "n", "associated_function")[0]
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "x.n()"
    )
    assert call.target == member_n.id


def test_instance_member_does_not_pick_merged_namespace_function():
    # class C and namespace C merge — instance member wins; the
    # namespace's same-named function is a static facet.
    source = """
namespace N { export class C { m(): void {} } export namespace C { export function m(): void {} } }
const x = new N.C(); x.m();
"""
    report = build_ts_bindings(source)
    class_m = _member_bindings(report, "m", "associated_function")[0]
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "x.m()"
    )
    assert call.target == class_m.id


def test_member_alias_collision_value_side_prefers_winner_member():
    # Class and namespace share the export alias `Public`. When both
    # provide `f`, the winning class's static member applies; the
    # namespace member only fills in when the class lacks the name.
    # Parenthesized receivers take the same path.
    source = """
namespace N { export class C { static f(): void {} } namespace M { export function f(): void {} } export {C as Public}; export {M as Public} }
N.Public.f();
(N.Public).f();
"""
    report = build_ts_bindings(source)
    static_f = _member_bindings(report, "f", "associated_function")[0]
    calls = _calls(report)
    assert len(calls) == 2
    assert all(c.target == static_f.id for c in calls)


def test_member_alias_collision_value_side_falls_back_to_loser():
    source = """
namespace N { export class C { } namespace M { export function f(): void {} } export {C as Public}; export {M as Public} }
N.Public.f();
(N.Public).f();
"""
    report = build_ts_bindings(source)
    ns_f = _member_bindings(report, "f", "function")[0]
    calls = _calls(report)
    assert len(calls) == 2
    assert all(c.target == ns_f.id for c in calls)


def test_member_alias_collision_deeper_segments_fall_back_to_loser():
    # Both `Public` candidates provide `B`; the rest of the path
    # exists only under the losing namespace's `B` — the inherited
    # member still resolves.
    source = """
namespace N { namespace A { export class B { } } namespace M { export class B { } } namespace M { export namespace B { export class D { k(): void {} } } } export {A as Public}; export {M as Public} }
interface X extends N.Public.B.D {}
const x: X = null as any; x.k();
"""
    report = build_ts_bindings(source)
    member_k = _member_bindings(report, "k", "associated_function")[0]
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "x.k()"
    )
    assert call.target == member_k.id


def test_member_alias_collision_shared_base_keeps_winner_inheritance():
    # C1 and C2 collide on the alias `Public` and share a base class:
    # the winner's inherited static member beats the loser's
    # overriding member — the shared base must not be demoted to a
    # seeded candidate.
    source = """
class Base { static f(): void {} }
namespace N { class C1 extends Base { } class C2 extends Base { static f(): void {} } export {C1 as Public}; export {C2 as Public} }
N.Public.f();
"""
    report = build_ts_bindings(source)
    base_f = _member_bindings(report, "f", "associated_function")[0]
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "N.Public.f()"
    )
    assert call.target == base_f.id


def test_member_alias_collision_value_side_deep_loser_path():
    # `N.Public.B.D.k()` — the loser's intermediate members carry the
    # rest of the path on the value side too.
    source = """
namespace N { namespace A { export class B { } } namespace M { export class B { } } namespace M { export namespace B { export class D { static k(): void {} } } } export {A as Public}; export {M as Public} }
N.Public.B.D.k();
"""
    report = build_ts_bindings(source)
    member_k = _member_bindings(report, "k", "associated_function")[0]
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "N.Public.B.D.k()"
    )
    assert call.target == member_k.id


def test_qualified_type_annotation_types_receiver_members():
    source = """
namespace N { export class A { m(): void {} } }
let w: N.A = null as any; w.m();
"""
    report = build_ts_bindings(source)
    base_m = _member_bindings(report, "m", "associated_function")[0]
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "w.m()"
    )
    assert call.target == base_m.id


def test_qualified_type_annotation_through_clause_alias():
    source = """
namespace N { namespace Inner { export class B { m(): void {} } } export {Inner as Public} }
let v: N.Public.B = null as any; v.m();
"""
    report = build_ts_bindings(source)
    base_m = _member_bindings(report, "m", "associated_function")[0]
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "v.m()"
    )
    assert call.target == base_m.id


def test_qualified_type_annotation_private_segment_stays_unresolved():
    source = """
namespace N { namespace Inner { export class B { m(): void {} } } export {Inner as Public} }
let z: N.Inner.B = null as any; z.m();
"""
    report = build_ts_bindings(source)
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "z.m()"
    )
    assert call.target is None or call.kind == "opaque_method"
    unresolved = [u for u in report.unresolved if source[u.span.start : u.span.end] == "N.Inner.B"]
    assert unresolved


def test_member_qualified_alias_annotation_resolves_through_alias():
    # `N.T` aliasing class `C` types `x` as `C` — the alias is
    # transparent for member resolution, so `x.m()` reaches `C.m`.
    source = """
namespace N { class C { m(): void {} } export type T = C }
const x: N.T = null as any; x.m();
"""
    report = build_ts_bindings(source)
    member_m = _member_bindings(report, "m", "associated_function")[0]
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "x.m()"
    )
    assert call.target == member_m.id


def test_member_qualified_alias_annotation_keeps_initializer_inference():
    # A named-alias annotation must not block initializer inference:
    # `new C()` still types `x` as `C` when the alias resolves nowhere.
    source = """
class C { m(): void {} }
const x: Missing.T = new C(); x.m();
"""
    report = build_ts_bindings(source)
    member_m = _member_bindings(report, "m", "associated_function")[0]
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "x.m()"
    )
    assert call.target == member_m.id


def test_member_alias_prefers_clause_block_for_identical_signatures():
    # Overloads that the call cannot separate still prefer the clause
    # block's own declaration.
    source = """
declare namespace N {
  function f(): string { return "" }
}
declare namespace N {
  function f(): number { return 0 }
  export { f as g }
}
N.g();
"""
    report = build_ts_bindings(source)
    clause_block_f = next(
        b for b in report.bindings
        if b.name == "f"
        and b.span.start > source.index("export { f as g }") - 200
        and "number" in source[b.span.start : b.span.start + 30]
    )
    call = next(
        c for c in report.calls
        if source[c.span.start : c.span.end] == "N.g()"
    )
    assert call.target == clause_block_f.id

def test_member_overload_narrows_by_literal_arg_kind():
    source = """
class C { m(x: number): void; m(x: string): void; }
const c = new C(); c.m(1); c.m("s");
"""
    report = build_ts_bindings(source)
    overloads = _member_bindings(report, "m", "associated_function")
    number_sig = next(
        b for b in overloads if "number" in source[b.span.start : b.span.start + 12]
    )
    string_sig = next(
        b for b in overloads if "string" in source[b.span.start : b.span.start + 12]
    )
    calls = {source[c.span.start : c.span.end]: c for c in _calls(report)}
    assert calls["c.m(1)"].target == number_sig.id
    assert calls['c.m("s")'].target == string_sig.id

def test_member_overload_narrows_against_first_signature():
    source = """
class D { n(x: string): void; n(x: number): void; }
const d = new D(); d.n(1);
"""
    report = build_ts_bindings(source)
    overloads = _member_bindings(report, "n", "associated_function")
    number_sig = next(
        b for b in overloads if "number" in source[b.span.start : b.span.start + 12]
    )
    calls = {source[c.span.start : c.span.end]: c for c in _calls(report)}
    assert calls["d.n(1)"].target == number_sig.id

def test_member_overload_narrows_by_arity():
    source = """
class F { p(x: number, y: string): void; p(x: number): void; }
const f = new F(); f.p(1); f.p(1, "s");
"""
    report = build_ts_bindings(source)
    overloads = _member_bindings(report, "p", "associated_function")
    two = next(b for b in overloads if ", y" in source[b.span.start : b.span.start + 20])
    one = next(b for b in overloads if ", y" not in source[b.span.start : b.span.start + 20])
    calls = {source[c.span.start : c.span.end]: c for c in _calls(report)}
    assert calls["f.p(1)"].target == one.id
    assert calls['f.p(1, "s")'].target == two.id

def test_member_overload_spread_arg_leaves_order():
    source = """
class C { m(x: number): void; m(x: string): void; }
const c = new C(); const args: string[] = []; c.m(...args);
"""
    report = build_ts_bindings(source)
    overloads = _member_bindings(report, "m", "associated_function")
    calls = {source[c.span.start : c.span.end]: c for c in _calls(report)}
    assert calls["c.m(...args)"].target in {b.id for b in overloads}

def test_member_overload_identifier_arg_narrows_by_declared_type():
    source = """
class A {}
class B {}
class C { m(x: A): void; m(x: B): void; }
const c = new C(); const a: A = new A(); c.m(a);
"""
    report = build_ts_bindings(source)
    overloads = _member_bindings(report, "m", "associated_function")
    a_sig = next(
        b for b in overloads if "x: A" in source[b.span.start : b.span.start + 6]
    )
    calls = {source[c.span.start : c.span.end]: c for c in _calls(report)}
    assert calls["c.m(a)"].target == a_sig.id

def test_top_level_function_overload_narrowed_by_argument_kind():
    source = """
function f(x: number): void {}
function f(x: string): void {}
f("hi"); f(3);
"""
    report = build_ts_bindings(source)
    fs = sorted(
        (b for b in report.bindings if b.kind == "function"),
        key=lambda b: b.span.start,
    )
    number_f, string_f = fs
    calls = {source[c.span.start : c.span.end]: c for c in _calls(report)}
    assert calls['f("hi")'].target == string_f.id
    assert calls["f(3)"].target == number_f.id

def test_top_level_function_overload_no_match_keeps_last_signature():
    # No signature accepts a boolean — tsc reports an error; the call
    # still resolves to the last declared signature rather than
    # collapsing to unresolved.
    source = """
function f(x: number): void {}
function f(x: string): void {}
f(true);
"""
    report = build_ts_bindings(source)
    fs = sorted(
        (b for b in report.bindings if b.kind == "function"),
        key=lambda b: b.span.start,
    )
    string_f = fs[1]
    call = _calls(report)[0]
    assert call.target == string_f.id

def test_top_level_function_single_signature_unaffected():
    source = """
function f(x: number): void {}
f(3);
"""
    report = build_ts_bindings(source)
    f = next(b for b in report.bindings if b.kind == "function")
    assert _calls(report)[0].target == f.id


def test_overload_narrowing_respects_scope_shadowing():
    # The inner generic `f` shadows the outer `f`; `f(1)` inside the
    # block must stay on the shadowing declaration even though its
    # signature cannot be proven to fit.
    source = """
function f(x: number): number { return x }
{ function f<T>(x: T): T { return x } const y = f(1); }
"""
    report = build_ts_bindings(source)
    fs = _bindings(report, "f", "function")
    inner = next(b for b in fs if "T" in source[b.span.start : b.span.start + 40])
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "f(1)"
    )
    assert call.target == inner.id


def test_member_property_override_not_crossed_by_base_overloads():
    # A derived class's function-typed property overrides the base's
    # same-named method overloads; the call must not bind past it.
    source = """
class B { m(x: number): void; m(x: string): void; }
class D extends B { m: () => void = () => {} }
const d = new D(); d.m();
"""
    report = build_ts_bindings(source)
    prop = next(
        b for b in report.bindings
        if b.name == "m" and "=> void" in source[b.span.start : b.span.start + 30]
    )
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "d.m()"
    )
    assert call.target == prop.id or call.target == ""


def test_overload_param_alias_counts_as_its_target_kind():
    # `type Num = number` makes the first declaration fit a numeric
    # argument — the alias must not be compared as a bare string.
    source = """
type Num = number
function f(x: Num): void {}
function f(x: any): void {}
f(1);
"""
    report = build_ts_bindings(source)
    fs = _bindings(report, "f", "function")
    alias_sig = next(b for b in fs if "Num" in source[b.span.start : b.span.start + 30])
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "f(1)"
    )
    assert call.target == alias_sig.id


def test_overload_this_parameter_takes_no_argument():
    # `m(this: C, x: number)` is a one-argument signature — `this` is
    # not counted, so `c.m(1)` fits the number side.
    source = """
class C { m(this: C, x: number): void; m(x: string): void; }
const c = new C(); c.m(1);
"""
    report = build_ts_bindings(source)
    overloads = _member_bindings(report, "m", "associated_function")
    number_sig = next(b for b in overloads if "x: number" in source[b.span.start : b.span.start + 60])
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "c.m(1)"
    )
    assert call.target == number_sig.id


def test_overload_rest_param_compares_element_type():
    # `...x: Array<number>` accepts numeric arguments — the element
    # type, not the array type, is compared.
    source = """
function f(...x: Array<number>): void {}
function f(...x: any[]): void {}
f(1);
"""
    report = build_ts_bindings(source)
    fs = _bindings(report, "f", "function")
    array_sig = next(b for b in fs if "Array<number>" in source[b.span.start : b.span.start + 60])
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "f(1)"
    )
    assert call.target == array_sig.id


def test_overload_split_interface_blocks_merge_signatures():
    # Declaration merging puts `m` signatures on two `member_of`
    # blocks; both are overloads of the same member, not overrides.
    source = """
interface I { m(x: number): void }
interface I { m(x: string): void }
declare const i: I;
i.m("s");
"""
    report = build_ts_bindings(source)
    string_m = next(
        b for b in report.bindings
        if b.kind == "associated_function"
        and "string" in source[b.span.start : b.span.start + 30]
    )
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == 'i.m("s")'
    )
    assert call.target == string_m.id


def test_overload_generic_constraint_rejects_violating_argument():
    # `T extends string` does not accept a numeric argument — the
    # number overload wins even though the generic is declared first.
    source = """
function f<T extends string>(x: T): void {}
function f(x: number): void {}
f(1);
"""
    report = build_ts_bindings(source)
    fs = sorted(
        _bindings(report, "f", "function"), key=lambda b: b.span.start
    )
    call = _calls(report)[0]
    assert call.target == fs[1].id


def test_overload_generic_constraint_accepts_matching_argument():
    source = """
function f<T extends string>(x: T): void {}
function f(x: number): void {}
f("s");
"""
    report = build_ts_bindings(source)
    fs = sorted(
        _bindings(report, "f", "function"), key=lambda b: b.span.start
    )
    call = _calls(report)[0]
    assert call.target == fs[0].id

def test_overload_merged_interface_later_block_wins():
    # Both signatures accept — tsc puts the later merged block's
    # signatures first, so the `any` overload of block two wins.
    source = """
interface I { m(x: string): void }
interface I { m(x: any): void }
declare const i: I;
i.m("s");
"""
    report = build_ts_bindings(source)
    any_m = next(
        b for b in report.bindings
        if b.kind == "associated_function"
        and "any" in source[b.span.start : b.span.start + 30]
    )
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == 'i.m("s")'
    )
    assert call.target == any_m.id



def test_overload_generic_constraint_accepts_derived_argument():
    # `T extends Base` accepts `new Derived()` — a derived argument
    # fits the constraint, so the later `unknown` overload must not win.
    source = """
class Base {}
class Derived extends Base {}
function f<T extends Base>(x: T): void {}
function f(x: unknown): void {}
f(new Derived());
"""
    report = build_ts_bindings(source)
    fs = sorted(
        _bindings(report, "f", "function"), key=lambda b: b.span.start
    )
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "f(new Derived())"
    )
    assert call.target == fs[0].id

def test_overload_literal_signature_beats_wider_merged_signature():
    # `m(x: "s")` is more specific than `m(x: string)` — the literal
    # signature wins even though its block is declared earlier.
    source = """
interface I { m(x: "s"): void }
interface I { m(x: string): void }
declare const i: I;
i.m("s");
"""
    report = build_ts_bindings(source)
    literal_m = next(
        b for b in report.bindings
        if b.kind == "associated_function"
        and '"s"' in source[b.span.start : b.span.start + 30]
    )
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == 'i.m("s")'
    )
    assert call.target == literal_m.id


def test_overload_namespaced_base_is_not_global_base():
    # `D extends N.Base` is unrelated to the global `Base` — the
    # `x: Base` overload must not accept `new D()`.
    source = """
class Base {}
namespace N { export class Base {} }
class D extends N.Base {}
function f(x: Base): void {}
function f(x: unknown): void {}
f(new D());
"""
    report = build_ts_bindings(source)
    fs = sorted(
        _bindings(report, "f", "function"), key=lambda b: b.span.start
    )
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "f(new D())"
    )
    assert call.target == fs[1].id


def test_overload_shadowed_arg_type_uses_call_site_scope():
    # Inside `g` a local `D` shadows the outer `D extends Base` —
    # `new D()` there does not fit `T extends Base`.
    source = """
class Base {}
class D extends Base {}
function f<T extends Base>(x: T): void {}
function f(x: unknown): void {}
function g() {
  class D {}
  f(new D());
}
"""
    report = build_ts_bindings(source)
    fs = sorted(
        _bindings(report, "f", "function"), key=lambda b: b.span.start
    )
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "f(new D())"
    )
    assert call.target == fs[1].id

def test_overload_literal_annotation_rejects_different_literal():
    # `f("s", "bad")` does not fit `f("s", "t")` — the wider
    # `f(string, string)` overload wins instead.
    source = """
function f(a: string, b: string): void {}
function f(a: "s", b: "bad"): void {}
f("s", "t");
"""
    report = build_ts_bindings(source)
    fs = sorted(
        _bindings(report, "f", "function"), key=lambda b: b.span.start
    )
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == 'f("s", "t")'
    )
    assert call.target == fs[0].id


def test_overload_literal_count_does_not_reorder_declarations():
    # Both signatures fit `f("s", "t")`; tsc picks the first declared
    # even though the second matches two literals.
    source = """
function f(a: "s", b: string): void {}
function f(a: "s", b: "t"): void {}
f("s", "t");
"""
    report = build_ts_bindings(source)
    fs = sorted(
        _bindings(report, "f", "function"), key=lambda b: b.span.start
    )
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == 'f("s", "t")'
    )
    assert call.target == fs[0].id

def test_overload_literal_quote_style_does_not_reject_match():
    # `f('s')` fits `f(x: "s")` — quote style is not part of the
    # literal's value.
    source = """
function f(a: "s"): void {}
function f(a: string): void {}
f('s');
"""
    report = build_ts_bindings(source)
    fs = sorted(
        _bindings(report, "f", "function"), key=lambda b: b.span.start
    )
    call = next(
        c for c in _calls(report) if source[c.span.start:c.span.end] == "f('s')"
    )
    assert call.target == fs[0].id


def test_overload_literal_number_radix_equivalent():
    # `f(0x1)` fits `f(x: 1)`.
    source = """
function f(a: 1): void {}
function f(a: number): void {}
f(0x1);
"""
    report = build_ts_bindings(source)
    fs = sorted(
        _bindings(report, "f", "function"), key=lambda b: b.span.start
    )
    call = next(
        c for c in _calls(report) if source[c.span.start:c.span.end] == "f(0x1)"
    )
    assert call.target == fs[0].id

def test_overload_string_literal_does_not_match_bare_token():
    # `f(true)` does not fit `f(x: "true")` — a quoted literal only
    # matches a literal string argument, and `f(new Widget())` does
    # not fit `f(x: "Widget")` either.
    source = """
class Widget {}
function f(a: "true"): void {}
function f(a: "Widget"): void {}
function f(a: boolean): void {}
function f(a: Widget): void {}
f(true);
f(new Widget());
"""
    report = build_ts_bindings(source)
    fs = sorted(
        _bindings(report, "f", "function"), key=lambda b: b.span.start
    )
    bool_fn, widget_fn = fs[2], fs[3]
    true_call = next(
        c for c in _calls(report)
        if source[c.span.start:c.span.end] == "f(true)"
    )
    new_call = next(
        c for c in _calls(report)
        if source[c.span.start:c.span.end] == "f(new Widget())"
    )
    assert true_call.target == bool_fn.id
    assert new_call.target == widget_fn.id


def test_overload_interpolated_template_is_not_a_literal():
    # `f(`value-${n}`)` is computed — it does not fit the same-value
    # literal overload `f(x: "value-${n}")`, so `string` wins.
    name = "n"
    source = """
function f(a: "value-${n}"): void {}
function f(a: string): void {}
declare const n: string;
f(`value-${n}`);
"""
    report = build_ts_bindings(source)
    string_fn = sorted(
        _bindings(report, "f", "function"), key=lambda b: b.span.start
    )[1]
    call = next(
        c for c in _calls(report)
        if source[c.span.start:c.span.end] == "f(`value-${n}`)"
    )
    assert call.target == string_fn.id

def test_overload_escaped_template_is_a_literal():
    # `` `\${n}` `` evaluates to the literal `${n}` — the escape makes
    # it constant, so it fits the `"${n}"` literal overload.
    source = """
function f(a: "${n}"): void {}
function f(a: string): void {}
declare const n: string;
f(`\\${n}`);
"""
    report = build_ts_bindings(source)
    literal_fn = sorted(
        _bindings(report, "f", "function"), key=lambda b: b.span.start
    )[0]
    call = next(
        c for c in _calls(report)
        if source[c.span.start:c.span.end] == "f(`\\${n}`)"
    )
    assert call.target == literal_fn.id

def test_overload_double_backslash_template_still_interpolates():
    # `` `\\${n}` `` — the escaped backslash leaves `${` unescaped,
    # so it interpolates and does not fit the `"${n}"` literal.
    source = """
function f(a: "${n}"): void {}
function f(a: string): void {}
declare const n: string;
f(`\\\\${n}`);
"""
    report = build_ts_bindings(source)
    string_fn = sorted(
        _bindings(report, "f", "function"), key=lambda b: b.span.start
    )[1]
    call = next(
        c for c in _calls(report)
        if source[c.span.start:c.span.end] == "f(`\\\\${n}`)"
    )
    assert call.target == string_fn.id


def test_overload_double_backslash_constant_regression_detected():
    # `` `\\${n}` `` interpolates; a literal spelling the same two
    # backslashes matches only if the escape scan wrongly treats the
    # interpolation as constant text — this keeps that regression
    # detectable.
    source = """
function f(a: "\\\\${n}"): void {}
function f(a: string): void {}
declare const n: string;
f(`\\\\${n}`);
"""
    report = build_ts_bindings(source)
    string_fn = sorted(
        _bindings(report, "f", "function"), key=lambda b: b.span.start
    )[1]
    call = next(
        c for c in _calls(report)
        if source[c.span.start:c.span.end] == "f(`\\\\${n}`)"
    )
    assert call.target == string_fn.id

def test_call_receiver_uses_the_narrowed_overloads_return_type():
    # `make(1).methodA()` reads the `number` overload's `A` return,
    # not the last-declared `string -> B` signature.
    source = """
class A { methodA(): void {} }
class B { methodB(): void {} }
function make(x: number): A;
function make(x: string): B;
function make(x: any): any { return null as any; }
make(1).methodA();
"""
    report = build_ts_bindings(source)
    method_a = _bindings(report, "methodA", "associated_function")[0]
    call = next(
        c for c in _calls(report)
        if source[c.span.start:c.span.end] == "make(1).methodA()"
    )
    assert call.target == method_a.id


def test_return_type_ignores_shadowed_outer_overloads():
    # Both `make`s accept the argument, so only the inner scope's
    # shadowing picks `string -> A` — scope, not arg types, excludes
    # the outer declaration.
    source = """
class A { methodA(): void {} }
class B { methodB(): void {} }
function make(x: string): B { return null as any; }
{
    function make(x: string): A { return null as any; }
    make("s").methodA();
}
"""
    report = build_ts_bindings(source)
    method_a = _bindings(report, "methodA", "associated_function")[0]
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == 'make("s").methodA()'
    )
    assert call.target == method_a.id


def test_tagged_template_return_types_the_receiver():
    # A tag is called `(strings, ...values)` — `tag`x`` fits the
    # one-parameter overload, not the zero-parameter one.
    source = """
class A { methodA(): void {} }
class B { methodB(): void {} }
function tag(s: TemplateStringsArray): A;
function tag(): B;
function tag(...args: any[]): any { return null as any; }
tag`x`.methodA();
"""
    report = build_ts_bindings(source)
    method_a = _bindings(report, "methodA", "associated_function")[0]
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "tag`x`.methodA()"
    )
    assert call.target == method_a.id


def test_parenthesized_callee_return_types_the_receiver():
    source = """
class A { methodA(): void {} }
class B { methodB(): void {} }
function make(x: number): A;
function make(x: string): B;
function make(x: any): any { return null as any; }
(make)(1).methodA();
"""
    report = build_ts_bindings(source)
    method_a = _bindings(report, "methodA", "associated_function")[0]
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "(make)(1).methodA()"
    )
    assert call.target == method_a.id


def test_member_overload_return_types_the_receiver():
    # The narrowed member overload's return type feeds the chained
    # member call, same as the top-level function path.
    source = """
class A { methodA(): void {} }
class B { methodB(): void {} }
interface Factory {
    make(x: number): A;
    make(x: string): B;
}
declare const factory: Factory;
factory.make(1).methodA();
"""
    report = build_ts_bindings(source)
    method_a = _bindings(report, "methodA", "associated_function")[0]
    call = next(
        c for c in report.calls
        if source[c.span.start:c.span.end] == "factory.make(1).methodA()"
    )
    assert call.target == method_a.id


def test_tagged_template_narrows_by_interpolation_types():
    # Each `${...}` substitution narrows overloads by its
    # expression's type — `tag`x${1}`` picks the number overload.
    source = """
class A { methodA(): void {} }
class B { methodB(): void {} }
declare function tag(s: TemplateStringsArray, n: number): A;
declare function tag(s: TemplateStringsArray, n: string): B;
tag`x${1}`.methodA();
"""
    report = build_ts_bindings(source)
    method_a = _bindings(report, "methodA", "associated_function")[0]
    call = next(
        c for c in report.calls
        if "methodA()" in source[c.span.start:c.span.end]
    )
    assert call.target == method_a.id


def test_return_type_narrows_by_explicit_type_argument_count():
    # `(make<number, string>)(1)` cannot name a single-parameter
    # overload — the declared type-parameter count pins the signature.
    source = """
class A { methodA(): void {} }
class B { methodB(): void {} }
declare function make<T, U>(x: T): A;
declare function make<T>(x: T): B;
(make<number, string>)(1).methodA();
"""
    report = build_ts_bindings(source)
    method_a = _bindings(report, "methodA", "associated_function")[0]
    call = next(
        c for c in report.calls
        if "methodA()" in source[c.span.start:c.span.end]
    )
    assert call.target == method_a.id


def test_type_argument_defaults_keep_the_overload_eligible():
    # `make<number, string>` fits `make<T, U, V = string>` — a
    # defaulted type parameter need not be spelled.
    source = """
class A { methodA(): void {} }
class B { methodB(): void {} }
declare function make<T, U = string>(x: T): A;
declare function make<T>(x: T): B;
make<number>(1).methodA();
"""
    report = build_ts_bindings(source)
    method_a = _bindings(report, "methodA", "associated_function")[0]
    call = next(
        c for c in report.calls
        if "methodA()" in source[c.span.start:c.span.end]
    )
    assert call.target == method_a.id


def test_interpolation_bigint_narrows_overloads():
    # `${1n}` is a bigint literal — it fits `n: bigint`, not
    # `n: number`.
    source = """
class A { methodA(): void {} }
class B { methodB(): void {} }
declare function tag(s: TemplateStringsArray, n: bigint): A;
declare function tag(s: TemplateStringsArray, n: number): B;
tag`x${1n}`.methodA();
"""
    report = build_ts_bindings(source)
    method_a = _bindings(report, "methodA", "associated_function")[0]
    call = next(
        c for c in report.calls
        if "methodA()" in source[c.span.start:c.span.end]
    )
    assert call.target == method_a.id


def test_type_argument_pick_is_the_earliest_fitting_overload():
    # Both signatures fit the explicit count and the arguments cannot
    # discriminate — tsc binds the earliest declared overload.
    source = """
class A { methodA(): void {} }
class B { methodB(): void {} }
declare function make<T, U>(x: any): A;
declare function make<T, U>(x: any): B;
make<number, string>({}).methodA();
"""
    report = build_ts_bindings(source)
    method_a = _bindings(report, "methodA", "associated_function")[0]
    call = next(
        c for c in report.calls
        if "methodA()" in source[c.span.start:c.span.end]
    )
    assert call.target == method_a.id


def test_call_target_narrows_by_the_same_type_arguments():
    # `make<number, string>(1)` binds the `<T, U>` overload — the
    # reference and the return-type receiver must pick the same
    # signature.
    source = """
class A { methodA(): void {} }
class B { methodB(): void {} }
declare function make<T, U>(x: T): A;
declare function make<T>(x: T): B;
make<number, string>(1).methodA();
"""
    report = build_ts_bindings(source)
    overloads = _bindings(report, "make", "ambient")
    two_param = min(overloads, key=lambda b: b.span.start)
    ref = next(
        r for r in report.references
        if source[r.span.start:r.span.end] == "make"
        and r.span.start > source.index("): B")
    )
    assert ref.binding_id == two_param.id
    method_a = _bindings(report, "methodA", "associated_function")[0]
    call = next(
        c for c in report.calls
        if "methodA()" in source[c.span.start:c.span.end]
    )
    assert call.target == method_a.id


def test_type_argument_constraints_disqualify_overloads():
    # `make<number>` cannot bind `make<T extends string>` — the
    # explicit type argument violates the constraint, so the
    # unconstrained overload wins even though it is declared later.
    source = """
declare function make<T extends string>(x: T): number;
declare function make<T>(x: T): string;
make<number>(1);
"""
    report = build_ts_bindings(source)
    overloads = _bindings(report, "make", "ambient")
    unconstrained = max(overloads, key=lambda b: b.span.start)
    ref = next(
        r for r in report.references
        if source[r.span.start:r.span.end] == "make"
    )
    assert ref.binding_id == unconstrained.id


def test_type_argument_defaults_check_value_arguments():
    # `make<number>` binds `U = string` by default on the first
    # overload — `2n` does not fit `y: string`, so the `U = bigint`
    # overload takes the call despite being declared second.
    source = """
declare function make<T, U = string>(x: T, y: U): number;
declare function make<T, U = bigint>(x: T, y: U): string;
make<number>(1, 2n);
"""
    report = build_ts_bindings(source)
    overloads = _bindings(report, "make", "ambient")
    bigint_default = max(overloads, key=lambda b: b.span.start)
    ref = next(
        r for r in report.references
        if source[r.span.start:r.span.end] == "make"
    )
    assert ref.binding_id == bigint_default.id


def test_tuple_spread_arguments_narrow_overloads():
    # `make(...t)` with `t: [string, number]` supplies a string then a
    # number — only the second overload's parameters accept them.
    source = """
declare function make(x: number, y: string): number;
declare function make(x: string, y: number): string;
const t: [string, number] = ["s", 1];
make(...t);
"""
    report = build_ts_bindings(source)
    overloads = _bindings(report, "make", "ambient")
    fitting = max(overloads, key=lambda b: b.span.start)
    ref = next(
        r for r in report.references
        if source[r.span.start:r.span.end] == "make"
        and r.span.start > source.index("];")
    )
    assert ref.binding_id == fitting.id


def test_bigint_literal_separators_match_by_value():
    # `1_000n` and `1000n` spell the same bigint — the literal-typed
    # overload keeps the call over the generic `bigint` one.
    source = """
declare function m(x: 1000n): number;
declare function m(x: bigint): string;
m(1_000n);
"""
    report = build_ts_bindings(source)
    overloads = _bindings(report, "m", "ambient")
    literal_overload = min(overloads, key=lambda b: b.span.start)
    ref = next(
        r for r in report.references
        if source[r.span.start:r.span.end] == "m"
        and r.span.start > source.index(": string;")
    )
    assert ref.binding_id == literal_overload.id


def test_optional_and_nonnull_member_access_narrows_union():
    # `o?.pm()` and `o!.pm()` read `pm` on the non-null union part;
    # plain `o.pm()` on the union stays opaque (tsc flags it).
    source = """
class P { pm(): void {} }
declare const o: P | undefined;
o!.pm();
o?.pm();
o.pm();
"""
    report = build_ts_bindings(source)
    member_pm = _member_bindings(report, "pm", "associated_function")[0]
    bound = {
        source[c.span.start : c.span.end]
        for c in _calls(report)
        if c.target == member_pm.id
    }
    assert bound == {"o!.pm()", "o?.pm()"}


def test_optional_member_access_keeps_multi_part_unions_opaque():
    # `P | string` narrows to `P | string` — `pm` is not on `string`,
    # so `u?.pm()` cannot resolve (tsc TS2339). The declared union
    # stays authoritative over the `P`-typed initializer.
    source = """
class P { pm(): void {} }
declare const arr: P[];
const u: P | string = arr[0];
u?.pm();
"""
    report = build_ts_bindings(source)
    member_pm = _member_bindings(report, "pm", "associated_function")[0]
    call = next(
        c for c in _calls(report)
        if source[c.span.start : c.span.end] == "u?.pm()"
    )
    assert call.target != member_pm.id


def test_initializer_inference_types_subscript_and_call_results():
    # Unannotated `const q = arr[0]`/`f()` infer `q`'s type from the
    # initializer's declared result.
    source = """
class P { pm(): void {} }
declare const arr: P[];
function make(): P { return new P() }
const q = arr[0];
q.pm();
const r = make();
r.pm();
arr[0]?.pm();
"""
    report = build_ts_bindings(source)
    member_pm = _member_bindings(report, "pm", "associated_function")[0]
    bound = {
        source[c.span.start : c.span.end]
        for c in _calls(report)
        if c.target == member_pm.id
    }
    assert bound == {"q.pm()", "r.pm()", "arr[0]?.pm()"}


def test_optional_access_peels_union_carried_through_initializer():
    # `const v = o` carries `o`'s union through the initializer —
    # `v?.pm()` narrows it; plain `v.pm()` stays opaque.
    source = """
class P { pm(): void {} }
declare const o: P | undefined;
const v = o;
v?.pm();
v.pm();
"""
    report = build_ts_bindings(source)
    member_pm = _member_bindings(report, "pm", "associated_function")[0]
    bound = {
        source[c.span.start : c.span.end]
        for c in _calls(report)
        if c.target == member_pm.id
    }
    assert bound == {"v?.pm()"}
