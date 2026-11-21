import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from agent.lexical_bindings import MAX_REPORT_BYTES, ByteSpan, Gap, Unresolved
from agent.rust_bindings import build_rust_bindings
from agent.rust_compiler_snapshot import (
    ALLOWED_LSIF_LABELS,
    ALLOWED_RUST_ANALYZER_VERSIONS,
    ENVELOPE_PROFILE,
    PROFILE,
    RustCompilerSnapshotError,
    compare_with_lexical,
    load_rust_compiler_snapshot,
)

FIXTURES = Path(__file__).parent / "fixtures" / "rust_analyzer"
FIXTURE_NAMES = (
    "local_shadowing",
    "cross_file",
    "external_stdlib",
    "macro_usage",
    "build_script",
)
_STATUSES = (
    "external",
    "cross_file",
    "agree",
    "disagree",
    "lexical_unresolved",
    "lexical_missing",
)


def _envelope(name):
    return json.loads((FIXTURES / f"{name}.envelope.json").read_bytes())


def _source(name):
    envelope = _envelope(name)
    return (FIXTURES / name / envelope["target"]).read_bytes()


def _payload(envelope):
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode()


def _source_lines(source):
    text = source.decode("utf-8")
    lines = []
    cursor = 0
    index = 0
    while index < len(text):
        if text.startswith("\r\n", index):
            lines.append(text[cursor:index])
            index += 2
            cursor = index
        elif text[index] in "\r\n":
            lines.append(text[cursor:index])
            index += 1
            cursor = index
        else:
            index += 1
    lines.append(text[cursor:])
    return lines


def _python_index(line, utf16_character):
    units = 0
    for index, character in enumerate(line):
        if units == utf16_character:
            return index
        width = 2 if ord(character) > 0xFFFF else 1
        if units < utf16_character < units + width:
            raise AssertionError("position is inside a surrogate pair")
        units += width
    assert units == utf16_character
    return len(line)


def _target_document_id(envelope):
    target_uri = f"file:///project/{envelope['target']}"
    return next(
        row["id"]
        for row in envelope["lsif"]
        if row.get("type") == "vertex"
        and row.get("label") == "document"
        and row.get("uri") == target_uri
    )


def _reference_range(envelope, source, name):
    rows = envelope["lsif"]
    vertices = {row["id"]: row for row in rows if row.get("type") == "vertex"}
    target_id = _target_document_id(envelope)
    lines = _source_lines(source)
    for edge in rows:
        if (
            edge.get("type") != "edge"
            or edge.get("label") != "item"
            or edge.get("property") != "references"
            or edge.get("document") != target_id
        ):
            continue
        for range_id in edge["inVs"]:
            value = vertices[range_id]
            start = value["start"]
            end = value["end"]
            line = lines[start["line"]]
            start_index = _python_index(line, start["character"])
            end_index = _python_index(line, end["character"])
            if line[start_index:end_index] == name:
                return value
    raise AssertionError(f"missing target reference to {name!r}")


def _refresh_document(envelope, path, content):
    document = next(item for item in envelope["documents"] if item["path"] == path)
    document["content"] = content
    document["sha256"] = f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"


def _add_dependency(envelope, section):
    document = next(
        item for item in envelope["documents"] if item["path"] == "Cargo.toml"
    )
    document["content"] += f"\n{section}"
    document["sha256"] = (
        f"sha256:{hashlib.sha256(document['content'].encode()).hexdigest()}"
    )


@pytest.mark.parametrize("name", FIXTURE_NAMES[:-1])
def test_pinned_fixture_labels_match_the_allowlist(name):
    envelope = _envelope(name)
    assert envelope["profile"] == ENVELOPE_PROFILE
    labels = {row["label"] for row in envelope["lsif"]}
    assert labels <= ALLOWED_LSIF_LABELS


def test_allowlist_is_the_union_observed_in_all_pinned_fixtures():
    labels = {
        row["label"]
        for name in FIXTURE_NAMES
        for row in _envelope(name)["lsif"]
    }
    assert labels == ALLOWED_LSIF_LABELS
    assert ALLOWED_RUST_ANALYZER_VERSIONS == {
        "1.100.0 (0ef1bc3 2026-11-09)"
    }


