import subprocess
import sys

import pytest

from agent.lexical_bindings import LexicalReportError, load_lexical_report
from agent.sol_bindings import (
    MAX_SOURCE_BYTES,
    PROFILE,
    build_sol_bindings as _build_sol_bindings,
)


def build_sol_bindings(source):
    report = _build_sol_bindings(source)
    reference_keys = [
        (reference.span, reference.binding_id, reference.kind)
        for reference in report.references
    ]
    assert len(reference_keys) == len(set(reference_keys)), source
    call_spans = [call.span for call in report.calls]
    assert len(call_spans) == len(set(call_spans)), source
    assert _load(report, source).to_json() == report.to_json()
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


def _text(source, span):
    return source.encode()[span.start : span.end].decode()


def _refs(report, source, name=None, kind=None):
    return sorted(
        (
            reference
            for reference in report.references
            if (name is None or _text(source, reference.span) == name)
            and (kind is None or reference.kind == kind)
        ),
        key=lambda reference: (reference.span.start, reference.kind),
    )


def _unresolved(report, name=None, reason=None):
    return [
        item
        for item in report.unresolved
        if (name is None or item.name == name)
        and (reason is None or item.reason == reason)
    ]


def _calls(report, source, kind=None):
    return [
        call
        for call in report.calls
        if kind is None or call.kind == kind
    ]


def _load(report, source):
    return load_lexical_report(
        report.to_json(),
        source,
        profile=PROFILE,
        target={},
    )


def test_file_scope_order_shadowing_and_stable_report_round_trip():
    source = """
contract C {
    function caller() internal { helper(); }
    function helper() internal {}
    function scoped(uint x) public {
        uint value = x;
        { uint value = value + 1; value++; }
        value++;
    }
}
"""
    report = build_sol_bindings(source)
    helper = _bindings(report, "helper", "function")[0]
    call = _calls(report, source, "direct_local")[0]
    assert call.target == helper.id
    assert _text(source, call.span) == "helper()"

    values = _bindings(report, "value", "local")
    assert len(values) == 2
    value_refs = _refs(report, source, "value")
    assert [ref.binding_id for ref in value_refs] == [
        values[0].id,
        values[1].id,
        values[1].id,
        values[0].id,
        values[0].id,
    ]
    assert report.to_json() == build_sol_bindings(source).to_json()
    assert _load(report, source).to_json() == report.to_json()
    assert report.complete
    assert _bindings(build_sol_bindings(source + " "), "helper", "function")[0].id != helper.id


_INTEGER_TYPES = [
    ("uint", 256, False),
    ("int", 256, True),
    *[(f"uint{width}", width, False) for width in range(8, 257, 8)],
    *[(f"int{width}", width, True) for width in range(8, 257, 8)],
]
_TYPE_FACTS = [
    (name, kind, width, signed)
    for name, width, signed in _INTEGER_TYPES
    for kind in ("int",)
]
_TYPE_FACTS += [("bool", "bool", 1, None), ("address", "address", 160, False)]
_TYPE_FACTS.append(("address payable", "address", 160, False))
_TYPE_FACTS.extend(
    (f"bytes{size}", "fixed_bytes", size * 8, False) for size in range(1, 33)
)


@pytest.mark.parametrize(("type_name", "kind", "width", "signed"), _TYPE_FACTS)
def test_explicit_scalar_type_facts(type_name, kind, width, signed):
    source = (
        f"contract C {{ {type_name} state; "
        f"function f({type_name} x) public returns ({type_name} y) "
        "{ y = x; return y; } }"
    )
    report = build_sol_bindings(source)
    facts = [
        _bindings(report, "state", "state_variable")[0].type,
        _bindings(report, "x", "parameter")[0].type,
        _bindings(report, "y", "return_parameter")[0].type,
    ]
    assert [(fact.kind, fact.bit_width, fact.signed) for fact in facts] == [
        (kind, width, signed)
    ] * 3
    assert _load(report, source).to_json() == report.to_json()


def test_udvt_width_and_named_type_facts():
    source = """
type Wad is uint16;
struct Data { uint value; }
enum Status { Ready, Done }
contract Base {}
interface I {}
contract C {
    Wad amount;
    Data data;
    Status status;
    Base base;
    I iface;
}
"""
    report = build_sol_bindings(source)
    wad = _bindings(report, "Wad", "user_type")[0]
    amount = _bindings(report, "amount", "state_variable")[0]
    assert (
        amount.type.kind,
        amount.type.name,
        amount.type.bit_width,
        amount.type.signed,
    ) == (wad.type.kind, wad.type.name, wad.type.bit_width, wad.type.signed)
    assert amount.type.type_id == wad.id
    assert (wad.type.kind, wad.type.name, wad.type.bit_width, wad.type.signed) == (
        "int",
        "uint16",
        16,
        False,
    )
    for name, kind in (
        ("Data", "struct"),
        ("Status", "enum"),
        ("Base", "contract"),
        ("I", "interface"),
    ):
        declaration = _bindings(report, name, kind)[0]
        field_name = {
            "Data": "data",
            "Status": "status",
            "Base": "base",
            "I": "iface",
        }[name]
        field = _bindings(report, field_name, "state_variable")[0]
        assert field.type.kind == "named"
        assert field.type.type_id == declaration.id


@pytest.mark.parametrize(
    ("source", "declaration_marker", "kind", "expected_type", "expected_width"),
    [
        (
            "struct T { uint file; } contract C { "
            "struct T { address local; } T value; }",
            "struct T { address local; }",
            "struct",
            "named",
            0,
        ),
        (
            "enum T { File } contract C { enum T { Local } T value; }",
            "enum T { Local }",
            "enum",
            "named",
            0,
        ),
        (
            "type T is uint8; contract C { type T is uint16; T value; }",
            "type T is uint16;",
            "user_type",
            "int",
            16,
        ),
        (
            "struct T { uint file; } "
            "contract Base { struct T { address base; } } "
            "contract C is Base { T value; }",
            "struct T { address base; }",
            "struct",
            "named",
            0,
        ),
        (
            "struct T { uint file; } "
            "contract Base { struct T { address base; } } "
            "contract C is Base { struct T { bool derived; } T value; }",
            "struct T { bool derived; }",
            "struct",
            "named",
            0,
        ),
        (
            "struct T { uint file; } contract C { T value; }",
            "struct T { uint file; }",
            "struct",
            "named",
            0,
        ),
    ],
)
def test_contract_and_base_types_precede_file_scope(
    source, declaration_marker, kind, expected_type, expected_width
):
    report = build_sol_bindings(source)
    declaration_start = source.index(declaration_marker)
    name_start = source.index("T", declaration_start)
    declaration = next(
        binding
        for binding in _bindings(report, "T", kind)
        if binding.span.start == name_start
    )
    value = _bindings(report, "value", "state_variable")[0]
    assert value.type.kind == expected_type
    assert value.type.bit_width == expected_width
    assert value.type.type_id == declaration.id
    type_use_start = source.index("T value")
    type_reference = next(
        reference
        for reference in report.references
        if reference.span.start == type_use_start
    )
    assert type_reference.binding_id == declaration.id


