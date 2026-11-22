import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from agent.lexical_bindings import MAX_REPORT_BYTES
from agent.ts_bindings import build_ts_bindings
from agent.ts_compiler_snapshot import (
    ALLOWED_TYPESCRIPT_VERSIONS,
    PROFILE,
    TsCompilerSnapshotError,
    compare_with_lexical,
    load_ts_compiler_snapshot,
)

FIXTURES = Path(__file__).parent / "fixtures" / "tsc"
HELPER_DIR = Path(__file__).parents[1] / "tools" / "ts-bindings"
FIXTURE_NAMES = (
    "bom_source",
    "block_scope_shadowing",
    "builtin_math",
    "class_closure",
    "function_overloads",
    "function_param_call",
    "export_local",
    "import_source",
    "intrinsic_globals",
    "mapped_property",
    "member_access",
    "state_write_operators",
    "tsx_fragment",
    "type_error",
)
POSITIVE_FIXTURES = (
    ("function_param_call", ["agree", "agree"]),
    ("export_local", ["agree", "agree"]),
    ("block_scope_shadowing", ["agree", "agree"]),
    ("function_overloads", ["agree", "agree"]),
    ("class_closure", ["agree", "agree"]),
    ("builtin_math", ["builtin", "builtin"]),
    ("intrinsic_globals", ["builtin", "builtin", "builtin", "builtin"]),
    ("tsx_fragment", ["agree"]),
    ("state_write_operators", ["agree", "agree"]),
    ("member_access", ["agree"] * 29 + ["builtin", "agree", "agree", "builtin"]),
)
_STATUSES = (
    "builtin",
    "agree",
    "disagree",
    "lexical_unresolved",
    "lexical_missing",
)


def _envelope(name):
    return json.loads((FIXTURES / f"{name}.envelope.json").read_text(encoding="utf-8"))


def _source(name):
    for extension in (".ts", ".tsx"):
        path = FIXTURES / f"{name}{extension}"
        if path.exists():
            return path.read_text(encoding="utf-8")
    raise AssertionError(f"missing source fixture: {name}")


def _payload(envelope):
    return json.dumps(envelope, ensure_ascii=False).encode("utf-8")


def _references(envelope):
    return envelope["references"]


def _assert_rejected(envelope, source, *, raw=None):
    with pytest.raises(TsCompilerSnapshotError):
        load_ts_compiler_snapshot(
            _payload(envelope) if raw is None else raw,
            source,
        )


@pytest.mark.parametrize(("name", "statuses"), POSITIVE_FIXTURES)
def test_captured_references_have_exact_lexical_comparison_statuses(name, statuses):
    source = _source(name)
    snapshot = load_ts_compiler_snapshot(
        (FIXTURES / f"{name}.envelope.json").read_bytes(),
        source,
    )
    report = build_ts_bindings(source, tsx=name == "tsx_fragment")

    comparison = compare_with_lexical(snapshot, report)

    assert [item["status"] for item in comparison["references"]] == statuses
    assert comparison["summary"] == {
        status: statuses.count(status) for status in _STATUSES
    }
    assert set(comparison) == {
        "profile",
        "compiler_version",
        "source_sha256",
        "references",
        "summary",
    }
    assert comparison["profile"] == PROFILE
    assert comparison["compiler_version"] in ALLOWED_TYPESCRIPT_VERSIONS
    assert comparison["source_sha256"] == f"sha256:{report.source_sha256}"


def test_math_is_reported_as_a_library_builtin():
    source = _source("builtin_math")
    snapshot = load_ts_compiler_snapshot(
        (FIXTURES / "builtin_math.envelope.json").read_bytes(),
        source,
    )
    comparison = compare_with_lexical(
        snapshot,
        build_ts_bindings(source),
    )

    assert len(comparison["references"]) == 2
    assert [item["name"] for item in comparison["references"]] == [
        "Math",
        "max",
    ]
    for reference in comparison["references"]:
        assert reference["status"] == "builtin"
        assert reference["library"] is True
        assert reference["declarations"] == []


