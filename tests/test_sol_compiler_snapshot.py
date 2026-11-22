import json
from dataclasses import replace
from pathlib import Path

import pytest

from agent.lexical_bindings import ByteSpan, MAX_REPORT_BYTES
from agent.sol_bindings import build_sol_bindings
from agent.sol_compiler_snapshot import (
    ALLOWED_SOLC_VERSIONS,
    PROFILE,
    SolCompilerSnapshotError,
    compare_with_lexical,
    load_sol_compiler_snapshot,
)

FIXTURES = Path(__file__).parent / "fixtures" / "solc"


def _envelope(name):
    return json.loads((FIXTURES / f"{name}.envelope.json").read_text())


def _source(name):
    return (FIXTURES / f"{name}.sol").read_text()


def _payload(envelope):
    return json.dumps(envelope).encode("utf-8")


def _nodes(root):
    stack = [root]
    while stack:
        value = stack.pop()
        if type(value) is dict:
            if "nodeType" in value:
                yield value
            stack.extend(value.values())
        elif type(value) is list:
            stack.extend(value)


def _ast(envelope, source_name):
    return envelope["output"]["sources"][source_name]["ast"]


def _state_count_identifier(envelope):
    ast = _ast(envelope, "state_write.sol")
    return next(
        node
        for node in _nodes(ast)
        if node.get("nodeType") == "Identifier" and node.get("name") == "count"
    )


def _declaration(envelope, identifier):
    ast = _ast(envelope, "state_write.sol")
    return next(
        node
        for node in _nodes(ast)
        if node.get("id") == identifier["referencedDeclaration"]
    )


def _assert_rejected(envelope, source, *, raw=None):
    with pytest.raises(SolCompilerSnapshotError):
        load_sol_compiler_snapshot(
            _payload(envelope) if raw is None else raw,
            source,
        )


@pytest.mark.parametrize(
    ("name", "statuses"),
    [
        (
            "overloaded",
            ["agree", "agree", "lexical_unresolved"],
        ),
        (
            "inheritance_override",
            ["agree", "agree"],
        ),
        (
            "require_builtin",
            ["builtin", "agree"],
        ),
        (
            "state_write",
            ["agree", "agree"],
        ),
        (
            "state_write_operators",
            ["agree", "agree"],
        ),
        (
            "block_scope_shadowing",
            ["agree"] * 8,
        ),
        (
            "member_access",
            ["agree"] * 12
            + ["builtin"]
            + ["agree"] * 4
            + ["builtin"] * 2
            + ["agree"]
            + ["builtin"]
            + ["agree"] * 2
            + ["builtin"]
            + ["agree"] * 6,
        ),
    ],
)
def test_captured_references_have_exact_lexical_comparison_statuses(name, statuses):
    envelope = _envelope(name)
    source = _source(name)
    snapshot = load_sol_compiler_snapshot(_payload(envelope), source)
    report = build_sol_bindings(source)

    comparison = compare_with_lexical(snapshot, report)

    assert [item["status"] for item in comparison["references"]] == statuses
    assert comparison["summary"] == {
        status: statuses.count(status)
        for status in (
            "builtin",
            "agree",
            "disagree",
            "lexical_unresolved",
            "lexical_missing",
        )
    }
    assert set(comparison) == {
        "profile",
        "compiler_version",
        "source_sha256",
        "references",
        "summary",
    }
    assert comparison["profile"] == PROFILE
    assert comparison["compiler_version"] in ALLOWED_SOLC_VERSIONS
    assert comparison["source_sha256"] == f"sha256:{report.source_sha256}"


def test_overload_keeps_the_compiler_declaration_for_lexical_ambiguity():
    source = _source("overloaded")
    envelope = _envelope("overloaded")
    snapshot = load_sol_compiler_snapshot(_payload(envelope), source)
    comparison = compare_with_lexical(snapshot, build_sol_bindings(source))

    unresolved = next(
        item
        for item in comparison["references"]
        if item["status"] == "lexical_unresolved"
    )
    assert unresolved["name"] == "choose"
    assert unresolved["reason"] == "ambiguous_overload"
    assert unresolved["declaration"] is not None