def test_file_level_constant_and_free_function_are_order_independent():
    source = """
function useValue() pure returns (uint) { return helper(TOP); }
uint constant TOP = 2;
function helper(uint value) pure returns (uint) { return value; }
import {External} from "x.sol";
struct FileData { uint value; }
enum FileState { Ready }
type FileValue is uint8;
interface FileInterface {}
library FileLibrary {}
event FileEvent(uint value);
error FileError(uint value);
contract C {
    function readValue() public pure returns (uint) { return TOP; }
    function signal() public { emit FileEvent(TOP); revert FileError(TOP); }
}
"""
    report = build_sol_bindings(source)
    helper = _bindings(report, "helper", "function")[0]
    direct_call = next(
        call for call in report.calls if _text(source, call.span) == "helper(TOP)"
    )
    assert direct_call.kind == "direct_local"
    assert direct_call.target == helper.id
    assert _bindings(report, "TOP", "const")
    assert len(_refs(report, source, "TOP", "read")) == 4
    for name, kind in (
        ("External", "import"),
        ("FileData", "struct"),
        ("FileState", "enum"),
        ("FileValue", "user_type"),
        ("FileInterface", "interface"),
        ("FileLibrary", "library"),
        ("FileEvent", "event"),
        ("FileError", "error"),
    ):
        assert _bindings(report, name, kind)
    assert any(call.kind == "emit" for call in report.calls)
    assert any(call.kind == "error_constructor" for call in report.calls)
    assert report.complete


def test_event_parameters_are_not_bindings_and_fallback_receive_have_no_name_binding():
    source = """
contract C {
    event E(uint indexed value);
    fallback() external {}
    receive() external payable {}
}
"""
    report = build_sol_bindings(source)
    assert _bindings(report, "E", "event")
    assert not _bindings(report, "value")
    assert not _bindings(report, "fallback")
    assert not _bindings(report, "receive")


@pytest.mark.parametrize(
    "source",
    [
        "enum Status { Ready } contract C { Status value; }",
        "contract C { enum Status { Ready } Status value; }",
    ],
)
def test_file_and_contract_enums_are_type_names(source):
    report = build_sol_bindings(source)
    enum = _bindings(report, "Status", "enum")[0]
    value = _bindings(report, "value", "state_variable")[0]
    reference = _refs(report, source, "Status", "read")[0]
    assert value.type.kind == "named"
    assert value.type.type_id == enum.id
    assert reference.binding_id == enum.id


def test_unknown_enum_type_stays_unresolved():
    source = "contract C { MissingStatus value; }"
    report = build_sol_bindings(source)
    value = _bindings(report, "value", "state_variable")[0]
    assert value.type.kind == "unknown"
    assert _unresolved(report, "MissingStatus", "unknown_name")
    assert not _refs(report, source, "MissingStatus")


@pytest.mark.parametrize(
    "type_name",
    [
        "string",
        "bytes",
        "uint[]",
        "uint[4]",
        "mapping(address => uint)",
        "function() external",
    ],
)
def test_dynamic_and_composite_type_facts_remain_unknown(type_name):
    source = f"contract C {{ {type_name} value; }}"
    report = build_sol_bindings(source)
    fact = _bindings(report, "value", "state_variable")[0].type
    assert (fact.kind, fact.bit_width, fact.signed, fact.type_id) == (
        "unknown",
        0,
        None,
        "",
    )


@pytest.mark.parametrize(
    "type_name",
    [
        "T[]",
        "T[2]",
        "mapping(address => T)",
        "mapping(address => T[])",
        "mapping(address => mapping(uint => T))",
    ],
)
def test_composite_user_types_are_unknown_but_keep_type_references(type_name):
    source = f"struct T {{ uint field; }} contract C {{ {type_name} value; }}"
    report = build_sol_bindings(source)
    value = _bindings(report, "value", "state_variable")[0]
    declaration = _bindings(report, "T", "struct")[0]
    references = _refs(report, source, "T", "read")
    assert (value.type.kind, value.type.bit_width, value.type.signed) == (
        "unknown",
        0,
        None,
    )
    assert len(references) == 1
    assert references[0].binding_id == declaration.id


def test_plain_user_type_remains_named():
    source = "struct T { uint field; } contract C { T value; }"
    report = build_sol_bindings(source)
    value = _bindings(report, "value", "state_variable")[0]
    declaration = _bindings(report, "T", "struct")[0]
    assert value.type.kind == "named"
    assert value.type.type_id == declaration.id
    assert _refs(report, source, "T", "read")[0].binding_id == declaration.id


def test_imported_type_remains_unknown():
    source = 'import {ExternalType} from "x.sol"; contract C { ExternalType value; }'
    report = build_sol_bindings(source)
    assert _bindings(report, "value", "state_variable")[0].type.kind == "unknown"


@pytest.mark.parametrize(
    ("source", "expected", "expected_call_kind"),
    [
        (
            'import "lib.sol" as Lib; contract C { function f() public { Lib.run(); } }',
            {"Lib"},
            "opaque_member",
        ),
        (
            'import * as Lib from "lib.sol"; contract C { function f() public { Lib.run(); } }',
            {"Lib"},
            "opaque_member",
        ),
        (
            'import {A, B as Alias} from "lib.sol"; '
            "contract C { function f() public { A(); Alias(); } }",
            {"A", "Alias"},
            "opaque_import",
        ),
        (
            'import {A as Alias, B} from "lib.sol"; '
            "contract C { function f() public { Alias(); B(); } }",
            {"Alias", "B"},
            "opaque_import",
        ),
    ],
)
def test_import_bindings_preserve_aliases_and_calls_are_opaque(
    source, expected, expected_call_kind
):
    report = build_sol_bindings(source)
    assert {binding.name for binding in report.bindings if binding.kind == "import"} == expected
    assert all(call.kind == expected_call_kind for call in report.calls)
    assert all(
        call.target if expected_call_kind == "opaque_import" else not call.target
        for call in report.calls
    )
    assert _load(report, source).to_json() == report.to_json()


