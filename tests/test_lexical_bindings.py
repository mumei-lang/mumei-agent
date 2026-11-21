import copy
import hashlib
import json

import pytest

from agent.lexical_bindings import (
    Binding,
    ByteSpan,
    Function,
    LexicalBindingReport,
    LexicalReportError,
    Reference,
    TypeFact,
    Unresolved,
    binding_id,
    load_lexical_report,
)
from agent.rust_bindings import PROFILE as RUST_PROFILE, build_rust_bindings
from agent.sol_bindings import (
    PROFILE as SOL_PROFILE,
    build_sol_bindings as _build_sol_bindings,
)

PROFILE = "test.lexical/v1"
SOURCE = "fn f() {}"
TARGET = {"mode": "unit"}
UNKNOWN = TypeFact("unknown", "", 0, None, "")


def _report(source=SOURCE):
    digest = hashlib.sha256(source.encode()).hexdigest()
    decl = ByteSpan(3, 4)
    scope = ByteSpan(0, len(source.encode()))
    identifier = binding_id(digest, decl.start, scope.start, scope.end)
    return LexicalBindingReport(
        PROFILE,
        digest,
        TARGET,
        (
            Binding(identifier, "f", "function", decl, scope, UNKNOWN, False),
        ),
        (),
        (),
        (Function(identifier, ByteSpan(7, 9), (), UNKNOWN, False, False, False, False),),
        (),
        (),
    )


def _document(source=SOURCE):
    return json.loads(_report(source).to_json())


def _load(doc=None, source=SOURCE):
    return load_lexical_report(
        json.dumps(_document(source) if doc is None else doc),
        source,
        profile=PROFILE,
        target=TARGET,
    )


def _producer_document(source):
    return json.loads(build_rust_bindings(source, pointer_width=64).to_json())


def _load_producer_document(doc, source):
    return load_lexical_report(
        json.dumps(doc),
        source,
        profile=RUST_PROFILE,
        target={"pointer_width": 64},
    )


def _sol_document(source):
    return json.loads(build_sol_bindings(source).to_json())


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


def _load_sol_document(doc, source):
    return load_lexical_report(
        json.dumps(doc),
        source,
        profile=SOL_PROFILE,
        target={},
    )


def test_binding_ids_pin_source_and_scope_coordinates():
    digest = hashlib.sha256(SOURCE.encode()).hexdigest()
    assert binding_id(digest, 3, 0, len(SOURCE)) == f"sha256:{digest}:3:0:9"
    assert _report().bindings[0].id != _report(SOURCE + " ").bindings[0].id


def test_report_serialization_is_deterministic_and_round_trips():
    report = _report()
    assert report.to_json() == _report().to_json()
    assert report.to_json().endswith("\n")
    restored = _load()
    assert restored == report
    assert restored.complete
    assert restored.binding(report.bindings[0].id) == report.bindings[0]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(profile="wrong"),
        lambda d: d.update(resolution="typed"),
        lambda d: d.update(source_sha256="0" * 64),
        lambda d: d.update(target={"mode": "other"}),
        lambda d: d.update(extra=True),
        lambda d: d.pop("calls"),
        lambda d: d.update(complete=1),
        lambda d: d["bindings"][0]["span"].update(start=True),
        lambda d: d["bindings"][0]["span"].update(end=10),
        lambda d: d["bindings"][0]["type"].update(bit_width=True),
        lambda d: d["bindings"][0]["type"].update(type_id="missing"),
        lambda d: d["bindings"][0].update(id="sha256:" + "0" * 64 + ":3:0:9"),
        lambda d: d["bindings"].append(copy.deepcopy(d["bindings"][0])),
        lambda d: d["references"].append(
            {"span": {"start": 3, "end": 4}, "binding_id": "missing", "kind": "read"}
        ),
        lambda d: d["functions"][0].update(binding_id="missing"),
        lambda d: d["functions"][0].update(parameters=["missing"]),
        lambda d: d.update(complete=False),
        lambda d: d["bindings"][0]["type"].update(kind="pointer"),
        lambda d: d["bindings"][0].update(kind="unknown_binding"),
        lambda d: d["bindings"][0].update(unexpected=None),
        lambda d: d["bindings"][0].pop("mutable"),
    ],
)
def test_reader_rejects_tampering(mutate):
    doc = _document()
    mutate(doc)
    with pytest.raises(LexicalReportError):
        _load(doc)


def test_reader_rejects_dangling_call_target_and_owner():
    for field in ("owner", "target"):
        doc = _document()
        doc["calls"] = [
            {
                "span": {"start": 3, "end": 4},
                "arguments": [],
                "owner": "missing" if field == "owner" else "",
                "target": "missing" if field == "target" else "",
                "kind": "direct_local",
            }
        ]
        with pytest.raises(LexicalReportError):
            _load(doc)


