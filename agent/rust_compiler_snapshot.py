"""Read pinned rust-analyzer LSIF metadata without launching compiler tools."""

from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from dataclasses import dataclass
from itertools import pairwise
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse

from agent.lexical_bindings import (
    MAX_REPORT_BYTES,
    Binding,
    ByteSpan,
    LexicalBindingReport,
    Reference,
)

PROFILE = "mumei.rust-compiler-bindings/v1"
ENVELOPE_PROFILE = "mumei.rust-analyzer-lsif-envelope/v1"
ALLOWED_RUST_ANALYZER_VERSIONS = frozenset(
    {"1.100.0 (0ef1bc3 2026-11-09)"}
)
ALLOWED_LSIF_LABELS = frozenset(
    {
        "contains",
        "definitionResult",
        "document",
        "foldingRangeResult",
        "hoverResult",
        "item",
        "metaData",
        "moniker",
        "next",
        "packageInformation",
        "range",
        "referenceResult",
        "resultSet",
        "textDocument/definition",
        "textDocument/foldingRange",
        "textDocument/hover",
        "textDocument/references",
    }
)

_LEXICAL_PROFILE = "mumei.rust-lexical-bindings/v1"
_SOURCE_HASH = re.compile(r"(?:sha256:)?([0-9a-f]{64})\Z")
_DOCUMENT_HASH = re.compile(r"sha256:([0-9a-f]{64})\Z")
_UNSUPPORTED_GAPS = frozenset(
    {"macro_invocation", "macro_definition", "conditional_compilation"}
)
_STATUSES = (
    "external",
    "cross_file",
    "agree",
    "disagree",
    "lexical_unresolved",
    "lexical_missing",
)
_DEPENDENCY_TABLES = frozenset(
    {"dependencies", "dev-dependencies", "build-dependencies"}
)
_ENVELOPE_KEYS = {
    "profile",
    "rust_analyzer_version",
    "target",
    "documents",
    "lsif",
}
_VERTEX_FIELDS = {
    "metaData": {
        "id",
        "type",
        "label",
        "positionEncoding",
        "projectRoot",
        "toolInfo",
        "version",
    },
    "document": {"id", "type", "label", "uri", "languageId"},
    "range": {"id", "type", "label", "start", "end"},
    "resultSet": {"id", "type", "label"},
    "definitionResult": {"id", "type", "label"},
    "referenceResult": {"id", "type", "label"},
    "hoverResult": {"id", "type", "label", "result"},
    "foldingRangeResult": {"id", "type", "label", "result"},
    "moniker": {
        "id",
        "type",
        "label",
        "identifier",
        "kind",
        "scheme",
        "unique",
    },
    "packageInformation": {
        "id",
        "type",
        "label",
        "manager",
        "name",
        "version",
    },
}
_SIMPLE_EDGE_LABELS = frozenset(
    {
        "moniker",
        "next",
        "packageInformation",
        "textDocument/definition",
        "textDocument/foldingRange",
        "textDocument/hover",
        "textDocument/references",
    }
)


class RustCompilerSnapshotError(ValueError):
    """Rust compiler metadata is missing, stale, or inconsistent."""


@dataclass(frozen=True)
class RustCompilerReference:
    span: ByteSpan
    name: str
    resolution: str
    declaration: ByteSpan | None = None
    definition_path: str | None = None
    definition_span: ByteSpan | None = None
    moniker: str | None = None


@dataclass(frozen=True)
class RustCompilerSnapshot:
    rust_analyzer_version: str
    source_sha256: str
    references: tuple[RustCompilerReference, ...]


def _require(condition: bool, message: str = "invalid Rust compiler snapshot") -> None:
    if not condition:
        raise RustCompilerSnapshotError(message)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(_: str) -> Any:
    raise RustCompilerSnapshotError("non-standard JSON value")


def _finite_float(value: str) -> float:
    parsed = float(value)
    _require(math.isfinite(parsed), "non-finite JSON number")
    return parsed