def test_plain_import_is_a_glob_barrier_and_keeps_unknowns_explicit():
    source = 'import "library.sol"; contract C { function f() public { missing(); } }'
    report = build_sol_bindings(source)
    assert any(gap.reason == "glob_import" for gap in report.gaps)
    assert _unresolved(report, "missing", "glob_import")
    assert _calls(report, source, "unresolved")
    assert not report.complete


def test_nested_block_shadowing_and_for_scope():
    source = """
contract C {
    function f(uint n) public {
        uint value = n;
        { uint value = value + 1; value++; }
        value++;
        for (uint i = 0; i < n; i++) { n += i; }
        i;
    }
}
"""
    report = build_sol_bindings(source)
    values = _bindings(report, "value", "local")
    value_refs = _refs(report, source, "value")
    assert len(values) == 2
    assert [ref.binding_id for ref in value_refs[:2]] == [values[0].id, values[1].id]
    assert any(item.name == "i" and item.reason == "unknown_name" for item in report.unresolved)
    i_binding = _bindings(report, "i", "local")[0]
    in_loop = [
        reference
        for reference in report.references
        if _text(source, reference.span) == "i"
        and reference.binding_id == i_binding.id
    ]
    assert {reference.kind for reference in in_loop} == {"read", "write"}


def test_conditions_are_visited_in_their_enclosing_scope():
    source = """
contract C {
    function check(uint x) internal pure returns (bool) { return x > 0; }
    function f(uint x) public {
        if (check(x)) { x++; } else { x = 0; }
        while (x < 3) { x++; }
    }
}
"""
    report = build_sol_bindings(source)
    parameters = _bindings(report, "x", "parameter")
    split = source.index("function f")
    assert all(
        ref.binding_id == (
            parameters[0].id if ref.span.start < split else parameters[1].id
        )
        for ref in _refs(report, source, "x")
    )
    assert any(call.kind == "direct_local" for call in report.calls)
    assert report.complete


def test_try_returns_and_catch_parameters_have_branch_local_scopes():
    source = """
contract C {
    function g() external returns (uint) { return 1; }
    function f() public {
        try this.g() returns (uint result) { result; }
        catch Error(string memory reason) { reason; }
        result;
        reason;
    }
}
"""
    report = build_sol_bindings(source)
    result = _bindings(report, "result", "parameter")[0]
    reason = _bindings(report, "reason", "parameter")[0]
    result_refs = _refs(report, source, "result")
    reason_refs = _refs(report, source, "reason")
    assert any(ref.binding_id == result.id for ref in result_refs)
    assert any(ref.binding_id == reason.id for ref in reason_refs)
    assert _unresolved(report, "result", "unknown_name")
    assert _unresolved(report, "reason", "unknown_name")


def test_modifier_parameters_do_not_leak_between_modifier_and_function():
    source = """
contract C {
    modifier gate(uint q) { uint a = value; q; _; }
    function f(uint value) public gate(value) {}
}
"""
    report = build_sol_bindings(source)
    modifier = _bindings(report, "gate", "modifier")[0]
    function = _bindings(report, "f", "function")[0]
    assert any(item.name == "value" and item.reason == "unknown_name" for item in report.unresolved)
    assert any(call.kind == "modifier" and call.target == modifier.id for call in report.calls)
    invocation = next(call for call in report.calls if call.kind == "modifier")
    assert invocation.owner == function.id
    assert not any(_text(source, ref.span) == "_" for ref in report.references)


def test_tuple_declarations_skip_empty_slots_and_bind_each_name():
    source = """
contract C {
    function pair() internal pure returns (uint, uint, uint) { return (1, 2, 3); }
    function f() public { (uint a,,uint c) = pair(); a = c; }
}
"""
    report = build_sol_bindings(source)
    assert len(_bindings(report, "a", "local")) == 1
    assert len(_bindings(report, "c", "local")) == 1
    assert not any(binding.name == "_" for binding in report.bindings)
    assert any(call.kind == "direct_local" for call in report.calls)


def test_inheritance_order_private_members_and_unresolved_bases():
    source = """
contract A { function chosen() internal {} function hidden() private {} }
contract B { function chosen() internal {} }
contract C is A, B { function f() public { chosen(); hidden(); } }
contract External is Remote { function g() public { absent(); } }
"""
    report = build_sol_bindings(source)
    chosen_call = next(call for call in report.calls if _text(source, call.span) == "chosen()")
    assert chosen_call.kind == "opaque_overload"
    assert chosen_call.target == ""
    assert _unresolved(report, "chosen", "ambiguous_overload")
    assert _unresolved(report, "hidden", "private_base_member")
    assert _unresolved(report, "Remote", "unresolved_base")
    assert _unresolved(report, "absent", "unresolved_base")
    assert any(gap.reason == "unresolved_base" for gap in report.gaps)


def test_private_inherited_state_is_distinguished_from_unknown_names():
    source = """
contract Base { uint private hidden; uint visible; }
contract Derived is Base {
    function f() public view returns (uint) {
        return hidden + visible + missing;
    }
}
"""
    report = build_sol_bindings(source)
    visible = _bindings(report, "visible", "state_variable")[0]
    assert _unresolved(report, "hidden", "private_base_member")
    assert not _unresolved(report, "hidden", "unknown_name")
    assert any(
        reference.binding_id == visible.id and reference.kind == "read"
        for reference in report.references
    )
    assert _unresolved(report, "missing", "unknown_name")


def test_inherited_overloads_collect_bases_and_remove_overridden_functions():
    source = """
contract Base {
    function f(uint x) internal virtual {}
}
contract Derived is Base {
    function f(uint renamed) internal override virtual {}
    function selected(uint x) public { f(x); }
}
contract OtherBase {
    function f(address x) internal {}
}
contract Ambiguous is OtherBase {
    function f(uint x) internal {}
    function unresolved(uint x) public { f(x); }
}
"""
    report = build_sol_bindings(source)
    derived = next(
        binding
        for binding in _bindings(report, "f", "function")
        if source.index("contract Derived")
        < binding.span.start
        < source.index("contract OtherBase")
    )
    selected_call = next(
        call for call in report.calls if call.span.start == source.index("f(x)")
    )
    assert selected_call.kind == "opaque_virtual"
    assert selected_call.target == derived.id
    ambiguous_start = source.rindex("f(x)")
    ambiguous_call = next(
        call for call in report.calls if call.span.start == ambiguous_start
    )
    assert ambiguous_call.kind == "opaque_overload"
    assert ambiguous_call.target == ""
    assert _unresolved(report, "f", "ambiguous_overload")