def test_inheritance_call_resolves_to_the_override_declaration():
    source = _source("inheritance_override")
    envelope = _envelope("inheritance_override")
    snapshot = load_sol_compiler_snapshot(_payload(envelope), source)
    comparison = compare_with_lexical(snapshot, build_sol_bindings(source))

    call_start = source.index("hook();", source.index("function invoke"))
    call = next(
        item
        for item in comparison["references"]
        if item["span"] == {"start": call_start, "end": call_start + len("hook")}
    )
    override_start = source.index("hook", source.index("contract Child"))
    assert call["status"] == "agree"
    assert call["declaration"] == {
        "start": override_start,
        "end": override_start + len("hook"),
    }


def test_block_scope_shadowing_resolves_each_declared_binding():
    # The inner `count` shadows the state variable inside the block:
    # reads/writes there bind to the inner declaration, while `count`
    # outside the block binds to the state variable — and `local`
    # reassignments keep one declaration identity.
    source = _source("block_scope_shadowing")
    envelope = _envelope("block_scope_shadowing")
    snapshot = load_sol_compiler_snapshot(_payload(envelope), source)
    comparison = compare_with_lexical(snapshot, build_sol_bindings(source))

    state_decl = {
        "start": source.index("count"),
        "end": source.index("count") + len("count"),
    }
    inner_decl_start = source.index("count", source.index("{", source.index("local = count")))
    inner_decl = {"start": inner_decl_start, "end": inner_decl_start + len("count")}
    local_decl_start = source.index("local", source.index("uint256 local"))
    local_decl = {"start": local_decl_start, "end": local_decl_start + len("local")}

    by_span = {
        (item["span"]["start"], item["name"]): item
        for item in comparison["references"]
    }
    # `count` before and after the block → the state variable.
    for start in (
        source.index("count + 1"),
        source.index("count;", source.index("return")),
    ):
        assert by_span[(start, "count")]["declaration"] == state_decl
    # Inside the block both the read and the write bind to the inner `count`.
    for start in (
        source.index("count = count"),
        source.index("count + 10"),
    ):
        assert by_span[(start, "count")]["declaration"] == inner_decl
    # Every `local` reference binds to the single local declaration.
    local_refs = [item for item in comparison["references"] if item["name"] == "local"]
    assert len(local_refs) == 4
    assert all(item["declaration"] == local_decl for item in local_refs)


def test_inheritance_specifier_path_agrees_with_the_base_declaration():
    # `is Base` is an `IdentifierPath` reference in the 0.8.39 AST —
    # captured alongside `Identifier` references and agreeing with the
    # lexical base-name record.
    source = _source("inheritance_override")
    envelope = _envelope("inheritance_override")
    snapshot = load_sol_compiler_snapshot(_payload(envelope), source)
    comparison = compare_with_lexical(snapshot, build_sol_bindings(source))

    base_use = source.index("Base", source.index("contract Child"))
    base = next(
        item
        for item in comparison["references"]
        if item["span"] == {"start": base_use, "end": base_use + len("Base")}
    )
    base_decl = source.index("Base", source.index("contract "))
    assert base["name"] == "Base"
    assert base["status"] == "agree"
    assert base["declaration"] == {
        "start": base_decl,
        "end": base_decl + len("Base"),
    }


def test_require_is_reported_as_a_compiler_builtin():
    source = _source("require_builtin")
    envelope = _envelope("require_builtin")
    snapshot = load_sol_compiler_snapshot(_payload(envelope), source)
    comparison = compare_with_lexical(snapshot, build_sol_bindings(source))

    builtin = next(
        item for item in comparison["references"] if item["name"] == "require"
    )
    assert builtin["status"] == "builtin"
    assert builtin["builtin"] is True
    assert builtin["declaration"] is None


def test_state_variable_writes_agree_with_the_compiler_declaration():
    source = _source("state_write")
    envelope = _envelope("state_write")
    snapshot = load_sol_compiler_snapshot(_payload(envelope), source)
    comparison = compare_with_lexical(snapshot, build_sol_bindings(source))

    count_references = [
        item for item in comparison["references"] if item["name"] == "count"
    ]
    declaration_start = source.index("count")
    assert len(count_references) == 2
    assert all(item["status"] == "agree" for item in count_references)
    assert all(
        item["declaration"]
        == {"start": declaration_start, "end": declaration_start + len("count")}
        for item in count_references
    )