def test_local_shadowing_reassignment_and_unicode_references_agree():
    envelope = _envelope("local_shadowing")
    source = _source("local_shadowing")
    snapshot = load_rust_compiler_snapshot(_payload(envelope), source)
    report = build_rust_bindings(source.decode("utf-8"), pointer_width=64)

    comparison = compare_with_lexical(snapshot, report)

    assert set(comparison) == {
        "profile",
        "rust_analyzer_version",
        "source_sha256",
        "references",
        "summary",
    }
    assert comparison["profile"] == PROFILE
    assert comparison["source_sha256"] == snapshot.source_sha256
    assert comparison["rust_analyzer_version"] == next(
        iter(ALLOWED_RUST_ANALYZER_VERSIONS)
    )
    assert comparison["summary"] == {
        status: len(comparison["references"]) if status == "agree" else 0
        for status in _STATUSES
    }
    assert {item["name"] for item in comparison["references"]} >= {
        "count",
        "café",
        "𐐀value",
    }
    assert all(item["status"] == "agree" for item in comparison["references"])


def test_cross_file_and_external_references_are_metadata_only():
    envelope = _envelope("cross_file")
    source = _source("cross_file")
    snapshot = load_rust_compiler_snapshot(_payload(envelope), source)
    comparison = compare_with_lexical(
        snapshot, build_rust_bindings(source.decode("utf-8"), pointer_width=64)
    )

    cross_file = [
        item for item in comparison["references"] if item["status"] == "cross_file"
    ]
    external = [
        item for item in comparison["references"] if item["status"] == "external"
    ]
    assert any(item["name"] == "double" for item in cross_file)
    assert all(
        item["definition"]["path"] == "src/util.rs" for item in cross_file
    )
    assert {item["name"] for item in external} >= {"max"}
    assert any(
        item["name"] == "max" and "i64::Ord::max" in item["moniker"]
        for item in external
    )
    assert all(set(item) == {"span", "name", "moniker", "status"} for item in external)
    assert comparison["summary"]["cross_file"] == len(cross_file)
    assert comparison["summary"]["external"] == len(external)


def test_standard_library_path_is_reported_as_external():
    envelope = _envelope("external_stdlib")
    source = _source("external_stdlib")
    snapshot = load_rust_compiler_snapshot(_payload(envelope), source)
    comparison = compare_with_lexical(
        snapshot, build_rust_bindings(source.decode("utf-8"), pointer_width=64)
    )

    maximum = next(item for item in comparison["references"] if item["name"] == "max")
    assert maximum["status"] == "external"
    assert maximum["moniker"] == "core::cmp::max"
    assert "definition" not in maximum and "declaration" not in maximum


def test_macro_gap_refuses_lexical_comparison():
    envelope = _envelope("macro_usage")
    source = _source("macro_usage")
    snapshot = load_rust_compiler_snapshot(_payload(envelope), source)
    report = build_rust_bindings(source.decode("utf-8"), pointer_width=64)
    assert any(gap.reason == "macro_invocation" for gap in report.gaps)

    with pytest.raises(RustCompilerSnapshotError, match="lexical gaps"):
        compare_with_lexical(snapshot, report)

    assert compare_with_lexical(snapshot, replace(report, gaps=()))["profile"] == PROFILE


def test_rejects_non_identifier_reference_ranges():
    envelope = _envelope("cross_file")
    source = _source("cross_file")
    maximum = _reference_range(envelope, source, "max")
    maximum["start"]["character"] -= 1

    with pytest.raises(RustCompilerSnapshotError, match="not a Rust identifier"):
        load_rust_compiler_snapshot(_payload(envelope), source)

@pytest.mark.parametrize("reason", ["macro_definition", "conditional_compilation"])
def test_other_unsupported_lexical_gaps_refuse_comparison(reason):
    envelope = _envelope("local_shadowing")
    source = _source("local_shadowing")
    snapshot = load_rust_compiler_snapshot(_payload(envelope), source)
    report = build_rust_bindings(source.decode("utf-8"), pointer_width=64)
    report = replace(report, gaps=report.gaps + (Gap(reason, ByteSpan(0, 0)),))

    with pytest.raises(RustCompilerSnapshotError, match="lexical gaps"):
        compare_with_lexical(snapshot, report)


