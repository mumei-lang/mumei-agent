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
    b_function = next(
        binding
        for binding in _bindings(report, "chosen", "function")
        if source.index("contract B") < binding.span.start < source.index("contract C")
    )
    assert chosen_call.target == b_function.id
    assert _unresolved(report, "hidden", "private_base_member")
    assert _unresolved(report, "Remote", "unresolved_base")
    assert _unresolved(report, "absent", "unresolved_base")
    assert any(gap.reason == "unresolved_base" for gap in report.gaps)


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
    stored_refs = [ref for ref in report.references if ref.binding_id == stored.id]
    assert all(ref.kind == "read" for ref in stored_refs)


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
            "opaque_member",
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
    with pytest.raises(LexicalReportError):
        build_sol_bindings(source)


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
    assert restored.source_sha256 == _build_sol_bindings(source).source_sha256


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