def test_derived_implementation_replaces_bodyless_interface_function():
    source = """
interface I { function f(uint[] calldata input) external; }
contract C is I {
    function f(uint[] memory values) public {}
    function caller() internal {
        uint[] memory values = new uint[](1);
        f(values);
    }
}
"""
    report = build_sol_bindings(source)
    implementation = next(
        binding
        for binding in _bindings(report, "f", "function")
        if source.index("contract C") < binding.span.start
    )
    call = next(
        call for call in report.calls if _text(source, call.span) == "f(values)"
    )
    assert call.target == implementation.id
    assert call.kind in {"direct_local", "opaque_virtual"}
    assert not _unresolved(report, "f", "ambiguous_overload")


def test_bodyless_base_with_different_parameter_type_remains_ambiguous():
    source = """
abstract contract Base { function f(uint value) internal virtual; }
contract Derived is Base {
    function f(address value) internal {}
    function caller() internal { f(1); }
}
"""
    report = build_sol_bindings(source)
    call = next(
        call for call in report.calls if _text(source, call.span) == "f(1)"
    )
    assert call.kind == "opaque_overload"
    assert call.target == ""
    assert _unresolved(report, "f", "ambiguous_overload")


def test_uint_and_uint256_parameter_texts_remain_ambiguous():
    source = """
abstract contract Base { function f(uint value) internal virtual; }
contract Derived is Base {
    function f(uint256 value) internal {}
    function caller() internal { f(1); }
}
"""
    report = build_sol_bindings(source)
    call = next(
        call for call in report.calls if _text(source, call.span) == "f(1)"
    )
    assert call.kind == "opaque_overload"
    assert call.target == ""
    assert _unresolved(report, "f", "ambiguous_overload")


def test_unrecognized_parameter_type_keeps_inherited_candidate():
    source = """
abstract contract Base {
    function f(function(uint) external returns (uint) callback) internal virtual;
}
contract Derived is Base {
    function f(function(uint) external returns (uint) callback) internal override {}
    function caller(function(uint) external returns (uint) callback) internal {
        f(callback);
    }
}
"""
    report = build_sol_bindings(source)
    call = next(
        call for call in report.calls if _text(source, call.span) == "f(callback)"
    )
    assert call.kind == "opaque_overload"
    assert call.target == ""
    assert _unresolved(report, "f", "ambiguous_overload")


def test_different_arity_bodyless_base_function_remains_ambiguous():
    source = """
interface I { function f(uint) external; }
abstract contract C is I {
    function f(uint first, uint second) public {}
    function caller() internal { f(1); }
}
"""
    report = build_sol_bindings(source)
    call = next(
        call for call in report.calls if _text(source, call.span) == "f(1)"
    )
    assert call.kind == "opaque_overload"
    assert call.target == ""
    assert _unresolved(report, "f", "ambiguous_overload")


def test_overloads_and_virtual_dispatch_are_not_direct_local_calls():
    source = """
contract Base {
    function virtualCall() public virtual {}
    function caller() public { virtualCall(); }
    function overloaded(uint x) internal {}
    function overloaded(address x) internal {}
    function ambiguous() public { overloaded(1); }
}
contract Derived is Base {
    function virtualCall() public override {}
}
"""
    report = build_sol_bindings(source)
    assert any(call.kind == "opaque_virtual" for call in report.calls)
    assert any(call.kind == "opaque_overload" for call in report.calls)
    assert _unresolved(report, "overloaded", "ambiguous_overload")


def test_bodyless_inherited_function_call_is_opaque_bodyless():
    source = """
interface I { function f() external; }
contract C is I { function caller() public { f(); } }
"""
    report = build_sol_bindings(source)
    call = next(call for call in report.calls if _text(source, call.span) == "f()")
    assert call.kind == "opaque_bodyless"
    assert call.target == _bindings(report, "f", "function")[0].id
    assert _load(report, source).to_json() == report.to_json()


def test_assignment_place_matrix_and_nested_index_expressions():
    source = """
contract C {
    uint[] values;
    struct S { uint f; }
    function index() internal returns (uint) { return 0; }
    function f(S memory s, uint[] memory a, uint i) public {
        s.f = 1;
        a[index()][i] += 1;
        values[index()] = i;
        s.f++;
        delete s.f;
    }
}
"""
    report = build_sol_bindings(source)
    s = _bindings(report, "s", "parameter")[0]
    a = _bindings(report, "a", "parameter")[0]
    i = _bindings(report, "i", "parameter")[0]
    values = _bindings(report, "values", "state_variable")[0]
    assert {ref.kind for ref in report.references if ref.binding_id == s.id} == {
        "write",
        "read",
    }
    assert {ref.kind for ref in report.references if ref.binding_id == a.id} == {
        "write",
        "read",
    }
    assert any(ref.binding_id == values.id and ref.kind == "write" for ref in report.references)
    assert sum(
        ref.binding_id == i.id and ref.kind == "read"
        for ref in report.references
    ) >= 2
    assert sum(call.kind == "direct_local" for call in report.calls) == 2


def test_storage_pointer_and_this_member_writes_only_read_the_root():
    source = """
contract C {
    struct S { uint value; }
    S stored;
    function f(S storage pointer) public {
        pointer.value = 1;
        this.stored = stored;
    }
}
"""
    report = build_sol_bindings(source)
    pointer = _bindings(report, "pointer", "parameter")[0]
    assert [ref.kind for ref in report.references if ref.binding_id == pointer.id] == ["read"]
    stored = _bindings(report, "stored", "state_variable")[0]
    # `this.stored = stored` now emits the member's own write
    # reference alongside the right-hand read.
    stored_refs = [ref for ref in report.references if ref.binding_id == stored.id]
    assert sorted(ref.kind for ref in stored_refs) == ["read", "write"]
    value = _bindings(report, "value", "struct_field")[0]
    assert any(
        ref.binding_id == value.id and ref.kind == "write"
        for ref in report.references
    )


@pytest.mark.parametrize("qualifier", ["constant", "immutable"])
def test_constant_and_immutable_state_writes_are_gapped_and_not_mutable(qualifier):
    source = (
        f"contract C {{ uint {qualifier} fixedValue = 1; "
        "function f() public { fixedValue = 2; } }"
    )
    report = build_sol_bindings(source)
    binding = _bindings(report, "fixedValue", "state_variable")[0]
    assert not binding.mutable
    assert any(ref.binding_id == binding.id and ref.kind == "read" for ref in report.references)
    assert not any(ref.binding_id == binding.id and ref.kind == "write" for ref in report.references)
    assert any(gap.reason == "unsupported_syntax" for gap in report.gaps)