def test_bom_source_is_loaded_with_byte_offsets_including_the_bom():
    source = _source("bom_source")
    snapshot = load_ts_compiler_snapshot(
        (FIXTURES / "bom_source.envelope.json").read_bytes(),
        source,
    )

    q_reference = next(item for item in snapshot.references if item.name == "q")

    assert q_reference.span.start == 26
    comparison = compare_with_lexical(snapshot, build_ts_bindings(source))
    assert [item["status"] for item in comparison["references"]] == ["agree"]


def test_export_references_bind_to_the_local_declaration():
    source = _source("export_local")
    snapshot = load_ts_compiler_snapshot(
        (FIXTURES / "export_local.envelope.json").read_bytes(),
        source,
    )
    comparison = compare_with_lexical(
        snapshot,
        build_ts_bindings(source),
    )

    assert [item["name"] for item in comparison["references"]] == [
        "value",
        "value",
    ]
    assert all(
        item["declarations"] == [{"start": 6, "end": 11}]
        for item in comparison["references"]
    )


def test_declaration_free_intrinsics_are_reported_as_library_builtins():
    source = _source("intrinsic_globals")
    snapshot = load_ts_compiler_snapshot(
        (FIXTURES / "intrinsic_globals.envelope.json").read_bytes(),
        source,
    )
    comparison = compare_with_lexical(
        snapshot,
        build_ts_bindings(source),
    )

    assert [item["name"] for item in comparison["references"]] == [
        "undefined",
        "globalThis",
        "arguments",
        "length",
    ]
    assert all(item["library"] is True for item in comparison["references"])
    assert all(item["declarations"] == [] for item in comparison["references"])


def test_overload_reference_keeps_all_in_source_declarations():
    source = _source("function_overloads")
    snapshot = load_ts_compiler_snapshot(
        (FIXTURES / "function_overloads.envelope.json").read_bytes(),
        source,
    )
    comparison = compare_with_lexical(
        snapshot,
        build_ts_bindings(source),
    )

    choose = next(item for item in comparison["references"] if item["name"] == "choose")
    assert choose["status"] == "agree"
    assert len(choose["declarations"]) == 3


def test_duplicate_lexical_references_must_all_match_a_compiler_declaration():
    name = "state_write_operators"
    source = _source(name)
    snapshot = load_ts_compiler_snapshot(
        (FIXTURES / f"{name}.envelope.json").read_bytes(),
        source,
    )
    report = build_ts_bindings(source)
    references_by_span = {}
    for reference in report.references:
        references_by_span.setdefault(reference.span, []).append(reference)
    target = next(
        reference
        for reference in snapshot.references
        if reference.name == "count"
        and len(references_by_span.get(reference.span, ())) == 2
    )
    same_span_references = references_by_span[target.span]
    other_binding = next(
        binding for binding in report.bindings if binding.span != target.declarations[0]
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


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("import_source", _source("import_source")),
        ("mapped_property", _source("mapped_property")),
        ("type_error", _source("type_error")),
    ],
)
def test_captured_negative_envelopes_are_rejected(name, source):
    _assert_rejected(_envelope(name), source)


def _mutate_extra_key(envelope):
    envelope["extra"] = None


def _mutate_wrong_profile(envelope):
    envelope["profile"] = "wrong/profile"


def _mutate_wrong_version(envelope):
    envelope["typescript_version"] = "7.0.2"


def _mutate_wrong_options(envelope):
    envelope["compiler_options"]["noEmit"] = 1


def _mutate_file_name(envelope):
    envelope["file_name"] = "input.jsx"


def _mutate_source(envelope):
    envelope["source"] += " "


def _mutate_error_diagnostic(envelope):
    envelope["diagnostics"].append(
        {"category": "error", "code": 2584, "message": "missing global"}
    )


def _mutate_unsupported(envelope):
    envelope["unsupported"].append(
        {"kind": "ImportDeclaration", "span": {"start": 0, "end": 1}}
    )


def _mutate_malformed_reference_span(envelope):
    _references(envelope)[0]["span"] = {"start": "0", "end": 1}


def _mutate_out_of_range_reference_span(envelope):
    _references(envelope)[0]["span"]["end"] = len(envelope["source"].encode()) + 1


def _mutate_non_boundary_reference_span(envelope):
    accent_start = envelope["source"].encode().index("é".encode())
    _references(envelope)[0]["span"]["start"] = accent_start + 1


def _mutate_reference_name(envelope):
    _references(envelope)[0]["name"] = "other"