def test_reader_rejects_span_inside_multibyte_character():
    source = "é"
    doc = {
        "profile": PROFILE,
        "resolution": "lexical",
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "target": TARGET,
        "complete": False,
        "bindings": [],
        "references": [],
        "unresolved": [
            {"span": {"start": 1, "end": 2}, "name": "x", "reason": "unknown_name"}
        ],
        "functions": [],
        "calls": [],
        "gaps": [],
    }
    with pytest.raises(LexicalReportError):
        _load(doc, source)


def test_reader_rejects_oversize_input_and_duplicate_json_keys():
    with pytest.raises(LexicalReportError):
        load_lexical_report(
            b" " * (8 * 1024 * 1024 + 1),
            SOURCE,
            profile=PROFILE,
            target=TARGET,
        )
    with pytest.raises(LexicalReportError):
        load_lexical_report(
            '{"profile":"one","profile":"two"}',
            SOURCE,
            profile=PROFILE,
            target=TARGET,
        )


def test_reader_requires_strict_target_types():
    with pytest.raises(LexicalReportError):
        load_lexical_report(
            _report().to_json(),
            SOURCE,
            profile=PROFILE,
            target={"mode": 1},
        )


def test_resolve_returns_the_referenced_binding_and_never_resolves_unresolved_names():
    report = _report()
    binding = report.bindings[0]
    with_reference = LexicalBindingReport(
        PROFILE,
        report.source_sha256,
        TARGET,
        report.bindings,
        (Reference(ByteSpan(3, 4), binding.id, "read"),),
        (),
        report.functions,
        (),
        (),
    )
    assert with_reference.resolve(ByteSpan(3, 4)) == binding
    with_unresolved = LexicalBindingReport(
        PROFILE,
        report.source_sha256,
        TARGET,
        report.bindings,
        (Reference(ByteSpan(5, 6), binding.id, "read"),),
        (Unresolved(ByteSpan(5, 6), "unknown", "unknown_name"),),
        report.functions,
        (),
        (),
    )
    assert with_unresolved.resolve(ByteSpan(5, 6)) is None
    assert not with_unresolved.complete


def test_reader_rejects_reference_and_unresolved_at_the_same_span():
    source = "fn f(x:i32){ x; }"
    doc = _producer_document(source)
    reference = next(
        item
        for item in doc["references"]
        if source.encode()[item["span"]["start"] : item["span"]["end"]] == b"x"
    )
    doc["unresolved"].append(
        {"span": copy.deepcopy(reference["span"]), "name": "x", "reason": "unknown_name"}
    )
    doc["complete"] = False
    with pytest.raises(LexicalReportError):
        _load_producer_document(doc, source)


def test_reader_rejects_exact_duplicate_references_but_allows_distinct_kinds():
    source = "fn f(mut x:i32){ x += 1; }"
    doc = _producer_document(source)
    reference = next(
        item
        for item in doc["references"]
        if source.encode()[item["span"]["start"] : item["span"]["end"]] == b"x"
        and item["kind"] == "read"
    )
    doc["references"].append(copy.deepcopy(reference))
    with pytest.raises(LexicalReportError):
        _load_producer_document(doc, source)

    report = build_rust_bindings(source, pointer_width=64)
    x_references = [
        item
        for item in report.references
        if source.encode()[item.span.start : item.span.end] == b"x"
    ]
    assert [item.kind for item in x_references] == ["read", "write"]
    restored = _load_producer_document(json.loads(report.to_json()), source)
    assert restored.to_json() == report.to_json()


@pytest.mark.parametrize("tamper", ["duplicate", "function_kind", "parameter_kind"])
def test_reader_validates_function_records_and_parameter_kinds(tamper):
    source = "fn f(x:i32){ x; }"
    doc = _producer_document(source)
    function = doc["functions"][0]
    if tamper == "duplicate":
        doc["functions"].append(copy.deepcopy(function))
    elif tamper == "function_kind":
        function["binding_id"] = function["parameters"][0]
    else:
        function["parameters"] = [function["binding_id"]]
    with pytest.raises(LexicalReportError):
        _load_producer_document(doc, source)


@pytest.mark.parametrize("field", ["generic", "is_async"])
def test_reader_rejects_generic_or_async_direct_local_targets(field):
    source = "fn caller(){ callee(); } fn callee(){}"
    doc = _producer_document(source)
    call = next(call for call in doc["calls"] if call["kind"] == "direct_local")
    target = next(
        function
        for function in doc["functions"]
        if function["binding_id"] == call["target"]
    )
    target[field] = True
    with pytest.raises(LexicalReportError):
        _load_producer_document(doc, source)