def test_writes_compound_update_delete_tuple_and_field_root():
    source = """
contract C {
    struct S { uint x; }
    function f(uint x, uint y, S memory s) public {
        x = 1;
        x += 1;
        x++;
        delete y;
        (x, y) = (y, x);
        s.x = x;
    }
}
"""
    report = build_sol_bindings(source)
    for name in ("x", "y"):
        binding = _bindings(report, name, "parameter")[0]
        kinds = {ref.kind for ref in report.references if ref.binding_id == binding.id}
        assert kinds == {"read", "write"}
    structure = _bindings(report, "s", "parameter")[0]
    assert any(
        ref.binding_id == structure.id and ref.kind == "write"
        for ref in report.references
    )


@pytest.mark.parametrize(
    ("source", "expected_kind"),
    [
        (
            "contract C { function h(uint x) internal {} "
            "function f() public { h(1); } }",
            "direct_local",
        ),
        (
            "contract C { function h() public payable {} "
            "function f() public payable { h{value: 1}(); } }",
            "opaque_call_options",
        ),
        (
            "contract NewContract {} contract C { function f() public { new NewContract(); } }",
            "opaque_new",
        ),
        (
            "struct S { uint x; } contract C { function f() public { S({x: 1}); } }",
            "constructor",
        ),
        (
            "contract C { error E(uint x); function f() public { revert E(1); } }",
            "error_constructor",
        ),
        (
            "contract C { event E(uint x); function f(uint x) public { emit E(x); } }",
            "emit",
        ),
        (
            "contract C { modifier m() { _; } function f() public m {} }",
            "modifier",
        ),
        (
            "contract Base { constructor(uint x) {} } contract C is Base(1) {}",
            "base_constructor",
        ),
        (
            "contract C { function f(uint x) public { uint8(x); } }",
            "conversion",
        ),
        (
            "contract C { function f() public { require(true); } }",
            "builtin",
        ),
        (
            "contract C { function h() public {} function f() public { this.h(); } }",
            "direct_local",
        ),
        (
            "contract C { function f(function() external cb) public { cb(); } }",
            "opaque_value",
        ),
        (
            'import {External} from "x.sol"; contract C { function f() public { External(); } }',
            "opaque_import",
        ),
    ],
)
def test_calls_use_conservative_kinds_and_loadable_targets(source, expected_kind):
    report = build_sol_bindings(source)
    assert any(call.kind == expected_kind for call in report.calls)
    assert _load(report, source).to_json() == report.to_json()


def test_constructors_have_synthetic_owner_and_file_initializers_have_no_owner():
    source = """
contract C {
    function helper() internal {}
    constructor() { helper(); }
}
"""
    report = build_sol_bindings(source)
    constructor = _bindings(report, "constructor", "constructor")[0]
    function = next(item for item in report.functions if item.binding_id == constructor.id)
    call = next(call for call in report.calls if call.kind == "direct_local")
    assert function.body is not None
    assert call.owner == constructor.id
    assert _load(report, source).to_json() == report.to_json()


def test_constructor_modifier_position_resolves_base_constructor():
    source = """
contract Base { constructor(uint value) {} }
contract Derived is Base { constructor() Base(1) {} }
"""
    report = build_sol_bindings(source)
    base = _bindings(report, "Base", "contract")[0]
    call = next(call for call in report.calls if call.kind == "base_constructor")
    assert call.target == base.id
    reference = next(
        item
        for item in report.references
        if item.span.start == source.index("Base(1)") and item.kind == "call"
    )
    assert reference.binding_id == base.id


def test_constructor_modifier_name_outside_inheritance_chain_is_unresolved():
    source = """
contract Base {}
contract Other {}
contract Derived is Base { constructor() Other() {} }
"""
    report = build_sol_bindings(source)
    call = next(
        call
        for call in report.calls
        if call.span.start == source.index("Other()")
    )
    assert call.kind == "unresolved"
    assert call.target == ""
    assert _unresolved(report, "Other", "unknown_name")
    assert not any(
        item.span.start == source.index("Other()") and item.kind == "call"
        for item in report.references
    )


def test_constructor_modifier_wins_over_same_named_base_contract():
    source = """
contract Base { constructor(uint value) {} }
contract Derived is Base {
    modifier Base(uint value) { _; }
    constructor() Base(1) {}
}
"""
    report = build_sol_bindings(source)
    modifier = _bindings(report, "Base", "modifier")[0]
    call = next(
        call for call in report.calls if call.span.start == source.index("Base(1)")
    )
    assert call.kind == "modifier"
    assert call.target == modifier.id


def test_builtins_member_reads_and_qualified_imports_stay_conservative():
    source = """
import * as Lib from "lib.sol";
contract C {
    function f() public {
        msg.sender;
        Lib.run();
    }
}
"""
    report = build_sol_bindings(source)
    assert _unresolved(report, "msg", "builtin")
    assert any(call.kind == "opaque_member" and call.target == "" for call in report.calls)
    assert any(ref.kind == "read" and _text(source, ref.span) == "Lib" for ref in report.references)


def test_comments_are_skipped_and_argument_spans_remain_exact():
    source = """
contract C {
    function h(uint x) internal {}
    function f(uint x) public { h(/* ignored */ x); }
}
"""
    report = build_sol_bindings(source)
    call = next(call for call in report.calls if call.kind == "direct_local")
    assert len(call.arguments) == 1
    assert _text(source, call.arguments[0]) == "x"
    assert not report.gaps
    assert not any(item.name == "ignored" for item in report.unresolved)


def test_inline_assembly_is_a_gap_and_yul_names_are_not_resolved():
    source = "contract C { function f() public { assembly { hidden := 1 } } }"
    report = build_sol_bindings(source)
    assert any(gap.reason == "inline_assembly" for gap in report.gaps)
    assert not _unresolved(report, "hidden")
    assert not report.complete


def test_multibyte_prefix_determinism_and_source_pinning():
    source = "// λ before declarations\r\ncontract C { uint x; function f() public { x; } }\r\n"
    report = build_sol_bindings(source)
    for item in (*report.bindings, *report.references):
        assert source.encode()[item.span.start : item.span.end]
    assert _load(report, source).to_json() == report.to_json()
    with pytest.raises(LexicalReportError):
        load_lexical_report(
            report.to_json(),
            source + " ",
            profile=PROFILE,
            target={},
        )