def test_comparison_rejects_wrong_lexical_profile_and_source_hash():
    envelope = _envelope("local_shadowing")
    source = _source("local_shadowing")
    snapshot = load_rust_compiler_snapshot(_payload(envelope), source)
    report = build_rust_bindings(source.decode("utf-8"), pointer_width=64)

    with pytest.raises(RustCompilerSnapshotError):
        compare_with_lexical(snapshot, replace(report, profile="wrong/profile"))
    with pytest.raises(RustCompilerSnapshotError):
        compare_with_lexical(snapshot, replace(report, source_sha256="0" * 64))


def test_comparison_reports_disagree_unresolved_and_missing_local_references():
    envelope = _envelope("local_shadowing")
    source = _source("local_shadowing")
    snapshot = load_rust_compiler_snapshot(_payload(envelope), source)
    report = build_rust_bindings(source.decode("utf-8"), pointer_width=64)
    first = report.references[0]
    disagree_report = replace(
        report,
        references=(
            replace(first, binding_id="missing-binding"),
            *report.references[1:],
        ),
    )
    disagree = compare_with_lexical(snapshot, disagree_report)
    assert any(item["status"] == "disagree" for item in disagree["references"])

    unresolved_report = replace(
        report,
        references=report.references[1:],
        unresolved=report.unresolved
        + (
            Unresolved(
                first.span,
                source[first.span.start : first.span.end].decode("utf-8"),
                "unresolved",
            ),
        ),
    )
    unresolved = compare_with_lexical(snapshot, unresolved_report)
    assert any(
        item["span"] == first.span.to_dict()
        and item["status"] == "lexical_unresolved"
        for item in unresolved["references"]
    )

    missing_report = replace(report, references=report.references[1:])
    missing = compare_with_lexical(snapshot, missing_report)
    assert any(
        item["span"] == first.span.to_dict() and item["status"] == "lexical_missing"
        for item in missing["references"]
    )


@pytest.mark.parametrize("newline", ["\r\n", "\r"])
def test_utf16_positions_support_all_lsp_line_endings(newline):
    envelope = _envelope("local_shadowing")
    source = _source("local_shadowing").decode("utf-8").replace("\n", newline)
    _refresh_document(envelope, envelope["target"], source)
    source_bytes = source.encode("utf-8")
    snapshot = load_rust_compiler_snapshot(_payload(envelope), source_bytes)

    comparison = compare_with_lexical(
        snapshot, build_rust_bindings(source, pointer_width=64)
    )

    assert all(item["status"] == "agree" for item in comparison["references"])


def test_build_script_document_is_rejected():
    envelope = _envelope("build_script")
    source = _source("build_script")
    with pytest.raises(RustCompilerSnapshotError, match="build scripts"):
        load_rust_compiler_snapshot(_payload(envelope), source)


@pytest.mark.parametrize(
    "section",
    [
        '[dependencies]\nexample = "1"',
        '[target.\'cfg(unix)\'.dependencies]\nexample = "1"',
        '[workspace]\nmembers = ["other"]',
        "[lib]\nproc-macro = true",
    ],
)
def test_project_boundary_rejects_dependencies_workspaces_and_proc_macros(section):
    envelope = _envelope("local_shadowing")
    source = _source("local_shadowing")
    _add_dependency(envelope, section)

    with pytest.raises(RustCompilerSnapshotError):
        load_rust_compiler_snapshot(_payload(envelope), source)


def test_project_boundary_rejects_package_build_key_and_lock_sources():
    envelope = _envelope("local_shadowing")
    source = _source("local_shadowing")
    manifest = next(
        item for item in envelope["documents"] if item["path"] == "Cargo.toml"
    )
    manifest["content"] = manifest["content"].replace(
        'edition = "2024"', 'edition = "2024"\nbuild = "build.rs"'
    )
    manifest["sha256"] = (
        f"sha256:{hashlib.sha256(manifest['content'].encode()).hexdigest()}"
    )
    with pytest.raises(RustCompilerSnapshotError, match="build scripts"):
        load_rust_compiler_snapshot(_payload(envelope), source)

    envelope = _envelope("local_shadowing")
    lock = next(item for item in envelope["documents"] if item["path"] == "Cargo.lock")
    lock["content"] += '\nsource = "registry+https://example.invalid"\n'
    lock["sha256"] = f"sha256:{hashlib.sha256(lock['content'].encode()).hexdigest()}"
    with pytest.raises(RustCompilerSnapshotError):
        load_rust_compiler_snapshot(_payload(envelope), source)