def _decode_json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
        parse_float=_finite_float,
    )


def _canonical_source_hash(value: Any) -> str | None:
    if type(value) is not str:
        return None
    match = _SOURCE_HASH.fullmatch(value)
    return None if match is None else f"sha256:{match.group(1)}"


def _safe_project_path(value: Any) -> str:
    _require(type(value) is str and bool(value))
    _require("\\" not in value and "\x00" not in value)
    _require(not re.match(r"^[A-Za-z]:", value))
    path = PurePosixPath(value)
    _require(not path.is_absolute() and path.as_posix() == value)
    _require(all(part not in {"", ".", ".."} for part in value.split("/")))
    return value


def _document_location(uri: Any) -> tuple[str, str | None]:
    _require(type(uri) is str)
    parsed = urlparse(uri)
    _require(
        parsed.scheme == "file"
        and not parsed.netloc
        and not parsed.query
        and not parsed.fragment
    )
    path = unquote(parsed.path)
    if path == "/project":
        return "project", None
    if path.startswith("/project/"):
        return "project", _safe_project_path(path[len("/project/") :])
    if path == "/sysroot":
        return "sysroot", None
    if path.startswith("/sysroot/"):
        relative = path[len("/sysroot/") :]
        _require(bool(relative))
        return "sysroot", _safe_project_path(relative)
    raise RustCompilerSnapshotError("LSIF document URI is outside normalized roots")


def _validate_record(row: Any) -> None:
    _require(type(row) is dict)
    _require(type(row.get("type")) is str and row["type"] in {"vertex", "edge"})
    label = row.get("label")
    _require(
        type(label) is str and label in ALLOWED_LSIF_LABELS,
        "LSIF label is not in the pinned allowlist",
    )
    if row["type"] == "vertex":
        expected = _VERTEX_FIELDS.get(label)
        _require(expected is not None)
        allowed_fields = [expected]
        if label == "packageInformation":
            allowed_fields.append(expected | {"repository"})
    else:
        base = {"id", "type", "label", "outV"}
        if label in _SIMPLE_EDGE_LABELS:
            expected = base | {"inV"}
            allowed_fields = [expected]
        elif label == "contains":
            expected = base | {"inVs"}
            allowed_fields = [expected]
        elif label == "item":
            expected = base | {"document", "inVs"}
            allowed_fields = [expected, expected | {"property"}]
        else:
            raise RustCompilerSnapshotError("LSIF edge label is not supported")
    _require(set(row) in allowed_fields, "LSIF record fields do not match the pinned schema")
    _require(type(row["id"]) is int and row["id"] >= 0)

    if row["type"] == "vertex":
        if label == "metaData":
            _require(type(row["positionEncoding"]) is str)
            _require(type(row["projectRoot"]) is str)
            _require(type(row["version"]) is str)
            info = row["toolInfo"]
            _require(type(info) is dict and set(info) == {"name", "version"})
            _require(type(info["name"]) is str and type(info["version"]) is str)
        elif label == "document":
            _require(type(row["uri"]) is str and type(row["languageId"]) is str)
            _require(row["languageId"] == "rust")
        elif label == "range":
            for position in (row["start"], row["end"]):
                _require(type(position) is dict and set(position) == {"line", "character"})
                _require(
                    type(position["line"]) is int
                    and type(position["character"]) is int
                    and position["line"] >= 0
                    and position["character"] >= 0
                )
            _require(
                (row["end"]["line"], row["end"]["character"])
                >= (row["start"]["line"], row["start"]["character"])
            )
        elif label == "moniker":
            _require(
                type(row["identifier"]) is str
                and bool(row["identifier"])
                and row["kind"] in {"export", "import"}
                and row["scheme"] == "rust-analyzer"
                and row["unique"] == "scheme"
            )
        elif label == "packageInformation":
            _require(
                type(row["manager"]) is str
                and type(row["name"]) is str
                and type(row["version"]) is str
            )
            if "repository" in row:
                repository = row["repository"]
                _require(
                    type(repository) is dict and set(repository) == {"type", "url"}
                )
                _require(
                    repository["type"] == "git" and type(repository["url"]) is str
                )
    else:
        for key in ("outV", "inV", "document"):
            if key in row:
                _require(type(row[key]) is int and row[key] >= 0)
        if "inVs" in row:
            _require(type(row["inVs"]) is list)
            _require(all(type(identifier) is int and identifier >= 0 for identifier in row["inVs"]))
            _require(len(set(row["inVs"])) == len(row["inVs"]))
        if "property" in row:
            _require(row["property"] in {"definitions", "references"})