def test_parse_and_source_limits_fail_closed():
    with pytest.raises(LexicalReportError):
        build_sol_bindings("contract C { function broken( { }")
    with pytest.raises(LexicalReportError, match="source exceeds"):
        build_sol_bindings(" " * (MAX_SOURCE_BYTES + 1))


def test_deep_expression_recursion_fails_closed():
    expression = "+".join("1" for _ in range(2000))
    source = f"contract C {{ function f() public {{ uint x = {expression}; }} }}"
    previous_limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(1000)
        with pytest.raises(LexicalReportError):
            build_sol_bindings(source)
    finally:
        sys.setrecursionlimit(previous_limit)


def test_cli_preserves_crlf_bytes_and_emits_loadable_report(tmp_path):
    source_bytes = b"contract C {\r\n uint x;\r\n}\r\n"
    source_file = tmp_path / "sample.sol"
    source_file.write_bytes(source_bytes)
    result = subprocess.run(
        [sys.executable, "-m", "agent", "sol-bindings", str(source_file)],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    source = source_bytes.decode("utf-8", errors="strict")
    restored = load_lexical_report(
        result.stdout,
        source,
        profile=PROFILE,
        target={},
    )
    assert restored.source_sha256 == build_sol_bindings(source).source_sha256


@pytest.mark.parametrize(
    ("contents", "expected_error"),
    [
        (b"\xff", b"sol-bindings: source file is not valid UTF-8\n"),
        (b"contract {", b"sol-bindings: Solidity source has parse errors or missing nodes\n"),
    ],
)
def test_cli_fails_with_fixed_errors_and_no_json(tmp_path, contents, expected_error):
    source_file = tmp_path / "bad.sol"
    source_file.write_bytes(contents)
    result = subprocess.run(
        [sys.executable, "-m", "agent", "sol-bindings", str(source_file)],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == expected_error


def test_member_call_resolves_through_declared_contract_type():
    source = """
contract Token {
    function transfer(address to, uint256 amount) external {}
    uint256 public supply;
}
contract Vault {
    Token token;
    function run() external {
        token.transfer(address(0), 1);
        uint256 s = token.supply;
        s = s + 1;
    }
}
"""
    report = build_sol_bindings(source)
    token = next(
        binding for binding in report.bindings if binding.name == "Token"
    )
    transfer = next(
        binding
        for binding in report.bindings
        if binding.name == "transfer" and binding.scope is not None
    )
    supply = next(
        binding
        for binding in report.bindings
        if binding.name == "supply" and binding.scope is not None
    )
    assert token.id
    transfer_refs = [
        ref for ref in report.references if ref.binding_id == transfer.id
    ]
    assert [ref.kind for ref in transfer_refs] == ["call"]
    assert _text(source, transfer_refs[0].span) == "transfer"
    supply_refs = [
        ref for ref in report.references if ref.binding_id == supply.id
    ]
    assert [ref.kind for ref in supply_refs] == ["read"]
    assert _text(source, supply_refs[0].span) == "supply"
    call = next(
        call for call in report.calls if call.target == transfer.id
    )
    assert call.kind == "direct_local"


def test_member_call_through_this_and_super_resolves():
    source = """
contract B {
    function f() internal virtual {}
}
contract C is B {
    function f() internal override {}
    function g() public {
        this.g();
        super.f();
    }
}
"""
    report = build_sol_bindings(source)
    g = next(
        binding for binding in report.bindings if binding.name == "g"
    )
    f_base = next(
        binding for binding in report.bindings if binding.name == "f"
    )
    this_call = next(
        ref
        for ref in report.references
        if ref.binding_id == g.id and ref.kind == "call"
    )
    assert _text(source, this_call.span) == "g"
    super_call = next(
        ref
        for ref in report.references
        if ref.binding_id == f_base.id and ref.kind == "call"
    )
    assert _text(source, super_call.span) == "f"
    calls = {call.kind for call in report.calls}
    assert "direct_local" in calls
    assert "opaque_virtual" in calls
    assert _unresolved(report, "this", "builtin")
    assert _unresolved(report, "super", "builtin")


def test_member_lookup_finds_inherited_members_and_rejects_private():
    source = """
contract B {
    uint256 internal shared;
    uint256 private hidden;
}
contract C is B {
    B other;
    function g() external {
        uint256 x = other.shared;
        uint256 y = other.hidden;
        x = x + y;
    }
}
"""
    report = build_sol_bindings(source)
    shared = next(
        binding for binding in report.bindings if binding.name == "shared"
    )
    shared_ref = next(
        ref for ref in report.references if ref.binding_id == shared.id
    )
    assert _text(source, shared_ref.span) == "shared"
    assert _unresolved(report, "hidden", "private_base_member")


def test_member_access_on_non_contract_types_stays_opaque():
    source = """
contract C {
    uint256[] values;
    function g() external {
        uint256 n = values.length;
        values.push(1);
        n = n + 1;
    }
}
"""
    report = build_sol_bindings(source)
    assert any(
        call.kind == "opaque_member" and call.target == ""
        for call in report.calls
    )
    assert not any(
        _text(source, ref.span) in {"length", "push"}
        for ref in report.references
    )


def test_super_member_resolves_most_derived_base_first():
    source = """
contract A { function f() internal virtual {} }
contract B { function f() internal virtual {} }
contract C is A, B {
    function f() internal override(A, B) {}
    function g() public { super.f(); }
}
"""
    report = build_sol_bindings(source)
    fs = [
        binding for binding in report.bindings if binding.name == "f"
    ]
    # Declaration order: A.f, B.f, C.f — `super` in C binds to the most
    # derived base (B), not the first declared.
    f_base_b = fs[1]
    call = next(call for call in report.calls)
    assert call.target == f_base_b.id
    super_ref = next(
        ref
        for ref in report.references
        if ref.binding_id == f_base_b.id and ref.kind == "call"
    )
    assert _text(source, super_ref.span) == "f"


def test_super_member_follows_c3_order_in_a_diamond():
    source = """
contract O { function f() internal virtual {} }
contract A is O { function f() internal override {} }
contract B is O {}
contract C is A, B {
    function f() internal override(A, B) {}
    function g() public { super.f(); }
}
"""
    report = build_sol_bindings(source)
    fs = [
        binding for binding in report.bindings if binding.name == "f"
    ]
    # C3 order for `C is A, B` is C, B, A, O — A.f is the first
    # definition after C even though a depth-first walk of the bases
    # reaches O.f (through B) first.
    f_in_a = fs[1]
    call = next(call for call in report.calls)
    assert call.target == f_in_a.id


def test_super_member_with_mixed_signatures_stays_opaque():
    source = """
contract A { function f(uint256 x) internal virtual {} }
contract B is A { function f(bool x) internal virtual {} }
contract C is B {
    function g() public { super.f(1); }
}
"""
    report = build_sol_bindings(source)
    call = next(call for call in report.calls)
    # super.f sees the overload set {B.f(bool), A.f(uint)}; without
    # argument typing the call can't be bound to a single target.
    assert call.kind == "opaque_overload"
    assert not call.target
    assert not any(
        ref.kind == "call" for ref in report.references
    )


def test_qualified_declared_type_member_stays_opaque():
    source = """
library L {
    struct S { uint256 x; }
    uint256 internal x;
}
contract C {
    L.S s;
    function g() public {
        uint256 y = s.x;
        y = y + 1;
    }
}
"""
    report = build_sol_bindings(source)
    library_x = next(
        binding
        for binding in report.bindings
        if binding.name == "x" and binding.kind == "state_variable"
    )
    assert not any(
        ref.binding_id == library_x.id for ref in report.references
    )
    assert not any(
        item.name == "x" for item in report.unresolved
    )


def test_overloaded_member_call_classifies_opaque_overload():
    source = """
contract T {
    function f(uint256 a) external {}
    function f(bool b) external {}
}
contract C {
    T t;
    function g() external { t.f(1); }
}
"""
    report = build_sol_bindings(source)
    assert _unresolved(report, "f", "ambiguous_overload")
    assert any(
        call.kind == "opaque_overload" and call.target == ""
        for call in report.calls
    )


def test_member_call_through_using_for_type_resolves():
    source = """
library SafeMath {
    function add(uint256 a, uint256 b) internal pure returns (uint256) {}
}
contract Vault {
    using SafeMath for uint256;
    uint256 total;
    uint128 small;
    function run() external {
        total.add(1);
        small.add(1);
    }
}
"""
    report = build_sol_bindings(source)
    add = next(
        binding for binding in report.bindings if binding.name == "add"
    )
    add_refs = [
        ref
        for ref in report.references
        if ref.binding_id == add.id and ref.kind == "call"
    ]
    assert len(add_refs) == 1
    assert _text(source, add_refs[0].span) == "add"
    calls = [call for call in report.calls]
    assert calls[0].kind == "direct_local" and calls[0].target == add.id
    assert calls[1].kind == "opaque_member" and calls[1].target == ""


def test_member_call_through_using_star_and_global_resolves():
    source = """
library SafeMath {
    function add(uint256 a, uint256 b) internal pure returns (uint256) {}
}
struct Coin { uint256 v; }
library Stamps {
    function stamp(Coin memory c) internal pure {}
}
using Stamps for Coin global;
contract Vault {
    using SafeMath for *;
    uint256 total;
    Coin coin;
    function run() external {
        total.add(1);
        coin.stamp();
    }
}
"""
    report = build_sol_bindings(source)
    stamp = next(
        binding for binding in report.bindings if binding.name == "stamp"
    )
    add = next(
        binding for binding in report.bindings if binding.name == "add"
    )
    assert any(
        ref.binding_id == add.id and ref.kind == "call"
        for ref in report.references
    )
    assert any(
        ref.binding_id == stamp.id and ref.kind == "call"
        for ref in report.references
    )


def test_using_uint_alias_matches_declared_uint256():
    source = """
library L {
    function mark(uint256 a) internal pure {}
}
contract Vault {
    using L for uint;
    uint u;
    function run() external { u.mark(); }
}
"""
    report = build_sol_bindings(source)
    mark = next(
        binding for binding in report.bindings if binding.name == "mark"
    )
    assert any(
        ref.binding_id == mark.id and ref.kind == "call"
        for ref in report.references
    )


def test_using_for_dynamic_bytes_is_not_bytes1():
    source = """
library L {
    function mark(bytes memory b) internal pure {}
    function markByte(bytes1 b) internal pure {}
}
contract Vault {
    using L for bytes;
    bytes payload;
    bytes1 tag;
    function run() external {
        payload.mark();
        tag.markByte();
    }
}
"""
    report = build_sol_bindings(source)
    mark = next(
        binding for binding in report.bindings if binding.name == "mark"
    )
    mark_byte = next(
        binding
        for binding in report.bindings
        if binding.name == "markByte"
    )
    assert any(
        ref.binding_id == mark.id and ref.kind == "call"
        for ref in report.references
    )
    # `bytes` is dynamic, not `bytes1`: the directive does not cover
    # `tag`, so its call stays opaque.
    assert not any(
        ref.binding_id == mark_byte.id and ref.kind == "call"
        for ref in report.references
    )


def test_using_ambiguous_across_libraries_stays_opaque():
    source = """
library A { function f(uint256 a, bool b) internal pure {} }
library B { function f(uint256 a, uint256 b) internal pure {} }
contract Vault {
    using A for uint256;
    using B for uint256;
    uint256 total;
    function run() external { total.f(1); }
}
"""
    report = build_sol_bindings(source)
    assert _unresolved(report, "f", "ambiguous_overload")
    assert not any(
        ref.kind == "call" for ref in report.references
    )


def test_using_member_private_stays_fail_closed():
    source = """
library SafeMath {
    function hidden(uint256 a) private pure {}
}
contract Vault {
    using SafeMath for uint256;
    uint256 total;
    function run() external { total.hidden(); }
}
"""
    report = build_sol_bindings(source)
    assert _unresolved(report, "hidden", "private_base_member")
    assert not any(
        ref.kind == "call" for ref in report.references
    )


def test_member_call_on_array_element_resolves():
    source = """
contract Token {
    function transfer(address to, uint256 amount) external {}
}
contract Vault {
    Token[] tokens;
    uint256[] values;
    function run() external {
        tokens[0].transfer(address(0), 1);
        values[0].push;
    }
}
"""
    report = build_sol_bindings(source)
    transfer = next(
        binding
        for binding in report.bindings
        if binding.name == "transfer"
    )
    assert any(
        ref.binding_id == transfer.id and ref.kind == "call"
        for ref in report.references
    )


def test_member_call_on_call_return_resolves():
    source = """
contract Token {
    function transfer(address to, uint256 amount) external {}
}
contract Vault {
    function getToken() internal returns (Token) {}
    function run() external {
        getToken().transfer(address(0), 1);
        Token(address(0)).transfer(address(0), 1);
    }
}
"""
    report = build_sol_bindings(source)
    transfer = next(
        binding
        for binding in report.bindings
        if binding.name == "transfer"
    )
    transfer_refs = [
        ref
        for ref in report.references
        if ref.binding_id == transfer.id and ref.kind == "call"
    ]
    assert len(transfer_refs) == 2


def test_member_call_on_new_expression_resolves():
    source = """
contract Token {
    function transfer(address to, uint256 amount) external {}
}
contract Vault {
    function run() external {
        new Token().transfer(address(0), 1);
    }
}
"""
    report = build_sol_bindings(source)
    transfer = next(
        binding
        for binding in report.bindings
        if binding.name == "transfer"
    )
    assert any(
        ref.binding_id == transfer.id and ref.kind == "call"
        for ref in report.references
    )


def test_member_call_on_public_getter_call_resolves():
    source = """
contract Token {
    function transfer(address to, uint256 amount) external {}
}
contract Vault {
    Token public token;
    function run() external {
        this.token().transfer(address(0), 1);
    }
}
"""
    report = build_sol_bindings(source)
    transfer = next(
        binding
        for binding in report.bindings
        if binding.name == "transfer"
    )
    assert any(
        ref.binding_id == transfer.id and ref.kind == "call"
        for ref in report.references
    )


def test_member_call_on_function_typed_return_stays_opaque():
    source = """
contract Token {
    function transfer(address to, uint256 amount) external {}
}
contract Vault {
    function getCallback()
        internal
        returns (function() external returns (Token) cb)
    {}
    function run() external {
        getCallback().transfer(address(0), 1);
    }
}
"""
    report = build_sol_bindings(source)
    transfer = next(
        binding
        for binding in report.bindings
        if binding.name == "transfer"
    )
    assert not any(
        ref.binding_id == transfer.id for ref in report.references
    )


def test_member_call_on_function_pointer_stays_opaque():
    source = """
contract Token {
    function transfer(address to, uint256 amount) external {}
}
contract Vault {
    function(Token) external returns (Token) cb;
    function run(Token t) external {
        cb(t).transfer(address(0), 1);
    }
}
"""
    report = build_sol_bindings(source)
    transfer = next(
        binding
        for binding in report.bindings
        if binding.name == "transfer"
    )
    assert not any(
        ref.binding_id == transfer.id for ref in report.references
    )


def test_member_on_new_dynamic_array_stays_opaque():
    source = """
contract Token {
    function length() external {}
}
contract Vault {
    function run() external {
        new Token[](1).length;
    }
}
"""
    report = build_sol_bindings(source)
    length = next(
        binding for binding in report.bindings if binding.name == "length"
    )
    assert not any(
        ref.binding_id == length.id for ref in report.references
    )


def test_enum_member_access_resolves():
    source = """
enum Status { Ready, Done }
contract Vault {
    Status status;
    function run() external {
        status = Status.Ready;
    }
}
"""
    report = build_sol_bindings(source)
    ready = next(
        binding for binding in report.bindings if binding.name == "Ready"
    )
    assert ready.kind == "enum_member"
    assert any(
        ref.binding_id == ready.id and ref.kind == "read"
        for ref in report.references
    )


def test_struct_field_read_and_write_resolve():
    source = """
struct Coin { uint256 v; }
contract Vault {
    Coin coin;
    function run() external {
        coin.v = 1;
        uint256 x = coin.v;
    }
}
"""
    report = build_sol_bindings(source)
    v = next(binding for binding in report.bindings if binding.name == "v")
    assert v.kind == "struct_field"
    kinds = sorted(
        ref.kind for ref in report.references if ref.binding_id == v.id
    )
    assert kinds == ["read", "write"]


def test_member_chain_through_struct_field_resolves():
    source = """
struct Coin { Token t; }
contract Token {
    function transfer(address to, uint256 a) external {}
}
contract Vault {
    Coin coin;
    function run() external {
        coin.t.transfer(address(0), 1);
    }
}
"""
    report = build_sol_bindings(source)
    t = next(binding for binding in report.bindings if binding.name == "t")
    transfer = next(
        binding
        for binding in report.bindings
        if binding.name == "transfer"
    )
    assert any(
        ref.binding_id == t.id and ref.kind == "read"
        for ref in report.references
    )
    assert any(
        ref.binding_id == transfer.id and ref.kind == "call"
        for ref in report.references
    )


def test_struct_array_element_field_resolves():
    source = """
struct Coin { uint256 v; }
contract Vault {
    Coin[] coins;
    function run() external {
        coins[0].v = 1;
    }
}
"""
    report = build_sol_bindings(source)
    v = next(binding for binding in report.bindings if binding.name == "v")
    assert any(
        ref.binding_id == v.id and ref.kind == "write"
        for ref in report.references
    )


def test_struct_return_field_resolves():
    source = """
struct Coin { uint256 v; }
contract Vault {
    function getCoin() internal returns (Coin memory c) {}
    function run() external {
        uint256 x = getCoin().v;
    }
}
"""
    report = build_sol_bindings(source)
    v = next(binding for binding in report.bindings if binding.name == "v")
    assert any(
        ref.binding_id == v.id and ref.kind == "read"
        for ref in report.references
    )


def test_member_call_on_mapping_index_stays_opaque():
    source = """
contract Token {
    function transfer(address to, uint256 amount) external {}
}
contract Vault {
    mapping(uint256 => Token) byId;
    function run() external {
        byId[0].transfer(address(0), 1);
    }
}
"""
    report = build_sol_bindings(source)
    transfer = next(
        binding
        for binding in report.bindings
        if binding.name == "transfer"
    )
    assert not any(
        ref.binding_id == transfer.id for ref in report.references
    )


def test_using_member_binds_before_opaque_fallback():
    source = """
contract Owned {
    function flag() external {}
}
library Lib {
    function noop(Owned o) internal {}
}
contract Vault {
    using Lib for Owned;
    Owned owned;
    function run() external {
        owned.flag();
        owned.noop();
    }
}
"""
    report = build_sol_bindings(source)
    flag = next(
        binding for binding in report.bindings if binding.name == "flag"
    )
    noop = next(
        binding for binding in report.bindings if binding.name == "noop"
    )
    # The declared member wins over the using directive; the directive
    # only fills members the type itself does not declare.
    targets = {call.target for call in report.calls}
    assert {flag.id, noop.id} <= targets