def test_duplicate_lexical_references_at_a_span_must_all_agree():
    source = _source("state_write_operators")
    snapshot = load_sol_compiler_snapshot(
        _payload(_envelope("state_write_operators")),
        source,
    )
    report = build_sol_bindings(source)
    lexical_references_by_span = {}
    for reference in report.references:
        lexical_references_by_span.setdefault(reference.span, []).append(reference)
    target = next(
        reference
        for reference in snapshot.references
        if reference.name == "count"
        and len(lexical_references_by_span.get(reference.span, ())) == 2
    )
    same_span_references = lexical_references_by_span[target.span]
    other_binding = next(
        binding for binding in report.bindings if binding.span != target.declaration
    )
    changed_reference = same_span_references[0]
    inconsistent_report = replace(
        report,
        references=tuple(
            replace(reference, binding_id=other_binding.id)
            if reference == changed_reference
            else reference
            for reference in report.references
        ),
    )

    comparison = compare_with_lexical(snapshot, inconsistent_report)

    assert len(same_span_references) == 2
    assert (
        next(
            item
            for item in comparison["references"]
            if item["span"] == target.span.to_dict()
        )["status"]
        == "disagree"
    )


def test_comparison_reports_disagreement_and_missing_lexical_records():
    source = _source("state_write")
    snapshot = load_sol_compiler_snapshot(
        _payload(_envelope("state_write")),
        source,
    )
    report = build_sol_bindings(source)
    target = next(
        reference for reference in snapshot.references if reference.name == "count"
    )
    lexical_reference = next(
        reference for reference in report.references if reference.span == target.span
    )
    other_binding = next(
        binding for binding in report.bindings if binding.span != target.declaration
    )
    disagreement_report = replace(
        report,
        references=tuple(
            replace(reference, binding_id=other_binding.id)
            if reference == lexical_reference
            else reference
            for reference in report.references
        ),
    )
    missing_report = replace(
        report,
        references=tuple(
            reference
            for reference in report.references
            if reference.span != target.span
        ),
        unresolved=tuple(
            item for item in report.unresolved if item.span != target.span
        ),
    )

    disagreement = compare_with_lexical(snapshot, disagreement_report)
    missing = compare_with_lexical(snapshot, missing_report)

    assert (
        next(
            item
            for item in disagreement["references"]
            if item["span"] == target.span.to_dict()
        )["status"]
        == "disagree"
    )
    assert (
        next(
            item
            for item in missing["references"]
            if item["span"] == target.span.to_dict()
        )["status"]
        == "lexical_missing"
    )


def test_comparison_rejects_wrong_lexical_profile_or_source_hash():
    source = _source("state_write")
    snapshot = load_sol_compiler_snapshot(
        _payload(_envelope("state_write")),
        source,
    )
    report = build_sol_bindings(source)

    with pytest.raises(SolCompilerSnapshotError):
        compare_with_lexical(snapshot, replace(report, profile="wrong"))
    with pytest.raises(SolCompilerSnapshotError):
        compare_with_lexical(
            snapshot, replace(report, source_sha256="sha256:" + "0" * 64)
        )


def test_rejects_envelopes_over_the_lexical_report_size_limit():
    with pytest.raises(SolCompilerSnapshotError):
        load_sol_compiler_snapshot(
            b" " * (MAX_REPORT_BYTES + 1),
            _source("state_write"),
        )


def test_rejects_duplicate_json_keys():
    _assert_rejected(
        {},
        _source("state_write"),
        raw=b'{"profile":"first","profile":"second"}',
    )


@pytest.mark.parametrize("change", ["wrong_profile", "extra_key", "missing_key"])
def test_rejects_wrong_envelope_profile_or_keys(change):
    envelope = _envelope("state_write")
    if change == "wrong_profile":
        envelope["profile"] = "wrong"
    elif change == "extra_key":
        envelope["extra"] = True
    else:
        del envelope["output"]
    _assert_rejected(envelope, _source("state_write"))


def test_rejects_non_solidity_input_or_multiple_sources():
    source = _source("state_write")
    envelope = _envelope("state_write")
    envelope["input"]["language"] = "Yul"
    _assert_rejected(envelope, source)

    envelope = _envelope("state_write")
    envelope["input"]["sources"]["other.sol"] = {"content": "contract Other {}"}
    _assert_rejected(envelope, source)