def _validate_lsif(rows: Any) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    _require(type(rows) is list and bool(rows))
    _require(
        type(rows[0]) is dict
        and rows[0].get("type") == "vertex"
        and rows[0].get("label") == "metaData",
        "LSIF metadata must be first",
    )
    all_rows: dict[int, dict[str, Any]] = {}
    vertices: dict[int, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    metadata_count = 0
    for row in rows:
        _validate_record(row)
        identifier = row["id"]
        _require(identifier not in all_rows, "duplicate LSIF id")
        all_rows[identifier] = row
        if row["type"] == "vertex":
            vertices[identifier] = row
            metadata_count += row["label"] == "metaData"
        else:
            edges.append(row)
    _require(metadata_count == 1, "LSIF metadata is missing or duplicated")

    def _vertex(identifier: int, label: str | tuple[str, ...]) -> None:
        _require(identifier in vertices, "LSIF edge references an unknown vertex")
        labels = (label,) if type(label) is str else label
        _require(vertices[identifier]["label"] in labels, "LSIF edge endpoint has the wrong label")

    for edge in edges:
        label = edge["label"]
        _require(edge["outV"] in vertices, "LSIF edge references an unknown id")
        if "inV" in edge:
            _require(edge["inV"] in vertices, "LSIF edge references an unknown id")
        if "document" in edge:
            _vertex(edge["document"], "document")
        if "inVs" in edge:
            _require(
                all(identifier in vertices for identifier in edge["inVs"]),
                "LSIF edge references an unknown id",
            )

        if label == "contains":
            _vertex(edge["outV"], "document")
            for identifier in edge["inVs"]:
                _vertex(identifier, "range")
        elif label == "item":
            _vertex(edge["outV"], ("definitionResult", "referenceResult"))
            for identifier in edge["inVs"]:
                _vertex(identifier, "range")
            result_label = vertices[edge["outV"]]["label"]
            if result_label == "definitionResult":
                _require("property" not in edge)
            else:
                _require(edge.get("property") in {"definitions", "references"})
        elif label == "next":
            _vertex(edge["outV"], "range")
            _vertex(edge["inV"], "resultSet")
        elif label == "moniker":
            _vertex(edge["outV"], "resultSet")
            _vertex(edge["inV"], "moniker")
        elif label == "packageInformation":
            _vertex(edge["outV"], "moniker")
            _vertex(edge["inV"], "packageInformation")
        elif label == "textDocument/definition":
            _vertex(edge["outV"], "resultSet")
            _vertex(edge["inV"], "definitionResult")
        elif label == "textDocument/references":
            _vertex(edge["outV"], "resultSet")
            _vertex(edge["inV"], "referenceResult")
        elif label == "textDocument/hover":
            _vertex(edge["outV"], "resultSet")
            _vertex(edge["inV"], "hoverResult")
        elif label == "textDocument/foldingRange":
            _vertex(edge["outV"], "document")
            _vertex(edge["inV"], "foldingRangeResult")

    return vertices, edges


def _line_table(text: str) -> tuple[list[str], list[int]]:
    lines: list[str] = []
    starts: list[int] = []
    char_start = 0
    byte_start = 0
    for match in re.finditer(r"\r\n|\r|\n", text):
        line = text[char_start : match.start()]
        lines.append(line)
        starts.append(byte_start)
        byte_start += len(line.encode("utf-8")) + len(match.group().encode("utf-8"))
        char_start = match.end()
    lines.append(text[char_start:])
    starts.append(byte_start)
    return lines, starts


def _utf16_offset_to_byte(
    lines: list[str], line_starts: list[int], line: int, character: int
) -> int:
    _require(0 <= line < len(lines), "LSIF line is outside its document")
    _require(type(character) is int and character >= 0)
    units = 0
    byte_offset = 0
    for value in lines[line]:
        if units == character:
            return line_starts[line] + byte_offset
        width = 2 if ord(value) > 0xFFFF else 1
        _require(
            not (units < character < units + width),
            "LSIF position is inside a UTF-16 surrogate pair",
        )
        units += width
        byte_offset += len(value.encode("utf-8"))
    _require(units == character, "LSIF character is outside its line")
    return line_starts[line] + byte_offset


def _range_span(
    value: dict[str, Any], text: str, lines: list[str], line_starts: list[int]
) -> ByteSpan:
    start = _utf16_offset_to_byte(
        lines, line_starts, value["start"]["line"], value["start"]["character"]
    )
    end = _utf16_offset_to_byte(
        lines, line_starts, value["end"]["line"], value["end"]["character"]
    )
    _require(end >= start, "LSIF range ends before it starts")
    _require(
        end <= line_starts[-1] + len(lines[-1].encode("utf-8")),
        "LSIF range is outside its document",
    )
    return ByteSpan(start, end)


def _valid_rust_identifier(name: str) -> bool:
    identifier = name.removeprefix("r#")
    return bool(identifier) and identifier != "_" and identifier.isidentifier()


def _reject_project_dependencies(manifest_bytes: bytes, lock_bytes: bytes) -> None:
    manifest = tomllib.loads(manifest_bytes.decode("utf-8"))
    package = manifest.get("package")
    _require(type(package) is dict, "Cargo.toml must define one root package")
    _require("build" not in package, "Cargo build scripts are outside the project boundary")
    _require("workspace" not in package, "Cargo workspace members are outside the project boundary")
    library = manifest.get("lib", {})
    _require(type(library) is dict)
    for key in ("proc-macro", "proc_macro"):
        if key in library:
            _require(type(library[key]) is bool)
            _require(not library[key], "proc-macro projects are outside the project boundary")
    for key in ("crate-type", "crate_type"):
        if key in library:
            crate_types = library[key]
            _require(
                type(crate_types) is list and all(type(kind) is str for kind in crate_types)
            )
            _require(
                "proc-macro" not in crate_types,
                "proc-macro projects are outside the project boundary",
            )

    workspace = manifest.get("workspace", {})
    _require(type(workspace) is dict)
    members = workspace.get("members", [])
    _require(type(members) is list and all(type(member) is str for member in members))
    _require(
        all(PurePosixPath(member).as_posix() == "." for member in members),
        "Cargo workspace members are outside the project boundary",
    )

    for table in (manifest, workspace):
        _require(
            not any(key in table for key in _DEPENDENCY_TABLES),
            "Cargo dependencies are outside the project boundary",
        )
    targets = manifest.get("target", {})
    _require(type(targets) is dict)
    for target in targets.values():
        _require(type(target) is dict)
        _require(
            not any(key in target for key in _DEPENDENCY_TABLES),
            "target-specific Cargo dependencies are outside the project boundary",
        )

    lock = tomllib.loads(lock_bytes.decode("utf-8"))
    packages = lock.get("package")
    if packages is None:
        packages = lock.get("packages")
    _require(type(packages) is list, "Cargo.lock package list is unavailable")
    for lock_package in packages:
        _require(type(lock_package) is dict and "source" not in lock_package)


def _reference_moniker(
    result_set: int,
    edges_by_out: dict[int, list[dict[str, Any]]],
    vertices: dict[int, dict[str, Any]],
) -> str:
    monikers = [
        vertices[edge["inV"]]
        for edge in edges_by_out.get(result_set, [])
        if edge["label"] == "moniker"
    ]
    imports = [value for value in monikers if value["kind"] == "import"]
    candidates = imports if imports else monikers
    _require(len(candidates) == 1, "external LSIF reference has no unique moniker")
    identifier = candidates[0]["identifier"]
    _require(type(identifier) is str and bool(identifier))
    return identifier


def load_rust_compiler_snapshot(
    envelope_bytes: bytes,
    source_bytes: bytes,
) -> RustCompilerSnapshot:
    """Read a pinned LSIF envelope; launch no compiler or language server."""
    try:
        _require(type(envelope_bytes) is bytes and len(envelope_bytes) <= MAX_REPORT_BYTES)
        _require(type(source_bytes) is bytes)
        source_bytes.decode("utf-8")
        data = _decode_json(envelope_bytes)
        _require(type(data) is dict and set(data) == _ENVELOPE_KEYS)
        _require(data["profile"] == ENVELOPE_PROFILE)
        version = data["rust_analyzer_version"]
        _require(
            type(version) is str and version in ALLOWED_RUST_ANALYZER_VERSIONS,
            "rust-analyzer version is not allowed",
        )
        target_path = _safe_project_path(data["target"])

        document_rows = data["documents"]
        _require(type(document_rows) is list)
        document_contents: dict[str, bytes] = {}
        for document in document_rows:
            _require(
                type(document) is dict
                and set(document) == {"path", "sha256", "content"}
            )
            path = _safe_project_path(document["path"])
            _require(path not in document_contents, "duplicate project document path")
            content = document["content"]
            _require(type(content) is str)
            content_bytes = content.encode("utf-8")
            digest = document["sha256"]
            _require(
                type(digest) is str and _DOCUMENT_HASH.fullmatch(digest) is not None
            )
            _require(
                digest == f"sha256:{hashlib.sha256(content_bytes).hexdigest()}",
                "project document hash does not match its content",
            )
            document_contents[path] = content_bytes
        _require("Cargo.toml" in document_contents)
        _require("Cargo.lock" in document_contents)
        _require(target_path in document_contents, "target document is missing")
        _require(
            document_contents[target_path] == source_bytes,
            "target source is stale",
        )
        _reject_project_dependencies(
            document_contents["Cargo.toml"], document_contents["Cargo.lock"]
        )
        _require(
            not any(PurePosixPath(path).name == "build.rs" for path in document_contents),
            "Cargo build scripts are outside the project boundary",
        )

        vertices, edges = _validate_lsif(data["lsif"])
        metadata = data["lsif"][0]
        _require(metadata["positionEncoding"] == "utf-16")
        _require(metadata["projectRoot"] == "file:///project")
        _require(metadata["version"] == "0.5.0")
        _require(metadata["toolInfo"]["name"] == "rust-analyzer")
        _require(
            metadata["toolInfo"]["version"] == version,
            "envelope version differs from LSIF metadata",
        )

        document_locations: dict[int, tuple[str, str | None]] = {}
        project_document_ids: dict[str, int] = {}
        for identifier, vertex in vertices.items():
            if vertex["label"] != "document":
                continue
            location = _document_location(vertex["uri"])
            _require(location[0] != "project" or location[1] is not None)
            if location[0] == "project":
                path = location[1]
                assert path is not None
                _require(path in document_contents, "LSIF project document entry is missing")
                _require(path not in project_document_ids, "duplicate LSIF project document URI")
                project_document_ids[path] = identifier
            document_locations[identifier] = location
        _require(target_path in project_document_ids, "target is not an LSIF document")
        target_document_id = project_document_ids[target_path]

        range_owners: dict[int, set[int]] = {}
        edges_by_out: dict[int, list[dict[str, Any]]] = {}
        item_edges_by_out: dict[int, list[dict[str, Any]]] = {}
        next_by_range: dict[int, list[dict[str, Any]]] = {}
        definitions_by_result_set: dict[int, list[dict[str, Any]]] = {}
        for edge in edges:
            edges_by_out.setdefault(edge["outV"], []).append(edge)
            if edge["label"] == "contains":
                for range_id in edge["inVs"]:
                    range_owners.setdefault(range_id, set()).add(edge["outV"])
            elif edge["label"] == "item":
                item_edges_by_out.setdefault(edge["outV"], []).append(edge)
            elif edge["label"] == "next":
                next_by_range.setdefault(edge["outV"], []).append(edge)
            elif edge["label"] == "textDocument/definition":
                definitions_by_result_set.setdefault(edge["outV"], []).append(edge)

        line_tables: dict[str, tuple[str, list[str], list[int]]] = {}

        def document_table(path: str) -> tuple[str, list[str], list[int]]:
            if path not in line_tables:
                text = document_contents[path].decode("utf-8")
                line_tables[path] = (text, *_line_table(text))
            return line_tables[path]

        range_ids = {
            identifier
            for identifier, vertex in vertices.items()
            if vertex["label"] == "range"
        }
        _require(set(range_owners) == range_ids, "LSIF ranges are not contained by documents")
        for range_id, document_ids in range_owners.items():
            _require(len(document_ids) == 1, "LSIF range belongs to multiple documents")
            document_id = next(iter(document_ids))
            document_location = document_locations[document_id]
            if document_location[0] == "project":
                path = document_location[1]
                assert path is not None
                _range_span(vertices[range_id], *document_table(path))

        for edge in edges:
            if edge["label"] != "item":
                continue
            document_id = edge["document"]
            for range_id in edge["inVs"]:
                _require(
                    range_owners.get(range_id) == {document_id},
                    "LSIF item range does not belong to its document",
                )

        target_text, target_lines, target_line_starts = document_table(target_path)
        raw_references: list[RustCompilerReference] = []
        seen_reference_ids: set[int] = set()
        for edge in edges:
            if (
                edge["label"] != "item"
                or edge.get("property") != "references"
                or edge["document"] != target_document_id
            ):
                continue
            for range_id in edge["inVs"]:
                _require(range_id not in seen_reference_ids, "duplicate LSIF reference range")
                seen_reference_ids.add(range_id)
                reference_range = vertices[range_id]
                reference_span = _range_span(
                    reference_range, target_text, target_lines, target_line_starts
                )
                name = source_bytes[reference_span.start : reference_span.end].decode("utf-8")
                _require(
                    _valid_rust_identifier(name),
                    "LSIF reference is not a Rust identifier",
                )
                next_edges = next_by_range.get(range_id, [])
                _require(len(next_edges) == 1, "LSIF reference has no unique result set")
                result_set = next_edges[0]["inV"]
                definition_edges = definitions_by_result_set.get(result_set, [])
                _require(
                    len(definition_edges) == 1,
                    "LSIF reference does not have exactly one definition",
                )
                definition_result = definition_edges[0]["inV"]
                definition_items = [
                    item
                    for item in item_edges_by_out.get(definition_result, [])
                    if "property" not in item
                ]
                definitions = [
                    (item["document"], definition_range_id)
                    for item in definition_items
                    for definition_range_id in item["inVs"]
                ]
                _require(
                    len(definitions) == 1,
                    "LSIF reference does not have exactly one definition range",
                )
                definition_document_id, definition_range_id = definitions[0]
                definition_location = document_locations[definition_document_id]
                import_monikers = [
                    vertices[edge["inV"]]
                    for edge in edges_by_out.get(result_set, [])
                    if edge["label"] == "moniker"
                    and vertices[edge["inV"]]["kind"] == "import"
                ]

                if import_monikers or definition_location[0] == "sysroot":
                    moniker = _reference_moniker(result_set, edges_by_out, vertices)
                    raw_references.append(
                        RustCompilerReference(
                            reference_span,
                            name,
                            "external",
                            moniker=moniker,
                        )
                    )
                    continue

                definition_path = definition_location[1]
                _require(definition_location[0] == "project" and definition_path is not None)
                definition_text, definition_lines, definition_line_starts = document_table(
                    definition_path
                )
                definition_span = _range_span(
                    vertices[definition_range_id],
                    definition_text,
                    definition_lines,
                    definition_line_starts,
                )
                if definition_path == target_path:
                    raw_references.append(
                        RustCompilerReference(
                            reference_span,
                            name,
                            "local",
                            declaration=definition_span,
                        )
                    )
                else:
                    raw_references.append(
                        RustCompilerReference(
                            reference_span,
                            name,
                            "cross_file",
                            definition_path=definition_path,
                            definition_span=definition_span,
                        )
                    )

        raw_references.sort(key=lambda item: (item.span.start, item.span.end))
        for previous, current in pairwise(raw_references):
            _require(previous.span.end <= current.span.start, "LSIF reference ranges overlap")

        source_hash = f"sha256:{hashlib.sha256(source_bytes).hexdigest()}"
        return RustCompilerSnapshot(version, source_hash, tuple(raw_references))
    except RustCompilerSnapshotError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, UnicodeError, RecursionError):
        raise RustCompilerSnapshotError(
            "Rust compiler snapshot unavailable or inconsistent"
        ) from None


