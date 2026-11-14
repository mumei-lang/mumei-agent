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
from typing import Any

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
        "concurrent",
        "deferred",
    }
)
# Identity of an object declared in a resolved imported unit: it embeds that
# unit's own file digest, file index and coordinates, so the target a caller
# records is exactly the binding identity the callee's own report produces.
_IMPORTED_ID = re.compile(r"sha256:[0-9a-f]{64}:[0-9]+:[0-9]+:-?[0-9]+:-?[0-9]+\Z")
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


@dataclass(frozen=True)
class Binding:
    id: str
    name: str
    kind: str
    span: ByteSpan
    scope: ByteSpan | None
    type: GoType


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


@dataclass(frozen=True)
class Call:
    span: ByteSpan
    arguments: tuple[ByteSpan, ...]
    owner: str
    target: str
    kind: str


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
        if fn.body is None or fn.method or fn.generic or fn.variadic:
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


@dataclass(frozen=True)
class PackageCall:
    span: FileSpan
    arguments: tuple[FileSpan, ...]
    owner: str
    target: str
    kind: str


@dataclass(frozen=True)
class PackageGap:
    reason: str
    span: FileSpan


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
        if fn.body is None or fn.method or fn.generic or fn.variadic:
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
    v = _record(value, "kind", "basic_name", "bit_width", "signed", "type_id")
    kind, name, width = v["kind"], v["basic_name"], v["bit_width"]
    signed, type_id = v["signed"], _string(v["type_id"])
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
            kind in {"function", "unsupported", "untyped"}
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
        if kind == "function":
            names = {""}
        elif kind == "untyped":
            names = {
                "untyped " + n
                for n in ("int", "rune", "float", "complex", "string", "bool", "nil")
            }
        _require(name in names)
    return GoType(kind, name, width, signed, type_id)


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
            b = _record(item, "id", "name", "kind", "span", "scope", "type")
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
                    binding_id, name, kind, sp, scope, _go_type(b["type"], target_arch)
                )
            )
        by_id = {b.id: b for b in bindings}
        _require(len(by_id) == len(bindings))
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
                )
            )
        fn_by_id = {f.binding_id: f for f in functions}
        _require(len(fn_by_id) == len(functions))
        calls = []
        for item in _list(v["calls"]):
            c = _record(item, "span", "arguments", "owner", "target", "kind")
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
            if kind == "direct_local":
                _require(target in fn_by_id)
                callee = fn_by_id[target]
                _require(
                    callee.body is not None
                    and not (callee.method or callee.generic or callee.variadic)
                )
            else:
                _require(target == "")
            args = tuple(_span(a, raw) for a in _list(c["arguments"]))
            _require(all(sp.start <= a.start <= a.end <= sp.end for a in args))
            calls.append(Call(sp, args, owner, target, kind))
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
                not t.type_id or t.type_id in by_id and by_id[t.type_id].kind == "type"
                for t in types_to_check
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
        v = _record(
            data,
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
        )
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
            snapshot_files, v["source_sha256"], target_arch, compiler, (), (), (), (), ()
        )
        raws = _package_raws(probe, sources)
        bindings = []
        for item in _list(v["bindings"]):
            b = _record(item, "id", "name", "kind", "span", "scope", "type")
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
                    binding_id, name, kind, sp, scope, _go_type(b["type"], target_arch)
                )
            )
        by_id = {b.id: b for b in bindings}
        _require(len(by_id) == len(bindings))
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
                )
            )
        fn_by_id = {f.binding_id: f for f in functions}
        _require(len(fn_by_id) == len(functions))
        calls = []
        for item in _list(v["calls"]):
            c = _record(item, "span", "arguments", "owner", "target", "kind")
            sp, owner, target = (
                _file_span(c["span"], raws),
                _string(c["owner"]),
                _string(c["target"]),
            )
            kind = _string(c["kind"])
            _require(kind in _CALL_KINDS and (not owner or owner in fn_by_id))
            if kind == "direct_local":
                _require(target in fn_by_id)
                callee = fn_by_id[target]
                _require(
                    callee.body is not None
                    and not (callee.method or callee.generic or callee.variadic)
                )
            elif kind == "direct_import":
                # The callee lives in a resolved imported unit: the target
                # is that unit's own binding identity, never a local one.
                _require(
                    _IMPORTED_ID.fullmatch(target) is not None
                    and target not in fn_by_id
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
            calls.append(PackageCall(sp, args, owner, target, kind))
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
                not t.type_id or t.type_id in by_id and by_id[t.type_id].kind == "type"
                for t in types_to_check
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
        )
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError):
        raise SnapshotError("Go type snapshot unavailable or inconsistent") from None
