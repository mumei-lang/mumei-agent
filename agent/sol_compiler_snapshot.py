"""Read operator-produced Solidity compiler metadata without launching tools."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from agent.lexical_bindings import (
    MAX_REPORT_BYTES,
    ByteSpan,
    LexicalBindingReport,
    Reference,
)

ALLOWED_SOLC_VERSIONS = frozenset({"0.8.39+commit.ce47f2c8"})
ENVELOPE_PROFILE = "mumei.solc-standard-json-envelope/v1"
PROFILE = "mumei.sol-compiler-bindings/v1"
_LEXICAL_PROFILE = "mumei.sol-lexical-bindings/v1"
_SOLC_VERSION = re.compile(
    r"(?m)^\s*Version:\s*(\d+\.\d+\.\d+\+commit\.[0-9a-fA-F]+)"
    r"(?:\.[^\r\n]*)?\s*$"
)
_LOCATION = re.compile(r"([0-9]+):([0-9]+):([0-9]+)\Z")
_SOURCE_HASH = re.compile(r"(?:sha256:)?([0-9a-f]{64})\Z")
_STATUSES = (
    "builtin",
    "agree",
    "disagree",
    "lexical_unresolved",
    "lexical_missing",
)


class SolCompilerSnapshotError(ValueError):
    """Solidity compiler metadata is missing, stale, or inconsistent."""


@dataclass(frozen=True)
class CompilerReference:
    span: ByteSpan
    name: str
    declaration: ByteSpan | None
    builtin: bool


@dataclass(frozen=True)
class SolCompilerSnapshot:
    compiler_version: str
    source_sha256: str
    references: tuple[CompilerReference, ...]


def _require(
    condition: bool, message: str = "invalid Solidity compiler snapshot"
) -> None:
    if not condition:
        raise SolCompilerSnapshotError(message)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(_: str) -> Any:
    raise SolCompilerSnapshotError("non-standard JSON value")


def _canonical_source_hash(value: Any) -> str | None:
    if type(value) is not str:
        return None
    match = _SOURCE_HASH.fullmatch(value)
    return None if match is None else f"sha256:{match.group(1)}"


def _decode_json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )


def _location_span(value: Any, source_bytes: bytes) -> ByteSpan:
    _require(type(value) is str)
    match = _LOCATION.fullmatch(value)
    _require(match is not None)
    assert match is not None
    start, length, file_index = (int(part) for part in match.groups())
    end = start + length
    _require(file_index == 0 and 0 <= start <= end <= len(source_bytes))
    _require(
        all(
            offset == len(source_bytes) or source_bytes[offset] & 0xC0 != 0x80
            for offset in (start, end)
        )
    )
    return ByteSpan(start, end)


def _ast_nodes(root: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    nodes: list[dict[str, Any]] = []
    stack: list[Any] = [root]
    while stack:
        value = stack.pop()
        if type(value) is dict:
            if "nodeType" in value:
                nodes.append(value)
            stack.extend(value.values())
        elif type(value) is list:
            stack.extend(value)
    return tuple(nodes)


def _compiler_metadata_version(output: dict[str, Any], version: str) -> None:
    contracts = output.get("contracts", {})
    _require(type(contracts) is dict)
    for source_contracts in contracts.values():
        _require(type(source_contracts) is dict)
        for contract in source_contracts.values():
            _require(type(contract) is dict)
            if "metadata" not in contract:
                continue
            metadata = contract["metadata"]
            _require(type(metadata) is str)
            decoded = _decode_json(metadata.encode("utf-8"))
            _require(type(decoded) is dict)
            compiler = decoded.get("compiler")
            _require(type(compiler) is dict and compiler.get("version") == version)


def load_sol_compiler_snapshot(
    envelope: bytes,
    source: str,
    *,
    allowed_versions: Iterable[str] = ALLOWED_SOLC_VERSIONS,
) -> SolCompilerSnapshot:
    """Read a pinned single-file solc AST envelope; launch no compiler."""
    try:
        _require(type(envelope) is bytes and len(envelope) <= MAX_REPORT_BYTES)
        _require(type(source) is str)
        source_bytes = source.encode("utf-8")
        _require(not isinstance(allowed_versions, (str, bytes)))
        versions = frozenset(allowed_versions)
        _require(all(type(version) is str for version in versions))

        data = _decode_json(envelope)
        _require(
            type(data) is dict
            and set(data) == {"profile", "solc_version_output", "input", "output"}
        )
        _require(data["profile"] == ENVELOPE_PROFILE)

        version_output = data["solc_version_output"]
        _require(type(version_output) is str)
        matches = list(_SOLC_VERSION.finditer(version_output))
        _require(len(matches) == 1, "solc version output is not recognized")
        compiler_version = matches[0].group(1)
        _require(compiler_version in versions, "solc version is not allowed")

        input_data = data["input"]
        output_data = data["output"]
        _require(type(input_data) is dict and type(output_data) is dict)
        _require(input_data.get("language") == "Solidity")
        sources = input_data.get("sources")
        _require(type(sources) is dict and len(sources) == 1)
        source_name, source_entry = next(iter(sources.items()))
        _require(
            type(source_name) is str
            and bool(source_name)
            and type(source_entry) is dict
            and source_entry.get("content") == source
        )

        errors = output_data.get("errors", [])
        _require(type(errors) is list)
        for diagnostic in errors:
            _require(
                type(diagnostic) is dict and type(diagnostic.get("severity")) is str
            )
            _require(
                diagnostic["severity"] != "error",
                "solc reported a compilation error",
            )

        _compiler_metadata_version(output_data, compiler_version)

        output_sources = output_data.get("sources")
        _require(type(output_sources) is dict and set(output_sources) == {source_name})
        output_source = output_sources[source_name]
        _require(type(output_source) is dict and type(output_source.get("id")) is int)
        _require(output_source["id"] == 0)
        ast_root = output_source.get("ast")
        _require(type(ast_root) is dict and ast_root.get("nodeType") == "SourceUnit")
        _require(type(ast_root.get("nodes")) is list)
        nodes = _ast_nodes(ast_root)
        _require(all(type(node.get("nodeType")) is str for node in nodes))
        _require(
            not any(
                node["nodeType"] in {"ImportDirective", "InlineAssembly"}
                for node in nodes
            ),
            "imports and inline assembly are unsupported",
        )

        declarations: dict[int, dict[str, Any]] = {}
        for node in nodes:
            identifier = node.get("id")
            if type(identifier) is int and identifier >= 0:
                _require(identifier not in declarations)
                declarations[identifier] = node

        references: list[CompilerReference] = []
        for node in nodes:
            # `IdentifierPath` is the 0.8.39 path form: it carries
            # inheritance specifiers, `using ... for` lists and
            # user-defined type names (the older `UserDefinedTypeName`
            # node no longer appears). A dotted path such as `Lib.S`
            # still resolves atomically to one declaration; the lexical
            # report only records the base segment's reference, so the
            # whole-path span honestly compares as `lexical_missing`.
            if node["nodeType"] not in {"Identifier", "IdentifierPath"}:
                continue
            name = node.get("name")
            referenced = node.get("referencedDeclaration")
            _require(type(name) is str and bool(name))
            _require(
                type(referenced) is int,
                "Identifier has no compiler declaration reference",
            )
            span = _location_span(node.get("src"), source_bytes)
            if referenced < 0:
                references.append(CompilerReference(span, name, None, True))
                continue
            declaration_node = declarations.get(referenced)
            _require(
                declaration_node is not None,
                "compiler declaration reference is missing",
            )
            assert declaration_node is not None
            declaration = _location_span(
                declaration_node.get("nameLocation"), source_bytes
            )
            references.append(CompilerReference(span, name, declaration, False))

        references.sort(
            key=lambda reference: (reference.span.start, reference.span.end)
        )
        digest = hashlib.sha256(source_bytes).hexdigest()
        return SolCompilerSnapshot(
            compiler_version,
            f"sha256:{digest}",
            tuple(references),
        )
    except SolCompilerSnapshotError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError):
        raise SolCompilerSnapshotError(
            "Solidity compiler snapshot unavailable or inconsistent"
        ) from None


def compare_with_lexical(
    snapshot: SolCompilerSnapshot, report: LexicalBindingReport
) -> dict[str, Any]:
    """Compare compiler declaration spans with a same-source lexical report."""
    _require(report.profile == _LEXICAL_PROFILE, "wrong lexical report profile")
    _require(
        _canonical_source_hash(report.source_sha256) == snapshot.source_sha256,
        "lexical report source does not match compiler snapshot",
    )

    references_by_span: dict[ByteSpan, list[Reference]] = {}
    for lexical_reference in report.references:
        references_by_span.setdefault(lexical_reference.span, []).append(
            lexical_reference
        )
    unresolved_by_span = {item.span: item for item in report.unresolved}
    _require(len(unresolved_by_span) == len(report.unresolved))
    _require(not set(references_by_span) & set(unresolved_by_span))
    bindings_by_id = {binding.id: binding for binding in report.bindings}

    summary = {status: 0 for status in _STATUSES}
    compared: list[dict[str, Any]] = []
    for reference in snapshot.references:
        item: dict[str, Any] = {
            "span": reference.span.to_dict(),
            "name": reference.name,
            "declaration": (
                None
                if reference.declaration is None
                else reference.declaration.to_dict()
            ),
            "builtin": reference.builtin,
        }
        if reference.builtin:
            status = "builtin"
        elif reference.span in references_by_span:
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
        "compiler_version": snapshot.compiler_version,
        "source_sha256": snapshot.source_sha256,
        "references": compared,
        "summary": summary,
    }