def test_rejects_stale_target_source():
    envelope = _envelope("local_shadowing")
    with pytest.raises(RustCompilerSnapshotError, match="stale"):
        load_rust_compiler_snapshot(_payload(envelope), _source("local_shadowing") + b" ")


def test_rejects_missing_project_document_entry():
    envelope = _envelope("cross_file")
    envelope["documents"] = [
        item for item in envelope["documents"] if item["path"] != "src/util.rs"
    ]

    with pytest.raises(RustCompilerSnapshotError, match="document entry is missing"):
        load_rust_compiler_snapshot(_payload(envelope), _source("cross_file"))


def test_rejects_duplicate_document_path_and_sha_mismatch():
    envelope = _envelope("local_shadowing")
    envelope["documents"].append(copy.deepcopy(envelope["documents"][0]))
    with pytest.raises(RustCompilerSnapshotError, match="duplicate"):
        load_rust_compiler_snapshot(_payload(envelope), _source("local_shadowing"))

    envelope = _envelope("local_shadowing")
    envelope["documents"][0]["content"] += " "
    with pytest.raises(RustCompilerSnapshotError, match="hash"):
        load_rust_compiler_snapshot(_payload(envelope), _source("local_shadowing"))


def test_rejects_unsafe_document_paths():
    for path in ("/absolute.rs", "../outside.rs", "src/../main.rs"):
        envelope = _envelope("local_shadowing")
        envelope["documents"][0]["path"] = path
        with pytest.raises(RustCompilerSnapshotError):
            load_rust_compiler_snapshot(_payload(envelope), _source("local_shadowing"))


def test_rejects_wrong_version_encoding_and_non_placeholder_root():
    for key, value in (
        ("rust_analyzer_version", "1.99.0"),
        ("positionEncoding", "utf-8"),
        ("version", "0.6.0"),
        ("projectRoot", "file:///home/operator/project"),
    ):
        envelope = _envelope("local_shadowing")
        if key == "rust_analyzer_version":
            envelope[key] = value
        else:
            metadata = next(
                row
                for row in envelope["lsif"]
                if row.get("label") == "metaData"
            )
            metadata[key] = value
        with pytest.raises(RustCompilerSnapshotError):
            load_rust_compiler_snapshot(_payload(envelope), _source("local_shadowing"))


def test_rejects_lsif_metadata_not_first_and_extra_record_fields():
    envelope = _envelope("local_shadowing")
    envelope["lsif"][0], envelope["lsif"][1] = (
        envelope["lsif"][1],
        envelope["lsif"][0],
    )
    with pytest.raises(RustCompilerSnapshotError, match="metadata must be first"):
        load_rust_compiler_snapshot(_payload(envelope), _source("local_shadowing"))

    envelope = _envelope("local_shadowing")
    envelope["lsif"][1]["extra"] = None
    with pytest.raises(RustCompilerSnapshotError, match="record fields"):
        load_rust_compiler_snapshot(_payload(envelope), _source("local_shadowing"))


def test_rejects_envelope_and_lsif_metadata_version_mismatch():
    envelope = _envelope("local_shadowing")
    metadata = envelope["lsif"][0]
    metadata["toolInfo"]["version"] = "1.100.1"

    with pytest.raises(RustCompilerSnapshotError, match="version"):
        load_rust_compiler_snapshot(_payload(envelope), _source("local_shadowing"))


def test_rejects_duplicate_ids_unknown_labels_and_unknown_edge_ids():
    envelope = _envelope("local_shadowing")
    envelope["lsif"][-1]["id"] = envelope["lsif"][0]["id"]
    with pytest.raises(RustCompilerSnapshotError, match="duplicate LSIF id"):
        load_rust_compiler_snapshot(_payload(envelope), _source("local_shadowing"))

    envelope = _envelope("local_shadowing")
    envelope["lsif"][-1]["label"] = "unknownLabel"
    with pytest.raises(RustCompilerSnapshotError, match="allowlist"):
        load_rust_compiler_snapshot(_payload(envelope), _source("local_shadowing"))

    envelope = _envelope("local_shadowing")
    next_edge = next(row for row in envelope["lsif"] if row.get("label") == "next")
    next_edge["inV"] = 999999
    with pytest.raises(RustCompilerSnapshotError, match="unknown id"):
        load_rust_compiler_snapshot(_payload(envelope), _source("local_shadowing"))