def test_rejects_source_content_mismatch():
    envelope = _envelope("state_write")
    envelope["input"]["sources"]["state_write.sol"]["content"] += "\n"
    _assert_rejected(envelope, _source("state_write"))


@pytest.mark.parametrize(
    "version_output",
    [
        "solc, the solidity compiler",
        "Version: invalid",
        "Version: 0.8.38+commit.deadbeef.Linux.g++",
    ],
)
def test_rejects_unparseable_or_disallowed_compiler_versions(version_output):
    envelope = _envelope("state_write")
    envelope["solc_version_output"] = version_output
    _assert_rejected(envelope, _source("state_write"))


def test_rejects_contract_metadata_with_a_different_compiler_version():
    envelope = _envelope("state_write")
    metadata = envelope["output"]["contracts"]["state_write.sol"]["Counter"]["metadata"]
    decoded = json.loads(metadata)
    decoded["compiler"]["version"] = "0.8.38+commit.deadbeef"
    envelope["output"]["contracts"]["state_write.sol"]["Counter"]["metadata"] = (
        json.dumps(decoded)
    )
    _assert_rejected(envelope, _source("state_write"))


def test_rejects_captured_compiler_error_output():
    envelope = _envelope("compile_error")
    assert any(
        diagnostic["severity"] == "error" for diagnostic in envelope["output"]["errors"]
    )
    _assert_rejected(envelope, _source("compile_error"))


@pytest.mark.parametrize(
    "change",
    ["missing_source", "extra_output_source", "nonzero_source_id", "wrong_ast_root"],
)
def test_rejects_missing_or_invalid_output_source(change):
    envelope = _envelope("state_write")
    if change == "missing_source":
        del envelope["output"]["sources"]["state_write.sol"]
    elif change == "extra_output_source":
        envelope["output"]["sources"]["other.sol"] = {"id": 1, "ast": {}}
    elif change == "nonzero_source_id":
        envelope["output"]["sources"]["state_write.sol"]["id"] = 1
    else:
        _ast(envelope, "state_write.sol")["nodeType"] = "ContractDefinition"
    _assert_rejected(envelope, _source("state_write"))


@pytest.mark.parametrize("change", ["missing_nodes", "none_nodes"])
def test_rejects_missing_or_invalid_ast_nodes(change):
    envelope = _envelope("state_write")
    ast = _ast(envelope, "state_write.sol")
    if change == "missing_nodes":
        del ast["nodes"]
    else:
        ast["nodes"] = None
    _assert_rejected(envelope, _source("state_write"))


def test_rejects_captured_import_source_and_import_ast_nodes():
    envelope = _envelope("import_source")
    assert len(envelope["input"]["sources"]) == 2
    assert any(
        node["nodeType"] == "ImportDirective"
        for node in _nodes(_ast(envelope, "import_source.sol"))
    )
    _assert_rejected(envelope, _source("import_source"))

    envelope = _envelope("state_write")
    _ast(envelope, "state_write.sol")["nodes"].append({"nodeType": "ImportDirective"})
    _assert_rejected(envelope, _source("state_write"))


def test_rejects_inline_assembly_ast_nodes():
    envelope = _envelope("state_write")
    _ast(envelope, "state_write.sol")["nodes"].append({"nodeType": "InlineAssembly"})
    _assert_rejected(envelope, _source("state_write"))


@pytest.mark.parametrize(
    "invalid_location",
    ["not-a-span", "999999:1:0", "0:1:1"],
)
def test_rejects_invalid_identifier_source_spans(invalid_location):
    envelope = _envelope("state_write")
    identifier = _state_count_identifier(envelope)
    identifier["src"] = invalid_location
    _assert_rejected(envelope, _source("state_write"))


def test_rejects_missing_identifier_source_span():
    envelope = _envelope("state_write")
    identifier = _state_count_identifier(envelope)
    del identifier["src"]
    _assert_rejected(envelope, _source("state_write"))


@pytest.mark.parametrize(
    "invalid_location",
    ["not-a-span", "999999:5:0", "0:5:1"],
)
def test_rejects_invalid_declaration_name_locations(invalid_location):
    envelope = _envelope("state_write")
    identifier = _state_count_identifier(envelope)
    _declaration(envelope, identifier)["nameLocation"] = invalid_location
    _assert_rejected(envelope, _source("state_write"))