def _mutate_declaration_name_span(envelope):
    _references(envelope)[0]["declarations"][0] = {"start": 0, "end": 1}


def _mutate_null_declarations(envelope):
    _references(envelope)[0]["declarations"] = None


def _mutate_library_with_declarations(envelope):
    reference = _references(envelope)[0]
    reference["declarations"] = [reference["span"].copy()]


def _mutate_non_library_without_declarations(envelope):
    _references(envelope)[0]["declarations"] = []


def _mutate_duplicate_reference_span(envelope):
    _references(envelope).append(_references(envelope)[0].copy())


def _mutate_overlapping_reference_spans(envelope):
    reference = _references(envelope)[0]
    overlapping = json.loads(json.dumps(reference))
    overlapping["span"]["start"] += 1
    overlapping["name"] = "alue"
    overlapping["declarations"][0]["start"] += 1
    _references(envelope).append(overlapping)


@pytest.mark.parametrize(
    ("mutation", "fixture"),
    [
        (_mutate_extra_key, "function_param_call"),
        (_mutate_wrong_profile, "function_param_call"),
        (_mutate_wrong_version, "function_param_call"),
        (_mutate_wrong_options, "function_param_call"),
        (_mutate_file_name, "function_param_call"),
        (_mutate_source, "function_param_call"),
        (_mutate_error_diagnostic, "function_param_call"),
        (_mutate_unsupported, "function_param_call"),
        (_mutate_malformed_reference_span, "function_param_call"),
        (_mutate_out_of_range_reference_span, "function_param_call"),
        (_mutate_non_boundary_reference_span, "function_param_call"),
        (_mutate_reference_name, "function_param_call"),
        (_mutate_declaration_name_span, "function_param_call"),
        (_mutate_null_declarations, "function_param_call"),
        (_mutate_library_with_declarations, "builtin_math"),
        (_mutate_non_library_without_declarations, "function_param_call"),
        (_mutate_duplicate_reference_span, "function_param_call"),
        (_mutate_overlapping_reference_spans, "function_param_call"),
    ],
    ids=lambda value: value.__name__ if callable(value) else value,
)
def test_rejects_mutated_envelopes(mutation, fixture):
    envelope = _envelope(fixture)
    source = _source(fixture)
    mutation(envelope)
    _assert_rejected(envelope, source)


def test_rejects_oversized_envelopes():
    with pytest.raises(TsCompilerSnapshotError):
        load_ts_compiler_snapshot(
            b"x" * (MAX_REPORT_BYTES + 1),
            _source("function_param_call"),
        )


@pytest.mark.parametrize(
    "raw",
    [
        b'{"profile":"one","profile":"two"}',
        b'{"profile":NaN}',
    ],
)
def test_rejects_duplicate_keys_and_nonstandard_numbers(raw):
    with pytest.raises(TsCompilerSnapshotError):
        load_ts_compiler_snapshot(raw, _source("function_param_call"))


def test_comparison_rejects_wrong_lexical_profile_and_source_hash():
    name = "function_param_call"
    source = _source(name)
    snapshot = load_ts_compiler_snapshot(
        (FIXTURES / f"{name}.envelope.json").read_bytes(),
        source,
    )
    report = build_ts_bindings(source)

    with pytest.raises(TsCompilerSnapshotError):
        compare_with_lexical(snapshot, replace(report, profile="wrong/profile"))
    with pytest.raises(TsCompilerSnapshotError):
        compare_with_lexical(snapshot, replace(report, source_sha256="0" * 64))


@pytest.mark.skipif(
    shutil.which("node") is None or not (HELPER_DIR / "node_modules").is_dir(),
    reason="Node.js and tools/ts-bindings/node_modules are required",
)
def test_operator_helper_reproduces_committed_envelopes_byte_for_byte():
    node = shutil.which("node")
    assert node is not None
    for name in FIXTURE_NAMES:
        source = next(
            path
            for path in (FIXTURES / f"{name}.ts", FIXTURES / f"{name}.tsx")
            if path.exists()
        )
        result = subprocess.run(
            [node, str(HELPER_DIR / "helper.js"), str(source)],
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        assert result.stdout == (FIXTURES / f"{name}.envelope.json").read_bytes()