def test_rejects_multiple_definitions_for_one_reference():
    envelope = _envelope("cross_file")
    rows = envelope["lsif"]
    vertices = {row["id"]: row for row in rows if row.get("type") == "vertex"}
    target_id = _target_document_id(envelope)
    source = _source("cross_file")
    double_range = _reference_range(envelope, source, "double")
    range_id = double_range["id"]
    result_set = next(
        row["inV"]
        for row in rows
        if row.get("label") == "next" and row.get("outV") == range_id
    )
    definition_result = next(
        row["inV"]
        for row in rows
        if row.get("label") == "textDocument/definition"
        and row.get("outV") == result_set
    )
    definition_item = next(
        row
        for row in rows
        if row.get("label") == "item"
        and row.get("outV") == definition_result
    )
    document_id = definition_item["document"]
    other_range = next(
        range_id
        for row in rows
        if row.get("label") == "contains" and row.get("outV") == document_id
        for range_id in row["inVs"]
        if range_id not in definition_item["inVs"]
    )
    definition_item["inVs"].append(other_range)

    with pytest.raises(RustCompilerSnapshotError, match="exactly one definition range"):
        load_rust_compiler_snapshot(_payload(envelope), source)
    assert target_id in vertices


def test_rejects_utf16_surrogate_interior_and_out_of_range_positions():
    source = _source("local_shadowing")
    envelope = _envelope("local_shadowing")
    value_range = _reference_range(envelope, source, "𐐀value")
    value_range["start"]["character"] += 1
    with pytest.raises(RustCompilerSnapshotError, match="surrogate pair"):
        load_rust_compiler_snapshot(_payload(envelope), source)

    envelope = _envelope("local_shadowing")
    count_range = _reference_range(envelope, source, "count")
    count_range["start"]["character"] += 1000
    count_range["end"]["character"] += 1000
    with pytest.raises(RustCompilerSnapshotError, match="outside"):
        load_rust_compiler_snapshot(_payload(envelope), source)


def test_rejects_end_before_start_and_non_integer_ids():
    source = _source("local_shadowing")
    envelope = _envelope("local_shadowing")
    count_range = _reference_range(envelope, source, "count")
    count_range["end"]["character"] = count_range["start"]["character"] - 1
    with pytest.raises(RustCompilerSnapshotError):
        load_rust_compiler_snapshot(_payload(envelope), source)

    envelope = _envelope("local_shadowing")
    envelope["lsif"][0]["id"] = True
    with pytest.raises(RustCompilerSnapshotError):
        load_rust_compiler_snapshot(_payload(envelope), source)


def test_rejects_wrong_top_level_shape_and_non_strict_json():
    envelope = _envelope("local_shadowing")
    envelope["extra"] = None
    with pytest.raises(RustCompilerSnapshotError):
        load_rust_compiler_snapshot(_payload(envelope), _source("local_shadowing"))

    envelope = _envelope("local_shadowing")
    envelope["profile"] = "wrong/profile"
    with pytest.raises(RustCompilerSnapshotError):
        load_rust_compiler_snapshot(_payload(envelope), _source("local_shadowing"))

    envelope = _envelope("local_shadowing")
    del envelope["target"]
    with pytest.raises(RustCompilerSnapshotError):
        load_rust_compiler_snapshot(_payload(envelope), _source("local_shadowing"))

    for raw in (
        b'{"profile":"one","profile":"two"}',
        b'{"profile":NaN}',
        b'{"profile":1e999}',
    ):
        with pytest.raises(RustCompilerSnapshotError):
            load_rust_compiler_snapshot(raw, _source("local_shadowing"))


def test_rejects_oversized_envelope():
    with pytest.raises(RustCompilerSnapshotError):
        load_rust_compiler_snapshot(
            b"x" * (MAX_REPORT_BYTES + 1), _source("local_shadowing")
        )