def test_rejects_missing_declaration_name_location():
    envelope = _envelope("state_write")
    identifier = _state_count_identifier(envelope)
    del _declaration(envelope, identifier)["nameLocation"]
    _assert_rejected(envelope, _source("state_write"))


def test_rejects_identifier_without_referenced_declaration():
    envelope = _envelope("state_write")
    del _state_count_identifier(envelope)["referencedDeclaration"]
    _assert_rejected(envelope, _source("state_write"))


def test_rejects_nonnegative_reference_to_missing_declaration():
    envelope = _envelope("state_write")
    _state_count_identifier(envelope)["referencedDeclaration"] = 999999
    _assert_rejected(envelope, _source("state_write"))


def test_compiler_references_use_lexical_byte_spans():
    source = _source("require_builtin")
    snapshot = load_sol_compiler_snapshot(
        _payload(_envelope("require_builtin")),
        source,
    )
    require_start = source.index("require")
    builtin = next(
        reference for reference in snapshot.references if reference.name == "require"
    )

    assert snapshot.source_sha256.startswith("sha256:")
    assert builtin.span == ByteSpan(require_start, require_start + len("require"))
    assert builtin.builtin is True
    assert builtin.declaration is None


def test_member_access_declarations_match_lexical_member_bindings():
    source = _source("member_access")
    envelope = _envelope("member_access")
    snapshot = load_sol_compiler_snapshot(_payload(envelope), source)
    report = build_sol_bindings(source)
    comparison = compare_with_lexical(snapshot, report)

    bindings_by_id = {binding.id: binding for binding in report.bindings}
    lexical_by_span = {
        (ref.span.start, ref.span.end): ref for ref in report.references
    }
    member_items = [
        item
        for item in comparison["references"]
        if item["name"]
        in {"transfer", "supply", "vaultFn", "baseFn", "seed", "add", "stamp"}
    ]
    assert [item["status"] for item in member_items] == [
        "agree",
        "agree",
        "agree",
        "agree",
        "agree",
        "agree",
        "agree",
    ]
    for item in member_items:
        span = item["span"]
        lexical = lexical_by_span[(span["start"], span["end"])]
        binding = bindings_by_id[lexical.binding_id]
        assert item["declaration"] == binding.span.to_dict()
    transfer = next(
        binding
        for binding in report.bindings
        if binding.name == "transfer"
    )
    call = next(
        call for call in report.calls if call.target == transfer.id
    )
    assert call.kind == "direct_local"
    vault_fn = next(
        binding
        for binding in report.bindings
        if binding.name == "vaultFn"
    )
    this_call = next(
        call for call in report.calls if call.target == vault_fn.id
    )
    assert this_call.kind == "direct_local"
    base_fn = next(
        binding
        for binding in report.bindings
        if binding.name == "baseFn"
    )
    super_call = next(
        call for call in report.calls if call.target == base_fn.id
    )
    assert super_call.kind == "opaque_virtual"
    builtins = [
        item
        for item in comparison["references"]
        if item["name"] in {"push", "length", "this", "super"}
    ]
    assert all(item["status"] == "builtin" for item in builtins)


def test_member_access_without_analysis_output_is_rejected():
    # A `stopAfter: "parsing"` envelope leaves MemberAccess nodes with
    # empty `typeDescriptions`; without the check every member would be
    # miscounted as a builtin reference.
    source = _source("member_access")
    envelope = _envelope("member_access")
    ast = _ast(envelope, "member_access.sol")
    for node in _nodes(ast):
        if node.get("nodeType") == "MemberAccess":
            node.pop("referencedDeclaration", None)
            node["typeDescriptions"] = {}
    with pytest.raises(SolCompilerSnapshotError):
        load_sol_compiler_snapshot(_payload(envelope), source)


def test_member_access_loads_without_contract_outputs():
    # Contract outputs (`output.contracts`) are optional for the member
    # slice: an analyzed AST produced without them carries the same
    # member references.
    source = _source("member_access")
    envelope = _envelope("member_access")
    envelope["output"].pop("contracts")
    snapshot = load_sol_compiler_snapshot(_payload(envelope), source)
    assert [ref.name for ref in snapshot.references] == [
        ref.name
        for ref in load_sol_compiler_snapshot(
            _payload(_envelope("member_access")), source
        ).references
    ]
