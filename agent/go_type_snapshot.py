"""Opt-in consumer of single-file go/types metadata, not a proof/trust gate.

The companion helper uses the Go compiler's type checker without loading imports
or executing source. This reader launches nothing. Reports require a trusted
producer; hashes reject stale input but do not authenticate compiler claims.
Bindings are lexical identities, not SSA values or interprocedural summaries.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterator

from agent import control_flow

PROFILE = "mumei.go-types-single-file/v1"
PACKAGE_PROFILE = "mumei.go-types-package/v1"
MAX_SOURCE_BYTES = 64 * 1024
MAX_FILES = 64
MAX_REPORT_BYTES = 8 * 1024 * 1024
TARGETS = frozenset({"amd64", "386", "arm64"})
_CALL_KINDS = frozenset(
    {
        "direct_local",
        "direct_import",
        "conversion",
        "builtin",
        "indirect_or_selector",
        "external_or_bodyless",
        "method_generic_or_variadic",
        "interface_dispatch",
        "concurrent",
        "deferred",
    }
)
# Identity of an object declared in a resolved imported unit: it embeds that
# unit's own file digest, file index and coordinates, so the target a caller
# records is exactly the binding identity the callee's own report produces.
_IMPORTED_ID = re.compile(r"sha256:[0-9a-f]{64}:[0-9]+:[0-9]+:-?[0-9]+:-?[0-9]+\Z")
# A type-declaration identity in either unit shape: the packaged form
# embeds the file index, the single-file form does not — `interface_
# dispatch` targets pin a named interface's declaration either way.
_TYPE_ID = re.compile(r"sha256:[0-9a-f]{64}(?::-?[0-9]+){3,4}\Z")
_GAPS = frozenset(
    {
        "unsupported_value_semantics",
        "closure_body_not_summarized",
        "blank_function_not_indexed",
        "call_outside_named_body",
        *("call_not_summarized_" + kind for kind in _CALL_KINDS - {"direct_local"}),
    }
)


class SnapshotError(ValueError):
    """A missing, stale or malformed compiler report cannot supply metadata."""


@dataclass(frozen=True)
class ByteSpan:
    """Half-open UTF-8 byte offsets in the complete source, not CFG offsets."""

    start: int
    end: int


@dataclass(frozen=True)
class GoType:
    kind: str
    basic_name: str
    bit_width: int
    signed: bool | None
    type_id: str
    # The element fact on slice/array kinds — `[]T`, `[N]T` and
    # named/alias types whose underlying is one. On map kinds it
    # carries the value fact. On pointer kinds it carries the
    # pointee's fact — an unnamed `*int64` leaves `type_id` empty
    # yet `elem` still classifies the pointee as scalar.
    elem: "GoType | None" = None
    # The key fact on map kinds — `map[K]V` — so a named key's
    # identity pins like the value's does.
    key: "GoType | None" = None


@dataclass(frozen=True)
class Binding:
    id: str
    name: str
    kind: str
    span: ByteSpan
    scope: ByteSpan | None
    type: GoType
    # A func-typed binding's declared named/alias signature type
    # identities (`func F(f func(N) int64)`, `var f MyFn`) — the
    # func type fact carries no inner facts, so callers pin these
    # for staleness exactly like a member's signature_type_ids.
    signature_type_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Reference:
    span: ByteSpan
    binding_id: str
    kind: str


@dataclass(frozen=True)
class Parameter:
    binding_id: str
    type: GoType


@dataclass(frozen=True)
class Function:
    binding_id: str
    body: ByteSpan | None
    parameters: tuple[Parameter, ...]
    results: tuple[Parameter, ...]
    method: bool
    generic: bool
    variadic: bool
    # A method's receiver binds like a leading parameter: a `st.M(args)`
    # call evaluates the receiver operand into actual[0], so the callee
    # summary's `return_dependencies` index 0 is the receiver.
    receiver: Parameter | None = None


@dataclass(frozen=True)
class Call:
    span: ByteSpan
    arguments: tuple[ByteSpan, ...]
    owner: str
    target: str
    kind: str
    # `method` marks a `direct_local` `recv.M(args)` call — the receiver
    # operand is evaluated separately and binds the callee's leading
    # receiver parameter. `method_expr` marks `T.M(recv, args)` — the
    # leading argument already IS the receiver.
    method: bool = False
    method_expr: bool = False


@dataclass(frozen=True)
class Gap:
    reason: str
    span: ByteSpan


@dataclass(frozen=True)
class GoTypeSnapshot:
    source_sha256: str
    target_arch: str
    compiler_version: str
    bindings: tuple[Binding, ...]
    references: tuple[Reference, ...]
    functions: tuple[Function, ...]
    calls: tuple[Call, ...]
    gaps: tuple[Gap, ...]
    profile: str = PROFILE
    language_version: str = "go1.23"

    def binding(self, binding_id: str) -> Binding | None:
        return next((b for b in self.bindings if b.id == binding_id), None)

    def cfg_for_function(
        self, source: str, binding_id: str
    ) -> control_flow.CFGConstruction:
        """Join to C05 only after checking the entire unit, including callees."""
        raw = _source_bytes(source)
        _require(hashlib.sha256(raw).hexdigest() == self.source_sha256)
        fn = next((f for f in self.functions if f.binding_id == binding_id), None)
        _require(fn is not None)
        assert fn is not None
        if fn.body is None or fn.generic or fn.variadic:
            return control_flow.CFGConstruction(
                None,
                (control_flow.CFGGap("typed_function_profile_not_supported"),),
            )
        body = raw[fn.body.start : fn.body.end].decode("utf-8")
        return control_flow.build_go_cfg(body)


def _require(condition: bool) -> None:
    if not condition:
        raise SnapshotError("Go type snapshot unavailable or inconsistent")


def _source_bytes(source: str) -> bytes:
    try:
        raw = source.encode("utf-8")
    except UnicodeError:
        raise SnapshotError("Unsupported Go source encoding") from None
    _require(len(raw) <= MAX_SOURCE_BYTES)
    return raw


def _record(value: Any, *keys: str) -> dict[str, Any]:
    _require(isinstance(value, dict) and set(value) == set(keys))
    return value


def _list(value: Any) -> list[Any]:
    _require(isinstance(value, list))
    return value


def _string(value: Any) -> str:
    _require(isinstance(value, str))
    return value


def _boolean(value: Any) -> bool:
    _require(type(value) is bool)
    return value


def _span(value: Any, raw: bytes) -> ByteSpan:
    v = _record(value, "start", "end")
    start, end = v["start"], v["end"]
    _require(type(start) is int and type(end) is int and 0 <= start <= end <= len(raw))
    _require(all(p == len(raw) or raw[p] & 0xC0 != 0x80 for p in (start, end)))
    return ByteSpan(start, end)


@dataclass(frozen=True)
class FileSpan:
    """A span in one file of a package unit (-1 is the unit-scope sentinel)."""

    file: int
    start: int
    end: int


def _file_span(value: Any, raws: tuple[bytes, ...]) -> FileSpan:
    v = _record(value, "file", "start", "end")
    file, start, end = v["file"], v["start"], v["end"]
    _require(type(file) is int and type(start) is int and type(end) is int)
    if file == -1:
        _require(start == 0 and end == 0)
        return FileSpan(-1, 0, 0)
    _require(0 <= file < len(raws))
    raw = raws[file]
    _require(0 <= start <= end <= len(raw))
    _require(all(p == len(raw) or raw[p] & 0xC0 != 0x80 for p in (start, end)))
    return FileSpan(file, start, end)


@dataclass(frozen=True)
class PackageBinding:
    id: str
    name: str
    kind: str
    span: FileSpan
    scope: FileSpan | None
    type: GoType
    # Same as Binding.signature_type_ids: a func-typed binding's
    # declared named/alias signature identities (`f func(N) int64`,
    # `var f MyFn`, `type MyFn func(N)`).
    signature_type_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PackageReference:
    span: FileSpan
    binding_id: str
    kind: str


@dataclass(frozen=True)
class PackageFunction:
    binding_id: str
    body: FileSpan | None
    parameters: tuple[Parameter, ...]
    results: tuple[Parameter, ...]
    method: bool
    generic: bool
    variadic: bool
    # A method's receiver binds like a leading parameter: a `st.M(args)`
    # call evaluates the receiver operand into actual[0], so the callee
    # summary's `return_dependencies` index 0 is the receiver.
    receiver: Parameter | None = None


@dataclass(frozen=True)
class PackageCall:
    span: FileSpan
    arguments: tuple[FileSpan, ...]
    owner: str
    target: str
    kind: str
    # `method` marks a `direct_import` call whose callee is a method on a
    # named type of an imported unit: the consumer evaluates the receiver
    # expression too, so `recv.M(args)` unions the receiver's deps.
    method: bool = False
    # `method_expr` marks a `direct_import` call recorded from a
    # method expression `lib.T.M(recv, args)` — the leading argument
    # is the receiver, so the consumer applies the receiver rules to
    # it (a composite imported var is a dep-free external read).
    method_expr: bool = False
    # `results` declares the result arity of a `direct_import` callee
    # when it is greater than one — the consumer needs it to admit the
    # tuple unpacking `a, b := lib.F(x)`. 0 means zero or one result.
    results: int = 0
    # `type_arg_type_ids` pins the named/alias identities an
    # instantiated callee's type arguments resolve to — the substituted
    # identities are declared nowhere else, so the call record carries
    # them for staleness pinning exactly like a member's signature ids.
    type_arg_type_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PackageGap:
    reason: str
    span: FileSpan


@dataclass(frozen=True)
class PackageMember:
    """A referenced imported object's declared kind and type.

    The identity is the object's binding id in the imported unit's own
    coordinate space, matching the `import` reference that names it.
    """

    id: str
    name: str
    kind: str
    type: GoType
    # A function member's declared named/alias signature type identities,
    # in the imported unit's coordinate space — staleness pins for callers.
    signature_type_ids: tuple[str, ...] = ()
    # A pointer-typed var's pointee identities at any depth — `**T`
    # declares `[T]`; `*int64` declares `[]` — emitted only when the
    # pointee tree resolves fully, so None (key absent) marks an
    # unpinnable pointee rather than an empty list.
    pointee_type_ids: tuple[str, ...] | None = None
    # The pointee's underlying kind word ("integer", "pointer",
    # "slice", ...) — emitted iff `pointee_type_ids` is, so a
    # dereference read can classify its result when `type_id` is empty.
    pointee_kind: str | None = None
    # A function member's declared result type facts — `ch := lib.G()`
    # admits the external queue model only when the single result's
    # fact is a scalar-element `chan`. Empty for other kinds and for
    # zero-result callees.
    result_types: tuple[GoType, ...] = ()


@dataclass(frozen=True)
class GoPackageSnapshot:
    """A multi-file unit's compiler report — per-file digests anchor spans."""

    files: tuple[tuple[str, str], ...]
    source_sha256: str
    target_arch: str
    compiler_version: str
    bindings: tuple[PackageBinding, ...]
    references: tuple[PackageReference, ...]
    functions: tuple[PackageFunction, ...]
    calls: tuple[PackageCall, ...]
    gaps: tuple[PackageGap, ...]
    profile: str = PACKAGE_PROFILE
    language_version: str = "go1.23"
    # Last on purpose: positional construction predating this field keeps
    # `profile` in place.
    imported_members: tuple[PackageMember, ...] = ()

    def binding(self, binding_id: str) -> PackageBinding | None:
        return next((b for b in self.bindings if b.id == binding_id), None)

    def cfg_for_function(
        self, sources: "dict[str, str] | list[str]", binding_id: str
    ) -> control_flow.CFGConstruction:
        """Join to C05 only after checking every file, including callees."""
        raw = _package_raws(self, sources)
        fn = next((f for f in self.functions if f.binding_id == binding_id), None)
        _require(fn is not None)
        assert fn is not None
        if fn.body is None or fn.generic or fn.variadic:
            return control_flow.CFGConstruction(
                None,
                (control_flow.CFGGap("typed_function_profile_not_supported"),),
            )
        body = raw[fn.body.file][fn.body.start : fn.body.end].decode("utf-8")
        return control_flow.build_go_cfg(body)