@pytest.mark.parametrize(
    ("source", "expected_kind", "callee"),
    [
        ("fn caller(){ callee(); } fn callee(){}", "direct_local", "callee"),
        ("fn caller(){ callee(); } fn callee<T>(){}", "opaque_generic", "callee"),
        ("async fn callee(){} fn caller(){ callee(); }", "opaque_async", "callee"),
        (
            'extern "C" { fn callee(); } fn caller(){ callee(); }',
            "opaque_bodyless",
            "callee",
        ),
        (
            "use outside::callee; fn caller(){ callee(); }",
            "opaque_import",
            "callee",
        ),
        ("fn caller(callee:fn()){ callee(); }", "opaque_value", "callee"),
        ("struct Callee(); fn caller(){ Callee(); }", "constructor", "Callee"),
    ],
)
def test_reader_requires_targets_for_targeted_call_kinds(source, expected_kind, callee):
    doc = _producer_document(source)
    call = next(
        item
        for item in doc["calls"]
        if source.encode()[item["span"]["start"] : item["span"]["end"]].startswith(
            f"{callee}(".encode()
        )
    )
    assert call["kind"] == expected_kind
    assert call["target"]
    call["target"] = ""
    with pytest.raises(LexicalReportError):
        _load_producer_document(doc, source)


@pytest.mark.parametrize(
    "kind", ["unresolved", "opaque_path", "opaque_method", "opaque_expression"]
)
def test_reader_rejects_targets_for_empty_target_call_kinds(kind):
    source = "fn caller(){ callee(); } fn callee(){}"
    doc = _producer_document(source)
    doc["calls"][0]["kind"] = kind
    with pytest.raises(LexicalReportError):
        _load_producer_document(doc, source)


def test_reader_validates_call_owners_and_direct_local_function_bodies():
    source = "fn caller(x:i32){ callee(); } fn callee(){}"
    doc = _producer_document(source)
    parameter_id = next(
        item["id"] for item in doc["bindings"] if item["name"] == "x"
    )
    doc["calls"][0]["owner"] = parameter_id
    with pytest.raises(LexicalReportError):
        _load_producer_document(doc, source)

    source = 'extern "C" { fn callee(); } fn caller(){ callee(); }'
    doc = _producer_document(source)
    assert doc["calls"][0]["kind"] == "opaque_bodyless"
    doc["calls"][0]["kind"] = "direct_local"
    with pytest.raises(LexicalReportError):
        _load_producer_document(doc, source)


def test_reader_rejects_write_references_to_non_assignable_bindings():
    source = "const K:u8=0; fn f(){ K = 1; }"
    doc = _producer_document(source)
    reference = next(
        item
        for item in doc["references"]
        if source.encode()[item["span"]["start"] : item["span"]["end"]] == b"K"
    )
    assert reference["kind"] == "read"
    reference["kind"] = "write"
    with pytest.raises(LexicalReportError):
        _load_producer_document(doc, source)


@pytest.mark.parametrize(
    ("type_name", "tamper"),
    [
        ("address", {"bit_width": 159}),
        ("address", {"signed": True}),
        ("bytes4", {"bit_width": 31}),
        ("bytes4", {"signed": True}),
    ],
)
def test_sol_reader_validates_address_and_fixed_bytes_facts(type_name, tamper):
    source = f"contract C {{ {type_name} value; }}"
    doc = _sol_document(source)
    binding = next(item for item in doc["bindings"] if item["name"] == "value")
    for key, value in tamper.items():
        binding["type"][key] = value
    with pytest.raises(LexicalReportError):
        _load_sol_document(doc, source)


@pytest.mark.parametrize(
    ("source", "binding_kind"),
    [
        ("contract C {}", "contract"),
        ("interface I {}", "interface"),
        ("library L {}", "library"),
        ("contract C { modifier m() { _; } }", "modifier"),
        ("contract C { event E(); }", "event"),
        ("contract C { error E(); }", "error"),
        ("type W is uint8;", "user_type"),
    ],
)
def test_sol_reader_rejects_writes_to_non_assignable_binding_kinds(
    source, binding_kind
):
    doc = _sol_document(source)
    binding = next(item for item in doc["bindings"] if item["kind"] == binding_kind)
    doc["references"].append(
        {
            "span": binding["span"],
            "binding_id": binding["id"],
            "kind": "write",
        }
    )
    with pytest.raises(LexicalReportError):
        _load_sol_document(doc, source)


