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