def _package_raws(
    snapshot: GoPackageSnapshot, sources: "dict[str, str] | list[str]"
) -> tuple[bytes, ...]:
    """Bind caller-supplied file contents to the report's per-file digests.

    The supplied set must be exactly the declared unit — extra files are
    rejected, not ignored, so a stale unit can never silently pass.
    """
    if isinstance(sources, dict):
        _require(set(sources) == {n for n, _ in snapshot.files})
    else:
        _require(len(sources) == len(snapshot.files))
    raws: list[bytes] = []
    for i, (name, digest) in enumerate(snapshot.files):
        source = sources[name] if isinstance(sources, dict) else sources[i]
        _require(isinstance(source, str))
        raw = _source_bytes(source)
        _require(hashlib.sha256(raw).hexdigest() == digest)
        raws.append(raw)
    return tuple(raws)


def _go_type(value: Any, arch: str) -> GoType:
    # `elem`/`key` are omitempty: slice, array, map and pointer facts
    # carry them, so they join the optional keys rather than the
    # required set.
    _require(
        isinstance(value, dict)
        and {"kind", "basic_name", "bit_width", "signed", "type_id"}
        <= set(value)
        <= {"kind", "basic_name", "bit_width", "signed", "type_id", "elem", "key"}
    )
    v = value
    kind, name, width = v["kind"], v["basic_name"], v["bit_width"]
    signed, type_id = v["signed"], _string(v["type_id"])
    elem_raw = v["elem"] if "elem" in v else None
    key_raw = v["key"] if "key" in v else None
    _require(isinstance(kind, str) and isinstance(name, str) and type(width) is int)
    if kind == "integer":
        widths = {
            "int8": 8,
            "uint8": 8,
            "byte": 8,
            "int16": 16,
            "uint16": 16,
            "int32": 32,
            "uint32": 32,
            "rune": 32,
            "int64": 64,
            "uint64": 64,
            **{n: 32 if arch == "386" else 64 for n in ("int", "uint", "uintptr")},
        }
        _require(name in widths and width == widths[name] and type(signed) is bool)
        _require(signed == (not name.startswith("u") and name != "byte"))
    elif kind == "boolean":
        _require(name == "bool" and width == 1 and signed is None)
    else:
        _require(
            kind
            in {
                "function",
                "pointer",
                "unsupported",
                "untyped",
                "slice",
                "array",
                "map",
                "struct",
                "chan",
            }
            and width == 0
            and signed is None
        )
        names = {
            "",
            "invalid type",
            "float32",
            "float64",
            "complex64",
            "complex128",
            "string",
            "unsafe.Pointer",
        }
        if kind in {
            "function",
            "pointer",
            "slice",
            "array",
            "map",
            "struct",
            "chan",
        }:
            # A pointer fact's identity lives in `type_id` (the
            # pointee's named/alias type), not in a basic name; a
            # slice/array fact's element lives in `elem`, and a map
            # fact's key/value live in `key`/`elem`.
            names = {""}
        elif kind == "untyped":
            names = {
                "untyped " + n
                for n in ("int", "rune", "float", "complex", "string", "bool", "nil")
            }
        _require(name in names)
    if kind in {"slice", "array"}:
        _require(isinstance(elem_raw, dict) and key_raw is None)
        elem = _go_type(elem_raw, arch)
        key = None
    elif kind == "map":
        _require(isinstance(elem_raw, dict) and isinstance(key_raw, dict))
        elem = _go_type(elem_raw, arch)
        key = _go_type(key_raw, arch)
    elif kind == "pointer":
        # The pointee fact is optional: snapshots from a helper that
        # predates it simply carry none, and no pointee is classified
        # then — `*p` reads/writes stay closed like before.
        _require(key_raw is None and (elem_raw is None or isinstance(elem_raw, dict)))
        elem = _go_type(elem_raw, arch) if elem_raw is not None else None
        key = None
    elif kind == "chan":
        # The element fact lets `<-ch` classify what it returns.
        _require(key_raw is None and isinstance(elem_raw, dict))
        elem = _go_type(elem_raw, arch)
        key = None
    else:
        _require(elem_raw is None and key_raw is None)
        elem = key = None
    return GoType(kind, name, width, signed, type_id, elem, key)


