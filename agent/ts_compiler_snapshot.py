"""Read operator-produced TypeScript compiler metadata without launching tools."""

from __future__ import annotations

import hashlib
import itertools
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from agent.lexical_bindings import (
    MAX_REPORT_BYTES,
    Binding,
    ByteSpan,
    LexicalBindingReport,
    Reference,
)

ALLOWED_TYPESCRIPT_VERSIONS = frozenset({"5.9.3"})
ENVELOPE_PROFILE = "mumei.tsc-symbol-envelope/v1"
PROFILE = "mumei.ts-compiler-bindings/v1"
COMPILER_OPTIONS = {
    "noEmit": True,
    "strict": True,
    "target": "ES2022",
    "lib": ["lib.es2022.d.ts"],
    "types": [],
    "noResolve": True,
    "jsx": "preserve",
}
_LEXICAL_PROFILE = "mumei.ts-lexical-bindings/v1"
_SOURCE_HASH = re.compile(r"(?:sha256:)?([0-9a-f]{64})\Z")
_STATUSES = (
    "builtin",
    "agree",
    "disagree",
    "lexical_unresolved",
    "lexical_missing",
)
_ENVELOPE_KEYS = {
    "profile",
    "typescript_version",
    "compiler_options",
    "file_name",
    "source",
    "diagnostics",
    "unsupported",
    "references",
}


class TsCompilerSnapshotError(ValueError):
    """TypeScript compiler metadata is missing, stale, or inconsistent."""


@dataclass(frozen=True)
class TsCompilerReference:
    span: ByteSpan
    name: str
    declarations: tuple[ByteSpan, ...]
    library: bool


@dataclass(frozen=True)
class TsCompilerSnapshot:
    compiler_version: str
    source_sha256: str
    references: tuple[TsCompilerReference, ...]


def _require(
    condition: bool, message: str = "invalid TypeScript compiler snapshot"
) -> None:
    if not condition:
        raise TsCompilerSnapshotError(message)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(_: str) -> Any:
    raise TsCompilerSnapshotError("non-standard JSON value")


def _decode_json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )


def _strict_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(
            _strict_equal(left[key], right[key]) for key in left
        )
    if type(left) is list:
        return len(left) == len(right) and all(
            _strict_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return left == right


def _source_boundaries(source: str) -> tuple[bytes, frozenset[int]]:
    source_bytes = source.encode("utf-8")
    boundaries = {0}
    offset = 0
    for character in source:
        offset += len(character.encode("utf-8"))
        boundaries.add(offset)
    return source_bytes, frozenset(boundaries)


def _span(value: Any, source_bytes: bytes, boundaries: frozenset[int]) -> ByteSpan:
    _require(type(value) is dict and set(value) == {"start", "end"})
    start = value["start"]
    end = value["end"]
    _require(type(start) is int and type(end) is int)
    _require(
        0 <= start < end <= len(source_bytes)
        and start in boundaries
        and end in boundaries
    )
    return ByteSpan(start, end)


def _canonical_source_hash(value: Any) -> str | None:
    if type(value) is not str:
        return None
    match = _SOURCE_HASH.fullmatch(value)
    return None if match is None else f"sha256:{match.group(1)}"


def _diagnostics(value: Any) -> None:
    _require(type(value) is list)
    for diagnostic in value:
        _require(
            type(diagnostic) is dict
            and set(diagnostic) == {"category", "code", "message"}
        )
        category = diagnostic["category"]
        _require(
            type(category) is str
            and category in {"error", "warning", "suggestion", "message"}
        )
        _require(type(diagnostic["code"]) is int)
        _require(type(diagnostic["message"]) is str)
        _require(
            category != "error",
            "TypeScript reported a compilation error",
        )


def load_ts_compiler_snapshot(
    envelope: bytes,
    source: str,
    *,
    allowed_versions: Iterable[str] = ALLOWED_TYPESCRIPT_VERSIONS,
) -> TsCompilerSnapshot:
    """Read a pinned single-file TypeScript compiler envelope; launch no compiler."""
    try:
        _require(type(envelope) is bytes and len(envelope) <= MAX_REPORT_BYTES)
        _require(type(source) is str)
        source_bytes, boundaries = _source_boundaries(source)
        _require(not isinstance(allowed_versions, (str, bytes)))
        versions = frozenset(allowed_versions)
        _require(all(type(version) is str for version in versions))

        data = _decode_json(envelope)
        _require(type(data) is dict and set(data) == _ENVELOPE_KEYS)
        _require(data["profile"] == ENVELOPE_PROFILE)

        compiler_version = data["typescript_version"]
        _require(
            type(compiler_version) is str and compiler_version in versions,
            "TypeScript version is not allowed",
        )
        _require(
            _strict_equal(data["compiler_options"], COMPILER_OPTIONS),
            "TypeScript compiler options are not allowed",
        )
        _require(
            type(data["file_name"]) is str
            and data["file_name"] in {"input.ts", "input.tsx"}
        )
        _require(
            type(data["source"]) is str and data["source"] == source,
            "TypeScript compiler source is stale",
        )
        _diagnostics(data["diagnostics"])
        _require(
            type(data["unsupported"]) is list and not data["unsupported"],
            "TypeScript source contains unsupported constructs",
        )

        raw_references = data["references"]
        _require(type(raw_references) is list)
        references: list[TsCompilerReference] = []
        for item in raw_references:
            _require(
                type(item) is dict
                and set(item) == {"span", "name", "declarations", "library"}
            )
            name = item["name"]
            _require(type(name) is str and bool(name))
            encoded_name = name.encode("utf-8")
            reference_span = _span(item["span"], source_bytes, boundaries)
            _require(
                source_bytes[reference_span.start : reference_span.end] == encoded_name
            )
            raw_declarations = item["declarations"]
            _require(
                type(raw_declarations) is list,
                "TypeScript reference declarations are unavailable",
            )
            declaration_spans: list[ByteSpan] = []
            for raw_declaration in raw_declarations:
                declaration = _span(raw_declaration, source_bytes, boundaries)
                _require(
                    source_bytes[declaration.start : declaration.end] == encoded_name
                )
                declaration_spans.append(declaration)
            library = item["library"]
            _require(type(library) is bool)
            _require(
                not (library and declaration_spans)
                and not (not library and not declaration_spans)
            )
            references.append(
                TsCompilerReference(
                    reference_span,
                    name,
                    tuple(declaration_spans),
                    library,
                )
            )

        references.sort(key=lambda item: (item.span.start, item.span.end))
        for previous, current in itertools.pairwise(references):
            _require(
                previous.span.end <= current.span.start,
                "TypeScript reference spans overlap",
            )

        return TsCompilerSnapshot(
            compiler_version,
            f"sha256:{hashlib.sha256(source_bytes).hexdigest()}",
            tuple(references),
        )
    except TsCompilerSnapshotError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError):
        raise TsCompilerSnapshotError(
            "TypeScript compiler snapshot unavailable or inconsistent"
        ) from None


def compare_with_lexical(
    snapshot: TsCompilerSnapshot, report: LexicalBindingReport
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
    bindings_by_id: dict[str, Binding] = {
        binding.id: binding for binding in report.bindings
    }

    summary = {status: 0 for status in _STATUSES}
    compared: list[dict[str, Any]] = []
    for reference in snapshot.references:
        item: dict[str, Any] = {
            "span": reference.span.to_dict(),
            "name": reference.name,
            "declarations": [
                declaration.to_dict() for declaration in reference.declarations
            ],
            "library": reference.library,
        }
        if reference.library:
            status = "builtin"
        elif reference.span in references_by_span:
            status = "agree"
            declaration_spans = set(reference.declarations)
            for lexical_reference in references_by_span[reference.span]:
                binding = bindings_by_id.get(lexical_reference.binding_id)
                if binding is None or binding.span not in declaration_spans:
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