def compare_with_lexical(
    snapshot: RustCompilerSnapshot, report: LexicalBindingReport
) -> dict[str, Any]:
    """Compare local compiler declarations with same-source lexical bindings."""
    try:
        _require(type(snapshot) is RustCompilerSnapshot)
        _require(type(report) is LexicalBindingReport)
        _require(report.profile == _LEXICAL_PROFILE, "wrong lexical report profile")
        _require(
            _canonical_source_hash(report.source_sha256) == snapshot.source_sha256,
            "lexical report source does not match compiler snapshot",
        )
        _require(
            not any(gap.reason in _UNSUPPORTED_GAPS for gap in report.gaps),
            "Rust lexical gaps prevent compiler comparison",
        )

        references_by_span: dict[ByteSpan, list[Reference]] = {}
        for lexical_reference in report.references:
            references_by_span.setdefault(lexical_reference.span, []).append(
                lexical_reference
            )
        unresolved_by_span = {item.span: item for item in report.unresolved}
        _require(len(unresolved_by_span) == len(report.unresolved))
        _require(not set(references_by_span) & set(unresolved_by_span))
        bindings_by_id: dict[str, Binding] = {
            binding.id: binding for binding in report.bindings
        }

        summary = {status: 0 for status in _STATUSES}
        compared: list[dict[str, Any]] = []
        for reference in snapshot.references:
            item: dict[str, Any] = {
                "span": reference.span.to_dict(),
                "name": reference.name,
            }
            if reference.resolution == "external":
                _require(reference.moniker is not None)
                item["moniker"] = reference.moniker
                status = "external"
            elif reference.resolution == "cross_file":
                _require(
                    reference.definition_path is not None
                    and reference.definition_span is not None
                )
                item["definition"] = {
                    "path": reference.definition_path,
                    "span": reference.definition_span.to_dict(),
                }
                status = "cross_file"
            else:
                _require(
                    reference.resolution == "local" and reference.declaration is not None
                )
                item["declaration"] = reference.declaration.to_dict()
                if reference.span in references_by_span:
                    status = "agree"
                    for lexical_reference in references_by_span[reference.span]:
                        binding = bindings_by_id.get(lexical_reference.binding_id)
                        if binding is None or binding.span != reference.declaration:
                            status = "disagree"
                            break
                elif reference.span in unresolved_by_span:
                    status = "lexical_unresolved"
                    item["reason"] = unresolved_by_span[reference.span].reason
                else:
                    status = "lexical_missing"
            item["status"] = status
            summary[status] += 1
            compared.append(item)

        return {
            "profile": PROFILE,
            "rust_analyzer_version": snapshot.rust_analyzer_version,
            "source_sha256": snapshot.source_sha256,
            "references": compared,
            "summary": summary,
        }
    except RustCompilerSnapshotError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError):
        raise RustCompilerSnapshotError(
            "Rust compiler comparison unavailable or inconsistent"
        ) from None