def _type_ids(t: GoType) -> Iterator[str]:
    """Every type identity a fact tree declares, elements included."""
    if t.type_id:
        yield t.type_id
    if t.elem is not None:
        yield from _type_ids(t.elem)
    if t.key is not None:
        yield from _type_ids(t.key)


def _parameter(value: Any, arch: str) -> Parameter:
    v = _record(value, "binding_id", "type")
    return Parameter(_string(v["binding_id"]), _go_type(v["type"], arch))


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj = dict(pairs)
    _require(len(obj) == len(pairs))
    return obj


def load_go_snapshot(
    payload: bytes, source: str, *, target_arch: str
) -> GoTypeSnapshot:
    """Read a complete type-check result for an explicitly chosen target.

    Non-ok reports fail closed, without returning partial bindings or echoing
    diagnostics. An ok report can still have opaque calls/value semantics.
    No report can suppress audit findings or discharge an obligation here.
    """
    raw = _source_bytes(source)
    _require(target_arch in TARGETS and len(payload) <= MAX_REPORT_BYTES)
    try:
        data = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
        v = _record(
            data,
            "profile",
            "source_sha256",
            "target_arch",
            "language_version",
            "compiler_version",
            "status",
            "bindings",
            "references",
            "functions",
            "calls",
            "gaps",
        )
        digest = hashlib.sha256(raw).hexdigest()
        _require(v["profile"] == PROFILE and v["source_sha256"] == digest)
        _require(
            v["status"] == "ok"
            and v["target_arch"] == target_arch
            and v["language_version"] == "go1.23"
        )
        compiler = _string(v["compiler_version"])
        _require(re.fullmatch(r"go1\.\d+\.\d+", compiler) is not None)
        bindings = []
        for item in _list(v["bindings"]):
            _require(
                isinstance(item, dict)
                and {"id", "name", "kind", "span", "scope", "type"} <= set(item)
                and set(item)
                <= {
                    "id",
                    "name",
                    "kind",
                    "span",
                    "scope",
                    "type",
                    "signature_type_ids",
                }
            )
            b = item
            sp = _span(b["span"], raw)
            scope = _span(b["scope"], raw) if b["scope"] is not None else None
            name, kind = _string(b["name"]), _string(b["kind"])
            _require(
                bool(name)
                and name != "_"
                and raw[sp.start : sp.end].decode("utf-8") == name
            )
            _require(kind in {"variable", "function", "type", "constant", "label"})
            start, end = (scope.start, scope.end) if scope else (-1, -1)
            binding_id = f"sha256:{digest}:{sp.start}:{start}:{end}"
            _require(b["id"] == binding_id)
            bindings.append(
                Binding(
                    binding_id,
                    name,
                    kind,
                    sp,
                    scope,
                    _go_type(b["type"], target_arch),
                    tuple(
                        _string(s)
                        for s in _list(b.get("signature_type_ids", []))
                    ),
                )
            )
        by_id = {b.id: b for b in bindings}
        _require(len(by_id) == len(bindings))
        for b in bindings:
            _require(
                len(set(b.signature_type_ids)) == len(b.signature_type_ids)
                and all(
                    (s in by_id and by_id[s].kind == "type")
                    or (
                        s not in by_id
                        and _IMPORTED_ID.fullmatch(s) is not None
                    )
                    for s in b.signature_type_ids
                )
            )
        references = []
        for item in _list(v["references"]):
            ref = _record(item, "span", "binding_id", "kind")
            sp, binding_id = _span(ref["span"], raw), _string(ref["binding_id"])
            kind = ref["kind"]
            _require(kind in {"local", "universe"})
            _require(
                (kind == "local" and binding_id in by_id)
                or (kind == "universe" and binding_id == "")
            )
            if binding_id:
                _require(
                    raw[sp.start : sp.end].decode("utf-8") == by_id[binding_id].name
                )
            references.append(Reference(sp, binding_id, kind))
        functions = []
        for item in _list(v["functions"]):
            f = _record(
                item,
                "binding_id",
                "body",
                "parameters",
                "results",
                "method",
                "generic",
                "variadic",
                "receiver",
            )
            binding_id = _string(f["binding_id"])
            _require(binding_id in by_id and by_id[binding_id].kind == "function")
            body = _span(f["body"], raw) if f["body"] is not None else None
            if body is not None:
                _require(
                    body.start > 0
                    and raw[body.start - 1 : body.start] == b"{"
                    and raw[body.end : body.end + 1] == b"}"
                )
            functions.append(
                Function(
                    binding_id,
                    body,
                    tuple(_parameter(p, target_arch) for p in _list(f["parameters"])),
                    tuple(_parameter(p, target_arch) for p in _list(f["results"])),
                    _boolean(f["method"]),
                    _boolean(f["generic"]),
                    _boolean(f["variadic"]),
                    _parameter(f["receiver"], target_arch)
                    if f["receiver"] is not None
                    else None,
                )
            )
        fn_by_id = {f.binding_id: f for f in functions}
        _require(len(fn_by_id) == len(functions))
        calls = []
        for item in _list(v["calls"]):
            _require(
                isinstance(item, dict)
                and {"span", "arguments", "owner", "target", "kind"}
                <= set(item)
                and set(item)
                <= {
                    "span",
                    "arguments",
                    "owner",
                    "target",
                    "kind",
                    "method",
                    "method_expr",
                }
            )
            c = item
            sp, owner, target = (
                _span(c["span"], raw),
                _string(c["owner"]),
                _string(c["target"]),
            )
            kind = _string(c["kind"])
            _require(
                kind in _CALL_KINDS
                and kind != "direct_import"
                and (not owner or owner in fn_by_id)
            )
            method = _boolean(c.get("method", False))
            method_expr = _boolean(c.get("method_expr", False))
            # `method`/`method_expr` only travel on a `direct_local`
            # or `interface_dispatch` record here — a single file
            # declares no imports — and a method-value call (receiver
            # operand) never doubles as a method-expression call
            # (leading receiver argument).
            _require(
                (
                    not method
                    or kind in ("direct_local", "interface_dispatch")
                )
                and (
                    not method_expr
                    or (
                        kind in ("direct_local", "interface_dispatch")
                        and not method
                    )
                )
            )
            if kind == "direct_local":
                _require(target in fn_by_id)
                callee = fn_by_id[target]
                _require(
                    callee.body is not None
                    and not (callee.generic or callee.variadic)
                    and callee.method == (method or method_expr)
                )
            elif kind == "interface_dispatch":
                # The receiver dispatches dynamically: the target pins
                # the named interface's own declaration identity and
                # stays empty for an unnamed `interface{ M() }`
                # receiver.
                _require(not target or _TYPE_ID.fullmatch(target))
            else:
                _require(target == "")
            args = tuple(_span(a, raw) for a in _list(c["arguments"]))
            _require(all(sp.start <= a.start <= a.end <= sp.end for a in args))
            calls.append(Call(sp, args, owner, target, kind, method, method_expr))
        gaps = []
        for item in _list(v["gaps"]):
            g = _record(item, "reason", "span")
            _require(g["reason"] in _GAPS)
            gaps.append(Gap(g["reason"], _span(g["span"], raw)))
        types_to_check = [b.type for b in bindings]
        for fn in functions:
            for p in (*fn.parameters, *fn.results):
                _require(not p.binding_id or p.binding_id in by_id)
                types_to_check.append(p.type)
        _require(
            all(
                not tid or tid in by_id and by_id[tid].kind == "type"
                for t in types_to_check
                for tid in _type_ids(t)
            )
        )
        return GoTypeSnapshot(
            digest,
            target_arch,
            compiler,
            tuple(bindings),
            tuple(references),
            tuple(functions),
            tuple(calls),
            tuple(gaps),
        )
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError):
        raise SnapshotError("Go type snapshot unavailable or inconsistent") from None