def test_sol_reader_rejects_writes_to_immutable_state_variables():
    source = "contract C { uint immutable value; }"
    doc = _sol_document(source)
    binding = next(item for item in doc["bindings"] if item["name"] == "value")
    assert binding["mutable"] is False
    doc["references"].append(
        {
            "span": binding["span"],
            "binding_id": binding["id"],
            "kind": "write",
        }
    )
    with pytest.raises(LexicalReportError):
        _load_sol_document(doc, source)


def test_sol_reader_accepts_modifier_constructor_and_return_parameter_function_records():
    source = """
contract C {
    modifier m(uint p) { _; }
    constructor(uint x) {}
    function f(uint x) public returns (uint result) { result = x; }
}
"""
    doc = _sol_document(source)
    _load_sol_document(doc, source)
    function_ids = {item["binding_id"] for item in doc["functions"]}
    binding_by_id = {item["id"]: item for item in doc["bindings"]}
    assert {binding_by_id[identifier]["kind"] for identifier in function_ids} == {
        "modifier",
        "constructor",
        "function",
    }

    bad_function = copy.deepcopy(doc)
    function_id = next(
        item["binding_id"]
        for item in bad_function["functions"]
        if binding_by_id[item["binding_id"]]["kind"] == "modifier"
    )
    next(item for item in bad_function["bindings"] if item["id"] == function_id)[
        "kind"
    ] = "local"
    with pytest.raises(LexicalReportError):
        _load_sol_document(bad_function, source)

    bad_parameter = copy.deepcopy(doc)
    return_parameter_id = next(
        item["id"]
        for item in bad_parameter["bindings"]
        if item["kind"] == "return_parameter"
    )
    next(item for item in bad_parameter["bindings"] if item["id"] == return_parameter_id)[
        "kind"
    ] = "local"
    with pytest.raises(LexicalReportError):
        _load_sol_document(bad_parameter, source)


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        (
            "contract C { function f() public {} function g() public { f(); } }",
            "direct_local",
        ),
        (
            "contract A {} contract C { function f() public { new A(); } }",
            "opaque_new",
        ),
        (
            "struct S { uint x; } contract C { function f() public { S({x: 1}); } }",
            "constructor",
        ),
        (
            "import {A} from 'x.sol'; contract C { function f() public { A(); } }",
            "opaque_import",
        ),
        (
            "contract C { error E(); function f() public { revert E(); } }",
            "error_constructor",
        ),
        (
            "contract C { event E(); function f() public { emit E(); } }",
            "emit",
        ),
        (
            "contract C { modifier m() { _; } function f() public m {} }",
            "modifier",
        ),
        (
            "contract A { constructor() {} } contract C is A() {}",
            "base_constructor",
        ),
        (
            "interface I { function f() external; } "
            "contract C is I { function g() public { f(); } }",
            "opaque_bodyless",
        ),
        (
            "contract A { function f() public virtual {} function g() public { f(); } } "
            "contract B is A { function f() public override {} }",
            "opaque_virtual",
        ),
        (
            "contract C { function f() public payable {} "
            "function g() public payable { f{value: 1}(); } }",
            "opaque_call_options",
        ),
    ],
)
def test_sol_reader_requires_targets_for_solidity_call_kinds(source, kind):
    doc = _sol_document(source)
    assert any(item["kind"] == kind for item in doc["calls"])
    _load_sol_document(doc, source)
    call = next(item for item in doc["calls"] if item["kind"] == kind)
    call["target"] = ""
    with pytest.raises(LexicalReportError):
        _load_sol_document(doc, source)


def test_sol_reader_rejects_wrong_constructor_target_kind_and_bad_owner():
    source = "contract A {} contract C { function f() public { new A(); } }"
    doc = _sol_document(source)
    call = next(item for item in doc["calls"] if item["kind"] == "opaque_new")
    function_id = next(item["id"] for item in doc["bindings"] if item["kind"] == "function")
    call["target"] = function_id
    with pytest.raises(LexicalReportError):
        _load_sol_document(doc, source)


def test_sol_reader_rejects_targets_for_opaque_member_calls():
    source = "contract C { function f() public { this.f(); new C(); } }"
    doc = _sol_document(source)
    call = next(item for item in doc["calls"] if item["kind"] == "opaque_member")
    call["target"] = next(
        item["id"] for item in doc["bindings"] if item["kind"] == "function"
    )
    with pytest.raises(LexicalReportError):
        _load_sol_document(doc, source)

    doc = _sol_document(source)
    call = next(item for item in doc["calls"] if item["kind"] == "opaque_new")
    call["owner"] = next(
        item["id"] for item in doc["bindings"] if item["kind"] == "contract"
    )
    with pytest.raises(LexicalReportError):
        _load_sol_document(doc, source)
