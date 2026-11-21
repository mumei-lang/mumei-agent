"""Shared data model and strict reader for lexical binding reports."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


MAX_REPORT_BYTES = 8 * 1024 * 1024
PROFILE_RESOLUTION = "lexical"
TYPE_KINDS = frozenset({"int", "float", "bool", "char", "unit", "named", "unknown"})
REFERENCE_KINDS = frozenset({"read", "write", "call"})
CALL_KINDS = frozenset(
    {
        "direct_local",
        "opaque_generic",
        "opaque_async",
        "opaque_bodyless",
        "constructor",
        "opaque_value",
        "opaque_import",
        "opaque_method",
        "opaque_path",
        "unresolved",
        "opaque_expression",
    }
)
BINDING_KINDS = frozenset(
    {
        "function",
        "const",
        "static",
        "struct",
        "enum",
        "type_alias",
        "trait",
        "union",
        "module",
        "import",
        "local",
        "parameter",
        "self_parameter",
        "generic_parameter",
        "associated_function",
        "associated_const",
    }
)
NON_ASSIGNABLE_WRITE_KINDS = frozenset(
    {
        "function",
        "struct",
        "enum",
        "const",
        "type_alias",
        "trait",
        "union",
        "module",
        "import",
        "associated_function",
        "associated_const",
        "generic_parameter",
    }
)
UNRESOLVED_REASONS = frozenset(
    {
        "prelude_name",
        "glob_import",
        "item_boundary",
        "module_boundary",
        "qualified_path",
        "unknown_name",
    }
)
GAP_REASONS = frozenset(
    {
        "unsupported_syntax",
        "macro_invocation",
        "macro_definition",
        "glob_import",
        "pattern_name_ambiguous",
        "or_pattern_mismatch",
        "conditional_compilation",
    }
)


class LexicalReportError(ValueError):
    """A lexical report is malformed, stale, or unsupported."""


@dataclass(frozen=True)
class ByteSpan:
    """Half-open UTF-8 byte offsets in the complete source."""

    start: int
    end: int

    def to_dict(self) -> dict[str, int]:
        return {"start": self.start, "end": self.end}


@dataclass(frozen=True)
class TypeFact:
    kind: str
    name: str
    bit_width: int
    signed: bool | None
    type_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "bit_width": self.bit_width,
            "signed": self.signed,
            "type_id": self.type_id,
        }


@dataclass(frozen=True)
class Binding:
    id: str
    name: str
    kind: str
    span: ByteSpan
    scope: ByteSpan | None
    type: TypeFact
    mutable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "span": self.span.to_dict(),
            "scope": None if self.scope is None else self.scope.to_dict(),
            "type": self.type.to_dict(),
            "mutable": self.mutable,
        }


@dataclass(frozen=True)
class Reference:
    span: ByteSpan
    binding_id: str
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "span": self.span.to_dict(),
            "binding_id": self.binding_id,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class Unresolved:
    span: ByteSpan
    name: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "span": self.span.to_dict(),
            "name": self.name,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Function:
    binding_id: str
    body: ByteSpan | None
    parameters: tuple[str, ...]
    result: TypeFact
    generic: bool
    is_async: bool
    method: bool
    variadic: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "body": None if self.body is None else self.body.to_dict(),
            "parameters": list(self.parameters),
            "result": self.result.to_dict(),
            "generic": self.generic,
            "is_async": self.is_async,
            "method": self.method,
            "variadic": self.variadic,
        }


@dataclass(frozen=True)
class Call:
    span: ByteSpan
    arguments: tuple[ByteSpan, ...]
    owner: str
    target: str
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "span": self.span.to_dict(),
            "arguments": [arg.to_dict() for arg in self.arguments],
            "owner": self.owner,
            "target": self.target,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class Gap:
    reason: str
    span: ByteSpan

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "span": self.span.to_dict()}


@dataclass(frozen=True)
class LexicalBindingReport:
    profile: str
    source_sha256: str
    target: dict[str, Any]
    bindings: tuple[Binding, ...]
    references: tuple[Reference, ...]
    unresolved: tuple[Unresolved, ...]
    functions: tuple[Function, ...]
    calls: tuple[Call, ...]
    gaps: tuple[Gap, ...]

    @property
    def complete(self) -> bool:
        return not self.unresolved and not self.gaps

    def binding(self, binding_id: str) -> Binding | None:
        return next((binding for binding in self.bindings if binding.id == binding_id), None)

    def resolve(self, span: ByteSpan) -> Binding | None:
        if any(unresolved.span == span for unresolved in self.unresolved):
            return None
        reference = next((ref for ref in self.references if ref.span == span), None)
        return None if reference is None else self.binding(reference.binding_id)

    def to_dict(self) -> dict[str, Any]:
        by_id = {binding.id: binding for binding in self.bindings}

        def order(span: ByteSpan, kind: str, name: str) -> tuple[int, int, str, str]:
            return (span.start, span.end, kind, name)

        bindings = sorted(
            self.bindings,
            key=lambda value: order(value.span, value.kind, value.name),
        )
        references = sorted(
            self.references,
            key=lambda value: order(
                value.span,
                value.kind,
                by_id[value.binding_id].name,
            ),
        )
        unresolved = sorted(
            self.unresolved,
            key=lambda value: order(value.span, value.reason, value.name),
        )
        functions = sorted(
            self.functions,
            key=lambda value: order(
                by_id[value.binding_id].span,
                "function",
                by_id[value.binding_id].name,
            ),
        )
        calls = sorted(self.calls, key=lambda value: order(value.span, value.kind, value.target))
        gaps = sorted(self.gaps, key=lambda value: order(value.span, value.reason, ""))
        return {
            "profile": self.profile,
            "resolution": PROFILE_RESOLUTION,
            "source_sha256": self.source_sha256,
            "target": self.target,
            "complete": self.complete,
            "bindings": [value.to_dict() for value in bindings],
            "references": [value.to_dict() for value in references],
            "unresolved": [value.to_dict() for value in unresolved],
            "functions": [value.to_dict() for value in functions],
            "calls": [value.to_dict() for value in calls],
            "gaps": [value.to_dict() for value in gaps],
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ) + "\n"


def binding_id(
    source_sha256: str,
    decl_start: int,
    scope_start: int,
    scope_end: int,
) -> str:
    return f"sha256:{source_sha256}:{decl_start}:{scope_start}:{scope_end}"


def _fail(condition: bool) -> None:
    if not condition:
        raise LexicalReportError("lexical binding report is malformed or inconsistent")


def _object(value: Any, keys: set[str]) -> dict[str, Any]:
    _fail(type(value) is dict and set(value) == keys)
    return value


def _string(value: Any) -> str:
    _fail(type(value) is str)
    return value


def _integer(value: Any) -> int:
    _fail(type(value) is int and value >= 0)
    return value


def _boolean(value: Any) -> bool:
    _fail(type(value) is bool)
    return value


def _array(value: Any) -> list[Any]:
    _fail(type(value) is list)
    return value


def _span(value: Any, boundaries: set[int], source_length: int) -> ByteSpan:
    record = _object(value, {"start", "end"})
    start = _integer(record["start"])
    end = _integer(record["end"])
    _fail(start <= end <= source_length and start in boundaries and end in boundaries)
    return ByteSpan(start, end)


def _type_fact(value: Any) -> TypeFact:
    record = _object(value, {"kind", "name", "bit_width", "signed", "type_id"})
    kind = _string(record["kind"])
    _fail(kind in TYPE_KINDS)
    name = _string(record["name"])
    width = _integer(record["bit_width"])
    signed_value = record["signed"]
    _fail(signed_value is None or type(signed_value) is bool)
    type_id_value = _string(record["type_id"])
    if kind in {"unknown", "named", "unit"}:
        _fail(width == 0 and signed_value is None)
    elif kind == "int":
        _fail(width > 0 and type(signed_value) is bool)
    elif kind == "float":
        _fail(width > 0 and signed_value is None)
    elif kind == "bool":
        _fail(width == 1 and signed_value is None)
    elif kind == "char":
        _fail(width == 32 and signed_value is None)
    return TypeFact(kind, name, width, signed_value, type_id_value)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LexicalReportError("lexical binding report is malformed or inconsistent")
        result[key] = value
    return result


def load_lexical_report(
    raw: bytes | str,
    source: str,
    *,
    profile: str,
    target: dict[str, Any],
) -> LexicalBindingReport:
    """Restore a report only when its complete structure pins to source."""
    try:
        encoded = raw.encode("utf-8") if isinstance(raw, str) else raw
        _fail(type(encoded) is bytes and len(encoded) <= MAX_REPORT_BYTES)
        decoded = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
        source_bytes = source.encode("utf-8")
        boundaries = {0}
        offset = 0
        for char in source:
            offset += len(char.encode("utf-8"))
            boundaries.add(offset)
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        top = _object(
            decoded,
            {
                "profile",
                "resolution",
                "source_sha256",
                "target",
                "complete",
                "bindings",
                "references",
                "unresolved",
                "functions",
                "calls",
                "gaps",
            },
        )
        _fail(_string(top["profile"]) == profile)
        _fail(_string(top["resolution"]) == PROFILE_RESOLUTION)
        _fail(_string(top["source_sha256"]) == source_hash)
        _fail(_strict_equal(top["target"], target))
        complete = _boolean(top["complete"])

        bindings: list[Binding] = []
        ids: set[str] = set()
        for item in _array(top["bindings"]):
            record = _object(
                item, {"id", "name", "kind", "span", "scope", "type", "mutable"}
            )
            identifier = _string(record["id"])
            name = _string(record["name"])
            kind = _string(record["kind"])
            _fail(kind in BINDING_KINDS)
            decl = _span(record["span"], boundaries, len(source_bytes))
            scope_value = record["scope"]
            scope = None if scope_value is None else _span(
                scope_value, boundaries, len(source_bytes)
            )
            expected = binding_id(
                source_hash,
                decl.start,
                0 if scope is None else scope.start,
                0 if scope is None else scope.end,
            )
            _fail(identifier == expected and identifier not in ids)
            ids.add(identifier)
            bindings.append(
                Binding(
                    identifier,
                    name,
                    kind,
                    decl,
                    scope,
                    _type_fact(record["type"]),
                    _boolean(record["mutable"]),
                )
            )
        _fail(
            all(
                not binding.type.type_id or binding.type.type_id in ids
                for binding in bindings
            )
        )
        binding_kinds = {binding.id: binding.kind for binding in bindings}

        references: list[Reference] = []
        for item in _array(top["references"]):
            record = _object(item, {"span", "binding_id", "kind"})
            span = _span(record["span"], boundaries, len(source_bytes))
            identifier = _string(record["binding_id"])
            kind = _string(record["kind"])
            _fail(identifier in ids and kind in REFERENCE_KINDS)
            _fail(
                kind != "write"
                or binding_kinds[identifier] not in NON_ASSIGNABLE_WRITE_KINDS
            )
            references.append(Reference(span, identifier, kind))

        unresolved: list[Unresolved] = []
        for item in _array(top["unresolved"]):
            record = _object(item, {"span", "name", "reason"})
            unresolved.append(
                Unresolved(
                    _span(record["span"], boundaries, len(source_bytes)),
                    _string(record["name"]),
                    _string(record["reason"]),
                )
            )
            _fail(unresolved[-1].reason in UNRESOLVED_REASONS)
        _fail(not ({reference.span for reference in references} & {
            entry.span for entry in unresolved
        }))

        functions: list[Function] = []
        function_ids: set[str] = set()
        for item in _array(top["functions"]):
            record = _object(
                item,
                {
                    "binding_id",
                    "body",
                    "parameters",
                    "result",
                    "generic",
                    "is_async",
                    "method",
                    "variadic",
                },
            )
            identifier = _string(record["binding_id"])
            _fail(
                identifier in ids
                and binding_kinds[identifier] in {"function", "associated_function"}
                and identifier not in function_ids
            )
            function_ids.add(identifier)
            body_value = record["body"]
            body = None if body_value is None else _span(
                body_value, boundaries, len(source_bytes)
            )
            parameters = tuple(_string(value) for value in _array(record["parameters"]))
            _fail(
                all(
                    value in ids
                    and binding_kinds[value] in {"parameter", "self_parameter"}
                    for value in parameters
                )
            )
            functions.append(
                Function(
                    identifier,
                    body,
                    parameters,
                    _type_fact(record["result"]),
                    _boolean(record["generic"]),
                    _boolean(record["is_async"]),
                    _boolean(record["method"]),
                    _boolean(record["variadic"]),
                )
            )
        _fail(
            all(
                not function.result.type_id or function.result.type_id in ids
                for function in functions
            )
        )
        functions_by_id = {function.binding_id: function for function in functions}

        calls: list[Call] = []
        for item in _array(top["calls"]):
            record = _object(item, {"span", "arguments", "owner", "target", "kind"})
            span = _span(record["span"], boundaries, len(source_bytes))
            arguments = tuple(
                _span(arg, boundaries, len(source_bytes))
                for arg in _array(record["arguments"])
            )
            owner = _string(record["owner"])
            target_id = _string(record["target"])
            kind = _string(record["kind"])
            _fail(kind in CALL_KINDS)
            _fail(not owner or owner in functions_by_id)
            _fail(not target_id or target_id in ids)
            if kind == "direct_local":
                target_function = functions_by_id.get(target_id)
                _fail(
                    target_function is not None
                    and target_function.body is not None
                    and not target_function.is_async
                    and not target_function.generic
                )
            elif kind in {
                "opaque_generic",
                "opaque_async",
                "opaque_bodyless",
                "opaque_import",
                "opaque_value",
                "constructor",
            }:
                _fail(bool(target_id))
            else:
                _fail(not target_id)
            calls.append(Call(span, arguments, owner, target_id, kind))

        gaps: list[Gap] = []
        for item in _array(top["gaps"]):
            record = _object(item, {"reason", "span"})
            reason = _string(record["reason"])
            _fail(reason in GAP_REASONS)
            gaps.append(
                Gap(
                    reason,
                    _span(record["span"], boundaries, len(source_bytes)),
                )
            )
        _fail(complete == (not unresolved and not gaps))
        return LexicalBindingReport(
            profile,
            source_hash,
            top["target"],
            tuple(bindings),
            tuple(references),
            tuple(unresolved),
            tuple(functions),
            tuple(calls),
            tuple(gaps),
        )
    except LexicalReportError:
        raise
    except (UnicodeError, TypeError, ValueError, json.JSONDecodeError):
        raise LexicalReportError("lexical binding report is malformed or inconsistent") from None


def _strict_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return set(left) == set(right) and all(
            _strict_equal(left[key], right[key]) for key in left
        )
    if type(left) is list:
        return len(left) == len(right) and all(
            _strict_equal(a, b) for a, b in zip(left, right)
        )
    return left == right