def load_go_package_snapshot(
    payload: bytes, sources: "dict[str, str] | list[str]", *, target_arch: str
) -> GoPackageSnapshot:
    """Read a type-check result for a multi-file package unit.

    Same contract as `load_go_snapshot`: non-ok reports fail closed and
    hashes reject stale input without authenticating compiler claims. Each
    binding identity embeds its declaring file's digest, so replacing one
    file only churns that file's identities — per-file freshness.
    """
    _require(target_arch in TARGETS and len(payload) <= MAX_REPORT_BYTES)
    try:
        data = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
        base_keys = {
            "profile",
            "source_sha256",
            "files",
            "target_arch",
            "language_version",
            "compiler_version",
            "status",
            "bindings",
            "references",
            "functions",
            "calls",
            "gaps",
        }
        # `imported_members` is optional: a report without it still loads,
        # imported names simply stay unmodelled.
        _require(isinstance(data, dict) and set(data) - {"imported_members"} == base_keys)
        v = data
        _require(v["profile"] == PACKAGE_PROFILE)
        _require(
            v["status"] == "ok"
            and v["target_arch"] == target_arch
            and v["language_version"] == "go1.23"
        )
        compiler = _string(v["compiler_version"])
        _require(re.fullmatch(r"go1\.\d+\.\d+", compiler) is not None)
        files = []
        for item in _list(v["files"]):
            f = _record(item, "name", "sha256")
            name, digest = _string(f["name"]), _string(f["sha256"])
            _require(name and re.fullmatch(r"[0-9a-f]{64}", digest))
            files.append((name, digest))
        _require(0 < len(files) <= MAX_FILES)
        _require(len({n for n, _ in files}) == len(files))
        digests = [d for _, d in files]
        h = hashlib.sha256()
        for (n, _), d in zip(files, digests):
            h.update(n.encode("utf-8"))
            h.update(b"\x00")
            h.update(bytes.fromhex(d))
        _require(v["source_sha256"] == h.hexdigest())
        snapshot_files = tuple(files)
        probe = GoPackageSnapshot(
            snapshot_files,
            v["source_sha256"],
            target_arch,
            compiler,
            (),
            (),
            (),
            (),
            (),
            imported_members=(),
        )
        raws = _package_raws(probe, sources)
        bindings = []
        for item in _list(v["bindings"]):
            _require(
                isinstance(item, dict)
                and {"id", "name", "kind", "span", "scope", "type"} <= set(item)
                and set(item)
                <= {
                    "id",
                    "name",
                    "kind",
                    "span",
                    "scope",
                    "type",
                    "signature_type_ids",
                }
            )
            b = item
            sp = _file_span(b["span"], raws)
            _require(sp.file >= 0)
            scope = _file_span(b["scope"], raws) if b["scope"] is not None else None
            name, kind = _string(b["name"]), _string(b["kind"])
            raw = raws[sp.file]
            _require(
                bool(name)
                and name != "_"
                and raw[sp.start : sp.end].decode("utf-8") == name
            )
            _require(kind in {"variable", "function", "type", "constant", "label"})
            start, end = (scope.start, scope.end) if scope else (-1, -1)
            binding_id = (
                f"sha256:{digests[sp.file]}:{sp.file}:{sp.start}:{start}:{end}"
            )
            _require(b["id"] == binding_id)
            bindings.append(
                PackageBinding(
                    binding_id,
                    name,
                    kind,
                    sp,
                    scope,
                    _go_type(b["type"], target_arch),
                    tuple(
                        _string(s)
                        for s in _list(b.get("signature_type_ids", []))
                    ),
                )
            )
        by_id = {b.id: b for b in bindings}
        _require(len(by_id) == len(bindings))
        for b in bindings:
            _require(
                len(set(b.signature_type_ids)) == len(b.signature_type_ids)
                and all(
                    (s in by_id and by_id[s].kind == "type")
                    or (
                        s not in by_id
                        and _IMPORTED_ID.fullmatch(s) is not None
                    )
                    for s in b.signature_type_ids
                )
            )
        references = []
        for item in _list(v["references"]):
            ref = _record(item, "span", "binding_id", "kind")
            sp, binding_id = _file_span(ref["span"], raws), _string(ref["binding_id"])
            _require(sp.file >= 0)
            kind = ref["kind"]
            _require(kind in {"local", "universe", "import"})
            if kind == "local":
                _require(binding_id in by_id)
                _require(
                    raws[sp.file][sp.start : sp.end].decode("utf-8")
                    == by_id[binding_id].name
                )
            elif kind == "import":
                _require(
                    _IMPORTED_ID.fullmatch(binding_id) is not None
                    and binding_id not in by_id
                )
            else:
                _require(binding_id == "")
            references.append(PackageReference(sp, binding_id, kind))
        members = []
        for item in _list(v.get("imported_members", [])):
            _require(
                isinstance(item, dict)
                and {"id", "name", "kind", "type"} <= set(item)
                and set(item)
                <= {
                    "id",
                    "name",
                    "kind",
                    "type",
                    "signature_type_ids",
                    "result_types",
                    "pointee_type_ids",
                    "pointee_kind",
                }
            )
            m = item
            mid = _string(m["id"])
            name, kind = _string(m["name"]), _string(m["kind"])
            t = _go_type(m["type"], target_arch)
            _require(
                _IMPORTED_ID.fullmatch(mid) is not None
                and mid not in by_id
                and bool(name)
                and kind in {"function", "const", "var", "type"}
            )
            _require(
                all(
                    not tid
                    or (tid in by_id and by_id[tid].kind == "type")
                    or (
                        tid not in by_id
                        and _IMPORTED_ID.fullmatch(tid) is not None
                    )
                    for tid in _type_ids(t)
                )
            )
            # A `type MyFn func(N) int64` member declares its inner
            # ids exactly like a `func` member does, and a func-typed
            # `var` member (`var F func(N)`, an imported struct's
            # `F func(N)` field) publishes them for the consumer's
            # opaque `s.f(args)` pin.
            _require(
                kind in {"function", "type"}
                or (kind == "var" and t.kind == "function")
                or "signature_type_ids" not in m
            )
            sig_ids_raw = _list(m.get("signature_type_ids", []))
            sig_ids = tuple(_string(s) for s in sig_ids_raw)
            _require(
                len(set(sig_ids)) == len(sig_ids)
                and all(
                    s not in by_id and _IMPORTED_ID.fullmatch(s) is not None
                    for s in sig_ids
                )
            )
            # `pointee_type_ids`/`pointee_kind` may only ride on a
            # pointer-typed var. `pointee_kind` without
            # `pointee_type_ids` is meaningless and rejected, but the
            # reverse is accepted: an older producer declares the ids
            # alone, and a missing kind simply degrades to the
            # pre-`pointee_kind` boundary — a deref read it cannot
            # classify stays closed, exactly as before.
            _require(kind == "var" or "pointee_type_ids" not in m)
            _require(
                "pointee_kind" not in m or "pointee_type_ids" in m
            )
            pointee_ids: tuple[str, ...] | None = None
            pointee_kind: str | None = None
            if "pointee_type_ids" in m:
                _require(t.kind == "pointer")
                pointee_ids = tuple(
                    _string(s) for s in _list(m["pointee_type_ids"])
                )
                _require(
                    len(set(pointee_ids)) == len(pointee_ids)
                    and all(
                        _IMPORTED_ID.fullmatch(s) is not None
                        for s in pointee_ids
                    )
                )
            if "pointee_kind" in m:
                pointee_kind = _string(m["pointee_kind"])
                _require(bool(pointee_kind))
            # `result_types` rides on a function member alone — the
            # per-result type facts let a caller classify what the
            # call binds (`ch := lib.G()` on a scalar-`chan` result).
            _require(
                kind == "function" or "result_types" not in m
            )
            result_types = tuple(
                _go_type(rt, target_arch)
                for rt in _list(m.get("result_types", []))
            )
            members.append(
                PackageMember(
                    mid, name, kind, t, sig_ids, pointee_ids,
                    pointee_kind, result_types,
                )
            )
        _require(len({m.id for m in members}) == len(members))
        functions = []
        for item in _list(v["functions"]):
            f = _record(
                item,
                "binding_id",
                "body",
                "parameters",
                "results",
                "method",
                "generic",
                "variadic",
                "receiver",
            )
            binding_id = _string(f["binding_id"])
            _require(binding_id in by_id and by_id[binding_id].kind == "function")
            body = _file_span(f["body"], raws) if f["body"] is not None else None
            if body is not None:
                _require(body.file >= 0)
                raw = raws[body.file]
                _require(
                    body.start > 0
                    and raw[body.start - 1 : body.start] == b"{"
                    and raw[body.end : body.end + 1] == b"}"
                )
            functions.append(
                PackageFunction(
                    binding_id,
                    body,
                    tuple(_parameter(p, target_arch) for p in _list(f["parameters"])),
                    tuple(_parameter(p, target_arch) for p in _list(f["results"])),
                    _boolean(f["method"]),
                    _boolean(f["generic"]),
                    _boolean(f["variadic"]),
                    _parameter(f["receiver"], target_arch)
                    if f["receiver"] is not None
                    else None,
                )
            )
        fn_by_id = {f.binding_id: f for f in functions}
        _require(len(fn_by_id) == len(functions))
        calls = []
        for item in _list(v["calls"]):
            _require(
                isinstance(item, dict)
                and {"span", "arguments", "owner", "target", "kind"}
                <= set(item)
                and set(item)
                <= {
                    "span",
                    "arguments",
                    "owner",
                    "target",
                    "kind",
                    "method",
                    "method_expr",
                    "results",
                    "type_arg_type_ids",
                }
            )
            c = item
            sp, owner, target = (
                _file_span(c["span"], raws),
                _string(c["owner"]),
                _string(c["target"]),
            )
            kind = _string(c["kind"])
            _require(kind in _CALL_KINDS and (not owner or owner in fn_by_id))
            method = _boolean(c.get("method", False))
            # `method` travels on a method call — `lib.VS.PF(args)` on
            # an imported member, `st.M(args)` on a same-package one or
            # `i.M(args)` dispatching on an interface — never on a
            # plain function call.
            _require(
                not method
                or kind
                in ("direct_import", "direct_local", "interface_dispatch")
            )
            method_expr = _boolean(c.get("method_expr", False))
            # `method_expr` likewise only travels on a method-expression
            # record, and never beside `method` — a `recv.M(args)` call
            # has a receiver node, not a leading receiver argument.
            _require(
                not method_expr
                or (
                    kind
                    in ("direct_import", "direct_local", "interface_dispatch")
                    and not method
                )
            )
            # `results` declares an imported callee's arity when it
            # exceeds one — a 0/1-result callee omits it, and no other
            # kind carries it.
            results = c.get("results", 0)
            _require(
                type(results) is int
                and (results == 0 or results >= 2)
                and (not results or kind == "direct_import")
            )
            # `type_arg_type_ids` only travels on a `direct_import`
            # record — no other callee can substitute type arguments.
            type_arg_ids = _list(c.get("type_arg_type_ids", []))
            _require(
                (not type_arg_ids or kind == "direct_import")
                and all(
                    type(i) is str and _IMPORTED_ID.fullmatch(i) is not None
                    for i in type_arg_ids
                )
            )
            if kind == "direct_local":
                _require(target in fn_by_id)
                callee = fn_by_id[target]
                # A same-package method call carries `method`
                # (`st.M(args)`) or `method_expr` (`T.M(st, args)`); a
                # plain function never does — the flag and the callee's
                # receiver must agree.
                _require(
                    callee.body is not None
                    and not (callee.generic or callee.variadic)
                    and callee.method == (method or method_expr)
                )
            elif kind == "direct_import":
                # The callee lives in a resolved imported unit: the target
                # is that unit's own binding identity, never a local one.
                _require(
                    _IMPORTED_ID.fullmatch(target) is not None
                    and target not in fn_by_id
                )
            elif kind == "interface_dispatch":
                # The receiver dispatches dynamically: the target pins
                # the named interface's own declaration identity (a
                # method-set redeclare stales the caller) and stays
                # empty for an unnamed `interface{ M() }` receiver.
                _require(
                    not target
                    or (
                        _IMPORTED_ID.fullmatch(target) is not None
                        and target not in fn_by_id
                    )
                )
            else:
                _require(target == "")
            args = tuple(_file_span(a, raws) for a in _list(c["arguments"]))
            _require(
                all(
                    a.file == sp.file and sp.start <= a.start <= a.end <= sp.end
                    for a in args
                )
            )
            calls.append(
                PackageCall(
                    sp,
                    args,
                    owner,
                    target,
                    kind,
                    method,
                    method_expr,
                    results,
                    tuple(type_arg_ids),
                )
            )
        gaps = []
        for item in _list(v["gaps"]):
            g = _record(item, "reason", "span")
            _require(g["reason"] in _GAPS)
            gaps.append(PackageGap(g["reason"], _file_span(g["span"], raws)))
        types_to_check = [b.type for b in bindings]
        for fn in functions:
            for p in (*fn.parameters, *fn.results):
                _require(not p.binding_id or p.binding_id in by_id)
                types_to_check.append(p.type)
        _require(
            all(
                not tid
                or (tid in by_id and by_id[tid].kind == "type")
                or (
                    tid not in by_id
                    and _IMPORTED_ID.fullmatch(tid) is not None
                )
                for t in types_to_check
                for tid in _type_ids(t)
            )
        )
        return GoPackageSnapshot(
            snapshot_files,
            v["source_sha256"],
            target_arch,
            compiler,
            tuple(bindings),
            tuple(references),
            tuple(functions),
            tuple(calls),
            tuple(gaps),
            imported_members=tuple(members),
        )
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError):
        raise SnapshotError("Go type snapshot unavailable or inconsistent") from None
